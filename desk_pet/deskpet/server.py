"""HTTP daemon: receives agent hooks, serves state to the simulator (and later the device).

Routes
  POST /hook/<agent>   hook payload (JSON body); optional ?event=<name>
  GET  /api/state      current snapshot
  GET  /api/stream     the same snapshot as Server-Sent Events, pushed on change
  POST /api/button     {"button": "B"} acknowledge alerts, or feed the pet
  GET  /api/config     which agents the screen shows; POST to change it
  GET  /api/agents     every supported agent with its hook config
  POST /api/demo       play a scripted demo session
  GET  /               web simulator
"""

import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import agents as registry
from . import demo
from .core import Tracker
from .pet import Pet
from .usage import ClaudeUsage

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/sim.js": ("sim.js", "text/javascript; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8")}
AGENT_RE = re.compile(r"^/hook/([a-z0-9_-]{1,24})$")
MAX_BODY = 2 * 1024 * 1024
PROTOCOL_VERSION = 1
MAX_ROUTES = 1000


class App:
    def __init__(self, pet_path=None, usage=True, usage_interval=60, config_path=None,
                 agents=None):
        self.changed = threading.Condition()
        self.pet = Pet(pet_path)
        self.tracker = Tracker(on_task_done=self._task_done)
        self.usage = ClaudeUsage() if usage else None
        self.usage_interval = usage_interval
        self.demo_stop = None
        self.routes = {}  # (endpoint, session) -> agent that really sent it
        self.device = None  # set by device.SerialLink while a board is connected
        self.config_path = config_path
        self.config = {"mode": "custom", "agents": list(registry.DEFAULT_AGENTS)}
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, encoding="utf-8") as f:
                    self._apply_config(json.load(f))
            except (OSError, ValueError):
                pass
        if agents:
            self.set_config({"mode": "custom", "agents": agents})

    def _apply_config(self, cfg):
        if not isinstance(cfg, dict):
            return
        if cfg.get("mode") in ("custom", "auto"):
            self.config["mode"] = cfg["mode"]
        if isinstance(cfg.get("agents"), list):
            chosen = registry.normalize_list(cfg["agents"])
            if chosen:
                self.config["agents"] = chosen

    def set_config(self, cfg):
        self._apply_config(cfg)
        if self.config_path:
            try:
                os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(self.config, f)
            except OSError:
                pass
        self.notify()
        return dict(self.config)

    def set_device(self, info):
        self.device = info
        self.notify()

    def shown_agents(self):
        if self.config["mode"] == "auto":
            live = [a for a, v in self.tracker.snapshot()["agents"].items() if v["state"] != "offline"]
            return registry.normalize_list(live) + [a for a in live if a not in registry.AGENTS]
        return list(self.config["agents"])

    def _task_done(self, agent, result, duration, tools):
        self.pet.task_done(agent, result, duration, tools)

    def notify(self):
        with self.changed:
            self.changed.notify_all()

    def route(self, endpoint, payload):
        """Which agent a payload belongs to: the endpoint, unless the bridge's
        hints say otherwise (Grok running Claude hooks, Claude Code on DeepSeek...)."""
        hints = payload.pop("_deskpet", None) if isinstance(payload, dict) else None
        sid = str(payload.get("session_id") or "") if isinstance(payload, dict) else ""
        key = (endpoint, sid)
        found = registry.identify(endpoint, payload if isinstance(payload, dict) else {}, hints)
        if found and sid:
            if len(self.routes) >= MAX_ROUTES:
                self.routes.clear()
            self.routes[key] = found
        return found or self.routes.get(key, endpoint)

    def handle_hook(self, endpoint, payload, event=None):
        agent = self.route(endpoint, payload)
        ev = self.tracker.handle(agent, payload, event)
        if ev == "SessionEnd" and isinstance(payload, dict):
            self.routes.pop((endpoint, str(payload.get("session_id") or "")), None)
        self.notify()
        return ev

    def button(self, name):
        if name != "B":
            return "none"
        action = "ack" if self.tracker.ack() else "feed"
        if action == "feed":
            self.pet.feed()
        self.notify()
        return action

    def start_demo(self, speed=1.0):
        if self.demo_stop is not None:
            self.demo_stop.set()
        cast = self.shown_agents() if self.config["mode"] == "custom" else []
        self.demo_stop = demo.start(self.handle_hook, cast or list(registry.DEFAULT_AGENTS), speed)

    def snapshot(self):
        shown = self.shown_agents()
        snap = self.tracker.snapshot(shown)
        for name, entry in snap["agents"].items():
            info = registry.describe(name)
            entry["label"], entry["abbr"] = info["label"], info["abbr"]
        snap["order"] = shown
        snap["mode"] = self.config["mode"]
        snap["device"] = self.device
        snap["v"] = PROTOCOL_VERSION
        snap["pet"] = self.pet.snapshot()
        snap["usage"] = {"claude": self.usage.snapshot()} if self.usage else None
        return snap

    def usage_loop(self):
        while True:
            before = self.usage.snapshot()
            self.usage.scan()
            if self.usage.snapshot() != before:
                self.notify()
            time.sleep(self.usage_interval)


class Handler(BaseHTTPRequestHandler):
    server_version = "deskpet/1"
    app = None  # set by serve()

    def log_message(self, fmt, *args):  # keep hook traffic out of the console
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _foreign_origin(self):
        # Hooks and curl send no Origin; a browser tab on another site does.
        origin = self.headers.get("Origin")
        if not origin:
            return False
        host = urlparse(origin).netloc
        return host != self.headers.get("Host")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/state":
            return self._json(200, self.app.snapshot())
        if path == "/api/stream":
            return self._stream()
        if path == "/api/config":
            return self._json(200, dict(self.app.config, presets=registry.PRESETS))
        if path == "/api/agents":
            port = self.server.server_address[1]
            out = []
            for a in registry.ORDER:
                info = registry.describe(a)
                info["file"], info["text"], info["notes"] = registry.hook_config(a, port)
                info["command"] = "python3 -m deskpet hooks " + a
                out.append(info)
            return self._json(200, out)
        if path in STATIC:
            name, ctype = STATIC[path]
            try:
                with open(os.path.join(WEB_DIR, name), "rb") as f:
                    body = f.read()
            except OSError:
                return self._json(404, {"error": "missing " + name})
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return None
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if self._foreign_origin():
            return self._json(403, {"error": "cross-origin request refused"})
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._json(413, {"error": "body too large"})
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw.strip() else {}
        except ValueError:
            return self._json(400, {"error": "invalid JSON"})

        m = AGENT_RE.match(url.path)
        if m:
            event = (parse_qs(url.query).get("event") or [None])[0]
            self.app.handle_hook(m.group(1), body, event)
            return self._json(200, {})  # empty hook output: never alter agent behaviour
        if not isinstance(body, dict):
            body = {}
        if url.path == "/api/button":
            return self._json(200, {"action": self.app.button(str(body.get("button", "")))})
        if url.path == "/api/config":
            return self._json(200, self.app.set_config(body))
        if url.path == "/api/demo":
            self.app.start_demo(float(body.get("speed") or 1.0))
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "not found"})

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        last, idle = None, 0
        try:
            while True:
                body = json.dumps(self.app.snapshot(), sort_keys=True)
                if body != last:
                    self.wfile.write(b"data: " + body.encode() + b"\n\n")
                    last, idle = body, 0
                elif idle >= 15:
                    self.wfile.write(b": ping\n\n")
                    idle = 0
                self.wfile.flush()
                with self.app.changed:
                    self.app.changed.wait(timeout=1.0)
                idle += 1
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


def serve(host="127.0.0.1", port=7878, pet_path=None, usage=True, demo_on_start=False,
          config_path=None, agents=None):
    app = App(pet_path=pet_path, usage=usage, config_path=config_path, agents=agents)
    handler = type("BoundHandler", (Handler,), {"app": app})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    if app.usage:
        threading.Thread(target=app.usage_loop, daemon=True).start()
    if demo_on_start:
        app.start_demo()
    return app, httpd

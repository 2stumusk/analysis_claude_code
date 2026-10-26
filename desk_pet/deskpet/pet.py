"""The pet: grows with finished agent tasks, gets hungry when ignored."""

import json
import os
import tempfile
import threading
import time
from datetime import date

ENERGY_DECAY = 15 * 60   # lose 1 energy per this many seconds
FEED_ENERGY = 15
TASK_ENERGY = 4


def xp_to_reach(level):
    """Total XP needed to reach `level` (level 1 needs 0)."""
    return 50 * (level - 1) * level


class Pet:
    def __init__(self, path=None, clock=time.time):
        self.path = path
        self.clock = clock
        self.lock = threading.Lock()
        self.data = {"xp": 0, "energy": 80, "energy_at": clock(),
                     "day": date.fromtimestamp(clock()).isoformat(), "tasks_today": 0,
                     "tools_today": 0, "errors_today": 0,
                     "levelup_at": None, "fed_at": None}
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.data.update(json.load(f))
            except (OSError, ValueError):
                pass

    def _tick(self):
        d, now = self.data, self.clock()
        steps = int((now - d["energy_at"]) // ENERGY_DECAY)
        if steps > 0:
            d["energy"] = max(0, d["energy"] - steps)
            d["energy_at"] += steps * ENERGY_DECAY
        today = date.fromtimestamp(now).isoformat()
        if d["day"] != today:
            d.update(day=today, tasks_today=0, tools_today=0, errors_today=0)

    def level(self):
        lv = 1
        while self.data["xp"] >= xp_to_reach(lv + 1):
            lv += 1
        return lv

    def task_done(self, agent, result, duration, tools):
        with self.lock:
            self._tick()
            d = self.data
            before = self.level()
            if result == "error":
                d["errors_today"] += 1
                d["xp"] += 2
            else:
                d["tasks_today"] += 1
                d["xp"] += 10 + min(int(tools), 20) + min(int(duration // 60), 10)
                d["energy"] = min(100, d["energy"] + TASK_ENERGY)
            d["tools_today"] += int(tools)
            if self.level() > before:
                d["levelup_at"] = self.clock()
            self._save()

    def feed(self):
        with self.lock:
            self._tick()
            self.data["energy"] = min(100, self.data["energy"] + FEED_ENERGY)
            self.data["fed_at"] = self.clock()
            self._save()

    def snapshot(self):
        with self.lock:
            self._tick()
            d = self.data
            lv = self.level()
            energy = d["energy"]
            return {
                "level": lv,
                "xp": d["xp"],
                "xp_level": xp_to_reach(lv),
                "xp_next": xp_to_reach(lv + 1),
                "energy": energy,
                "mood": "happy" if energy >= 60 else "ok" if energy >= 25 else "hungry",
                "tasks_today": d["tasks_today"],
                "tools_today": d["tools_today"],
                "errors_today": d["errors_today"],
                "levelup_at": d["levelup_at"],
                "fed_at": d["fed_at"],
            }

    def _save(self):
        if not self.path:
            return
        try:
            folder = os.path.dirname(self.path)
            os.makedirs(folder, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f)
            os.replace(tmp, self.path)
        except OSError:
            pass

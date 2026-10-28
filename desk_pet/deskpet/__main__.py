"""deskpet command line.

  python -m deskpet                          start the daemon and web simulator
  python -m deskpet --demo                   same, and play a demo session
  python -m deskpet --agents claude,kimi     choose which agents the screen shows
  python -m deskpet --serial auto            also drive a USB-connected device
  python -m deskpet --city 无锡              weather page for a city (remembered)
  python -m deskpet --pages face,clock,weather   which pages button A cycles
  python -m deskpet hooks <agent>            print hook config for one agent
  python -m deskpet agents                   list supported agents
"""

import argparse
import os
import sys

from . import agents as registry
from .device import SerialLink
from .server import PAGES, serve

HOME = os.path.join(os.path.expanduser("~"), ".deskpet")
STATUS = {"tested": "已实测", "docs": "按官方文档", "community": "按第三方资料", "unverified": "未核实"}


def main(argv=None):
    p = argparse.ArgumentParser(prog="deskpet", description="Desk pet for coding agents")
    sub = p.add_subparsers(dest="cmd")
    h = sub.add_parser("hooks", help="print hook configuration for an agent")
    h.add_argument("agent", choices=registry.ORDER)
    h.add_argument("--port", type=int, default=7878)
    sub.add_parser("agents", help="list supported agents")
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address (default 127.0.0.1; hook payloads contain your prompts)")
    p.add_argument("--port", type=int, default=7878)
    p.add_argument("--agents", help="comma-separated agents to show, or a preset: "
                   + ", ".join(registry.PRESETS))
    p.add_argument("--demo", action="store_true", help="play a demo session on start")
    p.add_argument("--serial", metavar="PORT", help="drive a deskpet device over USB: a port such as "
                   "/dev/ttyUSB0 or COM3, or 'auto' to find it")
    p.add_argument("--city", help="city for the weather page, e.g. 无锡 or Wuxi; '' turns it off")
    p.add_argument("--pages", help="pages button A cycles through, from: " + ", ".join(PAGES))
    p.add_argument("--no-usage", action="store_true", help="do not read ~/.claude/projects")
    p.add_argument("--state-file", default=os.path.join(HOME, "pet.json"))
    p.add_argument("--config-file", default=os.path.join(HOME, "config.json"))
    args = p.parse_args(argv)

    if args.cmd == "hooks":
        path, text, notes = registry.hook_config(args.agent, args.port)
        for note in ["写入 " + path] + notes:
            print("# " + note, file=sys.stderr)
        print(text)
        return 0
    if args.cmd == "agents":
        for a in registry.ORDER:
            info = registry.describe(a)
            print("%-9s %-26s %-30s %s" % (a, info["name"], info["config"], STATUS[info["status"]]))
        return 0

    chosen = None
    if args.agents:
        chosen = registry.PRESETS.get(args.agents) or [x.strip() for x in args.agents.split(",")]
        unknown = [x for x in chosen if x not in registry.AGENTS]
        if unknown:
            p.error("unknown agent(s): %s (choose from %s)" % (", ".join(unknown), ", ".join(registry.ORDER)))

    pages = None
    if args.pages:
        pages = [x.strip() for x in args.pages.split(",") if x.strip()]
        unknown = [x for x in pages if x not in PAGES]
        if unknown or not pages:
            p.error("unknown page(s): %s (choose from %s)" % (", ".join(unknown), ", ".join(PAGES)))

    app, httpd = serve(args.host, args.port, args.state_file, usage=not args.no_usage,
                       demo_on_start=args.demo, config_path=args.config_file, agents=chosen)
    changes = {}
    if pages:
        changes["pages"] = pages
    if args.city is not None:
        changes["city"] = args.city
    if changes:
        app.set_config(changes)
    print("deskpet: simulator at http://%s:%d/" % (
        "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host, args.port))
    print("         showing: %s (%s mode)" % (", ".join(app.config["agents"]), app.config["mode"]))
    print("         pages: %s; weather: %s" % (", ".join(app.config["pages"]),
                                               app.config["city"] or "off (--city 无锡)"))
    print("         hook config: python -m deskpet hooks <agent>")
    if args.serial:
        SerialLink(app, args.serial).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

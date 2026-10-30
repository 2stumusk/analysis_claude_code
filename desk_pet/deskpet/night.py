"""Night mode: dim or switch off the desk pet's screen on a schedule.

The daemon decides (it knows the local time and the config) and sends the
level in every frame; the device and the web simulator keep the screen lit
anyway while something needs you (an alert or a permission request), and for
a while after a button press.
"""

import re
import time

DAY, DIM, OFF = 0, 1, 2
DEFAULT = {"on": False, "from": "23:00", "to": "07:00", "level": "off"}
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def minutes(hhmm):
    m = TIME_RE.match(hhmm)
    return int(m.group(1)) * 60 + int(m.group(2))


def clean(cfg, current):
    """Merge a config patch into `current`, ignoring anything malformed."""
    out = dict(current)
    if not isinstance(cfg, dict):
        return out
    if isinstance(cfg.get("on"), bool):
        out["on"] = cfg["on"]
    for key in ("from", "to"):
        if isinstance(cfg.get(key), str) and TIME_RE.match(cfg[key]):
            out[key] = cfg[key]
    if cfg.get("level") in ("off", "dim"):
        out["level"] = cfg["level"]
    return out


def level(cfg, now=None):
    """DAY, DIM or OFF for local time `now`. The window may cross midnight;
    from == to means all day."""
    if not cfg.get("on"):
        return DAY
    t = time.localtime(time.time() if now is None else now)
    m = t.tm_hour * 60 + t.tm_min
    start, end = minutes(cfg["from"]), minutes(cfg["to"])
    inside = (start <= m < end) if start < end else (m >= start or m < end)
    if not inside:
        return DAY
    return OFF if cfg["level"] == "off" else DIM

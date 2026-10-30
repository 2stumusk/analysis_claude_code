import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from deskpet import night  # noqa: E402
from deskpet.server import App  # noqa: E402


def at(hhmm):
    """Today's local time `hhmm` as a unix timestamp."""
    h, m = (int(v) for v in hhmm.split(":"))
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, h, m, 0, 0, 0, -1))


class NightTest(unittest.TestCase):
    def test_window_across_midnight(self):
        cfg = dict(night.DEFAULT, on=True)  # 23:00-07:00, off
        self.assertEqual([night.level(cfg, at(t)) for t in ("22:59", "23:00", "02:30", "06:59", "07:00", "12:00")],
                         [0, 2, 2, 2, 0, 0])

    def test_window_within_a_day_and_dim(self):
        cfg = {"on": True, "from": "12:30", "to": "14:00", "level": "dim"}
        self.assertEqual([night.level(cfg, at(t)) for t in ("12:29", "12:30", "13:59", "14:00")], [0, 1, 1, 0])

    def test_off_switch_and_all_day(self):
        self.assertEqual(night.level(dict(night.DEFAULT), at("02:00")), 0)
        always = {"on": True, "from": "08:00", "to": "08:00", "level": "off"}
        self.assertEqual({night.level(always, at(t)) for t in ("00:00", "08:00", "17:45")}, {2})

    def test_clean_ignores_malformed_values(self):
        cur = dict(night.DEFAULT)
        got = night.clean({"on": "yes", "from": "24:00", "to": "7:00", "level": "black"}, cur)
        self.assertEqual(got, cur)
        got = night.clean({"on": True, "from": "22:15", "level": "dim"}, cur)
        self.assertEqual(got, {"on": True, "from": "22:15", "to": "07:00", "level": "dim"})
        self.assertEqual(night.clean("nope", cur), cur)

    def test_app_config_and_snapshot(self):
        app = App(usage=False, weather_factory=None)
        self.assertEqual(app.snapshot()["night"], 0)
        start = time.strftime("%H:%M", time.localtime(time.time() - 60))
        end = time.strftime("%H:%M", time.localtime(time.time() + 3600))
        cfg = app.set_config({"night": {"on": True, "from": start, "to": end, "level": "dim"}})
        self.assertEqual(cfg["night"]["level"], "dim")
        self.assertEqual(app.snapshot()["night"], 1)
        app.set_config({"night": {"on": False}})
        self.assertEqual(app.snapshot()["night"], 0)


if __name__ == "__main__":
    unittest.main()

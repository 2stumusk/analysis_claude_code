import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from deskpet import weather  # noqa: E402
from deskpet.device import device_frame, encode, frame_key, weather_frame  # noqa: E402
from deskpet.server import App  # noqa: E402
from deskpet.weather import OpenMeteo, WeatherService, describe, normalize, pick_place  # noqa: E402

NOW = 1793080000  # some instant; the fixture's hours are laid out around it
OFFSET = 8 * 3600


def forecast_fixture():
    """Shaped like Open-Meteo's documented response with timeformat=unixtime."""
    start = NOW - NOW % 3600 - 3600
    times = [start + i * 3600 for i in range(30)]
    return {
        "latitude": 31.5, "longitude": 120.25, "utc_offset_seconds": OFFSET, "timezone": "Asia/Shanghai",
        "current": {"time": NOW - 300, "interval": 900, "temperature_2m": 17.4, "apparent_temperature": 16.2,
                    "relative_humidity_2m": 82, "weather_code": 61, "wind_speed_10m": 13.6, "is_day": 1},
        "hourly": {"time": times,
                   "temperature_2m": [17.0 - i * 0.5 for i in range(30)],
                   "weather_code": [61 if i < 4 else 3 for i in range(30)],
                   "precipitation_probability": [70 if i < 4 else None for i in range(30)],
                   "is_day": [1 if i < 5 else 0 for i in range(30)]},
        "daily": {"time": [start, start + 86400], "temperature_2m_max": [21.2, 19.0],
                  "temperature_2m_min": [13.6, 12.0], "precipitation_probability_max": [80, 20]},
    }


class FakeApi:
    def __init__(self, geo=None, forecast=None, fail=None):
        self.calls = []
        self.geo = geo if geo is not None else {"results": [
            {"name": "Wuxi Village", "latitude": 1, "longitude": 1, "feature_code": "PPL", "population": 900},
            {"name": "Wuxi", "latitude": 31.5, "longitude": 120.25, "feature_code": "PPLA2", "population": 3000000},
            {"name": "Wuxi Lake", "latitude": 2, "longitude": 2, "feature_code": "LK", "population": 0},
        ]}
        self.forecast = forecast or forecast_fixture()
        self.fail = fail

    def __call__(self, url, params):
        self.calls.append((url, params))
        if self.fail:
            raise self.fail
        return self.geo if url == weather.GEOCODE_URL else self.forecast


class WeatherTest(unittest.TestCase):
    def test_codes(self):
        self.assertEqual(describe(0)[0], "clear")
        self.assertEqual(describe(63)[:2], ("rain", "Rain"))
        self.assertEqual(describe(95)[0], "thunder")
        self.assertEqual(describe(48)[0], "fog")
        self.assertEqual(describe(1234)[0], "cloudy")  # unknown codes do not crash
        self.assertTrue(all(k in weather.KINDS for k, _, _ in weather.WMO.values()))

    def test_pick_place_prefers_big_towns(self):
        self.assertEqual(pick_place(FakeApi().geo["results"])["name"], "Wuxi")
        self.assertIsNone(pick_place([]))

    def test_normalize(self):
        w = normalize(forecast_fixture(), {"name": "Wuxi"}, NOW)
        self.assertEqual((w["temp"], w["feels"], w["humidity"], w["wind"]), (17, 16, 82, 14))
        self.assertEqual((w["kind"], w["text"], w["text_zh"], w["day"]), ("rain", "Light rain", "小雨", True))
        self.assertEqual((w["hi"], w["lo"], w["pop"]), (21, 14, 80))
        self.assertEqual(len(w["hours"]), weather.HOURS)
        first = w["hours"][0]
        self.assertGreater(first["h"], -1)
        # Slots start at the first hour after now and are HOUR_STEP apart, in local time.
        local_now_hour = (NOW + OFFSET) // 3600 % 24
        self.assertEqual(first["h"], (local_now_hour + 1) % 24)
        self.assertEqual([h["h"] for h in w["hours"]], [(first["h"] + 2 * i) % 24 for i in range(6)])
        self.assertEqual(first["p"], 70)
        self.assertEqual(w["hours"][-1]["p"], -1)  # missing probability
        self.assertEqual(w["hours"][-1]["d"], 0)

    def test_provider_requests(self):
        api = FakeApi()
        p = OpenMeteo("无锡", get_json=api, clock=lambda: NOW)
        place = p.locate()
        self.assertEqual(place, {"name": "Wuxi", "lat": 31.5, "lon": 120.25})
        self.assertEqual(api.calls[0][1]["name"], "无锡")
        self.assertEqual(api.calls[0][1]["language"], "en")  # ASCII names for the device fonts
        w = p.fetch(place)
        params = api.calls[1][1]
        self.assertEqual((params["timezone"], params["timeformat"]), ("auto", "unixtime"))
        self.assertIn("weather_code", params["current"])
        self.assertEqual(w["city"], "Wuxi")

    def test_chinese_name_retries_with_shi(self):
        class Geo(FakeApi):
            def __call__(self, url, params):
                self.calls.append((url, params))
                if params.get("name") == "无锡市":
                    return {"results": [{"name": "Wuxi", "latitude": 31.5, "longitude": 120.25,
                                         "feature_code": "PPLA2", "population": 3000000}]}
                return {}
        api = Geo()
        self.assertEqual(OpenMeteo("无锡", get_json=api).locate()["name"], "Wuxi")
        self.assertEqual([c[1]["name"] for c in api.calls], ["无锡", "无锡市"])
        api.calls.clear()
        self.assertEqual(OpenMeteo("Wuxi", get_json=api).queries(), ["Wuxi"])
        with self.assertRaises(LookupError) as cm:
            OpenMeteo("Wuxi", get_json=api).locate()
        self.assertIn("pinyin", str(cm.exception))
        self.assertEqual([c[1]["name"] for c in api.calls], ["Wuxi"])  # no 市 for latin names

    def test_coordinates_in_city_field(self):
        api = FakeApi()
        place = OpenMeteo("31.49, 120.31", get_json=api).locate()
        self.assertEqual((place["lat"], place["lon"]), (31.49, 120.31))
        self.assertEqual(api.calls, [])
        self.assertEqual(OpenMeteo("31.49，120.31").lat, 31.49)  # full-width comma

    def test_provider_unknown_city(self):
        with self.assertRaises(LookupError):
            OpenMeteo("Nowhere", get_json=FakeApi(geo={})).locate()

    def test_coordinates_skip_geocoding(self):
        api = FakeApi()
        OpenMeteo("Home", lat=31.5, lon=120.25, get_json=api).locate()
        self.assertEqual(api.calls, [])

    def test_service_states(self):
        clock = [NOW]
        api = FakeApi(fail=OSError("offline"))
        changes = []
        svc = WeatherService(OpenMeteo("无锡", get_json=api, clock=lambda: clock[0]), "无锡",
                             interval=1200, on_change=lambda: changes.append(1), clock=lambda: clock[0])
        self.assertEqual(svc.snapshot()["status"], "loading")
        self.assertFalse(svc.refresh())
        snap = svc.snapshot()
        self.assertEqual((snap["status"], snap["query"]), ("error", "无锡"))
        self.assertIn("offline", snap["error"])
        api.fail = None
        self.assertTrue(svc.refresh())
        self.assertEqual(svc.snapshot()["status"], "ok")
        api.fail = OSError("offline again")  # keep showing the last forecast
        svc.refresh()
        clock[0] += 3 * 1200 + 1
        snap = svc.snapshot()
        self.assertEqual((snap["status"], snap["temp"]), ("stale", 17))
        self.assertIn("offline again", snap["error"])
        self.assertEqual(len(changes), 3)


class AppWeatherTest(unittest.TestCase):
    def test_city_and_pages_config(self):
        started = []

        class Svc:
            def __init__(self, city, on_change):
                self.city = city
                self.stop = __import__("threading").Event()
                started.append(self)

            def snapshot(self):
                return {"status": "loading", "query": self.city, "error": None}

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            app = App(usage=False, config_path=path, weather_factory=Svc)
            self.assertIsNone(app.snapshot()["weather"])
            app.set_config({"city": " 无锡 ", "pages": ["weather", "clock", "bogus"]})
            snap = app.snapshot()
            self.assertEqual(snap["pages"], ["clock", "weather"])  # canonical order
            self.assertEqual(snap["weather"]["query"], "无锡")
            app.set_config({"city": "无锡"})  # unchanged: no restart
            self.assertEqual(len(started), 1)
            app.set_config({"pages": []})  # never empty
            self.assertEqual(app.config["pages"], ["clock", "weather"])
            again = App(usage=False, config_path=path, weather_factory=Svc)
            self.assertEqual(again.config["city"], "无锡")
            self.assertEqual(len(started), 2)
            again.set_config({"city": ""})
            self.assertTrue(started[1].stop.is_set())
            self.assertIsNone(again.snapshot()["weather"])


class WeatherFrameTest(unittest.TestCase):
    def snap(self, w=None, pages=None):
        app = App(usage=False, weather_factory=None)
        if pages:
            app.set_config({"pages": pages})
        s = app.snapshot()
        s["weather"] = w
        return s

    def ready(self, **extra):
        w = normalize(forecast_fixture(), {"name": "Wuxi"}, NOW)
        w.update(dict(status="ok", age=420, query="无锡", error=None), **extra)
        return w

    def test_frames(self):
        self.assertIsNone(device_frame(self.snap())["w"])
        self.assertEqual(device_frame(self.snap())["pg"], "fcwas")
        self.assertEqual(device_frame(self.snap(pages=["clock", "face"]))["pg"], "fc")
        self.assertEqual(weather_frame({"status": "loading", "query": "无锡"}), {"st": "loading", "c": "??"})
        f = device_frame(self.snap(self.ready()))["w"]
        self.assertEqual((f["st"], f["c"], f["k"], f["t"], f["ag"]), ("ok", "Wuxi", "rain", 17, 7))
        self.assertEqual(len(f["h"]), 6)
        self.assertLess(len(encode(device_frame(self.snap(self.ready())))), 4096)

    def test_key_ignores_age(self):
        a, b = self.snap(self.ready()), self.snap(self.ready(age=900))
        self.assertEqual(frame_key(a, device_frame(a)), frame_key(b, device_frame(b)))
        c = self.snap(self.ready(temp=25))
        self.assertNotEqual(frame_key(a, device_frame(a)), frame_key(c, device_frame(c)))


@unittest.skipUnless(shutil.which("g++") or shutil.which("c++"), "needs a C++ compiler")
class FirmwareWeatherParseTest(unittest.TestCase):
    def test_round_trip(self):
        fw = os.path.join(ROOT, "firmware")
        with tempfile.TemporaryDirectory() as d:
            exe = os.path.join(d, "preview_main")
            cxx = shutil.which("g++") or shutil.which("c++")
            subprocess.run([cxx, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror", "-o", exe,
                            os.path.join(fw, "tools", "preview_main.cpp"),
                            *[os.path.join(fw, "src", n) for n in ("ui.cpp", "frame.cpp", "model.cpp")]],
                           check=True)
            w = normalize(forecast_fixture(), {"name": "Wuxi"}, NOW)
            w.update(status="stale", age=4000, query="无锡", error="x", sample=True)
            app = App(usage=False, weather_factory=None)
            app.set_config({"pages": ["face", "weather", "stats"]})
            snap = app.snapshot()
            snap["weather"] = w
            lines = [encode(device_frame(snap)).decode().strip()]
            snap["weather"] = {"status": "error", "query": "Atlantis", "error": "LookupError"}
            lines.append(encode(device_frame(snap)).decode().strip())
            out = subprocess.run([exe, "parse"], input="\n".join(lines) + "\n", capture_output=True,
                                 text=True, check=True).stdout.splitlines()
        got = json.loads(out[0])
        self.assertEqual(got["pages"], 1 | 4 | 16)
        status, sky, day, sample, temp, feels, hi, lo, pop, age, hours, city, text, slots = got["weather"]
        self.assertEqual((status, sky, day, sample), (4, 5, 1, 1))  # Stale, Rain
        self.assertEqual((temp, feels, hi, lo, pop, age, hours), (17, 16, 21, 14, 80, 66, 6))
        self.assertEqual((city, text), ("Wuxi", "Light rain"))
        self.assertEqual(slots[0][:3], [w["hours"][0]["h"], w["hours"][0]["t"], 5])
        self.assertEqual(slots[-1][3:], [-1, 0])
        err = json.loads(out[1])["weather"]
        self.assertEqual((err[0], err[11]), (2, "Atlantis"))  # Error, city shown


if __name__ == "__main__":
    unittest.main()

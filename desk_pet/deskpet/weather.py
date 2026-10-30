"""Weather for the weather page: a provider fetches it, a service keeps it fresh.

The default provider is Open-Meteo (https://open-meteo.com): no key, but its
free API is for non-commercial use only. A product that is sold needs a paid
plan or another provider; anything with a `locate()` and `fetch(place)` works.

Request and response shapes follow Open-Meteo's own docs (open-meteo-website:
docs/+page.svelte, docs/geocoding-api, code/docs/*-object.svx).
"""

import json
import re
import threading
import time
import urllib.parse
import urllib.request

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURS = 6        # slots in the hourly strip
HOUR_STEP = 2    # hours between slots: covers the next 12 hours
COORDS = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)\s*$")

# WMO weather codes Open-Meteo emits -> (icon kind, English text, Chinese text).
WMO = {
    0: ("clear", "Clear sky", "晴"),
    1: ("clear", "Mainly clear", "晴间少云"),
    2: ("partly", "Partly cloudy", "多云"),
    3: ("cloudy", "Overcast", "阴"),
    45: ("fog", "Fog", "雾"),
    48: ("fog", "Rime fog", "雾凇"),
    51: ("drizzle", "Light drizzle", "小毛毛雨"),
    53: ("drizzle", "Drizzle", "毛毛雨"),
    55: ("drizzle", "Dense drizzle", "大毛毛雨"),
    56: ("drizzle", "Freezing drizzle", "冻毛毛雨"),
    57: ("drizzle", "Freezing drizzle", "冻毛毛雨"),
    61: ("rain", "Light rain", "小雨"),
    63: ("rain", "Rain", "中雨"),
    65: ("rain", "Heavy rain", "大雨"),
    66: ("rain", "Freezing rain", "冻雨"),
    67: ("rain", "Freezing rain", "冻雨"),
    71: ("snow", "Light snow", "小雪"),
    73: ("snow", "Snow", "中雪"),
    75: ("snow", "Heavy snow", "大雪"),
    77: ("snow", "Snow grains", "米雪"),
    80: ("rain", "Rain showers", "阵雨"),
    81: ("rain", "Rain showers", "阵雨"),
    82: ("rain", "Violent showers", "强阵雨"),
    85: ("snow", "Snow showers", "阵雪"),
    86: ("snow", "Snow showers", "阵雪"),
    95: ("thunder", "Thunderstorm", "雷阵雨"),
    96: ("thunder", "Storm, hail", "雷阵雨伴冰雹"),
    97: ("thunder", "Heavy storm", "强雷暴"),
    99: ("thunder", "Storm, hail", "雷阵雨伴冰雹"),
}
KINDS = ["clear", "partly", "cloudy", "fog", "drizzle", "rain", "snow", "thunder"]


def describe(code):
    return WMO.get(int(code), ("cloudy", "Unknown", "未知"))


def _get_json(url, params, timeout=15):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": "deskpet"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def pick_place(results):
    """The most populous populated place; GeoNames feature codes PPL* are towns."""
    places = [r for r in results if str(r.get("feature_code", "")).startswith("PPL")] or results
    return max(places, key=lambda r: r.get("population") or 0) if places else None


def normalize(data, place, now):
    """Open-Meteo forecast (timeformat=unixtime) -> what the screens need."""
    cur = data["current"]
    kind, text, text_zh = describe(cur["weather_code"])
    offset = int(data.get("utc_offset_seconds") or 0)
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    hours = []
    for i, t in enumerate(times):
        if t <= now or (len(hours) and (t - hours[-1]["_t"]) < HOUR_STEP * 3600):
            continue
        hk = describe(hourly["weather_code"][i])[0]
        pop = (hourly.get("precipitation_probability") or [None] * len(times))[i]
        day = (hourly.get("is_day") or [1] * len(times))[i]
        hours.append({"_t": t, "h": (t + offset) // 3600 % 24, "t": round(hourly["temperature_2m"][i]),
                      "k": hk, "p": pop if pop is not None else -1, "d": int(day)})
        if len(hours) == HOURS:
            break
    for h in hours:
        del h["_t"]
    daily = data.get("daily") or {}

    def first(key):
        values = daily.get(key) or [None]
        return values[0]

    hi, lo, pop = first("temperature_2m_max"), first("temperature_2m_min"), first("precipitation_probability_max")
    return {
        "city": place["name"],
        "temp": round(cur["temperature_2m"]),
        "feels": round(cur["apparent_temperature"]),
        "humidity": int(cur["relative_humidity_2m"]),
        "wind": round(cur["wind_speed_10m"]),
        "code": int(cur["weather_code"]),
        "kind": kind,
        "day": bool(cur.get("is_day", 1)),
        "text": text,
        "text_zh": text_zh,
        "hi": round(hi) if hi is not None else None,
        "lo": round(lo) if lo is not None else None,
        "pop": pop if pop is not None else -1,
        "hours": hours,
        "updated": now,
        "source": "Open-Meteo",
    }


class OpenMeteo:
    name = "Open-Meteo"

    def __init__(self, city=None, lat=None, lon=None, get_json=_get_json, clock=time.time):
        self.city, self.lat, self.lon = city, lat, lon
        m = COORDS.match(city or "")
        if m and lat is None and lon is None:  # "31.49,120.31" skips the name lookup
            self.lat, self.lon = float(m.group(1)), float(m.group(2))
        self.get_json = get_json
        self.clock = clock

    def locate(self):
        if self.lat is not None and self.lon is not None:
            return {"name": self.city or "%.2f,%.2f" % (self.lat, self.lon), "lat": self.lat, "lon": self.lon}
        for query in self.queries():
            found = self.get_json(GEOCODE_URL, {"name": query, "count": 10, "language": "en", "format": "json"})
            place = pick_place(found.get("results") or [])
            if place:
                return {"name": place["name"], "lat": place["latitude"], "lon": place["longitude"]}
        raise LookupError("city not found: %s (try the English or pinyin name, e.g. Wuxi, "
                          "or latitude,longitude)" % self.city)

    def queries(self):
        """Names to try. Open-Meteo matches queries of one or two characters
        exactly only, so a two-character Chinese name like 无锡 misses an
        entry stored as 无锡市; the 市 form is tried next."""
        name = self.city.strip()
        out = [name]
        if any(ord(ch) > 0x2E80 for ch in name) and not name.endswith("市"):
            out.append(name + "市")
        return out

    def fetch(self, place):
        data = self.get_json(FORECAST_URL, {
            "latitude": place["lat"], "longitude": place["lon"],
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,"
                       "wind_speed_10m,is_day",
            "hourly": "temperature_2m,weather_code,precipitation_probability,is_day",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto", "timeformat": "unixtime", "forecast_days": 2,
        })
        return normalize(data, place, self.clock())


class WeatherService:
    """Refreshes in the background; snapshot() never blocks."""

    def __init__(self, provider, city, interval=20 * 60, retry=5 * 60, on_change=None, clock=time.time):
        self.provider = provider
        self.city = city
        self.interval, self.retry = interval, retry
        self.on_change = on_change or (lambda: None)
        self.clock = clock
        self.data = None
        self.error = None
        self.place = None
        self.stop = threading.Event()

    def refresh(self):
        try:
            if self.place is None:
                self.place = self.provider.locate()
            self.data = self.provider.fetch(self.place)
            self.error = None
            ok = True
        except Exception as e:  # noqa: BLE001 - network, lookup or format trouble
            self.error = "%s: %s" % (type(e).__name__, e)
            ok = False
        self.on_change()
        return ok

    def run(self):
        while not self.stop.is_set():
            ok = self.refresh()
            self.stop.wait(self.interval if ok else self.retry)

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()
        return self

    def snapshot(self):
        now = self.clock()
        if self.data:
            age = int(now - self.data["updated"])
            status = "stale" if age > 3 * self.interval else "ok"
            return dict(self.data, status=status, age=age, error=self.error, query=self.city)
        return {"status": "error" if self.error else "loading", "error": self.error, "query": self.city}

// What the device knows: the last frame the deskpet daemon sent over USB.
#pragma once

#include <stdint.h>

namespace pet {

enum class State : uint8_t {
  Offline, Idle, Thinking, Reading, Editing, Running, Waiting, Done, Error, Count
};

enum class Mood : uint8_t { Hungry, Ok, Happy };

enum class Sky : uint8_t { Clear, Partly, Cloudy, Fog, Drizzle, Rain, Snow, Thunder };

// Pages button A cycles through (bit i = View i in ui.h).
enum PageBit : uint8_t { PageFace = 1, PageClock = 2, PageWeather = 4, PageAgents = 8, PageStats = 16 };
constexpr uint8_t kAllPages = 31;

constexpr int kMaxAgents = 8;

// How the face page looks: the drawn eyes, or the pixel cat (cat_art.h).
enum class Skin : uint8_t { Eyes, Cat };

// Night mode the daemon asks for: screen as usual, dimmed, or off.
enum class Night : uint8_t { Day, Dim, Off };

// Text is UTF-8: ASCII plus GB2312 Chinese (up to 3 bytes per screen column).

struct Agent {
  char id[12];
  char label[10];    // "DEEPSEEK"
  char abbr[4];      // "DS"
  State state;
  char detail[148];  // 48 columns, already clipped by the daemon
  char cwd[68];      // 22 columns
  int32_t elapsed;   // task seconds when the frame was sent, -1 = no task
  uint16_t tools;
  uint8_t sessions;
  bool alert;        // waiting and not yet acknowledged
};

struct PetInfo {
  int level, xp_in_level, xp_span, energy;
  Mood mood;
  int tasks, tools, errors;
  float levelup_age, fed_age;  // seconds since, at receive time; < 0 = never
};

struct HourForecast {
  int8_t hour;
  int8_t pop;       // precipitation probability %, -1 unknown
  int16_t temp;
  Sky sky;
  bool day;
};

struct WeatherInfo {
  enum class Status : uint8_t { Off, Loading, Error, Ok, Stale } status = Status::Off;
  char city[16] = "";
  char text[24] = "";
  Sky sky = Sky::Clear;
  bool day = true;
  bool sample = false;   // demo data, not a real forecast
  int16_t temp = 0, feels = 0, hi = -99, lo = -99, wind = 0;
  int8_t humidity = 0, pop = -1;
  int age_min = 0;
  int hours = 0;
  HourForecast hour[6];
};

// A permission request the daemon is holding for button A (deny) / B (allow) / C (later).
struct Approval {
  bool active = false;
  char id[24] = "";
  int agent = -1;        // index into agents, -1 = not shown
  char label[10] = "";
  char tool[21] = "";
  char detail[364] = "";  // 120 columns
  int64_t deadline = 0;  // daemon unix time
  int wait = 30;         // full wait, seconds (countdown bar)
};

struct Model {
  bool connected = false;
  float rx_time = 0;      // device seconds when the frame arrived
  int64_t epoch = 0;      // daemon's unix time in that frame
  int32_t tz = 0;         // daemon's UTC offset, seconds
  int count = 0;
  int focus = -1;         // index into agents, -1 = none
  int rot_index = 0;      // the face is rotating between busy agents:
  int rot_count = 0;      //   showing number rot_index of rot_count (0 = not rotating)
  Agent agents[kMaxAgents];
  PetInfo pet{1, 0, 100, 80, Mood::Ok, 0, 0, 0, -1, -1};
  bool has_usage = false;
  int64_t usage_out = 0;  // Claude output tokens today
  int64_t usage_total = 0;
  uint8_t pages = kAllPages;
  WeatherInfo weather;
  Approval approval;
  Night night = Night::Day;
  Skin skin = Skin::Eyes;
};

State parseState(const char* s);
Sky parseSky(const char* s);
const char* stateLabel(State s);   // "NEEDS YOU"
const char* stateShort(State s);   // "WAIT"

}  // namespace pet

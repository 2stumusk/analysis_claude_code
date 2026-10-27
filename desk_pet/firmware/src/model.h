// What the device knows: the last frame the deskpet daemon sent over USB.
#pragma once

#include <stdint.h>

namespace pet {

enum class State : uint8_t {
  Offline, Idle, Thinking, Reading, Editing, Running, Waiting, Done, Error, Count
};

enum class Mood : uint8_t { Hungry, Ok, Happy };

constexpr int kMaxAgents = 8;

struct Agent {
  char id[12];
  char label[10];    // "DEEPSEEK"
  char abbr[4];      // "DS"
  State state;
  char detail[52];   // ASCII only, already clipped by the daemon
  char cwd[24];
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

struct Model {
  bool connected = false;
  float rx_time = 0;      // device seconds when the frame arrived
  int64_t epoch = 0;      // daemon's unix time in that frame
  int32_t tz = 0;         // daemon's UTC offset, seconds
  int count = 0;
  int focus = -1;         // index into agents, -1 = none
  Agent agents[kMaxAgents];
  PetInfo pet{1, 0, 100, 80, Mood::Ok, 0, 0, 0, -1, -1};
  bool has_usage = false;
  int64_t usage_out = 0;  // Claude output tokens today
  int64_t usage_total = 0;
};

State parseState(const char* s);
const char* stateLabel(State s);   // "NEEDS YOU"
const char* stateShort(State s);   // "WAIT"

}  // namespace pet

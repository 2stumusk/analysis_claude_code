#include "model.h"

#include <string.h>

namespace pet {

namespace {
struct Name {
  const char* wire;
  const char* label;
  const char* shortLabel;
};
// Indexed by State.
const Name kNames[] = {
    {"offline", "OFFLINE", "OFF"}, {"idle", "IDLE", "IDLE"},
    {"thinking", "THINKING", "THINK"}, {"reading", "READING", "READ"},
    {"editing", "EDITING", "EDIT"}, {"running", "RUNNING", "RUN"},
    {"waiting", "NEEDS YOU", "WAIT"}, {"done", "DONE", "DONE"},
    {"error", "ERROR", "ERR"},
};
}  // namespace

State parseState(const char* s) {
  for (int i = 0; i < (int)State::Count; i++) {
    if (strcmp(s, kNames[i].wire) == 0) return (State)i;
  }
  return State::Idle;
}

const char* stateLabel(State s) { return kNames[(int)s].label; }
const char* stateShort(State s) { return kNames[(int)s].shortLabel; }

}  // namespace pet

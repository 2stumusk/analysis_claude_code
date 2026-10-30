// Screens and the pet's face. Mirrors desk_pet/web/sim.js so the simulator
// and the device show the same thing.
//
// update() advances animation once per frame; draw() is pure and may run
// several times per frame (the device renders in horizontal bands).
#pragma once

#include "gfx.h"
#include "model.h"

namespace pet {

enum class Sound : uint8_t { None, Waiting, Done, Error, Click };

// Same order as the PageBit flags in model.h.
enum class View : uint8_t { Face, Clock, Weather, Agents, Stats, Count };

class Ui {
 public:
  void update(const Model& m, float now);
  void draw(Gfx& g, const Model& m, float now) const;

  void nextView(const Model& m);  // next page the daemon has enabled
  void setView(View v) { view_ = v; }
  View view() const { return view_; }
  void showToast(const char* text, float now);
  // Force the face to a state (desktop preview); State::Count clears it.
  void setPreview(State s) { preview_ = s; }
  void seed(uint32_t s) { rng_ = s ? s : 1; }
  float eyesOpen() const { return blink_; }  // 1 = fully open

  // Permission request: on screen until the daemon clears it or its deadline passes.
  bool approvalShown(const Model& m, float now) const;
  // Buttons answer it only after it has been visible a moment (no accidental presses).
  bool approvalArmed(const Model& m, float now) const;
  // Touch boards with two halves (CYD): DENY left, ALLOW right, hold for LATER.
  void setHalves(bool halves) { halves_ = halves; }

  Sound takeSound();
  // LED colour for boards that have one; false = off.
  bool led(const Model& m, float now, uint16_t* color) const;

 private:
  struct Pose {
    float lx, ly, h, lid, sad;
  };

  State faceState(const Model& m) const;
  Pose target(State s, Mood mood, float now);
  float random01();

  void drawEyes(Gfx& g, int cx, int cy, float s, State st, uint16_t color) const;
  void drawFace(Gfx& g, int cx, int cy, float s, State st, float now) const;
  void topBar(Gfx& g, const Model& m, float now) const;
  void alertRing(Gfx& g, const Model& m, float now) const;
  void viewFace(Gfx& g, const Model& m, float now) const;
  void viewClock(Gfx& g, const Model& m, float now) const;
  void viewAgents(Gfx& g, const Model& m, float now) const;
  void agentRows(Gfx& g, const Model& m, float now) const;
  void viewStats(Gfx& g, const Model& m, float now) const;
  void viewWeather(Gfx& g, const Model& m, float now) const;
  void viewApproval(Gfx& g, const Model& m, float now) const;

  View view_ = View::Face;
  State preview_ = State::Count;
  Pose pose_{0, 0, 1, 0, 0};
  float look_x_ = 0, look_y_ = 0, look_until_ = 0;
  float blink_at_ = 3, blink_ = 1;
  float last_ = 0;
  char toast_[24] = {0};
  float toast_until_ = 0;
  uint32_t rng_ = 0x2545F491;
  bool halves_ = false;
  char approval_id_[24] = "";
  float approval_seen_ = 0;

  // Transition tracking for chimes and jumping back to the face.
  char prev_ids_[kMaxAgents][12] = {};
  State prev_states_[kMaxAgents] = {};
  bool prev_alerts_[kMaxAgents] = {};
  int prev_count_ = 0;
  float last_alert_beep_ = -100;
  Sound sound_ = Sound::None;
};

// Wall clock from the last frame: seconds since local midnight and the date.
struct LocalTime {
  int hour, minute, second, year, month, day, weekday;  // weekday 0 = Sunday
};
bool localTime(const Model& m, float now, LocalTime* out);

}  // namespace pet

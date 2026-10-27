#include "ui.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#include <initializer_list>

namespace pet {

namespace {

const uint16_t BG = rgb(0x0b0d10);
const uint16_t FG = rgb(0xe8e6e3);
const uint16_t DIM = rgb(0x7a808a);
const uint16_t FAINT = rgb(0x262a31);
const uint16_t SOFT = rgb(0xb9bec6);
const uint16_t CARD = rgb(0x15181d);
const uint16_t ROW = rgb(0x12151a);
const uint16_t TOAST = rgb(0x2b3038);
const uint16_t HEART = rgb(0xff6b8b);
const uint16_t SWEAT = rgb(0x7cc4ff);
const uint16_t XP = rgb(0x8ab4ff);

// Indexed by State; same palette as the web simulator.
const uint16_t kStateColor[] = {
    rgb(0x5a5f68),  // offline
    rgb(0xe8e6e3),  // idle
    rgb(0x8ab4ff),  // thinking
    rgb(0x5fd4c4),  // reading
    rgb(0xc79bff),  // editing
    rgb(0xffd166),  // running
    rgb(0xff8a3d),  // waiting
    rgb(0x7ee081),  // done
    rgb(0xff5d5d),  // error
};

uint16_t colorOf(State s) { return kStateColor[(int)s]; }

const float kPi = 3.14159265f;

float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

bool busy(State s) { return s != State::Idle && s != State::Offline; }

void fmtDur(float secs, char* out, int cap) {
  int s = secs < 0 ? 0 : (int)secs;
  int h = s / 3600, m = (s % 3600) / 60;
  if (h) {
    snprintf(out, cap, "%d:%02d:%02d", h, m, s % 60);
  } else {
    snprintf(out, cap, "%02d:%02d", m, s % 60);
  }
}

void fmtNum(int64_t n, char* out, int cap) {
  if (n >= 1000000) {
    snprintf(out, cap, "%.1fM", n / 1e6);
  } else if (n >= 1000) {
    snprintf(out, cap, "%.1fk", n / 1e3);
  } else {
    snprintf(out, cap, "%d", (int)n);
  }
}

// Clip `s` to `maxW` pixels, ending in "..." when it had to be cut.
const char* fit(Gfx& g, const char* s, int maxW, Font f, char* out, int cap) {
  snprintf(out, cap, "%s", s);
  if (g.textWidth(out, f) <= maxW) return out;
  int n = (int)strlen(out);
  while (n > 0) {
    out[--n] = 0;
    char tmp[96];
    snprintf(tmp, sizeof(tmp), "%s...", out);
    if (g.textWidth(tmp, f) <= maxW) {
      snprintf(out, cap, "%s", tmp);
      return out;
    }
  }
  return out;
}

// fillArc wants 0 <= a0 < a1 <= 360; split arcs that cross 0 degrees.
void arc(Gfx& g, int x, int y, int r0, int r1, float a0, float a1, uint16_t c) {
  float span = clampf(a1 - a0, 0, 360);
  a0 = fmodf(a0, 360.0f);
  if (a0 < 0) a0 += 360.0f;
  a1 = a0 + span;
  if (a1 > 360.0f) {
    g.fillArc(x, y, r0, r1, a0, 360.0f, c);
    g.fillArc(x, y, r0, r1, 0, a1 - 360.0f, c);
  } else {
    g.fillArc(x, y, r0, r1, a0, a1, c);
  }
}

void bar(Gfx& g, int x, int y, int w, int h, float frac, uint16_t c) {
  g.fillRoundRect(x, y, w, h, h / 2, FAINT);
  frac = clampf(frac, 0, 1);
  if (frac > 0) {
    int fw = (int)(w * frac);
    g.fillRoundRect(x, y, fw < h ? h : fw, h, h / 2, c);
  }
}

void heart(Gfx& g, int x, int y, float s, uint16_t c) {
  int r = (int)(3.4f * s + 0.5f);
  g.fillCircle((int)(x - 3 * s), (int)(y - 3 * s), r, c);
  g.fillCircle((int)(x + 3 * s), (int)(y - 3 * s), r, c);
  g.fillTriangle((int)(x - 6.3f * s), (int)(y - 2 * s), (int)(x + 6.3f * s), (int)(y - 2 * s),
                 x, (int)(y + 5 * s), c);
}

void diamond(Gfx& g, int x, int y, float rx, float ry, uint16_t c) {
  g.fillTriangle(x, (int)(y - ry), (int)(x + rx), y, (int)(x - rx), y, c);
  g.fillTriangle(x, (int)(y + ry), (int)(x + rx), y, (int)(x - rx), y, c);
}

const char* kWeekdays[] = {"SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"};
const char* kMonths[] = {"JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                         "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"};

const Agent* agentAt(const Model& m, int i) { return (i >= 0 && i < m.count) ? &m.agents[i] : nullptr; }

bool anyAlert(const Model& m) {
  if (!m.connected) return false;
  for (int i = 0; i < m.count; i++) {
    if (m.agents[i].alert) return true;
  }
  return false;
}

}  // namespace

// ---------- time ----------

bool localTime(const Model& m, float now, LocalTime* out) {
  if (m.epoch <= 0) return false;
  int64_t secs = m.epoch + m.tz + (int64_t)(now - m.rx_time);
  int64_t days = secs >= 0 ? secs / 86400 : (secs - 86399) / 86400;
  int64_t sod = secs - days * 86400;
  out->hour = (int)(sod / 3600);
  out->minute = (int)(sod % 3600 / 60);
  out->second = (int)(sod % 60);
  out->weekday = (int)(((days % 7) + 11) % 7);  // 1970-01-01 was a Thursday
  // Civil date from day count (H. Hinnant's algorithm).
  int64_t z = days + 719468;
  int64_t era = (z >= 0 ? z : z - 146096) / 146097;
  int64_t doe = z - era * 146097;
  int64_t yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
  int64_t doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
  int64_t mp = (5 * doy + 2) / 153;
  out->day = (int)(doy - (153 * mp + 2) / 5 + 1);
  out->month = (int)(mp < 10 ? mp + 3 : mp - 9);
  out->year = (int)(yoe + era * 400 + (out->month <= 2));
  return true;
}

// ---------- state ----------

float Ui::random01() {
  rng_ ^= rng_ << 13;
  rng_ ^= rng_ >> 17;
  rng_ ^= rng_ << 5;
  return (rng_ & 0xFFFFFF) / 16777216.0f;
}

State Ui::faceState(const Model& m) const {
  if (preview_ != State::Count) return preview_;
  const Agent* a = agentAt(m, m.focus);
  if (!m.connected || !a) return State::Offline;
  return a->state;
}

Ui::Pose Ui::target(State s, Mood mood, float now) {
  Pose p{0, 0, 1, 0, 0};
  switch (s) {
    case State::Idle:
      if (now > look_until_) {
        look_x_ = (random01() - 0.5f) * 24;
        look_y_ = (random01() - 0.5f) * 10;
        look_until_ = now + 2 + random01() * 3;
      }
      p.lx = look_x_;
      p.ly = look_y_;
      if (mood == Mood::Hungry) {
        p.sad = 1;
        p.h = 0.8f;
        p.ly = 6;
      }
      break;
    case State::Thinking: p = {12, -12, 0.92f, 0, 0}; break;
    case State::Reading: p = {sinf(now * 2.2f) * 16, 5, 0.78f, 0, 0}; break;
    case State::Editing: p = {0, 9, 1, 0.38f, 0}; break;
    case State::Running: p = {0, sinf(now * 9) * 3, 1.02f, 0, 0}; break;
    case State::Waiting: p = {0, -2, 1.12f, 0, 0}; break;
    case State::Offline: p.h = 0.08f; break;
    default: break;
  }
  return p;
}

void Ui::update(const Model& m, float now) {
  float dt = clampf(now - last_, 0, 0.25f);
  last_ = now;
  State st = faceState(m);

  // Ease the eyes toward the expression; frame-rate independent.
  Pose tp = target(st, m.pet.mood, now);
  float k = 1 - powf(0.88f, dt * 60);
  pose_.lx += (tp.lx - pose_.lx) * k;
  pose_.ly += (tp.ly - pose_.ly) * k;
  pose_.h += (tp.h - pose_.h) * k;
  pose_.lid += (tp.lid - pose_.lid) * k;
  pose_.sad += (tp.sad - pose_.sad) * k;

  blink_ = 1;
  if (st != State::Offline && st != State::Done && st != State::Error) {
    if (now > blink_at_ + 0.16f) blink_at_ = now + 2.5f + random01() * 4;
    if (now > blink_at_) blink_ = fabsf((now - blink_at_) / 0.08f - 1);
  }

  if (!m.connected) return;

  // Chime on finishes and new alerts; jump to the face for the ones that matter.
  bool jump = false;
  for (int i = 0; i < m.count; i++) {
    const Agent& a = m.agents[i];
    State before = State::Offline;
    bool alertBefore = false;
    for (int j = 0; j < prev_count_; j++) {
      if (strcmp(prev_ids_[j], a.id) == 0) {
        before = prev_states_[j];
        alertBefore = prev_alerts_[j];
      }
    }
    if (a.alert && !alertBefore) jump = true;
    if (a.state != before && (a.state == State::Done || a.state == State::Error)) {
      sound_ = a.state == State::Done ? Sound::Done : Sound::Error;
      if (i == m.focus) jump = true;
    }
  }
  prev_count_ = m.count;
  for (int i = 0; i < m.count; i++) {
    snprintf(prev_ids_[i], sizeof(prev_ids_[i]), "%s", m.agents[i].id);
    prev_states_[i] = m.agents[i].state;
    prev_alerts_[i] = m.agents[i].alert;
  }
  if (jump && preview_ == State::Count) view_ = View::Face;

  if (anyAlert(m)) {
    if (now - last_alert_beep_ > 8) {
      last_alert_beep_ = now;
      if (sound_ == Sound::None) sound_ = Sound::Waiting;
    }
  } else {
    last_alert_beep_ = -100;
  }
}

void Ui::nextView() { view_ = (View)(((int)view_ + 1) % (int)View::Count); }

void Ui::showToast(const char* text, float now) {
  snprintf(toast_, sizeof(toast_), "%s", text);
  toast_until_ = now + 1.4f;
}

Sound Ui::takeSound() {
  Sound s = sound_;
  sound_ = Sound::None;
  return s;
}

bool Ui::led(const Model& m, float now, uint16_t* color) const {
  if (anyAlert(m)) {
    *color = colorOf(State::Waiting);
    return sinf(now * 6) > 0;
  }
  State st = faceState(m);
  *color = colorOf(st);
  return st == State::Done || st == State::Error;
}

// ---------- face ----------

void Ui::drawEyes(Gfx& g, int cx, int cy, float s, State st, uint16_t color) const {
  float ew = 58 * s, gap = 42 * s, r = 18 * s;
  float eh = fmaxf(4 * s, 66 * s * pose_.h * blink_);
  for (int side = -1; side <= 1; side += 2) {
    float ex = cx + side * (gap / 2 + ew / 2) + pose_.lx * s - ew / 2;
    float ey = cy + pose_.ly * s - eh / 2;
    int mx = (int)(ex + ew / 2);

    if (st == State::Done) {  // happy ^ ^
      float ar = ew * 0.38f, half = 4.5f * s;
      int ay = (int)(cy + 10 * s);
      arc(g, mx, ay, (int)(ar - half), (int)(ar + half), 207, 333, color);
      for (float deg : {207.0f, 333.0f}) {
        float rad = deg * kPi / 180;
        g.fillCircle((int)(mx + cosf(rad) * ar), (int)(ay + sinf(rad) * ar), (int)(half + 0.5f), color);
      }
      continue;
    }
    if (st == State::Error) {  // x x
      int m = (int)(ew * 0.3f);
      g.wideLine(mx - m, cy - m, mx + m, cy + m, 4 * s, color);
      g.wideLine(mx + m, cy - m, mx - m, cy + m, 4 * s, color);
      continue;
    }
    g.fillRoundRect((int)ex, (int)ey, (int)ew, (int)eh, (int)fminf(r, eh / 2), color);
    // Eyelids: cut the top off with the background colour.
    if (pose_.lid > 0.02f || pose_.sad > 0.02f) {
      float lidY = ey + eh * pose_.lid;
      float tilt = pose_.sad * 14 * s * side;  // sad: outer corners droop
      int x0 = (int)ex - 4, x1 = (int)(ex + ew) + 4, top = (int)ey - 4;
      int yl = (int)(lidY + fmaxf(0, -tilt)), yr = (int)(lidY + fmaxf(0, tilt));
      g.fillTriangle(x0, top, x1, top, x1, yr, BG);
      g.fillTriangle(x0, top, x1, yr, x0, yl, BG);
    }
  }
}

void Ui::drawFace(Gfx& g, int cx, int cy, float s, State st, float now) const {
  uint16_t color = st == State::Idle ? FG : colorOf(st);
  drawEyes(g, cx, cy, s, st, color);
  if (s < 0.8f) return;

  switch (st) {
    case State::Thinking:
      for (int i = 0; i < 3; i++) {
        float a = 0.25f + 0.75f * fmaxf(0, sinf(now * 4 - i * 0.7f));
        g.fillCircle(cx + 78 + i * 11, cy - 58, 4, blend(color, BG, a));
      }
      break;
    case State::Running: {
      float a0 = now * 6 * 180 / kPi;
      arc(g, cx + 112, cy - 50, 7, 10, a0, a0 + 234, color);
      break;
    }
    case State::Waiting: {
      float sc = 1 + 0.12f * sinf(now * 8);
      int x = cx + 112, y = cy - 46;
      g.fillRoundRect((int)(x - 3 * sc), (int)(y - 16 * sc), (int)(6 * sc), (int)(20 * sc), (int)(3 * sc), color);
      g.fillCircle(x, (int)(y + 11 * sc), (int)(3.5f * sc + 0.5f), color);
      break;
    }
    case State::Done: {
      static const int pts[][2] = {{-110, -48}, {104, -54}, {-96, 40}, {112, 30}, {0, -70}};
      for (int i = 0; i < 5; i++) {
        float a = fmaxf(0, sinf(now * 3 + i * 1.7f));
        if (a < 0.05f) continue;
        float r = 2 + a * 4;
        uint16_t c = blend(color, BG, a);
        diamond(g, cx + pts[i][0], cy + pts[i][1], r * 0.4f, r * 1.6f, c);
        diamond(g, cx + pts[i][0], cy + pts[i][1], r * 1.6f, r * 0.4f, c);
      }
      break;
    }
    case State::Error: {
      float p = fmodf(now * 0.8f, 1);
      int x = cx + 104, y = (int)(cy - 40 + p * 10);
      uint16_t c = blend(SWEAT, BG, 1 - p * 0.6f);
      g.fillCircle(x, y + 1, 4, c);
      g.fillTriangle(x, y - 7, x - 4, y, x + 4, y, c);
      break;
    }
    case State::Offline: {
      static const Font sizes[] = {Font::Tiny, Font::Small, Font::Medium};
      for (int i = 0; i < 3; i++) {
        float p = fmodf(now * 0.5f + i / 3.0f, 1);
        g.text("z", (int)(cx + 92 + p * 18 + i * 4), (int)(cy - 30 - p * 34), sizes[i], blend(DIM, BG, 1 - p));
      }
      break;
    }
    case State::Editing:
      if ((int)(now * 2) % 2) g.fillRect(cx - 14, cy + 46, 28, 4, color);
      break;
    default:
      break;
  }
}

// ---------- chrome ----------

void Ui::topBar(Gfx& g, const Model& m, float now) const {
  LocalTime lt;
  char hm[8] = "--:--";
  if (localTime(m, now, &lt)) snprintf(hm, sizeof(hm), "%02d:%02d", lt.hour, lt.minute);
  g.text(hm, 10, 18, Font::Label, FG);
  if (!m.connected) {
    g.text("NO LINK", 10, 34, Font::Tiny, colorOf(State::Error));
    return;
  }

  // Full names fit for two agents; abbreviations beyond, smaller if still too wide.
  bool shortNames = m.count > 2;
  Font f = Font::Small;
  int gap = shortNames ? 18 : 22;
  int room = W - 8 - 62, total = 0;
  for (int i = 0; i < m.count; i++) {
    total += g.textWidth(shortNames ? m.agents[i].abbr : m.agents[i].label, f) + gap;
  }
  if (total > room) {
    f = Font::Tiny;
    gap = 14;
  }
  int x = W - 8;
  for (int i = m.count - 1; i >= 0; i--) {
    const Agent& a = m.agents[i];
    const char* tag = shortNames ? a.abbr : a.label;
    int w = g.textWidth(tag, f);
    g.text(tag, x, 17, f, a.state == State::Offline ? DIM : FG, Align::Right);
    float pulse = a.alert ? 0.5f + 0.5f * sinf(now * 8) : 1;
    g.fillCircle(x - w - 7, 12, f == Font::Tiny ? 3 : 4, blend(colorOf(a.state), BG, pulse));
    x -= w + gap;
  }
}

void Ui::alertRing(Gfx& g, const Model& m, float now) const {
  bool alert = anyAlert(m);
  if (!alert && faceState(m) != State::Waiting) return;
  float a = alert ? 0.45f + 0.45f * sinf(now * 6) : 0.25f;
  uint16_t c = blend(colorOf(State::Waiting), BG, a);
  for (int i = 0; i < 4; i++) g.drawRoundRect(2 + i, 2 + i, W - 4 - 2 * i, H - 4 - 2 * i, 10 - i, c);
}

// ---------- views ----------

void Ui::viewFace(Gfx& g, const Model& m, float now) const {
  State st = faceState(m);
  bool previewing = preview_ != State::Count;
  drawFace(g, W / 2, 100, 1, st, now);

  // Hearts float up after feeding or a level-up.
  float age = -1;
  for (float a : {m.pet.fed_age, m.pet.levelup_age}) {
    if (a >= 0 && (age < 0 || a < age)) age = a;
  }
  if (age >= 0) {
    float p = (age + now - m.rx_time) / 2.5f;
    if (p >= 0 && p <= 1) {
      int dxs[] = {-70, 0, 70};
      for (int i = 0; i < 3; i++) {
        heart(g, W / 2 + dxs[i], (int)(70 - p * 40 - i * 6), 1.6f, blend(HEART, BG, 1 - p));
      }
    }
  }
  topBar(g, m, now);

  const Agent* a = m.connected ? agentAt(m, m.focus) : nullptr;
  uint16_t color = colorOf(st);
  const char* label = stateLabel(st);
  g.text(label, 12, 196, Font::Title, color);
  int lw = g.textWidth(label, Font::Title);
  if (a && (previewing || st != State::Offline)) g.text(a->label, 12 + lw + 8, 196, Font::Small, DIM);

  char buf[96];
  if (!previewing && a && a->elapsed >= 0 && busy(st)) {
    fmtDur(a->elapsed + now - m.rx_time, buf, sizeof(buf));
    g.text(buf, W - 12, 196, Font::MonoBold, FG, Align::Right);
  }

  const char* detail = previewing ? "preview" : (a ? a->detail : "");
  if (!previewing && st == State::Offline) {
    detail = m.connected ? "waiting for an agent..." : "run: deskpet --serial auto";
  }
  if (!previewing && st == State::Idle) {
    detail = m.pet.mood == Mood::Hungry ? "hungry - press B to feed" : "";
  }
  g.text(fit(g, detail, W - 24, Font::Mono, buf, sizeof(buf)), 12, 214, Font::Mono, SOFT);

  if (!previewing && a && a->state != State::Offline) {
    char bits[96] = "";
    if (a->tools) snprintf(bits + strlen(bits), sizeof(bits) - strlen(bits), "%d tools", a->tools);
    if (a->cwd[0]) snprintf(bits + strlen(bits), sizeof(bits) - strlen(bits), "%s%s", bits[0] ? " | " : "", a->cwd);
    if (a->sessions > 1) {
      snprintf(bits + strlen(bits), sizeof(bits) - strlen(bits), "%s%d sessions", bits[0] ? " | " : "", a->sessions);
    }
    g.text(fit(g, bits, W - 24, Font::Small, buf, sizeof(buf)), 12, 231, Font::Small, DIM);
  }
  alertRing(g, m, now);
}

void Ui::viewClock(Gfx& g, const Model& m, float now) const {
  LocalTime lt;
  char buf[32];
  if (localTime(m, now, &lt)) {
    snprintf(buf, sizeof(buf), "%02d:%02d", lt.hour, lt.minute);
    g.text(buf, W / 2 - 12, 104, Font::Clock, FG, Align::Center);
    snprintf(buf, sizeof(buf), "%02d", lt.second);
    g.text(buf, W / 2 + 112, 104, Font::ClockSec, DIM);
    snprintf(buf, sizeof(buf), "%s, %s %d", kWeekdays[lt.weekday], kMonths[lt.month - 1], lt.day);
    g.text(buf, W / 2, 132, Font::Medium, DIM, Align::Center);
  } else {
    g.text("--:--", W / 2 - 12, 104, Font::Clock, DIM, Align::Center);
    g.text("waiting for time from deskpet", W / 2, 132, Font::Small, DIM, Align::Center);
  }

  drawFace(g, 52, 190, 0.42f, faceState(m), now);
  if (!m.connected) return;
  if (m.count <= 3) {
    int y = 176;
    for (int i = 0; i < m.count; i++, y += 22) {
      const Agent& a = m.agents[i];
      g.fillCircle(116, y - 4, 4, colorOf(a.state));
      g.text(a.label, 128, y, Font::Small, FG);
      g.text(stateLabel(a.state), 200, y, Font::Small, colorOf(a.state));
      if (a.elapsed >= 0 && busy(a.state)) {
        fmtDur(a.elapsed + now - m.rx_time, buf, sizeof(buf));
        g.text(buf, W - 12, y, Font::Small, DIM, Align::Right);
      }
    }
  } else {
    // Two columns of "o DS RUN" chips, up to four rows.
    for (int i = 0; i < m.count; i++) {
      const Agent& a = m.agents[i];
      int x = 104 + (i % 2) * 106, y = 166 + (i / 2) * 18;
      float pulse = a.alert ? 0.5f + 0.5f * sinf(now * 8) : 1;
      g.fillCircle(x + 4, y - 4, 4, blend(colorOf(a.state), BG, pulse));
      g.text(a.abbr, x + 14, y, Font::Small, FG);
      g.text(stateShort(a.state), x + 38, y, Font::Small, colorOf(a.state));
    }
  }
  alertRing(g, m, now);
}

void Ui::viewAgents(Gfx& g, const Model& m, float now) const {
  g.text("AGENTS", 12, 22, Font::Label, DIM);
  if (!m.connected || m.count == 0) {
    g.text(m.connected ? "no agent selected" : "not connected", W / 2, H / 2, Font::Small, DIM, Align::Center);
    return;
  }
  if (m.count > 3) return agentRows(g, m, now);

  int n = m.count;
  int cardH = (H - 36 - 8 * (n - 1)) / n;
  if (cardH > 96) cardH = 96;
  bool compact = cardH < 80;
  char buf[96];
  for (int i = 0; i < n; i++) {
    const Agent& a = m.agents[i];
    uint16_t c = colorOf(a.state);
    int y = 32 + i * (cardH + 8);
    int y1 = y + (compact ? 19 : 24), y2 = y + (compact ? 37 : 46), y3 = y + (compact ? 54 : 68);
    g.fillRoundRect(8, y, W - 16, cardH, 10, CARD);
    g.fillRoundRect(8, y, 5, cardH, 2, c);
    g.text(a.label, 22, y1, Font::Label, FG);
    g.text(stateLabel(a.state), W - 20, y1, Font::Label, c, Align::Right);
    const char* detail = a.detail[0] ? a.detail
                         : a.state == State::Offline ? "not connected"
                         : a.state == State::Done    ? "task finished"
                                                     : "-";
    g.text(fit(g, detail, W - 44, Font::Mono, buf, sizeof(buf)), 22, y2, Font::Mono, SOFT);

    char bits[96] = "";
    if (a.elapsed >= 0 && busy(a.state)) fmtDur(a.elapsed + now - m.rx_time, bits, sizeof(bits));
    if (a.tools) snprintf(bits + strlen(bits), sizeof(bits) - strlen(bits), "%s%d tools", bits[0] ? " | " : "", a.tools);
    if (a.cwd[0]) snprintf(bits + strlen(bits), sizeof(bits) - strlen(bits), "%s%s", bits[0] ? " | " : "", a.cwd);
    if (y3 < y + cardH - 2) g.text(fit(g, bits, W - 44, Font::Small, buf, sizeof(buf)), 22, y3, Font::Small, DIM);

    if (a.alert) {
      uint16_t ring = blend(colorOf(State::Waiting), CARD, 0.5f + 0.5f * sinf(now * 6));
      g.drawRoundRect(8, y, W - 16, cardH, 10, ring);
      g.drawRoundRect(9, y + 1, W - 18, cardH - 2, 9, ring);
    }
  }
}

// Compact list for 4-8 agents: one row each.
void Ui::agentRows(Gfx& g, const Model& m, float now) const {
  int rowH = (H - 40) / m.count;
  if (rowH > 26) rowH = 26;
  char buf[96], dur[16];
  for (int i = 0; i < m.count; i++) {
    const Agent& a = m.agents[i];
    int y = 32 + i * rowH;
    if (i % 2 == 0) g.fillRect(6, y, W - 12, rowH, ROW);
    if (a.alert) g.fillRect(6, y, W - 12, rowH, blend(colorOf(State::Waiting), BG, 0.35f + 0.35f * sinf(now * 6)));
    int base = y + rowH / 2 + 4;
    g.fillCircle(16, base - 4, 4, colorOf(a.state));
    g.text(a.label, 26, base, Font::Small, a.state == State::Offline ? DIM : FG);
    g.text(stateShort(a.state), 106, base, Font::Small, colorOf(a.state));
    bool timed = a.elapsed >= 0 && busy(a.state);
    if (timed) {
      fmtDur(a.elapsed + now - m.rx_time, dur, sizeof(dur));
      g.text(dur, W - 12, base, Font::Small, DIM, Align::Right);
    }
    const char* detail = a.detail[0] ? a.detail : a.cwd;
    g.text(fit(g, detail, W - 160 - (timed ? 44 : 0), Font::Small, buf, sizeof(buf)), 148, base, Font::Small, SOFT);
  }
}

void Ui::viewStats(Gfx& g, const Model& m, float now) const {
  const PetInfo& p = m.pet;
  char buf[64];
  g.text("PET", 12, 22, Font::Label, DIM);
  drawFace(g, 56, 70, 0.5f, p.mood == Mood::Hungry ? State::Idle : faceState(m), now);
  snprintf(buf, sizeof(buf), "LV %d", p.level);
  g.text(buf, 116, 52, Font::Title, FG);
  snprintf(buf, sizeof(buf), "%d / %d XP", p.xp_in_level, p.xp_span);
  g.text(buf, W - 12, 52, Font::Small, DIM, Align::Right);
  bar(g, 116, 60, W - 128, 8, p.xp_span > 0 ? (float)p.xp_in_level / p.xp_span : 0, XP);

  uint16_t moodColor = p.mood == Mood::Happy ? colorOf(State::Done)
                       : p.mood == Mood::Ok  ? colorOf(State::Running)
                                             : colorOf(State::Error);
  snprintf(buf, sizeof(buf), "ENERGY %d", p.energy);
  g.text(buf, 116, 88, Font::Small, DIM);
  g.text(p.mood == Mood::Happy ? "HAPPY" : p.mood == Mood::Ok ? "OK" : "HUNGRY", W - 12, 88, Font::Small,
         moodColor, Align::Right);
  bar(g, 116, 94, W - 128, 8, p.energy / 100.0f, moodColor);

  g.text("TODAY", 12, 132, Font::Label, DIM);
  struct Cell {
    const char* name;
    char value[16];
  } cells[4];
  int n = 0;
  cells[n].name = "TASKS";
  snprintf(cells[n++].value, 16, "%d", p.tasks);
  cells[n].name = "TOOLS";
  snprintf(cells[n++].value, 16, "%d", p.tools);
  cells[n].name = "ERRORS";
  snprintf(cells[n++].value, 16, "%d", p.errors);
  if (m.has_usage) {
    cells[n].name = "CLAUDE OUT";
    fmtNum(m.usage_out, cells[n++].value, 16);
  }
  int cw = (W - 24) / n;
  for (int i = 0; i < n; i++) {
    g.text(cells[i].value, 12 + i * cw, 162, Font::Title, FG);
    g.text(cells[i].name, 12 + i * cw, 178, Font::Tiny, DIM);
  }
  if (m.has_usage) {
    char total[16];
    fmtNum(m.usage_total, total, sizeof(total));
    snprintf(buf, sizeof(buf), "claude tokens today %s", total);
    g.text(buf, 12, 206, Font::Small, DIM);
  } else {
    g.text("usage reading off", 12, 206, Font::Small, DIM);
  }
}

void Ui::draw(Gfx& g, const Model& m, float now) const {
  g.fillRect(0, 0, W, H, BG);
  switch (view_) {
    case View::Face: viewFace(g, m, now); break;
    case View::Clock: viewClock(g, m, now); break;
    case View::Agents: viewAgents(g, m, now); break;
    default: viewStats(g, m, now); break;
  }
  for (int i = 0; i < (int)View::Count; i++) {
    g.fillCircle(W / 2 - 18 + i * 12, H - 4, 2, i == (int)view_ ? FG : FAINT);
  }
  if (toast_[0] && now < toast_until_) {
    int w = g.textWidth(toast_, Font::Label) + 24;
    g.fillRoundRect(W / 2 - w / 2, 34, w, 24, 12, TOAST);
    g.text(toast_, W / 2, 51, Font::Label, FG, Align::Center);
  }
}

}  // namespace pet

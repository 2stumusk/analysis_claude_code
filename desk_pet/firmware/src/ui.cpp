#include "ui.h"

#include "cat_art.h"

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
const float kApprovalArm = 0.8f;  // seconds; same as ARM in web/sim.js

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

// Bytes of the UTF-8 character that starts at `s` (fewer if it is cut short).
int charLen(const char* s) {
  unsigned char c = (unsigned char)*s;
  int n = c >= 0xF0 ? 4 : c >= 0xE0 ? 3 : c >= 0xC0 ? 2 : 1;
  for (int i = 1; i < n; i++) {
    if (((unsigned char)s[i] & 0xC0) != 0x80) return i;
  }
  return n;
}

// Drop a character that a byte-limited copy cut in half.
void trimPartial(char* s) {
  for (int at = 0; s[at];) {
    unsigned char c = (unsigned char)s[at];
    int want = c >= 0xF0 ? 4 : c >= 0xE0 ? 3 : c >= 0xC0 ? 2 : 1;
    int got = charLen(s + at);
    if (got < want) {
      s[at] = 0;
      return;
    }
    at += got;
  }
}

// Clip `s` to `maxW` pixels, ending in "..." when it had to be cut. Never
// splits a UTF-8 character.
const char* fit(Gfx& g, const char* s, int maxW, Font f, char* out, int cap) {
  snprintf(out, cap, "%s", s);
  trimPartial(out);
  if (g.textWidth(out, f) <= maxW) return out;
  int n = (int)strlen(out);
  while (n > 0) {
    do {
      n--;  // back to the first byte of the last character
    } while (n > 0 && ((unsigned char)out[n] & 0xC0) == 0x80);
    if (n + 4 > cap) continue;
    memcpy(out + n, "...", 4);
    if (g.textWidth(out, f) <= maxW) return out;
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
  if (m.pages && !(m.pages & (1 << (int)view_))) nextView(m);  // page was switched off
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

  if (m.approval.active && strcmp(m.approval.id, approval_id_) != 0) {
    snprintf(approval_id_, sizeof(approval_id_), "%s", m.approval.id);
    approval_seen_ = now;
    sound_ = Sound::Waiting;
    last_alert_beep_ = now;
  } else if (!m.approval.active) {
    approval_id_[0] = 0;
  }

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
  // Alerts bring back the face, or the agent list when the face is switched off.
  if (jump && preview_ == State::Count) {
    if (m.pages & PageFace) {
      view_ = View::Face;
    } else if (m.pages & PageAgents) {
      view_ = View::Agents;
    }
  }

  if (anyAlert(m)) {
    if (now - last_alert_beep_ > 8) {
      last_alert_beep_ = now;
      if (sound_ == Sound::None) sound_ = Sound::Waiting;
    }
  } else {
    last_alert_beep_ = -100;
  }
}

bool Ui::approvalShown(const Model& m, float now) const {
  if (!m.approval.active || !m.connected || preview_ != State::Count) return false;
  int64_t daemonNow = m.epoch + (int64_t)(now - m.rx_time);
  return daemonNow < m.approval.deadline;
}

bool Ui::approvalArmed(const Model& m, float now) const {
  return approvalShown(m, now) && strcmp(m.approval.id, approval_id_) == 0 &&
         now - approval_seen_ >= kApprovalArm;
}

void Ui::nextView(const Model& m) {
  uint8_t pages = m.pages ? m.pages : kAllPages;
  for (int i = 1; i <= (int)View::Count; i++) {
    View v = (View)(((int)view_ + i) % (int)View::Count);
    if (pages & (1 << (int)v)) {
      view_ = v;
      return;
    }
  }
}

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
  drawExtras(g, cx, cy, st, color, now);
}

// Thought dots, spinner, "!", sparkles, sweat, zzz: drawn around a face or the cat.
void Ui::drawExtras(Gfx& g, int cx, int cy, State st, uint16_t color, float now) const {
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
  if (m.skin == Skin::Cat) {
    viewCat(g, m, now);
    return;
  }
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
  if (a && (previewing || st != State::Offline)) {
    char who[40];
    if (!previewing && m.rot_count > 1) {
      snprintf(who, sizeof(who), "%s  %d/%d", a->label, m.rot_index + 1, m.rot_count);
    } else {
      snprintf(who, sizeof(who), "%s", a->label);
    }
    g.text(who, 12 + lw + 8, 196, Font::Small, DIM);
  }

  char buf[160];
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
    char bits[160] = "";
    if (a->tools) snprintf(bits + strlen(bits), sizeof(bits) - strlen(bits), "%d tools", a->tools);
    if (a->cwd[0]) snprintf(bits + strlen(bits), sizeof(bits) - strlen(bits), "%s%s", bits[0] ? " | " : "", a->cwd);
    if (a->sessions > 1) {
      snprintf(bits + strlen(bits), sizeof(bits) - strlen(bits), "%s%d sessions", bits[0] ? " | " : "", a->sessions);
    }
    g.text(fit(g, bits, W - 24, Font::Small, buf, sizeof(buf)), 12, 231, Font::Small, DIM);
  }
  alertRing(g, m, now);
}

// ---------- cat skin ----------

namespace {

const char* stateZh(State s) {
  static const char* const kZh[] = {"离线", "空闲", "思考中", "读文件", "改代码", "跑命令", "需要你", "完成啦", "出错了"};
  return kZh[(int)s];
}

// One cat frame at `scale`, as runs of same-coloured pixels per row.
void drawCat(Gfx& g, CatFrame f, int x0, int y0, int scale) {
  for (int y = 0; y < kCatSize; y++) {
    const char* row = kCatFrames[f][y];
    for (int x = 0; x < kCatSize;) {
      char ch = row[x];
      int run = 1;
      while (x + run < kCatSize && row[x + run] == ch) run++;
      int idx = ch <= '9' ? ch - '0' : ch - 'a' + 10;
      if (idx) g.fillRect(x0 + x * scale, y0 + y * scale, run * scale, scale, kCatPalette[idx]);
      x += run;
    }
  }
}

CatFrame catFrame(State st, bool hungry, bool blinking, float now) {
  auto two = [now](CatFrame a, float hz) { return (CatFrame)(a + ((int)(now * hz) & 1)); };
  switch (st) {
    case State::Thinking: return blinking ? kCat_blink : two(kCat_think_0, 1);
    case State::Reading: return two(kCat_read_0, 1.5f);
    case State::Editing: return two(kCat_type_0, 4);
    case State::Running: return two(kCat_type_0, 6);
    case State::Waiting: return two(kCat_wait_0, 3);
    case State::Done: return two(kCat_done_0, 2);
    case State::Error: return two(kCat_error_0, 4);
    case State::Offline: return two(kCat_sleep_0, 0.8f);
    default:
      if (hungry) return two(kCat_hungry_0, 1);
      return blinking ? kCat_blink : two(kCat_idle_0, 0.7f);
  }
}

}  // namespace

// The face page as a pixel cat, with a card underneath: who, what state (in
// Chinese), what it is doing, and how long / how many tools so far. The bar
// only shows activity; hooks give no "percent done", so none is shown.
void Ui::viewCat(Gfx& g, const Model& m, float now) const {
  State st = faceState(m);
  bool previewing = preview_ != State::Count;
  bool hungry = st == State::Idle && m.pet.mood == Mood::Hungry;
  drawCat(g, catFrame(st, hungry, blink_ < 0.5f, now), 96, 32, 4);
  if (st != State::Editing) drawExtras(g, W / 2, 100, st, st == State::Idle ? FG : colorOf(st), now);

  float age = -1;  // hearts after feeding or a level-up, as on the eyes face
  for (float a : {m.pet.fed_age, m.pet.levelup_age}) {
    if (a >= 0 && (age < 0 || a < age)) age = a;
  }
  if (age >= 0) {
    float p = (age + now - m.rx_time) / 2.5f;
    if (p >= 0 && p <= 1) {
      for (int i = 0; i < 3; i++) heart(g, 72 + i * 88, (int)(80 - p * 40 - i * 6), 1.6f, blend(HEART, BG, 1 - p));
    }
  }
  topBar(g, m, now);

  const Agent* a = m.connected ? agentAt(m, m.focus) : nullptr;
  uint16_t color = colorOf(st);
  g.fillRoundRect(10, 166, W - 20, 60, 10, CARD);

  // Who, and the state as a pill on the right.
  char buf[160];
  g.fillCircle(24, 180, 4, color);
  if (a && !previewing && m.rot_count > 1) {
    snprintf(buf, sizeof(buf), "%s  %d/%d", a->label, m.rot_index + 1, m.rot_count);
  } else {
    snprintf(buf, sizeof(buf), "%s", a ? a->label : "DESK PET");
  }
  g.text(buf, 34, 186, Font::Label, FG);
  const char* zh = hungry ? "饿了" : stateZh(st);
  int tw = g.textWidth(zh, Font::Small);
  g.fillRoundRect(W - 22 - tw - 16, 172, tw + 16, 19, 9, blend(color, CARD, 0.25f));
  g.text(zh, W - 22 - tw / 2 - 8, 186, Font::Small, color, Align::Center);

  // What it is doing.
  const char* detail = previewing ? "preview" : (a ? a->detail : "");
  if (!previewing && st == State::Offline) {
    detail = m.connected ? "还没有 Agent 在工作" : "电脑上运行 deskpet --serial auto";
  } else if (!previewing && st == State::Idle) {
    detail = hungry ? "饿了，按 B 喂我" : (a && a->cwd[0] ? a->cwd : "空闲中，随时开工");
  }
  g.text(fit(g, detail, W - 44, Font::Mono, buf, sizeof(buf)), 22, 205, Font::Mono, SOFT);

  // Time and tool count, real numbers from the hooks.
  char stats[64] = "";
  if (!previewing && a && a->elapsed >= 0 && busy(st)) {
    char dur[16];
    fmtDur(a->elapsed + now - m.rx_time, dur, sizeof(dur));
    snprintf(stats, sizeof(stats), "用时 %s", dur);
  }
  if (!previewing && a && a->tools && st != State::Offline) {
    snprintf(stats + strlen(stats), sizeof(stats) - strlen(stats), "%s工具 %d 次", stats[0] ? " · " : "", a->tools);
  }
  int sw = stats[0] ? g.textWidth(stats, Font::Small) : 0;
  if (stats[0]) g.text(stats, W - 22, 220, Font::Small, DIM, Align::Right);

  // Activity bar: a sweep while busy, solid when done / failed, pulsing when it needs you.
  int bx = 22, bw = W - 44 - (sw ? sw + 10 : 0), by = 213;
  if (bw > 20) {
    g.fillRoundRect(bx, by, bw, 5, 2, FAINT);
    if (st == State::Done || st == State::Error) {
      g.fillRoundRect(bx, by, bw, 5, 2, color);
    } else if (st == State::Waiting) {
      g.fillRoundRect(bx, by, bw, 5, 2, blend(color, FAINT, 0.5f + 0.5f * sinf(now * 6)));
    } else if (busy(st)) {
      int seg = bw / 3;
      int pos = (int)fmodf(now * 90, (float)(bw + seg)) - seg;
      int x0 = pos < 0 ? 0 : pos, x1 = pos + seg > bw ? bw : pos + seg;
      if (x1 > x0) g.fillRoundRect(bx + x0, by, x1 - x0, 5, 2, color);
    }
  }
  alertRing(g, m, now);
}

void Ui::viewClock(Gfx& g, const Model& m, float now) const {
  LocalTime lt;
  char buf[64];
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

  const WeatherInfo& w = m.weather;
  if (m.connected && (w.status == WeatherInfo::Status::Ok || w.status == WeatherInfo::Status::Stale)) {
    snprintf(buf, sizeof(buf), "%s  %dC  %s", w.city, w.temp, w.text);
    g.text(buf, W / 2, 154, Font::Small, DIM, Align::Center);
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
  char buf[160];
  for (int i = 0; i < n; i++) {
    const Agent& a = m.agents[i];
    uint16_t c = colorOf(a.state);
    int y = 32 + i * (cardH + 8);
    int y1 = y + (compact ? 19 : 24), y2 = y + (compact ? 37 : 46), y3 = y + (compact ? 54 : 68);
    g.fillRoundRect(8, y, W - 16, cardH, 10, CARD);
    g.fillRoundRect(8, y, 5, cardH, 2, c);
    if (i == m.focus) g.fillTriangle(1, y + cardH / 2 - 5, 6, y + cardH / 2, 1, y + cardH / 2 + 5, FG);
    g.text(a.label, 22, y1, Font::Label, FG);
    g.text(stateLabel(a.state), W - 20, y1, Font::Label, c, Align::Right);
    const char* detail = a.detail[0] ? a.detail
                         : a.state == State::Offline ? "not connected"
                         : a.state == State::Done    ? "task finished"
                                                     : "-";
    g.text(fit(g, detail, W - 44, Font::Mono, buf, sizeof(buf)), 22, y2, Font::Mono, SOFT);

    char bits[160] = "";
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
  char buf[160], dur[16];
  for (int i = 0; i < m.count; i++) {
    const Agent& a = m.agents[i];
    int y = 32 + i * rowH;
    if (i % 2 == 0) g.fillRect(6, y, W - 12, rowH, ROW);
    if (a.alert) g.fillRect(6, y, W - 12, rowH, blend(colorOf(State::Waiting), BG, 0.35f + 0.35f * sinf(now * 6)));
    int base = y + rowH / 2 + 4;
    g.fillCircle(16, base - 4, 4, colorOf(a.state));
    if (i == m.focus) g.fillTriangle(1, base - 9, 6, base - 4, 1, base + 1, FG);
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

// ---------- weather ----------

namespace {

const uint16_t SUN = rgb(0xffd166);
const uint16_t MOON = rgb(0xe8e6e3);
const uint16_t CLOUD = rgb(0xd7dbe0);
const uint16_t CLOUD_DARK = rgb(0x8a929e);
const uint16_t RAIN = rgb(0x7cc4ff);
const uint16_t SNOW = rgb(0xffffff);

int sc(float v, float s) { return (int)(v * s + (v >= 0 ? 0.5f : -0.5f)); }

void cloud(Gfx& g, int cx, int cy, float s, uint16_t c) {
  g.fillCircle(cx + sc(-14, s), cy + sc(4, s), sc(12, s), c);
  g.fillCircle(cx + sc(2, s), cy + sc(-6, s), sc(16, s), c);
  g.fillCircle(cx + sc(16, s), cy + sc(4, s), sc(11, s), c);
  g.fillRoundRect(cx + sc(-26, s), cy + sc(2, s), sc(53, s), sc(14, s), sc(7, s), c);
}

void sun(Gfx& g, int cx, int cy, float s, float spin) {
  g.fillCircle(cx, cy, sc(15, s), SUN);
  if (s < 0.5f) return;
  for (int i = 0; i < 8; i++) {
    float a = spin + i * kPi / 4;
    g.wideLine(cx + (int)(cosf(a) * 21 * s), cy + (int)(sinf(a) * 21 * s), cx + (int)(cosf(a) * 28 * s),
               cy + (int)(sinf(a) * 28 * s), 1.8f * s, SUN);
  }
}

void moon(Gfx& g, int cx, int cy, float s) {
  g.fillCircle(cx, cy, sc(15, s), MOON);
  g.fillCircle(cx + sc(8, s), cy + sc(-6, s), sc(13, s), BG);
}

// Draws a weather icon about 80*s pixels wide centred on (cx, cy).
void weatherIcon(Gfx& g, int cx, int cy, float s, Sky sky, bool day, float now) {
  bool animate = s >= 0.8f;
  float t = animate ? now : 0;
  switch (sky) {
    case Sky::Clear:
      if (day) {
        sun(g, cx, cy, s * 1.15f, t * 0.4f);
      } else {
        moon(g, cx, cy, s * 1.2f);
      }
      break;
    case Sky::Partly:
      if (day) {
        sun(g, cx + sc(-12, s), cy + sc(-10, s), s * 0.75f, t * 0.4f);
      } else {
        moon(g, cx + sc(-12, s), cy + sc(-10, s), s * 0.8f);
      }
      cloud(g, cx + sc(6, s), cy + sc(6, s), s * 0.85f, CLOUD);
      break;
    case Sky::Cloudy:
      cloud(g, cx + sc(10, s), cy + sc(-8, s), s * 0.7f, CLOUD_DARK);
      cloud(g, cx + sc(-2, s), cy + sc(4, s), s, CLOUD);
      break;
    case Sky::Fog:
      for (int i = 0; i < 4; i++) {
        int dx = (i % 2) ? sc(6, s) : sc(-6, s);
        g.fillRoundRect(cx - sc(26, s) + dx, cy + sc(-14 + i * 9, s), sc(52, s), sc(5, s) + 1, sc(2.5f, s), CLOUD);
      }
      break;
    case Sky::Drizzle:
    case Sky::Rain:
    case Sky::Snow: {
      cloud(g, cx, cy + sc(-8, s), s, sky == Sky::Snow ? CLOUD : CLOUD_DARK);
      float fall = animate ? fmodf(t * 1.2f, 1) : 0.4f;
      for (int i = 0; i < 3; i++) {
        int x = cx + sc(-14 + i * 14, s);
        int y = cy + sc(16 + fall * 8 + (i % 2) * 5, s);
        if (sky == Sky::Rain) {
          g.wideLine(x + sc(3, s), y - sc(5, s), x - sc(1, s), y + sc(4, s), 1.6f * s + 0.4f, RAIN);
        } else if (sky == Sky::Drizzle) {
          g.fillCircle(x, y, sc(2, s) + 1, RAIN);
        } else {
          g.fillCircle(x, y, sc(3, s) + 1, SNOW);
        }
      }
      break;
    }
    case Sky::Thunder:
      cloud(g, cx, cy + sc(-8, s), s, CLOUD_DARK);
      g.fillTriangle(cx + sc(2, s), cy + sc(4, s), cx + sc(-8, s), cy + sc(20, s), cx + sc(1, s), cy + sc(20, s), SUN);
      g.fillTriangle(cx + sc(-1, s), cy + sc(17, s), cx + sc(8, s), cy + sc(17, s), cx + sc(-4, s), cy + sc(34, s), SUN);
      break;
  }
}

}  // namespace

void Ui::viewWeather(Gfx& g, const Model& m, float now) const {
  const WeatherInfo& w = m.weather;
  char buf[64];
  bool ready = m.connected && (w.status == WeatherInfo::Status::Ok || w.status == WeatherInfo::Status::Stale);
  if (!ready) {
    weatherIcon(g, W / 2, 78, 1, Sky::Partly, true, now);
    const char* title = !m.connected                                 ? "not connected"
                        : w.status == WeatherInfo::Status::Off       ? "no city set"
                        : w.status == WeatherInfo::Status::Error     ? "weather unavailable"
                                                                     : "loading weather...";
    g.text(title, W / 2, 150, Font::Label, FG, Align::Center);
    if (m.connected && w.status == WeatherInfo::Status::Off) {
      g.text("run: deskpet --city Wuxi", W / 2, 172, Font::Small, DIM, Align::Center);
    } else if (w.city[0]) {
      g.text(w.city, W / 2, 172, Font::Small, DIM, Align::Center);
    }
    return;
  }

  g.text(w.city, 12, 22, Font::Label, FG);
  if (w.sample) {
    snprintf(buf, sizeof(buf), "sample data");
  } else if (w.age_min < 1) {
    snprintf(buf, sizeof(buf), "just updated");
  } else {
    snprintf(buf, sizeof(buf), "%supdated %d min ago", w.status == WeatherInfo::Status::Stale ? "stale: " : "",
             w.age_min);
  }
  g.text(buf, W - 12, 21, Font::Small, w.status == WeatherInfo::Status::Stale ? colorOf(State::Running) : DIM,
         Align::Right);

  weatherIcon(g, 70, 84, 1.25f, w.sky, w.day, now);

  // Temperature with a hand-drawn degree sign (the fonts are ASCII only).
  snprintf(buf, sizeof(buf), "%d", w.temp);
  g.text(buf, 140, 104, Font::Clock, FG);
  int tw = g.textWidth(buf, Font::Clock);
  g.fillCircle(140 + tw + 9, 58, 6, FG);
  g.fillCircle(140 + tw + 9, 58, 3, BG);
  g.text("C", 140 + tw + 18, 72, Font::Medium, FG);

  g.text(w.text, 140, 128, Font::Label, FG);
  if (w.hi > -99 && w.lo > -99) {
    snprintf(buf, sizeof(buf), "H %d  L %d", w.hi, w.lo);
    g.text(buf, 140, 148, Font::Small, DIM);
  }
  int len = snprintf(buf, sizeof(buf), "feels %d  hum %d%%  wind %d", w.feels, w.humidity, w.wind);
  if (w.pop >= 0) snprintf(buf + len, sizeof(buf) - len, "  rain %d%%", w.pop);
  g.text(buf, 12, 170, Font::Small, DIM);

  // Next hours.
  int colW = (W - 20) / 6;
  for (int i = 0; i < w.hours; i++) {
    const HourForecast& h = w.hour[i];
    int x = 10 + colW * i + colW / 2;
    snprintf(buf, sizeof(buf), "%02d:00", h.hour);
    g.text(buf, x, 190, Font::Tiny, DIM, Align::Center);
    weatherIcon(g, x, 204, 0.32f, h.sky, h.day, now);
    snprintf(buf, sizeof(buf), "%d", h.temp);
    g.text(buf, x, 228, Font::Small, FG, Align::Center);
  }
}

// Mirrors viewApproval in web/sim.js: what is asked, a countdown, and what each key does.
void Ui::viewApproval(Gfx& g, const Model& m, float now) const {
  const Approval& ap = m.approval;
  float left = (float)(ap.deadline - m.epoch) - (now - m.rx_time);
  if (left < 0) left = 0;
  uint16_t warn = colorOf(State::Waiting);
  float pulse = 0.55f + 0.45f * sinf(now * 6);
  for (int i = 0; i < 4; i++) {
    g.drawRoundRect(2 + i, 2 + i, W - 4 - 2 * i, H - 4 - 2 * i, 10 - i, blend(warn, BG, pulse));
  }
  char buf[160];
  snprintf(buf, sizeof(buf), "%s asks to use", ap.label);
  g.text(buf, 14, 24, Font::Small, DIM);
  snprintf(buf, sizeof(buf), "%ds", (int)ceilf(left));
  g.text(buf, W - 14, 24, Font::MonoBold, left < 6 ? colorOf(State::Error) : FG, Align::Right);
  g.text(fit(g, ap.tool, W - 28, Font::Title, buf, sizeof(buf)), 14, 52, Font::Title, warn);

  // The command / file / URL, wrapped at whatever character fills the line
  // (commands rarely have spaces in the right places).
  g.fillRoundRect(12, 62, W - 24, 90, 8, CARD);
  const char* rest = ap.detail;
  for (int line = 0; line < 5 && *rest; line++) {
    int n = 0;
    while (rest[n]) {
      int step = charLen(rest + n);
      snprintf(buf, sizeof(buf), "%.*s", n + step, rest);
      if (n && g.textWidth(buf, Font::Mono) > W - 44) break;
      n += step;
    }
    if (line == 4 && rest[n]) {
      fit(g, rest, W - 44, Font::Mono, buf, sizeof(buf));
    } else {
      snprintf(buf, sizeof(buf), "%.*s", n, rest);
    }
    g.text(buf, 22, 80 + line * 16, Font::Mono, FG);
    rest += n;
  }
  bar(g, 12, 158, W - 24, 4, left / (float)ap.wait, left < 6 ? colorOf(State::Error) : warn);

  float a = approvalArmed(m, now) ? 1.0f : 0.35f;
  struct Key { const char* word; int x; uint16_t c; };
  const Key three[] = {{"DENY", 64, colorOf(State::Error)}, {"ALLOW", 160, colorOf(State::Done)},
                       {"LATER", 256, DIM}};
  const Key two[] = {{"DENY", 80, colorOf(State::Error)}, {"ALLOW", 240, colorOf(State::Done)}};
  const Key* keys = halves_ ? two : three;
  int n = halves_ ? 2 : 3;
  for (int i = 0; i < n; i++) {
    uint16_t c = blend(keys[i].c, BG, a);
    g.fillRoundRect(keys[i].x - 40, 176, 80, 30, 15, c);
    g.text(keys[i].word, keys[i].x, 196, Font::Label, BG, Align::Center);
    g.fillTriangle(keys[i].x - 6, 214, keys[i].x + 6, 214, keys[i].x, 222, c);
  }
  if (halves_) g.text("hold anywhere: decide on computer", W / 2, 230, Font::Tiny, DIM, Align::Center);
}

void Ui::draw(Gfx& g, const Model& m, float now) const {
  g.fillRect(0, 0, W, H, BG);
  if (approvalShown(m, now)) {
    viewApproval(g, m, now);
  } else switch (view_) {
    case View::Face: viewFace(g, m, now); break;
    case View::Clock: viewClock(g, m, now); break;
    case View::Weather: viewWeather(g, m, now); break;
    case View::Agents: viewAgents(g, m, now); break;
    default: viewStats(g, m, now); break;
  }
  // One dot per enabled page.
  uint8_t pages = m.pages ? m.pages : kAllPages;
  int n = 0, at = 0;
  for (int i = 0; i < (int)View::Count; i++) n += (pages >> i) & 1;
  for (int i = 0; i < (int)View::Count && !approvalShown(m, now); i++) {
    if (!((pages >> i) & 1)) continue;
    g.fillCircle(W / 2 - (n - 1) * 6 + at * 12, H - 4, 2, i == (int)view_ ? FG : FAINT);
    at++;
  }
  if (toast_[0] && now < toast_until_) {
    int w = g.textWidth(toast_, Font::Label) + 24;
    g.fillRoundRect(W / 2 - w / 2, 34, w, 24, 12, TOAST);
    g.text(toast_, W / 2, 51, Font::Label, FG, Align::Center);
  }
}

}  // namespace pet

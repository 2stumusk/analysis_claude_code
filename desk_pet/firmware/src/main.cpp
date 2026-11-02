// deskpet firmware: shows what your coding agents are doing.
//
// The PC runs `python -m deskpet --serial auto`, which sends one JSON frame per
// line over USB (see frame.h). The device draws the frame, plays chimes, and
// reports button B back so the daemon can acknowledge alerts or feed the pet.
//
// Boards (LovyanGFX autodetect picks the panel and touch controller):
//   M5Stack Basic / Gray   buttons A B C, speaker on GPIO25
//   M5Stack Core2          touch strip under the screen as A B C, no sound yet
//   ESP32-2432S028 "CYD"   touch: left half A, right half B; speaker connector
//                          on GPIO26, RGB LED
// A: next page (hold: sound on/off)  B: acknowledge the agent on screen, or feed
// the pet (hold: acknowledge every agent)  C: sound on/off
// While a permission request is on screen: A deny, B allow, C (or any hold)
// leave it to the computer.
// Night mode (set on the PC): the screen dims or goes dark; alerts and
// permission requests light it up, and a key press wakes it for 30 s (the
// press that wakes a dark screen does nothing else).
#include <Arduino.h>
#include <LGFX_AUTODETECT.hpp>
#include <LovyanGFX.hpp>
#include <Preferences.h>

#include "frame.h"
#include "gfx_lgfx.h"
#include "model.h"
#include "ui.h"

#ifndef DESKPET_FW_VERSION
#define DESKPET_FW_VERSION "dev"
#endif

using namespace pet;

namespace {

LGFX lcd;
lgfx::LGFX_Sprite band(&lcd);
LgfxGfx gfx(band);
int bandHeight = H;

Ui ui;
Model model;
Preferences prefs;
bool muted = false;

const uint32_t kBaud = 115200;
const float kLinkTimeout = 15;  // the daemon sends at least every 5 s
const uint32_t kLongPressMs = 800;
const uint8_t kBright = 160, kDim = 16;
const float kWakeSeconds = 30;
float awakeUntil = -100;   // a key press keeps the screen lit at night until then
uint8_t brightness = 0;

float nowSeconds() { return millis() / 1000.0f; }

// ---------- board ----------

enum class Kind : uint8_t { M5Basic, M5Core2, Cyd, Other };
Kind kind = Kind::Other;
int speakerPin = -1;
const int kCydLed[3] = {4, 16, 17};  // R G B, active low

const char* kindName() {
  switch (kind) {
    case Kind::M5Basic: return "m5stack-basic";
    case Kind::M5Core2: return "m5stack-core2";
    case Kind::Cyd: return "esp32-2432s028";
    default: return "unknown";
  }
}

void boardBegin() {
  switch (lcd.getBoard()) {
    case lgfx::board_t::board_M5Stack: kind = Kind::M5Basic; break;
    case lgfx::board_t::board_M5StackCore2: kind = Kind::M5Core2; break;
    case lgfx::board_t::board_Sunton_ESP32_2432S028: kind = Kind::Cyd; break;
    default: kind = Kind::Other; break;
  }
  if (kind == Kind::M5Basic) {
    for (int pin : {39, 38, 37}) pinMode(pin, INPUT);
    speakerPin = 25;
  } else if (kind == Kind::Cyd) {
    speakerPin = 26;
    for (int pin : kCydLed) {
      pinMode(pin, OUTPUT);
      digitalWrite(pin, HIGH);
    }
  }
  if (speakerPin >= 0) {
    ledcAttach(speakerPin, 1000, 10);
    ledcWrite(speakerPin, 0);
  }
}

// Which button is held right now (A=1, B=2, C=3), 0 for none.
int rawButton() {
  if (kind == Kind::M5Basic) {
    if (digitalRead(39) == LOW) return 1;
    if (digitalRead(38) == LOW) return 2;
    if (digitalRead(37) == LOW) return 3;
    return 0;
  }
  int32_t x, y;
  if (!lcd.getTouch(&x, &y)) return 0;
  if (kind == Kind::M5Core2) {  // the strip below the panel reports y 240..279
    if (y < H) return 0;
    return x < 107 ? 1 : (x < 213 ? 2 : 3);
  }
  return x < W / 2 ? 1 : 2;
}

enum Event { kNone, kA, kB, kC, kBLong };

// One event per release; holding A means C (boards without a C button), holding B means "all".
int pollButton() {
  static int held = 0;
  static uint32_t since = 0;
  int b = rawButton();
  uint32_t ms = millis();
  if (b && !held) {
    held = b;
    since = ms;
  } else if (!b && held) {
    bool longPress = ms - since >= kLongPressMs;
    int event = !longPress ? held : held == kB ? kBLong : kC;
    held = 0;
    if (ms - since >= 30) return event;  // debounce
  }
  return 0;
}

void setLed(bool on, uint16_t c) {
  if (kind != Kind::Cyd) return;
  bool r = on && ((c >> 11) & 31) > 12, g = on && ((c >> 5) & 63) > 24, b = on && (c & 31) > 12;
  digitalWrite(kCydLed[0], r ? LOW : HIGH);
  digitalWrite(kCydLed[1], g ? LOW : HIGH);
  digitalWrite(kCydLed[2], b ? LOW : HIGH);
}

// ---------- sound ----------

struct Note {
  uint16_t freq, ms;
};
const Note kWaiting[] = {{880, 140}, {0, 40}, {660, 200}, {0, 0}};
const Note kDone[] = {{660, 100}, {880, 100}, {1320, 220}, {0, 0}};
const Note kError[] = {{220, 300}, {0, 0}};
const Note kClick[] = {{1400, 25}, {0, 0}};
// Unanswered too long: three quick high beeps, twice.
const Note kUrgent[] = {{1320, 90}, {0, 50}, {1320, 90}, {0, 50}, {1320, 90}, {0, 250},
                        {1320, 90}, {0, 50}, {1320, 90}, {0, 50}, {1320, 90}, {0, 0}};
const Note* playing = nullptr;
uint32_t noteEnds = 0;

void startNote() {
  if (playing->freq) {
    ledcWriteTone(speakerPin, playing->freq);
    ledcWrite(speakerPin, 48);  // ~5% duty: quieter than the default 50%
  } else {
    ledcWrite(speakerPin, 0);
  }
  noteEnds = millis() + playing->ms;
}

void play(Sound s) {
  if (speakerPin < 0 || muted || s == Sound::None) return;
  playing = s == Sound::Waiting ? kWaiting
            : s == Sound::Urgent ? kUrgent
            : s == Sound::Done   ? kDone
            : s == Sound::Error  ? kError
                                 : kClick;
  startNote();
}

void soundTick() {
  if (!playing || (int32_t)(millis() - noteEnds) < 0) return;
  playing++;
  if (playing->ms == 0) {
    ledcWrite(speakerPin, 0);
    playing = nullptr;
    return;
  }
  startNote();
}

// ---------- link ----------

char line[4096];
size_t lineLen = 0;
bool overflow = false;
uint32_t lastHello = 0;

void sendHello() {
  Serial.printf("{\"hello\":\"deskpet\",\"fw\":\"%s\",\"board\":\"%s\"}\n", DESKPET_FW_VERSION, kindName());
}

void linkPoll() {
  while (Serial.available()) {
    int ch = Serial.read();
    if (ch == '\n') {
      line[lineLen] = 0;
      if (!overflow && lineLen && line[0] == '{') parseFrame(line, model, nowSeconds());
      lineLen = 0;
      overflow = false;
    } else if (ch != '\r') {
      if (lineLen < sizeof(line) - 1) {
        line[lineLen++] = (char)ch;
      } else {
        overflow = true;
      }
    }
  }
  float now = nowSeconds();
  if (model.connected && now - model.rx_time > kLinkTimeout) model.connected = false;
  // Announce ourselves until the daemon talks to us, so it can find the port.
  if (!model.connected && millis() - lastHello > 2000) {
    lastHello = millis();
    sendHello();
  }
}

// Answer the permission request on screen. Holding a key never allows.
void onApproval(int b, float now) {
  if (!ui.approvalArmed(model, now)) return;  // just appeared: ignore stray presses
  const char* decision = b == kA ? "deny" : b == kB ? "allow" : "skip";
  Serial.printf("{\"approval\":\"%s\",\"decision\":\"%s\"}\n", model.approval.id, decision);
  char text[24];
  snprintf(text, sizeof(text), "%s: %s",
           b == kA ? "denied" : b == kB ? "allowed" : "on computer", model.approval.label);
  ui.showToast(text, now);
  model.approval.active = false;  // the daemon's next frame confirms it
  play(Sound::Click);
}

bool needsYou(const Model& m, float now) {
  if (ui.approvalShown(m, now)) return true;
  for (int i = 0; i < m.count; i++) {
    if (m.agents[i].alert) return true;
  }
  return false;
}

// Brightness for night mode; 0 means the screen is off and not drawn.
uint8_t targetBrightness(float now) {
  if (!model.connected || model.night == Night::Day) return kBright;
  if (now < awakeUntil || needsYou(model, now)) return kBright;
  return model.night == Night::Dim ? kDim : 0;
}

void onButton(int b) {
  float now = nowSeconds();
  bool dark = brightness == 0;
  if (model.night != Night::Day) awakeUntil = now + kWakeSeconds;
  if (dark) return;  // this press only woke the screen
  if (ui.approvalShown(model, now)) {
    onApproval(b, now);
    return;
  }
  if (b == kA) {
    ui.nextView(model);
    play(Sound::Click);
  } else if (b == kB) {
    // Name the agent that is on screen, so a rotation between press and
    // arrival cannot acknowledge a different one.
    const Agent* a = model.focus >= 0 ? &model.agents[model.focus] : nullptr;
    if (a) {
      Serial.printf("{\"btn\":\"B\",\"agent\":\"%s\"}\n", a->id);
    } else {
      Serial.println("{\"btn\":\"B\"}");
    }
    bool ack = a && (a->alert || a->state == State::Done || a->state == State::Error);
    char text[24];
    snprintf(text, sizeof(text), "OK: %s", a ? a->label : "");
    ui.showToast(!model.connected ? "no link" : ack ? text : "yum! +energy", now);
    play(Sound::Click);
  } else if (b == kBLong) {
    Serial.println("{\"btn\":\"B\",\"all\":1}");
    ui.showToast(model.connected ? "all clear" : "no link", now);
    play(Sound::Click);
  } else if (b == kC) {
    muted = !muted;
    prefs.putBool("mute", muted);
    ui.showToast(muted ? "sound off" : "sound on", now);
    play(Sound::Click);
  }
}

}  // namespace

void setup() {
  Serial.setRxBufferSize(8192);
  Serial.begin(kBaud);
  lcd.init();
  if (lcd.width() < lcd.height()) lcd.setRotation(lcd.getRotation() ^ 1);
  lcd.setBrightness(kBright);
  brightness = kBright;
  lcd.fillScreen(TFT_BLACK);
  boardBegin();
  ui.setHalves(kind != Kind::M5Basic && kind != Kind::M5Core2);
  prefs.begin("deskpet", false);
  muted = prefs.getBool("mute", false);
  ui.seed(esp_random());

  // A full-screen 16-bit sprite needs 150 KB; without PSRAM draw in bands.
  band.setColorDepth(16);
  band.setPsram(psramFound());
  for (int h : {H, H / 2, H / 3, H / 4, H / 6}) {
    if ((h == H && !psramFound()) || H % h) continue;
    if (band.createSprite(W, h)) {
      bandHeight = h;
      break;
    }
  }
  sendHello();
}

void loop() {
  uint32_t start = millis();
  linkPoll();
  int b = pollButton();
  if (b) onButton(b);

  float now = nowSeconds();
  ui.update(model, now);
  Sound sound = ui.takeSound();
  // At night only "needs you" makes a sound; finished tasks stay quiet.
  if (model.night == Night::Day || sound == Sound::Waiting || sound == Sound::Urgent || sound == Sound::Click) {
    play(sound);
  }
  uint16_t ledColor = 0;
  bool ledOn = ui.led(model, now, &ledColor);
  uint8_t want = targetBrightness(now);
  setLed(ledOn && (model.night == Night::Day || needsYou(model, now)), ledColor);
  if (want != brightness) {
    brightness = want;
    lcd.setBrightness(brightness);
  }

  for (int y = 0; y < H && brightness > 0; y += bandHeight) {
    gfx.setBand(y);
    ui.draw(gfx, model, now);
    band.pushSprite(&lcd, 0, y);
    linkPoll();  // keep the UART buffer drained between bands
    soundTick();
  }

  uint32_t spent = millis() - start;
  if (spent < 33) delay(33 - spent);  // ~30 fps at most
  soundTick();
}

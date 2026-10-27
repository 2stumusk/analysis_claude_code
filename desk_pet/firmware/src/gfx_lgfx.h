// Gfx on a LovyanGFX sprite that covers one horizontal band of the screen.
#pragma once

#include <LovyanGFX.hpp>

#include "gfx.h"

namespace pet {

class LgfxGfx : public Gfx {
 public:
  explicit LgfxGfx(lgfx::LGFX_Sprite& s) : s_(s) {}

  // Top row of the screen that the sprite currently holds.
  void setBand(int y) { dy_ = y; }

  void fillRect(int x, int y, int w, int h, uint16_t c) override { s_.fillRect(x, y - dy_, w, h, c); }
  void fillRoundRect(int x, int y, int w, int h, int r, uint16_t c) override {
    s_.fillRoundRect(x, y - dy_, w, h, r, c);
  }
  void drawRoundRect(int x, int y, int w, int h, int r, uint16_t c) override {
    s_.drawRoundRect(x, y - dy_, w, h, r, c);
  }
  void fillCircle(int x, int y, int r, uint16_t c) override { s_.fillCircle(x, y - dy_, r, c); }
  void fillTriangle(int x0, int y0, int x1, int y1, int x2, int y2, uint16_t c) override {
    s_.fillTriangle(x0, y0 - dy_, x1, y1 - dy_, x2, y2 - dy_, c);
  }
  void fillArc(int x, int y, int r0, int r1, float a0, float a1, uint16_t c) override {
    s_.fillArc(x, y - dy_, r0, r1, a0, a1, c);
  }
  void wideLine(int x0, int y0, int x1, int y1, float r, uint16_t c) override {
    s_.drawWideLine(x0, y0 - dy_, x1, y1 - dy_, r, c);
  }
  void text(const char* str, int x, int baseline, Font f, uint16_t c, Align a) override {
    s_.setFont(font(f));
    s_.setTextColor(c);  // no background: transparent
    s_.setTextDatum(a == Align::Left     ? lgfx::textdatum_t::baseline_left
                    : a == Align::Center ? lgfx::textdatum_t::baseline_center
                                         : lgfx::textdatum_t::baseline_right);
    s_.drawString(str, x, baseline - dy_);
  }
  int textWidth(const char* str, Font f) override {
    s_.setFont(font(f));
    return s_.textWidth(str);
  }

  static const lgfx::IFont* font(Font f) {
    switch (f) {
      case Font::Tiny: return &fonts::DejaVu9;
      case Font::Small: return &fonts::DejaVu12;
      case Font::Medium: return &fonts::DejaVu18;
      case Font::Label: return &fonts::FreeSansBold9pt7b;
      case Font::Title: return &fonts::FreeSansBold12pt7b;
      case Font::Mono: return &fonts::FreeMono9pt7b;
      case Font::MonoBold: return &fonts::FreeMonoBold9pt7b;
      case Font::ClockSec: return &fonts::DejaVu24;
      case Font::Clock: return &fonts::DejaVu72;
      default: return &fonts::DejaVu12;
    }
  }

 private:
  lgfx::LGFX_Sprite& s_;
  int dy_ = 0;
};

}  // namespace pet

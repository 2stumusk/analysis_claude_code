// The small drawing surface the UI is written against.
//
// On the device it forwards to a LovyanGFX sprite (gfx_lgfx.h); the desktop
// preview records the calls instead (tools/preview). Coordinates are screen
// pixels on the 320x240 display; text is positioned by its baseline.
#pragma once

#include <stdint.h>

namespace pet {

constexpr int W = 320;
constexpr int H = 240;

// Fonts built into LovyanGFX (Adafruit GFX format, ASCII 0x20-0x7E).
enum class Font : uint8_t {
  Tiny,       // DejaVu9
  Small,      // DejaVu12
  Medium,     // DejaVu18
  Label,      // FreeSansBold9pt7b
  Title,      // FreeSansBold12pt7b
  Mono,       // FreeMono9pt7b
  MonoBold,   // FreeMonoBold9pt7b
  ClockSec,   // DejaVu24
  Clock,      // DejaVu72
  Count
};

enum class Align : uint8_t { Left, Center, Right };

constexpr uint16_t rgb(uint32_t hex) {
  return (uint16_t)(((hex >> 8) & 0xF800) | ((hex >> 5) & 0x07E0) | ((hex >> 3) & 0x001F));
}

// Mix `c` over `bg` with opacity `a` (0..1): stands in for alpha on a 565 screen.
inline uint16_t blend(uint16_t c, uint16_t bg, float a) {
  if (a >= 1.0f) return c;
  if (a <= 0.0f) return bg;
  int r = ((c >> 11) & 31) * a + ((bg >> 11) & 31) * (1 - a);
  int g = ((c >> 5) & 63) * a + ((bg >> 5) & 63) * (1 - a);
  int b = (c & 31) * a + (bg & 31) * (1 - a);
  return (uint16_t)((r << 11) | (g << 5) | b);
}

class Gfx {
 public:
  virtual ~Gfx() {}
  virtual void fillRect(int x, int y, int w, int h, uint16_t c) = 0;
  virtual void fillRoundRect(int x, int y, int w, int h, int r, uint16_t c) = 0;
  virtual void drawRoundRect(int x, int y, int w, int h, int r, uint16_t c) = 0;
  virtual void fillCircle(int x, int y, int r, uint16_t c) = 0;
  virtual void fillTriangle(int x0, int y0, int x1, int y1, int x2, int y2, uint16_t c) = 0;
  // Ring segment between radii r0 < r1, angles in degrees, 0 = +x, clockwise.
  virtual void fillArc(int x, int y, int r0, int r1, float a0, float a1, uint16_t c) = 0;
  // Line with round caps; `r` is half the stroke width.
  virtual void wideLine(int x0, int y0, int x1, int y1, float r, uint16_t c) = 0;
  virtual void text(const char* s, int x, int baseline, Font f, uint16_t c, Align a = Align::Left) = 0;
  virtual int textWidth(const char* s, Font f) = 0;
};

}  // namespace pet

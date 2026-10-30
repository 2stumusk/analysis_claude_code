// Desktop harness for the firmware UI and frame parser (no hardware, no LovyanGFX).
//
//   preview_main render <metrics>   stdin: "<name>\t<view>\t<preview>\t<time>\t<frame json>"
//                                   stdout: drawing commands, rendered by preview.py
//   preview_main parse              stdin: frame json lines; stdout: what the device understood
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <string>

#include "../src/frame.h"
#include "../src/ui.h"

using namespace pet;

namespace {

int advances[(int)Font::Count][95];
// Text with any non-ASCII byte is drawn in efontCN_12 (gfx_lgfx.h): 6 px per
// character, 12 px for the code points listed here.
bool wide[0x10000];

bool loadMetrics(const char* path) {
  FILE* f = fopen(path, "r");
  if (!f) return false;
  int font;
  while (fscanf(f, "%d", &font) == 1 && font >= 0 && font < (int)Font::Count) {
    for (int i = 0; i < 95; i++) {
      if (fscanf(f, "%d", &advances[font][i]) != 1) {
        fclose(f);
        return false;
      }
    }
  }
  int cp;
  while (fscanf(f, "%d", &cp) == 1) {  // after "-1": the wide code points
    if (cp > 0 && cp < 0x10000) wide[cp] = true;
  }
  fclose(f);
  return true;
}

// Records every call; widths come from the same font tables the device uses.
class Recorder : public Gfx {
 public:
  void fillRect(int x, int y, int w, int h, uint16_t c) override { printf("R %d %d %d %d %u\n", x, y, w, h, c); }
  void fillRoundRect(int x, int y, int w, int h, int r, uint16_t c) override {
    printf("RR %d %d %d %d %d %u\n", x, y, w, h, r, c);
  }
  void drawRoundRect(int x, int y, int w, int h, int r, uint16_t c) override {
    printf("DR %d %d %d %d %d %u\n", x, y, w, h, r, c);
  }
  void fillCircle(int x, int y, int r, uint16_t c) override { printf("C %d %d %d %u\n", x, y, r, c); }
  void fillTriangle(int x0, int y0, int x1, int y1, int x2, int y2, uint16_t c) override {
    printf("T %d %d %d %d %d %d %u\n", x0, y0, x1, y1, x2, y2, c);
  }
  void fillArc(int x, int y, int r0, int r1, float a0, float a1, uint16_t c) override {
    printf("A %d %d %d %d %.2f %.2f %u\n", x, y, r0, r1, a0, a1, c);
  }
  void wideLine(int x0, int y0, int x1, int y1, float r, uint16_t c) override {
    printf("L %d %d %d %d %.2f %u\n", x0, y0, x1, y1, r, c);
  }
  void text(const char* s, int x, int baseline, Font f, uint16_t c, Align a) override {
    printf("S %d %d %d %d %u|%s\n", x, baseline, (int)f, (int)a, c, s);
  }
  int textWidth(const char* s, Font f) override {
    int w = 0;
    bool ascii = true;
    for (const unsigned char* p = (const unsigned char*)s; *p; p++) ascii = ascii && *p < 0x80;
    if (!ascii) {
      for (const unsigned char* p = (const unsigned char*)s; *p;) {
        uint32_t cp = *p++;
        if (cp >= 0xE0) {
          cp = ((cp & 0x0F) << 12) | ((p[0] & 0x3F) << 6) | (p[1] & 0x3F);
          p += 2;
        } else if (cp >= 0xC0) {
          cp = ((cp & 0x1F) << 6) | (p[0] & 0x3F);
          p += 1;
        }
        w += cp < 0x10000 && wide[cp] ? 12 : 6;
      }
      return w;
    }
    for (const unsigned char* p = (const unsigned char*)s; *p; p++) {
      if (*p >= 0x20 && *p < 0x7F) w += advances[(int)f][*p - 0x20];
    }
    return w;
  }
};

std::string quoted(const char* s) {
  std::string out = "\"";
  for (; *s; s++) {
    if (*s == '"' || *s == '\\') out += '\\';
    out += *s;
  }
  return out + "\"";
}

State stateByName(const char* s) {
  if (!strcmp(s, "-") || !strcmp(s, "halves")) return State::Count;
  return parseState(s);
}

int render(const char* metrics) {
  if (!loadMetrics(metrics)) {
    fprintf(stderr, "cannot read metrics %s\n", metrics);
    return 1;
  }
  Recorder rec;
  static char line[16384];
  while (fgets(line, sizeof(line), stdin)) {
    line[strcspn(line, "\n")] = 0;
    char* fields[5];
    char* p = line;
    for (int i = 0; i < 5; i++) {
      fields[i] = p;
      p = (i < 4) ? strchr(p, '\t') : nullptr;
      if (i < 4) {
        if (!p) return 2;
        *p++ = 0;
      }
    }
    float now = (float)atof(fields[3]);
    Model m;
    if (strcmp(fields[4], "-") != 0 && !parseFrame(fields[4], m, now - 0.5f)) {
      fprintf(stderr, "frame for %s did not parse\n", fields[0]);
      return 3;
    }
    Ui ui;
    ui.seed(7);
    ui.setPreview(stateByName(fields[2]));
    ui.setHalves(!strcmp(fields[2], "halves"));  // CYD-style two-key layout
    // Let the eyes settle the way they would on the device.
    for (float t = now - 3; t < now; t += 1.0f / 30) ui.update(m, t);
    ui.update(m, now);
    // Don't catch the pet mid-blink.
    for (int i = 0; i < 30 && ui.eyesOpen() < 0.99f; i++) ui.update(m, now += 1.0f / 30);
    ui.setView((View)atoi(fields[1]));
    printf("BEGIN %s\n", fields[0]);
    ui.draw(rec, m, now);
    printf("END\n");
  }
  return 0;
}

int parse() {
  static char line[16384];
  while (fgets(line, sizeof(line), stdin)) {
    line[strcspn(line, "\n")] = 0;
    Model m;
    if (!parseFrame(line, m, 100)) {
      printf("{\"ok\":false}\n");
      continue;
    }
    std::string out = "{\"ok\":true,\"focus\":" + std::to_string(m.focus) + ",\"agents\":[";
    for (int i = 0; i < m.count; i++) {
      const Agent& a = m.agents[i];
      char nums[64];
      snprintf(nums, sizeof(nums), ",%d,%d,%d,%d]", (int)a.elapsed, a.tools, a.sessions, a.alert ? 1 : 0);
      out += std::string(i ? "," : "") + "[" + quoted(a.id) + "," + quoted(a.label) + "," + quoted(a.abbr) + "," +
             quoted(stateLabel(a.state)) + "," + quoted(a.detail) + "," + quoted(a.cwd) + nums;
    }
    LocalTime lt{};
    bool hasTime = localTime(m, 100, &lt);
    char tail[256];
    snprintf(tail, sizeof(tail),
             "],\"pet\":[%d,%d,%d,%d,%d,%d,%d,%d],\"usage\":%lld,\"time\":\"%04d-%02d-%02d %02d:%02d:%02d w%d\"}",
             m.pet.level, m.pet.xp_in_level, m.pet.xp_span, m.pet.energy, (int)m.pet.mood, m.pet.tasks,
             m.pet.tools, m.pet.errors, m.has_usage ? (long long)m.usage_out : -1LL, hasTime ? lt.year : 0,
             lt.month, lt.day, lt.hour, lt.minute, lt.second, lt.weekday);
    out += tail;
    out.pop_back();  // reopen the object for pages and weather
    const WeatherInfo& w = m.weather;
    char wbuf[160];
    snprintf(wbuf, sizeof(wbuf), ",\"pages\":%d,\"weather\":[%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d", m.pages,
             (int)w.status, (int)w.sky, w.day ? 1 : 0, w.sample ? 1 : 0, w.temp, w.feels, w.hi, w.lo, w.pop,
             w.age_min, w.hours);
    out += wbuf + std::string(",") + quoted(w.city) + "," + quoted(w.text) + ",[";
    for (int i = 0; i < w.hours; i++) {
      const HourForecast& h = w.hour[i];
      snprintf(wbuf, sizeof(wbuf), "%s[%d,%d,%d,%d,%d]", i ? "," : "", h.hour, h.temp, (int)h.sky, h.pop,
               h.day ? 1 : 0);
      out += wbuf;
    }
    out += "]]";
    const Approval& ap = m.approval;
    snprintf(wbuf, sizeof(wbuf), ",\"approval\":[%d,%d,%lld,%d,", ap.active ? 1 : 0, ap.agent,
             (long long)ap.deadline, ap.wait);
    out += wbuf + quoted(ap.id) + "," + quoted(ap.label) + "," + quoted(ap.tool) + "," + quoted(ap.detail) + "]";
    out += ",\"night\":" + std::to_string((int)m.night) + ",\"skin\":" + std::to_string((int)m.skin) + "}";
    puts(out.c_str());
  }
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc >= 3 && !strcmp(argv[1], "render")) return render(argv[2]);
  if (argc >= 2 && !strcmp(argv[1], "parse")) return parse();
  fprintf(stderr, "usage: preview_main render <metrics> | parse\n");
  return 64;
}

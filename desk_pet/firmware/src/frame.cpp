#include "frame.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <new>

namespace pet {

namespace {

// A tiny JSON reader over one line: enough for the frames deskpet sends,
// strict about structure, forgiving about unknown keys.
enum class T : uint8_t { Null, Bool, Num, Str, Arr, Obj };

struct Node {
  T type;
  const char* p;  // start of the token in the line
  int len;        // token length (strings: without quotes, still escaped)
  int child;      // first child, -1 if none
  int next;       // next sibling, -1 if none
  int key;        // object members: node index of the key string
};

constexpr int kMaxNodes = 320;

class Doc {
 public:
  explicit Doc(const char* s) : s_(s) {}

  int parse() {
    int root = value();
    skipWs();
    return (ok_ && *s_ == 0) ? root : -1;
  }

  const Node& at(int i) const { return nodes_[i]; }

  int get(int obj, const char* key) const {
    if (obj < 0 || nodes_[obj].type != T::Obj) return -1;
    for (int c = nodes_[obj].child; c >= 0; c = nodes_[c].next) {
      const Node& k = nodes_[nodes_[c].key];
      if ((int)strlen(key) == k.len && strncmp(k.p, key, k.len) == 0) return c;
    }
    return -1;
  }

  double num(int obj, const char* key, double fallback) const {
    int n = get(obj, key);
    if (n < 0) return fallback;
    if (nodes_[n].type == T::Num) return strtod(nodes_[n].p, nullptr);
    if (nodes_[n].type == T::Bool) return nodes_[n].p[0] == 't' ? 1 : 0;
    return fallback;
  }

  // Copy a string member as printable ASCII; anything else becomes '?'.
  // The string at `key` as UTF-8 (raw UTF-8 and \\uXXXX escapes both work),
  // cut at a character boundary to fit `cap`. Control characters and anything
  // outside the Basic Multilingual Plane become '?'.
  void str(int obj, const char* key, char* out, int cap) const {
    out[0] = 0;
    int n = get(obj, key);
    if (n < 0 || nodes_[n].type != T::Str) return;
    const char* p = nodes_[n].p;
    const char* end = p + nodes_[n].len;
    int o = 0;
    while (p < end) {
      uint32_t cp = (unsigned char)*p++;
      if (cp == '\\' && p < end) {
        char e = *p++;
        if (e == 'u') {
          cp = 0;
          for (int i = 0; i < 4 && p < end; i++, p++) {
            char h = *p;
            cp = cp * 16 + (h >= '0' && h <= '9' ? h - '0' : (h | 0x20) >= 'a' && (h | 0x20) <= 'f' ? (h | 0x20) - 'a' + 10 : 0);
          }
          if (cp >= 0xD800 && cp < 0xE000) cp = '?';  // half of a surrogate pair
        } else {
          cp = e == 'n' || e == 't' || e == 'r' ? ' ' : (unsigned char)e;
        }
      } else if (cp >= 0x80) {
        int more = cp >= 0xF0 ? 3 : cp >= 0xE0 ? 2 : cp >= 0xC0 ? 1 : -1;
        cp &= more == 3 ? 0x07 : more == 2 ? 0x0F : 0x1F;
        for (int i = 0; i < more; i++) {
          if (p >= end || ((unsigned char)*p & 0xC0) != 0x80) {
            more = -1;
            break;
          }
          cp = (cp << 6) | ((unsigned char)*p++ & 0x3F);
        }
        if (more < 0 || cp > 0xFFFF) cp = '?';
      }
      if (cp < 0x20 || cp == 0x7F) cp = '?';
      int len = cp < 0x80 ? 1 : cp < 0x800 ? 2 : 3;
      if (o + len > cap - 1) break;
      if (len == 1) {
        out[o++] = (char)cp;
      } else if (len == 2) {
        out[o++] = (char)(0xC0 | (cp >> 6));
        out[o++] = (char)(0x80 | (cp & 0x3F));
      } else {
        out[o++] = (char)(0xE0 | (cp >> 12));
        out[o++] = (char)(0x80 | ((cp >> 6) & 0x3F));
        out[o++] = (char)(0x80 | (cp & 0x3F));
      }
    }
    out[o] = 0;
  }

 private:
  int add(T type, const char* p) {
    if (count_ >= kMaxNodes) {
      ok_ = false;
      return -1;
    }
    nodes_[count_] = Node{type, p, 0, -1, -1, -1};
    return count_++;
  }

  void skipWs() {
    while (*s_ == ' ' || *s_ == '\t' || *s_ == '\r' || *s_ == '\n') s_++;
  }

  int value() {
    skipWs();
    if (!ok_) return -1;
    switch (*s_) {
      case '{': return object();
      case '[': return array();
      case '"': return string();
      case 't': return literal("true", T::Bool);
      case 'f': return literal("false", T::Bool);
      case 'n': return literal("null", T::Null);
      default: return number();
    }
  }

  int literal(const char* word, T type) {
    int n = (int)strlen(word);
    if (strncmp(s_, word, n) != 0) return fail();
    int i = add(type, s_);
    s_ += n;
    return i;
  }

  int number() {
    const char* start = s_;
    if (*s_ == '-') s_++;
    if (*s_ < '0' || *s_ > '9') return fail();
    while ((*s_ >= '0' && *s_ <= '9') || *s_ == '.' || *s_ == 'e' || *s_ == 'E' ||
           *s_ == '+' || *s_ == '-') {
      s_++;
    }
    int i = add(T::Num, start);
    if (i >= 0) nodes_[i].len = (int)(s_ - start);
    return i;
  }

  int string() {
    const char* start = ++s_;
    while (*s_ && *s_ != '"') {
      if (*s_ == '\\' && s_[1]) s_++;
      s_++;
    }
    if (*s_ != '"') return fail();
    int i = add(T::Str, start);
    if (i >= 0) nodes_[i].len = (int)(s_ - start);
    s_++;
    return i;
  }

  int array() {
    int arr = add(T::Arr, s_++);
    int prev = -1;
    skipWs();
    if (*s_ == ']') {
      s_++;
      return arr;
    }
    while (ok_) {
      int v = value();
      if (v < 0) return fail();
      link(arr, prev, v);
      prev = v;
      skipWs();
      if (*s_ == ',') {
        s_++;
        continue;
      }
      if (*s_ == ']') {
        s_++;
        return arr;
      }
      return fail();
    }
    return -1;
  }

  int object() {
    int obj = add(T::Obj, s_++);
    int prev = -1;
    skipWs();
    if (*s_ == '}') {
      s_++;
      return obj;
    }
    while (ok_) {
      skipWs();
      if (*s_ != '"') return fail();
      int k = string();
      skipWs();
      if (k < 0 || *s_ != ':') return fail();
      s_++;
      int v = value();
      if (v < 0) return fail();
      nodes_[v].key = k;
      link(obj, prev, v);
      prev = v;
      skipWs();
      if (*s_ == ',') {
        s_++;
        continue;
      }
      if (*s_ == '}') {
        s_++;
        return obj;
      }
      return fail();
    }
    return -1;
  }

  void link(int parent, int prev, int child) {
    if (parent < 0 || child < 0) return;
    if (prev < 0) {
      nodes_[parent].child = child;
    } else {
      nodes_[prev].next = child;
    }
  }

  int fail() {
    ok_ = false;
    return -1;
  }

  const char* s_;
  bool ok_ = true;
  int count_ = 0;
  Node nodes_[kMaxNodes];
};

Mood parseMood(const char* s) {
  if (strcmp(s, "happy") == 0) return Mood::Happy;
  if (strcmp(s, "hungry") == 0) return Mood::Hungry;
  return Mood::Ok;
}

}  // namespace

bool parseFrame(const char* line, Model& m, float now) {
  static Doc* doc = nullptr;  // ~8 KB; keep it off the loop task's stack
  if (!doc) doc = (Doc*)malloc(sizeof(Doc));
  if (!doc) return false;
  new (doc) Doc(line);
  int root = doc->parse();
  if (root < 0 || doc->at(root).type != T::Obj || doc->num(root, "v", 0) != 1) return false;
  int arr = doc->get(root, "a");
  if (arr < 0 || doc->at(arr).type != T::Arr) return false;

  static Model next;  // a few KB: keep it off the loop task's stack
  next = m;
  next.count = 0;
  for (int a = doc->at(arr).child; a >= 0 && next.count < kMaxAgents; a = doc->at(a).next) {
    if (doc->at(a).type != T::Obj) continue;
    Agent& ag = next.agents[next.count++];
    char state[16];
    doc->str(a, "id", ag.id, sizeof(ag.id));
    doc->str(a, "l", ag.label, sizeof(ag.label));
    doc->str(a, "b", ag.abbr, sizeof(ag.abbr));
    doc->str(a, "s", state, sizeof(state));
    doc->str(a, "d", ag.detail, sizeof(ag.detail));
    doc->str(a, "c", ag.cwd, sizeof(ag.cwd));
    ag.state = parseState(state);
    ag.elapsed = (int32_t)doc->num(a, "e", -1);
    ag.tools = (uint16_t)doc->num(a, "n", 0);
    ag.sessions = (uint8_t)doc->num(a, "k", 0);
    ag.alert = doc->num(a, "x", 0) != 0;
  }
  int focus = (int)doc->num(root, "f", -1);
  next.focus = (focus >= 0 && focus < next.count) ? focus : -1;
  next.rot_index = next.rot_count = 0;
  int ro = doc->get(root, "ro");
  if (ro >= 0 && doc->at(ro).type == T::Arr) {
    int first = doc->at(ro).child;
    int second = first >= 0 ? doc->at(first).next : -1;
    if (second >= 0 && doc->at(first).type == T::Num && doc->at(second).type == T::Num) {
      next.rot_index = (int)strtol(doc->at(first).p, nullptr, 10);
      next.rot_count = (int)strtol(doc->at(second).p, nullptr, 10);
    }
  }
  next.epoch = (int64_t)doc->num(root, "t", 0);
  next.tz = (int32_t)doc->num(root, "tz", 0);

  int p = doc->get(root, "p");
  if (p >= 0) {
    char mood[12];
    PetInfo& pi = next.pet;
    pi.level = (int)doc->num(p, "lv", 1);
    pi.xp_in_level = (int)doc->num(p, "xi", 0);
    pi.xp_span = (int)doc->num(p, "xs", 100);
    pi.energy = (int)doc->num(p, "en", 0);
    doc->str(p, "md", mood, sizeof(mood));
    pi.mood = parseMood(mood);
    pi.tasks = (int)doc->num(p, "tk", 0);
    pi.tools = (int)doc->num(p, "tl", 0);
    pi.errors = (int)doc->num(p, "er", 0);
    pi.levelup_age = (float)doc->num(p, "lu", -1);
    pi.fed_age = (float)doc->num(p, "fd", -1);
  }
  int u = doc->get(root, "u");
  next.has_usage = u >= 0 && doc->at(u).type == T::Obj;
  if (next.has_usage) {
    next.usage_out = (int64_t)doc->num(u, "o", 0);
    next.usage_total = (int64_t)doc->num(u, "t", 0);
  }
  // Pages: letters f c w a s, in any order; missing = all.
  char pages[8];
  doc->str(root, "pg", pages, sizeof(pages));
  next.pages = pages[0] ? 0 : kAllPages;
  for (const char* c = pages; *c; c++) {
    const char* letters = "fcwas";
    const char* at = strchr(letters, *c);
    if (at) next.pages |= (uint8_t)(1 << (at - letters));
  }
  if (!next.pages) next.pages = kAllPages;

  WeatherInfo& w = next.weather;
  w = WeatherInfo();
  int wn = doc->get(root, "w");
  if (wn >= 0 && doc->at(wn).type == T::Obj) {
    char st[12], sky[12];
    doc->str(wn, "st", st, sizeof(st));
    w.status = !strcmp(st, "ok")      ? WeatherInfo::Status::Ok
               : !strcmp(st, "stale") ? WeatherInfo::Status::Stale
               : !strcmp(st, "error") ? WeatherInfo::Status::Error
                                      : WeatherInfo::Status::Loading;
    doc->str(wn, "c", w.city, sizeof(w.city));
    doc->str(wn, "tx", w.text, sizeof(w.text));
    doc->str(wn, "k", sky, sizeof(sky));
    w.sky = parseSky(sky);
    w.day = doc->num(wn, "dy", 1) != 0;
    w.sample = doc->num(wn, "sm", 0) != 0;
    w.temp = (int16_t)doc->num(wn, "t", 0);
    w.feels = (int16_t)doc->num(wn, "fl", 0);
    w.hi = (int16_t)doc->num(wn, "hi", -99);
    w.lo = (int16_t)doc->num(wn, "lo", -99);
    w.wind = (int16_t)doc->num(wn, "ws", 0);
    w.humidity = (int8_t)doc->num(wn, "hu", 0);
    w.pop = (int8_t)doc->num(wn, "p", -1);
    w.age_min = (int)doc->num(wn, "ag", 0);
    int hs = doc->get(wn, "h");
    if (hs >= 0 && doc->at(hs).type == T::Arr) {
      for (int h = doc->at(hs).child; h >= 0 && w.hours < 6; h = doc->at(h).next) {
        // [hour, temp, sky, pop, day]
        int f[5] = {-1, -1, -1, -1, -1}, i = 0;
        for (int v = doc->at(h).child; v >= 0 && i < 5; v = doc->at(v).next) f[i++] = v;
        if (i < 5 || doc->at(f[2]).type != T::Str) continue;
        HourForecast& hf = w.hour[w.hours++];
        char hsky[12];
        snprintf(hsky, sizeof(hsky), "%.*s", doc->at(f[2]).len < 11 ? doc->at(f[2]).len : 11, doc->at(f[2]).p);
        hf.hour = (int8_t)strtol(doc->at(f[0]).p, nullptr, 10);
        hf.temp = (int16_t)strtod(doc->at(f[1]).p, nullptr);
        hf.sky = parseSky(hsky);
        hf.pop = (int8_t)strtol(doc->at(f[3]).p, nullptr, 10);
        hf.day = doc->at(f[4]).p[0] != '0';
      }
    }
  }
  Approval& ap = next.approval;
  ap = Approval();
  int an = doc->get(root, "ap");
  if (an >= 0 && doc->at(an).type == T::Obj) {
    doc->str(an, "id", ap.id, sizeof(ap.id));
    doc->str(an, "l", ap.label, sizeof(ap.label));
    doc->str(an, "t", ap.tool, sizeof(ap.tool));
    doc->str(an, "d", ap.detail, sizeof(ap.detail));
    int agent = (int)doc->num(an, "a", -1);
    ap.agent = (agent >= 0 && agent < next.count) ? agent : -1;
    ap.deadline = (int64_t)doc->num(an, "dl", 0);
    ap.wait = (int)doc->num(an, "n", 30);
    if (ap.wait < 1) ap.wait = 1;
    ap.active = ap.id[0] != 0;
  }
  int nt = (int)doc->num(root, "nt", 0);
  next.night = (nt == 1 || nt == 2) ? (Night)nt : Night::Day;
  next.connected = true;
  next.rx_time = now;
  m = next;
  return true;
}

}  // namespace pet

#include "frame.h"

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
  void str(int obj, const char* key, char* out, int cap) const {
    out[0] = 0;
    int n = get(obj, key);
    if (n < 0 || nodes_[n].type != T::Str) return;
    const char* p = nodes_[n].p;
    const char* end = p + nodes_[n].len;
    int o = 0;
    while (p < end && o < cap - 1) {
      unsigned char ch = (unsigned char)*p++;
      if (ch == '\\' && p < end) {
        char e = *p++;
        if (e == 'u') {
          p += (end - p >= 4) ? 4 : end - p;
          ch = '?';
        } else {
          ch = e == 'n' || e == 't' || e == 'r' ? ' ' : (unsigned char)e;
        }
      } else if (ch >= 0x80) {
        while (p < end && ((unsigned char)*p & 0xC0) == 0x80) p++;  // skip UTF-8 tail
        ch = '?';
      }
      out[o++] = (ch >= 0x20 && ch < 0x7F) ? (char)ch : '?';
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

  Model next = m;
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
  next.connected = true;
  next.rx_time = now;
  m = next;
  return true;
}

}  // namespace pet

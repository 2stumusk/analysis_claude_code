"""Today's Claude Code token usage, read from local session transcripts.

Claude Code writes one JSONL transcript per session under
~/.claude/projects/<project>/<session>.jsonl. Assistant lines carry
message.usage; one API response can be split over several lines that repeat the
same usage, so lines are de-duplicated by (message.id, requestId).
Nothing here touches the network or any credential.
"""

import glob
import json
import os
import threading
from datetime import date, datetime, time as dtime

FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens",
          "cache_creation_input_tokens")


def default_root():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(base, "projects")


class ClaudeUsage:
    def __init__(self, root=None, today=date.today):
        self.root = root or default_root()
        self.today = today
        self.lock = threading.Lock()
        self._reset(today())

    def _reset(self, day):
        self.day = day
        self.offsets = {}
        self.seen = set()
        self.totals = dict.fromkeys(FIELDS, 0)
        self.messages = 0

    def scan(self):
        day = self.today()
        with self.lock:
            if day != self.day:
                self._reset(day)
            start = datetime.combine(day, dtime.min).timestamp()
            for path in glob.glob(os.path.join(self.root, "**", "*.jsonl"), recursive=True):
                try:
                    if os.path.getmtime(path) < start:
                        continue
                    self._read(path, day)
                except OSError:
                    continue

    def _read(self, path, day):
        offset = self.offsets.get(path, 0)
        if os.path.getsize(path) < offset:  # file was rewritten
            offset = 0
        with open(path, "rb") as f:
            f.seek(offset)
            chunk = f.read()
        end = chunk.rfind(b"\n")
        if end < 0:
            return
        self.offsets[path] = offset + end + 1
        for raw in chunk[:end].splitlines():
            try:
                obj = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            msg = obj.get("message")
            usage = msg.get("usage") if isinstance(msg, dict) else None
            if not isinstance(usage, dict) or not obj.get("timestamp"):
                continue
            try:
                ts = datetime.fromisoformat(str(obj["timestamp"]).replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts.tzinfo is not None:
                ts = ts.astimezone()
            if ts.date() != day:
                continue
            key = (msg.get("id"), obj.get("requestId"))
            if key[0]:
                if key in self.seen:
                    continue
                self.seen.add(key)
            self.messages += 1
            for k in FIELDS:
                v = usage.get(k)
                if isinstance(v, int):
                    self.totals[k] += v

    def snapshot(self):
        with self.lock:
            t = self.totals
            return {
                "date": self.day.isoformat(),
                "input": t["input_tokens"],
                "output": t["output_tokens"],
                "cache_read": t["cache_read_input_tokens"],
                "cache_write": t["cache_creation_input_tokens"],
                "messages": self.messages,
            }

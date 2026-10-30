import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "firmware", "tools")
sys.path.insert(0, TOOLS)

import cat_art  # noqa: E402


class CatArtTest(unittest.TestCase):
    def test_generated_files_are_up_to_date(self):
        """src/cat_art.h and web/cat_art.js must match what cat_art.py draws."""
        frames = cat_art.build()
        with tempfile.TemporaryDirectory() as tmp:
            header, js = os.path.join(tmp, "cat_art.h"), os.path.join(tmp, "cat_art.js")
            cat_art.write_header(frames, header)
            cat_art.write_js(frames, js)
            for fresh, committed in ((header, os.path.join(ROOT, "firmware", "src", "cat_art.h")),
                                     (js, os.path.join(ROOT, "web", "cat_art.js"))):
                with open(fresh) as a, open(committed) as b:
                    self.assertEqual(a.read(), b.read(), "rerun firmware/tools/cat_art.py")

    def test_frames_are_well_formed(self):
        frames = cat_art.build()
        for name, rows in frames.items():
            self.assertEqual(len(rows), 32, name)
            self.assertTrue(all(len(r) == 32 and set(r) <= set("0123456789abcdef") for r in rows), name)
            used = {int(ch, 16) for r in rows for ch in r}
            self.assertIn(cat_art.O, used, name)   # every pose has an outline
            self.assertIn(cat_art.EYE, used, name)  # and a face
        # Every pose the firmware and the simulator ask for exists.
        for state in ("idle", "think", "read", "type", "wait", "done", "error", "sleep", "hungry"):
            for i in (0, 1):
                self.assertIn("%s_%d" % (state, i), frames)
        self.assertIn("blink", frames)

    def test_web_data_matches_frames(self):
        with open(os.path.join(ROOT, "web", "cat_art.js")) as f:
            src = f.read()
        data = json.loads(src[src.index("{"):src.rindex("}") + 1])
        self.assertEqual(data["frames"], cat_art.build())
        self.assertEqual(len(data["palette"]), 16)
        self.assertIsNone(data["palette"][0])


if __name__ == "__main__":
    unittest.main()

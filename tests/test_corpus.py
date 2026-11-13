"""Corpus round trip through the `hanword` CLI (same as tests/run-corpus.sh, but portable: Windows too).

Every document in tests/corpus/ (synthetic samples only) must pass `check` and survive
`roundtrip --via hwpx` and `--via docx`; evil.html must be flagged by `check` (exit 1).
"""
import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
CLI = os.path.join(APP, "hanword")
EXTS = (".html", ".htm", ".txt", ".hwpx", ".docx", ".doc")


def hw(*args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, CLI, "--json", *args], capture_output=True, timeout=120, env=env)


class Corpus(unittest.TestCase):
    def docs(self):
        return [f for f in sorted(glob.glob(os.path.join(HERE, "corpus", "*"))) if f.lower().endswith(EXTS)]

    def test_corpus_present(self):
        self.assertGreaterEqual(len(self.docs()), 8)

    def test_check_and_roundtrip(self):
        for f in self.docs():
            name = os.path.basename(f)
            with self.subTest(doc=name):
                r = hw("check", f)
                if "evil" in name:
                    self.assertEqual(r.returncode, 1, r.stdout[-400:])
                    continue
                self.assertEqual(r.returncode, 0, (r.stdout[-400:], r.stderr[-400:]))
                for via in ("hwpx", "docx"):
                    r = hw("roundtrip", f, "--via", via)
                    self.assertEqual(r.returncode, 0, (via, r.stdout[-600:], r.stderr[-400:]))

    def test_convert_cli(self):
        src = os.path.join(HERE, "corpus", "rich.html")
        with tempfile.TemporaryDirectory() as d:
            for ext in ("hwpx", "docx", "txt"):
                out = os.path.join(d, "out." + ext)
                r = hw("convert", src, out)
                self.assertEqual(r.returncode, 0, (ext, r.stdout[-300:], r.stderr[-300:]))
                self.assertGreater(os.path.getsize(out), 20)
            r = hw("info", os.path.join(d, "out.hwpx"))
            self.assertEqual(r.returncode, 0)
            self.assertTrue(json.loads(r.stdout).get("ok", True))

    def test_formats(self):
        r = hw("formats")
        self.assertEqual(r.returncode, 0)
        j = json.loads(r.stdout)
        for fmt in ("hwpx", "docx", "html", "txt"):
            self.assertIn(fmt, j["in"])
            self.assertIn(fmt, j["out"])


if __name__ == "__main__":
    unittest.main()

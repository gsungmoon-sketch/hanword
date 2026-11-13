"""HTTP server tests (stdlib only): starts server.py on a free port with a temporary data dir.

Covers /healthz, save/load/list round trip, stateless HWPX/DOCX conversion, security defaults
(loopback bind, Host check against DNS rebinding, cross-origin POST, debug bridge and board off).
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def start(extra_env=None, args=()):
    port = free_port()
    docs = tempfile.mkdtemp(prefix="hw-test-")
    env = {k: v for k, v in os.environ.items() if not k.startswith("WP_")}
    env.update({"WP_DOCS": docs, "WP_PORT": str(port), "PYTHONIOENCODING": "utf-8"})
    env.update(extra_env or {})
    p = subprocess.Popen([sys.executable, os.path.join(APP, "server.py"), *args], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for _ in range(100):
        if p.poll() is not None:
            break
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=1).read()
            break
        except Exception:
            time.sleep(0.1)
    return p, port, docs


def req(port, path, body=None, headers=None, method=None):
    data = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data, headers=headers or {},
                               method=method or ("POST" if data is not None else "GET"))
    if data is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class LocalMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p, cls.port, cls.docs = start()

    @classmethod
    def tearDownClass(cls):
        cls.p.terminate()
        cls.p.communicate(timeout=10)

    def test_healthz(self):
        st, b = req(self.port, "/healthz")
        self.assertEqual(st, 200)
        j = json.loads(b)
        self.assertTrue(j["ok"])
        self.assertEqual(j["app"], "hanword")
        self.assertFalse(j["public"])

    def test_index_and_assets(self):
        st, b = req(self.port, "/")
        self.assertEqual(st, 200)
        self.assertIn(b"<html", b.lower())
        self.assertNotIn(b"canonical", b)            # no site URL configured
        for a in ("/editor.css", "/wp-core.js", "/jspdf.min.js", "/html2canvas.min.js", "/guide.html"):
            self.assertEqual(req(self.port, a)[0], 200, a)

    def test_save_load_list_delete(self):
        html = "<p>안녕하세요 <b>한워드</b></p>"
        st, b = req(self.port, "/api/save", {"name": "시험문서", "html": html})
        self.assertEqual(st, 200, b)
        self.assertTrue(os.path.isfile(os.path.join(self.docs, "시험문서.html")))
        st, b = req(self.port, "/api/load?name=" + urllib.request.quote("시험문서"))
        self.assertEqual(json.loads(b)["html"], html)
        st, b = req(self.port, "/api/delete", {"name": "시험문서"})
        self.assertEqual(st, 200)
        self.assertFalse(os.path.exists(os.path.join(self.docs, "시험문서.html")))

    def test_path_traversal_name(self):
        req(self.port, "/api/save", {"name": "../../evil", "html": "x"})
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.docs), "evil.html")))

    def test_convert_hwpx_docx_roundtrip(self):
        html = "<p>표 시험</p><table><tr><td>가</td><td>나</td></tr></table>"
        for kind, magic in (("hwpx", b"PK"), ("docx", b"PK")):
            st, b = req(self.port, "/api/convert/" + kind, {"html": html, "name": "t"})
            self.assertEqual(st, 200, (kind, b[:200]))
            self.assertEqual(b[:2], magic)
            st, b2 = req(self.port, "/api/convert/import", b, {"Content-Type": "application/octet-stream"})
            self.assertEqual(st, 200, (kind, b2[:200]))
            out = json.loads(b2)["html"]
            self.assertIn("가", out)
            self.assertIn("나", out)

    def test_host_header_rebinding_rejected(self):
        st, _ = req(self.port, "/api/list", headers={"Host": "attacker.example:%d" % self.port})
        self.assertEqual(st, 421)
        st, _ = req(self.port, "/healthz", headers={"Host": "localhost:%d" % self.port})
        self.assertEqual(st, 200)

    def test_cross_origin_post_rejected(self):
        st, _ = req(self.port, "/api/save", {"name": "x", "html": "x"}, {"Origin": "https://attacker.example"})
        self.assertEqual(st, 403)

    def test_origin_must_match_port_and_site(self):
        same = "http://127.0.0.1:%d" % self.port
        self.assertEqual(req(self.port, "/api/save", {"name": "o", "html": "x"}, {"Origin": same})[0], 200)
        other = "http://127.0.0.1:%d" % (self.port + 1 if self.port < 65535 else self.port - 1)
        self.assertEqual(req(self.port, "/api/save", {"name": "o", "html": "y"}, {"Origin": other})[0], 403)
        self.assertEqual(req(self.port, "/api/save", {"name": "o", "html": "z"}, {"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(json.loads(req(self.port, "/api/load?name=o")[1])["html"], "x")

    def test_save_rejects_non_string_without_truncating(self):
        req(self.port, "/api/save", {"name": "keep", "html": "보존"})
        st, _ = req(self.port, "/api/save", {"name": "keep", "html": 123})
        self.assertEqual(st, 400)
        self.assertEqual(json.loads(req(self.port, "/api/load?name=keep")[1])["html"], "보존")

    def test_debug_and_board_off_by_default(self):
        self.assertEqual(req(self.port, "/api/debug/state")[0], 404)
        self.assertEqual(req(self.port, "/api/board/list")[0], 404)
        st, _ = req(self.port, "/api/board/post", {"title": "t", "body": "b"})
        self.assertEqual(st, 404)

    def test_no_sitemap_without_site_url(self):
        st, b = req(self.port, "/robots.txt")
        self.assertEqual(st, 200)
        self.assertNotIn(b"Sitemap", b)
        self.assertEqual(req(self.port, "/sitemap.xml")[0], 404)


class PublicMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p, cls.port, cls.docs = start({"WP_PUBLIC": "1", "WP_SITE_URL": "https://docs.example.com"})

    @classmethod
    def tearDownClass(cls):
        cls.p.terminate()
        cls.p.communicate(timeout=10)

    def test_server_storage_disabled(self):
        st, _ = req(self.port, "/api/save", {"name": "x", "html": "x"})
        self.assertEqual(st, 404)
        self.assertEqual(req(self.port, "/api/list")[0], 404)
        self.assertEqual(os.listdir(self.docs) and [f for f in os.listdir(self.docs) if f.endswith(".html")], [])

    def test_site_url(self):
        self.assertIn(b"https://docs.example.com/sitemap.xml", req(self.port, "/robots.txt")[1])
        self.assertEqual(req(self.port, "/sitemap.xml")[0], 200)
        self.assertIn(b'rel="canonical" href="https://docs.example.com/"', req(self.port, "/")[1])


class BindPolicy(unittest.TestCase):
    def test_refuse_non_loopback_in_local_mode(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("WP_")}
        env["WP_DOCS"] = tempfile.mkdtemp(prefix="hw-test-")
        p = subprocess.run([sys.executable, os.path.join(APP, "server.py"), "--host", "0.0.0.0", "--port", str(free_port())],
                           env=env, capture_output=True, timeout=30)
        self.assertEqual(p.returncode, 2)
        self.assertIn(b"refusing", p.stderr)


if __name__ == "__main__":
    unittest.main()

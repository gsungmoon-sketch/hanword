"""HTTP server tests (stdlib only): starts server.py on a free port with a temporary data dir.

Covers /healthz, save/load/list round trip, stateless HWPX/DOCX conversion, security defaults
(loopback bind, Host check against DNS rebinding, cross-origin POST, debug bridge and board off),
atomic save, rename collisions, name traversal and the raster PDF pixel cap.
"""
import base64
import errno
import http.client
import importlib
import threading
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
import zlib

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


def png(w, h):
    """minimal PNG header bytes with the given IHDR size (no pixel data needed for the cap check)."""
    ihdr = w.to_bytes(4, "big") + h.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
    chunk = len(ihdr).to_bytes(4, "big") + b"IHDR" + ihdr + zlib.crc32(b"IHDR" + ihdr).to_bytes(4, "big")
    return b"\x89PNG\r\n\x1a\n" + chunk


def raw_post(port, headers, body=b"{}"):
    """POST with exact header control (no automatic Host / Content-Length)."""
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.putrequest("POST", "/api/save", skip_host=True, skip_accept_encoding=True)
    for k, v in headers:
        c.putheader(k, v)
    c.endheaders()
    c.send(body)
    r = c.getresponse()
    st = r.status
    r.read()
    c.close()
    return st


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
        self.assertNotIn(b"docs.example.com", b)     # no site URL configured
        self.assertLessEqual(b.count(b'rel="canonical"'), 1)
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

    def test_host_check_on_post(self):
        st, _ = req(self.port, "/api/save", {"name": "h", "html": "x"}, {"Host": "rebind.example"})
        self.assertEqual(st, 421)
        self.assertFalse(os.path.exists(os.path.join(self.docs, "h.html")))

    def test_origin_userinfo_and_foreign_host(self):
        for o in ("http://127.0.0.1:%d@attacker.example" % self.port, "http://user@127.0.0.1:%d" % self.port,
                  "http://localhost.attacker.example:%d" % self.port, "null"):
            self.assertEqual(req(self.port, "/api/save", {"name": "u", "html": "x"}, {"Origin": o})[0], 403, o)

    def test_rename_does_not_overwrite(self):
        req(self.port, "/api/save", {"name": "ra", "html": "A"})
        req(self.port, "/api/save", {"name": "rb", "html": "B"})
        st, b = req(self.port, "/api/rename", {"old": "ra", "new": "rb"})
        self.assertEqual(st, 200)
        self.assertFalse(json.loads(b)["ok"])
        self.assertEqual(json.loads(req(self.port, "/api/load?name=ra")[1])["html"], "A")
        self.assertEqual(json.loads(req(self.port, "/api/load?name=rb")[1])["html"], "B")
        st, b = req(self.port, "/api/rename", {"old": "ra", "new": "rc"})
        self.assertTrue(json.loads(b)["ok"])
        self.assertEqual(json.loads(req(self.port, "/api/load?name=rc")[1])["html"], "A")
        self.assertFalse(os.path.exists(os.path.join(self.docs, "ra.html")))

    def test_media_names_cannot_escape(self):
        md = os.path.join(self.docs, "media")
        with open(os.path.join(md, "clip.mp4"), "wb") as f:
            f.write(b"\0" * 16)
        with open(os.path.join(md, "other.mp4"), "wb") as f:
            f.write(b"\1" * 16)
        for bad in ("../clip.mp4", "..\\clip.mp4", "a\\b.mp4", "c:clip.mp4", "x/y.mp4", "..", ".hidden.mp4"):
            st, b = req(self.port, "/api/media/rename", {"old": "clip.mp4", "new": bad})
            self.assertFalse(json.loads(b)["ok"], bad)
            st, b = req(self.port, "/api/media/rename", {"old": bad, "new": "z.mp4"})
            self.assertFalse(json.loads(b)["ok"], bad)
            st, b = req(self.port, "/api/media?name=" + urllib.request.quote(bad))
            self.assertFalse(json.loads(b)["ok"], bad)
        self.assertEqual(sorted(os.listdir(md)), ["clip.mp4", "other.mp4"])
        self.assertEqual(req(self.port, "/media/..%2F..%2Fetc%2Fpasswd")[0], 404)
        st, b = req(self.port, "/api/media/rename", {"old": "clip.mp4", "new": "other.mp4"})
        self.assertFalse(json.loads(b)["ok"])                 # collision refused
        with open(os.path.join(md, "other.mp4"), "rb") as f:
            self.assertEqual(f.read(), b"\1" * 16)
        st, b = req(self.port, "/api/media/rename", {"old": "clip.mp4", "new": "renamed"})
        self.assertEqual(json.loads(b), {"ok": True, "name": "renamed.mp4"})
        os.rename(os.path.join(md, "renamed.mp4"), os.path.join(md, "clip.mp4"))

    def test_doc_name_traversal_stays_inside(self):
        for bad in ("../../evil2", "..\\..\\evil2", "c:evil2", "/tmp/evil2"):
            req(self.port, "/api/save", {"name": bad, "html": "x"})
        parent = os.path.dirname(self.docs)
        self.assertFalse([f for f in os.listdir(parent) if "evil2" in f])
        self.assertFalse(os.path.exists("/tmp/evil2.html"))
        for f in os.listdir(self.docs):
            self.assertNotIn("/", f)

    def test_sec_fetch_site_variants(self):
        body = {"name": "sfs", "html": "x"}
        for v, want in (("same-origin", 200), ("none", 200), ("same-site", 403), ("cross-site", 403), ("Cross-Site", 403)):
            self.assertEqual(req(self.port, "/api/save", body, {"Sec-Fetch-Site": v})[0], want, v)
        self.assertEqual(req(self.port, "/api/debug/state", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_origin_null_and_scheme(self):
        self.assertEqual(req(self.port, "/api/save", {"name": "n", "html": "x"}, {"Origin": "null"})[0], 403)
        self.assertEqual(req(self.port, "/api/save", {"name": "n", "html": "x"},
                             {"Origin": "file://127.0.0.1:%d" % self.port})[0], 403)

    def test_host_variants(self):
        ok = ("127.0.0.1:%d" % self.port, "localhost.:%d" % self.port, "[::1]:%d" % self.port, "LOCALHOST")
        for h in ok:
            self.assertEqual(raw_post(self.port, [("Host", h), ("Content-Length", "2")]), 200, h)
        for h in ("[::2]:%d" % self.port, "evil.example.:%d" % self.port, "127.0.0.1.evil.example"):
            self.assertEqual(raw_post(self.port, [("Host", h), ("Content-Length", "2")]), 421, h)
        self.assertEqual(raw_post(self.port, [("Content-Length", "2")]), 421)   # no Host header

    def test_malformed_content_length(self):
        h = ("Host", "127.0.0.1:%d" % self.port)
        for v in ("+2", "2abc", "0x2", "-1", "1e3", "2 2"):
            self.assertEqual(raw_post(self.port, [h, ("Content-Length", v)]), 400, v)

    def test_symlink_escape_inside_docs(self):
        outside = tempfile.mkdtemp(prefix="hw-out-")
        target = os.path.join(outside, "victim.html")
        with open(target, "w") as f:
            f.write("orig")
        os.symlink(target, os.path.join(self.docs, "link.html"))
        os.symlink(target, os.path.join(self.docs, "media", "link.mp4"))
        try:
            st, _ = req(self.port, "/api/save", {"name": "link", "html": "pwned"})
            self.assertEqual(st, 500)
            with open(target) as f:
                self.assertEqual(f.read(), "orig")
            self.assertEqual(json.loads(req(self.port, "/api/load?name=link")[1])["html"], "")
            self.assertFalse(json.loads(req(self.port, "/api/media?name=link.mp4")[1])["ok"])
            self.assertEqual(req(self.port, "/media/link.mp4")[0], 404)
        finally:
            os.unlink(os.path.join(self.docs, "link.html"))
            os.unlink(os.path.join(self.docs, "media", "link.mp4"))

    def test_concurrent_saves_leave_no_temp(self):
        def one(i):
            req(self.port, "/api/save", {"name": "race", "html": "v%d" % i * 2000})
        ts = [threading.Thread(target=one, args=(i,)) for i in range(16)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertFalse([f for f in os.listdir(self.docs) if f.endswith(".tmp")])
        html = json.loads(req(self.port, "/api/load?name=race")[1])["html"]
        self.assertRegex(html, r"^(v\d+)\1*$")

    def test_print_and_quit_disabled_without_binaries(self):
        self.assertEqual(req(self.port, "/api/print", {"name": "p", "pages": []})[0], 403)
        self.assertEqual(req(self.port, "/api/quit", {})[0], 403)

    def test_no_sitemap_without_site_url(self):
        st, b = req(self.port, "/robots.txt")
        self.assertEqual(st, 200)
        self.assertNotIn(b"Sitemap", b)
        self.assertEqual(req(self.port, "/sitemap.xml")[0], 404)


class PublicMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p, cls.port, cls.docs = start({"WP_PUBLIC": "1", "WP_SITE_URL": "https://docs.example.com",
                                           "WP_PUBLIC_HOST": "docs.example.com, www.example.com"})

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
        page = req(self.port, "/")[1]
        self.assertIn(b'rel="canonical" href="https://docs.example.com/"', page)
        self.assertEqual(page.count(b'rel="canonical"'), 1)


    def test_any_host_header_and_origin_list(self):
        conv = "/api/convert/text"
        self.assertEqual(req(self.port, "/healthz", headers={"Host": "docs.example.com"})[0], 200)
        for o in ("https://docs.example.com", "https://www.example.com"):
            self.assertEqual(req(self.port, conv, b"hi", {"Origin": o, "Host": "docs.example.com"})[0], 200, o)
        for o in ("https://evil.docs.example.com", "https://docs.example.com.evil.example", "https://x@docs.example.com",
                  "http://docs.example.com", "https://docs.example.com:8443", "null"):
            self.assertEqual(req(self.port, conv, b"hi", {"Origin": o, "Host": "proxy.internal"})[0], 403, o)
        self.assertEqual(req(self.port, conv, b"hi", {"Origin": "https://docs.example.com", "Host": "proxy.internal"})[0], 200)
        self.assertEqual(req(self.port, conv, b"hi", {"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(req(self.port, conv, b"hi", {"Sec-Fetch-Site": "same-site"})[0], 200)

    def test_board_off_by_default(self):
        self.assertEqual(req(self.port, "/api/board/list")[0], 404)


class Limits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p, cls.port, cls.docs = start({"WP_MAX_BODY": "100"})

    @classmethod
    def tearDownClass(cls):
        cls.p.terminate()
        cls.p.communicate(timeout=10)

    def test_max_body_413(self):
        self.assertEqual(req(self.port, "/api/save", {"name": "big", "html": "x" * 200})[0], 413)
        self.assertEqual(req(self.port, "/api/save", {"name": "s", "html": "x"})[0], 200)

    def test_bad_env_exits_cleanly(self):
        for k, v in (("WP_PORT", "abc"), ("WP_PORT", "70000"), ("WP_MAX_BODY", "lots")):
            env = {kk: vv for kk, vv in os.environ.items() if not kk.startswith("WP_")}
            env.update({"WP_DOCS": tempfile.mkdtemp(prefix="hw-test-"), k: v})
            p = subprocess.run([sys.executable, os.path.join(APP, "server.py")], env=env, capture_output=True, timeout=30)
            self.assertEqual(p.returncode, 2, (k, v))
            self.assertIn(k.encode(), p.stderr)
            self.assertNotIn(b"Traceback", p.stderr)


class BoardEnabled(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p, cls.port, cls.docs = start({"WP_PUBLIC": "1", "WP_BOARD_ENABLE": "1"})

    @classmethod
    def tearDownClass(cls):
        cls.p.terminate()
        cls.p.communicate(timeout=10)

    def test_board_round_trip(self):
        st, b = req(self.port, "/api/board/post", {"title": "t", "body": "b", "password": "pw"})
        self.assertEqual(st, 200, b)
        pid = json.loads(b)["id"]
        st, b = req(self.port, "/api/board/list")
        self.assertIn(pid, [x["id"] for x in json.loads(b)["posts"]])


class InProcess(unittest.TestCase):
    """functions tested directly (no HTTP): atomic save under failure, PNG pixel cap."""
    @classmethod
    def setUpClass(cls):
        cls.docs = tempfile.mkdtemp(prefix="hw-test-")
        old = dict(os.environ)
        os.environ["WP_DOCS"] = cls.docs
        sys.path.insert(0, APP)
        try:
            cls.srv = importlib.import_module("server")
        finally:
            os.environ.clear(); os.environ.update(old)

    def test_atomic_write_failure_keeps_original(self):
        srv = self.srv
        fp = os.path.join(self.docs, "doc.html")
        srv.atomic_write(fp, "원본".encode())
        real = os.replace

        def boom(*a, **k):
            raise OSError("disk full")
        srv.os.replace = boom
        try:
            with self.assertRaises(OSError):
                srv.atomic_write(fp, b"new")
        finally:
            srv.os.replace = real
        with open(fp, encoding="utf-8") as f:
            self.assertEqual(f.read(), "원본")
        self.assertEqual(os.listdir(self.docs).count("doc.html"), 1)
        self.assertFalse([f for f in os.listdir(self.docs) if f.endswith(".tmp")])

    def test_rename_noclobber(self):
        a, b = os.path.join(self.docs, "a.html"), os.path.join(self.docs, "b.html")
        self.srv.atomic_write(a, b"A"); self.srv.atomic_write(b, b"B")
        self.assertFalse(self.srv.rename_noclobber(a, b))
        with open(b, "rb") as f:
            self.assertEqual(f.read(), b"B")

    def test_rename_link_fallback_and_missing_src(self):
        srv = self.srv
        a, b = os.path.join(self.docs, "fa.html"), os.path.join(self.docs, "fb.html")
        srv.atomic_write(a, b"A")
        real = os.link

        def nolink(*x, **k):
            raise OSError(errno.EPERM, "no hard links")
        srv.os.link = nolink
        try:
            self.assertTrue(srv.rename_noclobber(a, b))                     # O_EXCL fallback
            self.assertFalse(os.path.exists(a))
            with open(b, "rb") as f:
                self.assertEqual(f.read(), b"A")
            srv.atomic_write(a, b"A2")
            self.assertFalse(srv.rename_noclobber(a, b))                    # fallback still refuses to clobber
            with self.assertRaises(FileNotFoundError):
                srv.rename_noclobber(os.path.join(self.docs, "gone.html"), os.path.join(self.docs, "fc.html"))
            self.assertFalse(os.path.exists(os.path.join(self.docs, "fc.html")))
        finally:
            srv.os.link = real
        with self.assertRaises(FileNotFoundError):                         # normal path: missing src → error, no empty dst
            srv.rename_noclobber(os.path.join(self.docs, "gone.html"), os.path.join(self.docs, "fd.html"))
        self.assertFalse(os.path.exists(os.path.join(self.docs, "fd.html")))

    def test_png_pixel_cap(self):
        srv = self.srv
        if not srv._get_im():
            self.skipTest("ImageMagick not installed")
        du = lambda raw: "data:image/png;base64," + base64.b64encode(raw).decode()
        ok, _, err = srv.pages_to_pdf([du(png(10000, 10000))])
        self.assertFalse(ok)
        self.assertIn("너무 큼", err)
        ok, _, err = srv.pages_to_pdf([du(png(10, 10)[:20])])
        self.assertFalse(ok)
        self.assertIn("PNG", err)
        ok, _, err = srv.pages_to_pdf([du(png(6000, 6000))] * 12)            # 36MP each, 432MP total
        self.assertFalse(ok)
        self.assertIn("합계", err)
        self.assertIn("disk", srv.IM_LIMITS)


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

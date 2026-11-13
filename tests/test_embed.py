"""Embed mode (iframe host, docs/embed.md): converter module without a server, server-side sanitizer
allowlist, A4 government margin preset, and the ?embed=1 framing headers. Browser side = tests/e2e-embed.js."""
import io
import os
import re
import subprocess
import sys
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
sys.path.insert(0, HERE)

import hanword_embed as E  # noqa: E402

FORM = ('<p>기안</p><div class="objline"><table data-place="char"><tr data-row="item">'
        '<td data-field="name">품목</td><td data-sum="amount" data-x="1">1,000</td></tr></table></div>'
        '<p>합계 <span data-field="total" style="font-weight:bold">1,000</span></p>')


class Module(unittest.TestCase):
    def test_import_without_server(self):
        code = ("import sys; sys.path.insert(0, %r); import hanword_embed as E; "
                "assert E.html_to_hwpx('<p>a</p>')[:2] == b'PK'; assert E.html_to_docx('<p>a</p>')[:2] == b'PK'; "
                "assert 'server' not in sys.modules; print('ok')") % APP
        r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout.strip(), "ok", r.stderr[-500:])

    def test_gov_preset_docx(self):
        d = E.html_to_docx(FORM, page="gov")
        x = zipfile.ZipFile(io.BytesIO(d)).read("word/document.xml").decode()
        m = re.search(r"<w:pgMar[^>]*>", x).group(0)
        for k, v in (("top", 1701), ("left", 1134), ("right", 850), ("bottom", 850)):
            self.assertIn('w:%s="%d"' % (k, v), m)

    def test_gov_preset_hwpx(self):
        d = E.html_to_hwpx(FORM, page=E.GOV_PAGE)
        x = zipfile.ZipFile(io.BytesIO(d)).read("Contents/section0.xml").decode()
        m = re.search(r"<hp:margin[^>]*>", x).group(0)
        for k, v in (("top", 8504), ("left", 5669), ("right", 4252), ("bottom", 4252)):
            self.assertIn('%s="%d"' % (k, v), m)

    def test_page_from_document_meta(self):   # 편집기 get 응답 html 의 wpmeta 만으로도 용지 반영
        d = E.html_to_docx('<p>a</p><div id="wpmeta" hidden="" data-margins="30,15,15,20"></div>')
        self.assertIn('w:top="1701"', zipfile.ZipFile(io.BytesIO(d)).read("word/document.xml").decode())

    def test_normalize_page(self):
        self.assertEqual(E.normalize_page("gov"), {"paper": "A4", "orient": "portrait", "mt": 30.0, "mr": 15.0, "mb": 15.0, "ml": 20.0})
        bad = E.normalize_page({"paper": "../x", "orient": "up", "mt": float("nan"), "mr": 1e9, "mb": True, "ml": "5", "preset": "__proto__"})
        self.assertEqual(bad, {"paper": "A4", "orient": "portrait", "mt": 20.0, "mr": 20.0, "mb": 20.0, "ml": 20.0})
        self.assertIsNone(E.normalize_page(None))
        self.assertEqual(E.page_preset("gov")["mt"], 30)
        with self.assertRaises(ValueError):
            E.page_preset("nope")

    def test_pdf_meta_injection(self):
        h = E._with_page_meta('<p>a</p><div id="wpmeta" hidden="" data-header="H" data-margins="1,1,1,1"></div>', E.normalize_page("gov"))
        self.assertIn('data-margins="30,15,15,20"', h)
        self.assertIn('data-header="H"', h)
        self.assertNotIn('1,1,1,1', h)

    @unittest.skipUnless(os.environ.get("WP_NODE_PATH") and os.path.isfile(os.path.join(APP, "font", "NotoSansKR.ttf")),
                         "PDF needs node+playwright (WP_NODE_PATH) and fonts")
    def test_pdf(self):
        pdf = E.html_to_pdf(FORM, page="gov")
        self.assertEqual(pdf[:5], b"%PDF-")
        mb = re.search(rb"/MediaBox\s*\[\s*0 0 ([\d.]+) ([\d.]+)", pdf)
        self.assertTrue(mb and abs(float(mb.group(1)) - 595.3) < 2 and abs(float(mb.group(2)) - 841.9) < 2, mb)


class Sanitize(unittest.TestCase):
    def test_form_attributes_survive(self):
        out = E.sanitize_html(FORM)
        for a in ('data-row="item"', 'data-field="name"', 'data-sum="amount"', 'data-field="total"', 'class="objline"',
                  "font-weight:bold"):
            self.assertIn(a, out)
        self.assertNotIn("data-x", out)
        self.assertNotIn("data-place", out)

    def test_xss_vectors(self):
        evil = ('<p style="background:url(//e/x);color:red;width:expression(1);font-family:a\\75rl(x)">t</p>'
                '<img src=x onerror=alert(1)><a href="java&#x09;script:alert(1)">x</a><a href=" javascript:1">y</a>'
                '<svg onload=alert(1)><script>alert(2)</script></svg><iframe srcdoc="<script>1</script>"></iframe>'
                '<style>*{}</style><script>alert(3)</script><math><mi>z</mi></math><form action=//e><input></form>'
                '<p onmouseover=1 id=WP name=page>u</p><!-- c --><template><img src=x onerror=1></template>'
                '<object data=x></object><embed src=x><base href=//e/><meta http-equiv=refresh content=0>'
                '<img src="data:image/svg+xml;base64,PHN2Zz4=">')
        out = E.sanitize_html(evil).lower()
        for bad in ("onerror", "onload", "onmouseover", "javascript", "<script", "<svg", "<iframe", "srcdoc", "url(",
                    "expression", "<style", "<math", "<form", "<input", "<template", "<object", "<embed", "<base", "<meta",
                    "svg+xml", " id=", " name=", "<!--", "alert(2)", "alert(3)", "\\75"):
            self.assertNotIn(bad, out, bad)
        self.assertIn('style="color:red"', out)

    def test_data_attr_values(self):
        out = E.sanitize_html('<td data-field="a&quot;><script>x</script>">1</td><td data-field="합계_1">2</td>'
                              '<span data-sum="amount,tax">3</span><span data-sum="Function(name)()">f</span><p data-field="x">4</p><td data-row="' + "a" * 65 + '">5</td>'
                              '<td data-fieldx="1" data-field-="1" data-field="javascript:alert(1)">6</td>')
        self.assertNotIn("<script", out)
        self.assertIn('data-field="합계_1"', out)
        self.assertIn('data-sum="amount,tax"', out)
        self.assertEqual(out.count("data-sum="), 1)      # 식 모양(괄호) 값은 버림
        self.assertNotIn('<p data-field', out)          # p 에는 data-* 불가
        self.assertNotIn('a' * 65, out)
        self.assertNotIn("data-fieldx", out)
        self.assertNotIn("data-field-", out)
        self.assertEqual(out.count("data-field="), 1)    # 따옴표·꺾쇠 든 값, 스킴(콜론) 든 값은 버림
        self.assertNotIn("javascript", out)
        self.assertNotIn("&quot;", out)

    def test_wpmeta_and_links(self):
        out = E.sanitize_html('<div id="wpmeta" hidden data-header="&lt;img src=x onerror=1&gt;"><div>x</div></div><p>after</p>'
                              '<a href="https://ex.com/a?b=1">l</a><a href="mailto:a@b.c">m</a><a href="/api/delete">r</a>')
        self.assertNotIn("wpmeta", out)
        self.assertNotIn("onerror", out)
        self.assertIn("<p>after</p>", out)
        self.assertIn('href="https://ex.com/a?b=1" rel="noopener noreferrer"', out)
        self.assertIn('href="mailto:a@b.c"', out)
        self.assertNotIn("/api/delete", out)            # 같은 출처 상대 URL 금지

    def test_img_only_data_uri(self):
        ok = "data:image/png;base64,iVBORw0KGgo="
        out = E.sanitize_html('<img src="%s" style="width:50px"><img src="/files/1.png"><img src="https://e/x.png">' % ok)
        self.assertIn(ok, out)
        self.assertNotIn("/files/", out)
        self.assertNotIn("https://e", out)

    def test_browser_parity_raw_text(self):   # 감사 MED-2: 브라우저가 숨기는 글을 서버가 살리지 않음 / void wpmeta 로 나머지 유실 없음
        self.assertEqual(E.sanitize_html('<title/><p>1억 송금 승인</p></title><p>ok</p>'), "<p>ok</p>")
        self.assertEqual(E.sanitize_html('<textarea/><p>x</p></textarea><p>ok</p>'), "<p>ok</p>")
        self.assertNotIn("PY-ONLY", E.sanitize_html('<script><!--<script></script>PY-ONLY</script><p>after</p>'))
        self.assertEqual(E.sanitize_html('<br id=wpmeta><p>rest</p>'), "<p>rest</p>")
        self.assertEqual(E.sanitize_html('<script>a</script x><p>AFTER</p>'), "<p>AFTER</p>")
        self.assertEqual(E.sanitize_html('<p>A</p><script-x>k</script-x>'), "<p>A</p>k")

    def test_converters_sanitize_by_default(self):
        d = E.html_to_docx('<p>보임</p><title/><p>숨은글</p></title><div id="wpmeta" hidden="" data-margins="30,15,15,20"></div>')
        x = zipfile.ZipFile(io.BytesIO(d)).read("word/document.xml").decode()
        self.assertIn("보임", x)
        self.assertNotIn("숨은글", x)
        self.assertIn('w:top="1701"', x)            # 정제 전 wpmeta 용지 회수
        raw = E.html_to_docx('<p>보임</p><title/><p>숨은글</p></title>', sanitize=False)
        self.assertIn("숨은글", zipfile.ZipFile(io.BytesIO(raw)).read("word/document.xml").decode())

    def test_nesting_balanced(self):
        out = E.sanitize_html("<table><tr><td><b>x</td></tr></table><p>y")
        self.assertEqual(out, "<table><tr><td><b>x</b></td></tr></table><p>y</p>")


class EmbedEntry(unittest.TestCase):
    def test_embed_html_up_to_date(self):
        r = subprocess.run([sys.executable, os.path.join(APP, "scripts", "build_embed.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_embed_html_clean(self):   # 호스트가 그대로 벤더링: 인라인 스크립트·공개 주소·SEO 없음
        with open(os.path.join(APP, "embed.html"), encoding="utf-8") as f: s = f.read()
        self.assertEqual(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", s), [])
        for bad in ("sys" "plays", "hwd.", "canonical", "og:", "twitter:", "ld+json", "site-verification", "debug.js", 'content="index'):
            self.assertNotIn(bad, s, bad)
        self.assertIn("data-wp-embed", s)
        self.assertIn('src="wp-embed.js"', s)
        with open(os.path.join(APP, "index.html"), encoding="utf-8") as f: ix = f.read()
        if os.path.exists(os.path.join(APP, ".publicignore")):        # 개발 저장소만(공개 사본은 make_public 이 SEO 주소를 뺌)
            self.assertIn('rel="canonical"', ix)                     # 공개 index.html SEO 는 그대로
        self.assertEqual(re.findall(r'<script src="([^"]+)"', s), re.findall(r'<script src="([^"]+)"', ix))   # 같은 모듈 구성


class ExportFonts(unittest.TestCase):
    def test_exported_css_fonts_resolve(self):   # 배포 사본의 editor.css 폰트 url = 전부 배포 파일(404 없음)
        import shutil, tempfile
        if subprocess.run(["git", "-C", APP, "rev-parse", "HEAD"], capture_output=True).returncode: self.skipTest("git 저장소 아님")
        dst = tempfile.mkdtemp(prefix="hw-exp-"); shutil.rmtree(dst)
        try:
            r = subprocess.run([sys.executable, os.path.join(APP, "scripts", "export_embed.py"), dst], capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            sys.path.insert(0, os.path.join(APP, "scripts")); import fontcss
            with open(os.path.join(dst, "editor.css"), encoding="utf-8") as f: css = f.read()
            urls = fontcss.font_urls(css)
            self.assertTrue(urls)
            for u in urls: self.assertTrue(os.path.isfile(os.path.join(dst, "font", u)), u)
            for gone in ("Hamchorom", "UnBatang", "NanumGothic-400.woff2", "NanumMyeongjo-700.woff2"): self.assertNotIn(gone, css)
            self.assertIn("NanumGothic-Regular.ttf", css)
        finally: shutil.rmtree(dst, ignore_errors=True)

    def test_prune_rules(self):
        sys.path.insert(0, os.path.join(APP, "scripts")); import fontcss
        css = ('@font-face { font-family:"A"; src:url("font/a.woff2") format("woff2"), url("font/a.ttf") format("truetype"); }\n'
               '@font-face { font-family:"B"; src:url("/font/b.woff2") format("woff2"); }\n'
               '@font-face { font-family:"C"; src:local("C"), url(font/c.woff2); }\nbody{}')
        out = fontcss.prune_font_faces(css, {"a.ttf"})
        self.assertEqual(fontcss.font_urls(out), ["a.ttf"])
        self.assertNotIn('"B"', out); self.assertIn('local("C")', out); self.assertIn("body{}", out)


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_server as T
        cls.T = T
        cls.p, cls.port, cls.docs = T.start()

    @classmethod
    def tearDownClass(cls):
        cls.p.terminate()
        cls.p.wait(10)

    def head(self, path):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path)
        r = c.getresponse()
        body = r.read()
        return r, body

    def test_embed_framing_headers(self):
        r, b = self.head("/?embed=1")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.getheader("X-Frame-Options"), "SAMEORIGIN")
        self.assertIn("frame-ancestors 'self'", r.getheader("Content-Security-Policy"))
        r, b = self.head("/")
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertIn("frame-ancestors 'none'", r.getheader("Content-Security-Policy"))
        r, b = self.head("/?embed=1x")
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")

    def test_embed_entry_served(self):
        r, b = self.head("/embed.html")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.getheader("X-Frame-Options"), "SAMEORIGIN")
        self.assertIn("frame-ancestors 'self'", r.getheader("Content-Security-Policy"))
        self.assertIn(b"data-wp-embed", b)
        self.assertRegex(b, rb'src="wp-embed\.js\?v=\w+"')

    def test_embed_entry_public_mode(self):   # 공개모드·사이트 주소가 있어도 embed.html 엔 주입 없음
        p, port, _ = self.T.start({"WP_PUBLIC": "1", "WP_SITE_URL": "https://docs.example.com"})
        try:
            st, b = self.T.req(port, "/embed.html")
            self.assertEqual(st, 200)
            self.assertNotIn(b"WP_PUBLIC", b)
            self.assertNotIn(b"wp-public.js", b)
            self.assertNotIn(b"docs.example.com", b)
            st, ix = self.T.req(port, "/")
            self.assertIn(b"wp-public.js", ix)
            self.assertIn(b"docs.example.com", ix)
        finally:
            p.terminate(); p.wait(10)

    def test_relative_assets_versioned(self):
        r, b = self.head("/?embed=1")
        self.assertRegex(b, rb'<script nonce="[^"]+" src="wp-core\.js\?v=\w+"')
        self.assertRegex(b, rb'<script nonce="[^"]+" src="wp-embed\.js\?v=\w+"')
        self.assertRegex(b, rb'href="editor\.css\?v=\w+"')
        self.assertNotRegex(b, rb'src="/wp-')
        self.assertEqual(self.head("/wp-embed.js")[0].status, 200)


if __name__ == "__main__":
    unittest.main()

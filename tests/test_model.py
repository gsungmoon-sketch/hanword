#!/usr/bin/env python3
"""문서모델·렌더·편집연산 단위시험(stdlib unittest). 실행: python3 -m unittest tests/test_model.py
   python-hwpx/lxml 없는 환경(-s -I, Maru Alpine)에서도 전부 통과해야 함(.hwp만 pyhwp 필요 시 생략)."""
import os, sys, re, time, json, glob, unittest, copy
HERE = os.path.dirname(os.path.abspath(__file__)); APP = os.path.dirname(HERE)
sys.path.insert(0, APP); sys.path.insert(0, HERE)
import timing as tm
import hanword_core as core
import hanword_model as hm
from hanword_model import ModelError

import hwpxconv
HAVE_HWP5 = hwpxconv._hwp5_bin("hwp5html") is not None   # .hwp(HWP5)만 pyhwp 필요 — HWPX는 stdlib(hwpx_std)

def corpus():
    for f in sorted(glob.glob(os.path.join(HERE, "corpus", "*")) + glob.glob(os.path.join(HERE, "private", "*"))):
        if "evil" in f: continue
        if f.endswith(".hwp") and not HAVE_HWP5: continue
        yield f

BASE = {"version": 1, "meta": {}, "notes": {}, "blocks": [
    {"type": "h1", "runs": [{"text": "제목"}]},
    {"type": "p", "runs": [{"text": "가나다", "bold": True}, {"text": "라마"}]},
    {"type": "table", "rows": [[{"colspan": 1, "rowspan": 1, "runs": [{"text": "셀"}]}]]},
    {"type": "p", "runs": [{"text": "끝"}]}]}

class Identity(unittest.TestCase):
    def test_corpus_model_render_model(self):
        n = 0
        for f in corpus():
            with open(f, "rb") as fp: data = fp.read()
            html = core.import_bytes(data, None, f)
            m1 = core.model(html); hm.validate(m1)
            m2 = core.model(core.render(m1))
            self.assertEqual(m1, m2, "model→render→model 불일치: %s" % f)
            # 렌더 결과의 본문·구조도 원문과 같아야 함
            self.assertEqual(core.plain_text(html), core.plain_text(core.render(m1)), f)
            n += 1
        self.assertGreater(n, 0)
    def test_spaces_preserved(self):
        m = {"version": 1, "blocks": [{"type": "p", "runs": [{"text": " 앞  가운데   끝 "}]}]}
        self.assertEqual(core.model(core.render(m))["blocks"], m["blocks"])
    def test_br_placeholder(self):
        m = core.model("<p><br></p><p>a<br></p><p>b<br>c</p>")
        self.assertEqual([hm.block_text(b) for b in m["blocks"]], ["", "a", "b", "c"])

class Ops(unittest.TestCase):
    def ap(self, ops, m=BASE): return core.apply_ops(m, ops)
    def test_pure(self):
        before = copy.deepcopy(BASE); self.ap([{"op": "insert_text", "pos": [1, 0], "text": "x"}])
        self.assertEqual(BASE, before)
    def test_insert_inherits_style(self):
        m = self.ap([{"op": "insert_text", "pos": [1, 2], "text": "X"}])
        self.assertEqual(m["blocks"][1]["runs"][0], {"text": "가나X다", "bold": True})
        m = self.ap([{"op": "insert_text", "pos": [1, 3], "text": "Y", "attrs": {"bold": False, "color": "#FF0000"}}])
        self.assertIn({"text": "Y", "color": "#FF0000"}, m["blocks"][1]["runs"])
    def test_delete_cross_block(self):
        m = self.ap([{"op": "delete_range", "start": [1, 1], "end": [3, 0]}])   # 표까지 지움
        self.assertEqual([b["type"] for b in m["blocks"]], ["h1", "p"])
        self.assertEqual(hm.block_text(m["blocks"][1]), "가끝")
    def test_set_style_split(self):
        m = self.ap([{"op": "set_style", "start": [1, 1], "end": [1, 4], "attrs": {"italic": True, "bold": None}}])
        self.assertEqual(m["blocks"][1]["runs"], [{"text": "가", "bold": True}, {"text": "나다라", "italic": True}, {"text": "마"}])
    def test_split_merge(self):
        m = self.ap([{"op": "split_paragraph", "pos": [1, 2]}])
        self.assertEqual([hm.block_text(b) for b in m["blocks"][1:3]], ["가나", "다라마"])
        m = core.apply_ops(m, [{"op": "merge_paragraph", "index": 1}])
        self.assertEqual(m["blocks"][1]["runs"], BASE["blocks"][1]["runs"])
        m = self.ap([{"op": "split_paragraph", "pos": [0, 2]}])   # 제목 끝 Enter → 본문
        self.assertEqual(m["blocks"][1], {"type": "p", "runs": []})
    def test_block_type(self):
        m = self.ap([{"op": "set_block_type", "index": 1, "type": "li", "list": "number", "align": "center"}])
        self.assertEqual(m["blocks"][1]["list"], "number"); self.assertEqual(m["blocks"][1]["align"], "center")
        self.assertIn("<ol><li style=\"text-align:center;\">", core.render(m))
    def test_pgbreak(self):
        m = self.ap([{"op": "insert_pgbreak", "pos": [1, 1]}, {"op": "insert_pgbreak", "pos": [6, 0]}])
        self.assertEqual([b["type"] for b in m["blocks"]], ["h1", "p", "pgbreak", "p", "table", "p", "pgbreak"])
        self.assertEqual(core.model(core.render(m))["blocks"], m["blocks"])
    def test_delete_insert_block(self):
        m = self.ap([{"op": "delete_block", "index": 2}, {"op": "insert_block", "index": 0, "block": {"type": "pgbreak"}}])
        self.assertEqual([b["type"] for b in m["blocks"]], ["pgbreak", "h1", "p", "p"])
    def test_endnote_pruned(self):
        m0 = {"version": 1, "notes": {"1": "주석"}, "blocks": [{"type": "p", "runs": [{"text": "a"}, {"endnote": "1"}]}]}
        self.assertIn("1", core.apply_ops(m0, [])["notes"])
        self.assertEqual(core.apply_ops(m0, [{"op": "delete_range", "start": [0, 1], "end": [0, 2]}])["notes"], {})

class Reject(unittest.TestCase):
    def bad(self, ops, m=BASE):
        with self.assertRaises(ModelError): core.apply_ops(m, ops)
    def test_bounds(self):
        self.bad([{"op": "insert_text", "pos": [1, 99], "text": "x"}])
        self.bad([{"op": "insert_text", "pos": [9, 0], "text": "x"}])
        self.bad([{"op": "insert_text", "pos": [2, 0], "text": "x"}])          # 잠금 표
        self.bad([{"op": "insert_text", "pos": [1, True], "text": "x"}])       # bool≠int
        self.bad([{"op": "insert_text", "pos": [1, 0], "text": "a\nb"}])       # 줄바꿈
        self.bad([{"op": "insert_text", "pos": [1, 0], "text": "x" * (hm.MAX_INSERT + 1)}])
        self.bad([{"op": "delete_range", "start": [1, 2], "end": [1, 2]}])
        self.bad([{"op": "delete_range", "start": [1, 0], "end": [2, 0]}])     # 끝이 잠금 블록
        self.bad([{"op": "merge_paragraph", "index": 1}])                       # 다음이 표
        self.bad([{"op": "nope"}]); self.bad({"op": "x"}); self.bad([{"op": "insert_text", "pos": [1, 0], "text": "x", "evil": 1}])
    def test_style_values(self):
        for a in ({"color": "red"}, {"color": "#FFF"}, {"size": 0}, {"size": "12"}, {"font": 'x"><script>'},
                  {"link": "javascript:alert(1)"}, {"onclick": "x"}, {"bold": "yes"}):
            self.bad([{"op": "set_style", "start": [1, 0], "end": [1, 1], "attrs": a}])
    def test_model_values(self):
        for blk in ({"type": "script"}, {"type": "img", "src": "javascript:x"}, {"type": "img", "src": "data:image/svg+xml;base64,PHN2Zz4="},
                    {"type": "p", "runs": [{"text": "x", "link": "vbscript:x"}]}, {"type": "p", "runs": [{"img": "http://x/y.png"}]},
                    {"type": "table", "rows": [[{"colspan": 999}]]}, {"type": "p", "align": "evil"},
                    {"type": "table", "rows": [[{"borders": {"top": ["solid", 1, "red;x:y"]}}]]}):
            with self.assertRaises(ModelError, msg=str(blk)): hm.validate({"blocks": [blk]})
        with self.assertRaises(ModelError): hm.validate({"blocks": [], "meta": {"x\" onload=\"": "1"}})
    def test_render_escapes(self):
        m = {"version": 1, "meta": {"header": '"><img src=x onerror=alert(1)>'}, "notes": {},
             "blocks": [{"type": "p", "runs": [{"text": "<script>alert(1)</script>", "font": "Batang, 'NotoKR'"}]}]}
        h = core.render(m)
        self.assertNotIn("<script", h); self.assertNotIn("<img", h)
        self.assertEqual(core.model(h), m)

class AuditRegress(unittest.TestCase):   # Opus 감사(2026-11-13) 재현 박제
    def bad(self, fn):
        with self.assertRaises(ModelError): fn()
    def test_runs_required(self):
        self.bad(lambda: core.apply_ops({"blocks": [{"type": "p"}]}, [{"op": "insert_text", "pos": [0, 0], "text": "q"}]))
    def test_non_modelerror_inputs(self):
        self.bad(lambda: hm.validate({"blocks": [{"type": "table", "rows": [[{"borders": ["x"]}]]}]}))
        self.bad(lambda: hm.validate({"blocks": [{"type": "p", "runs": [{"text": "\ud800"}]}]}))
        self.bad(lambda: core.apply_ops(BASE, [{"op": [1]}]))
        self.bad(lambda: hm.loads(b"\xff"))
        self.bad(lambda: hm.loads("[" * 100000))
        self.bad(lambda: hm.validate({"blocks": [{"type": [[[]]]}]}))
        self.bad(lambda: hm.validate({"blocks": [{"type": "p", "runs": [{"text": "a", "color": "#FFFFFF\n"}]}]}))
        self.bad(lambda: hm.validate({"version": True, "blocks": []}))
    def test_model_output_validates(self):
        hm.validate(core.model('<table data-place="evil"><tr><td>x</td></tr></table><img data-place="zz" src="data:image/png;base64,AA==">'))
    def test_work_limits(self):
        import time
        big = {"version": 1, "blocks": [{"type": "p", "runs": [dict({"text": "x" * 1000}, **({"bold": True} if i % 2 == 0 else {})) for i in range(4000)]}]}
        t = time.time(); core.apply_ops(big, [{"op": "insert_text", "pos": [0, 5], "text": "y"}]); self.assertLess(time.time() - t, tm.limit(3))
        self.bad(lambda: core.apply_ops({"version": 1, "blocks": [{"type": "p", "runs": [{"text": "a"}]}]},
                                        [{"op": "insert_text", "pos": [0, 0], "text": "x" * 100000}] * 700))
        many = {"version": 1, "blocks": [{"type": "p", "runs": [{"text": "a"}]} for _ in range(5000)]}
        t = time.time()
        with self.assertRaises(ModelError):
            core.apply_ops(many, [{"op": "set_style", "start": [0, 0], "end": [4999, 1], "attrs": {"bold": True}}] * 1000)
        self.assertLess(time.time() - t, tm.limit(20))
    def test_border_tiny(self):
        m = {"version": 1, "meta": {}, "notes": {}, "blocks": [{"type": "table", "rows": [[{"colspan": 1, "rowspan": 1, "runs": [], "borders": {"top": ["solid", 0, None]}}]]}]}
        self.assertEqual(core.model(core.render(m))["blocks"][0]["rows"][0][0]["borders"]["top"][1], 0)

class Stdlib(unittest.TestCase):
    def test_core_imports_without_user_site(self):
        import subprocess
        code = ("import sys; sys.path.insert(0, %r); import hanword_core as c, hanword_model as m; "
                "h=c.render(c.model('<h1>a</h1><p>b</p>')); d=c.export_html(h,'docx'); x=c.export_html(h,'hwpx'); "
                "print(c.detect(d), c.detect(x), c.plain_text(c.import_bytes(x)))" % APP)
        r = subprocess.run([sys.executable, "-s", "-I", "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-500:]); self.assertEqual(r.stdout.split(), ["docx", "hwpx", "a", "b"])

class ServeStop(unittest.TestCase):   # v0.1.7 Windows 스모크: 부모(부트로더)만 죽고 자식이 포트를 계속 잡음
    START = 90   # 첫 import 가 느린 러너(macOS) 여유 — 준비는 서버 로그·포트로 결정적으로 판정
    def test_server_exits_with_launcher(self):
        import subprocess, signal, tempfile, shutil, http.client
        if os.name == "nt": self.skipTest("POSIX 경로 시험(Windows 는 릴리스 스모크가 같은 단언)")
        import socket
        with socket.socket() as so: so.bind(("127.0.0.1", 0)); port = so.getsockname()[1]
        tmp = tempfile.mkdtemp(prefix="hw-stop-")
        pidf, logf = os.path.join(tmp, "child.pid"), os.path.join(tmp, "child.log")
        env = dict(os.environ, HANWORD_EXIT_WITH_PARENT="1")
        # 실행기: 서버 자식을 띄우고(출력=파일, 파이프 없음) pid 를 파일로 — 파이프 버퍼·플러시에 기대지 않음
        launcher = ("import subprocess, sys, os\n"
                    "log = open(%r, 'wb')\n"
                    "p = subprocess.Popen([sys.executable, %r, 'serve', '--port', '%d', '--data', %r], stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)\n"
                    "open(%r + '.tmp', 'w').write(str(p.pid)); os.replace(%r + '.tmp', %r)\n"
                    "p.wait()\n") % (logf, os.path.join(APP, "packaging", "entry.py"), port, os.path.join(tmp, "docs"), pidf, pidf, pidf)
        par = subprocess.Popen([sys.executable, "-c", launcher], env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        child = None
        def up():
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            try: c.request("GET", "/healthz", headers={"Host": "127.0.0.1:%d" % port}); return c.getresponse().status == 200
            except OSError: return False
            finally: c.close()
        def alive(pid):
            try: os.kill(pid, 0); return True
            except OSError: return False
        def tail():
            try:
                with open(logf, "rb") as f: return f.read()[-1500:].decode("utf-8", "replace")
            except OSError: return ""
        try:
            t0 = time.time()
            while not up():
                if child is None and os.path.exists(pidf):
                    with open(pidf) as f: child = int(f.read())
                self.assertIsNone(par.poll(), "launcher exited: " + tail())
                if child is not None: self.assertTrue(alive(child), "server exited early: " + tail())
                self.assertLess(time.time() - t0, self.START, "server did not start: " + tail()); time.sleep(0.25)
            if child is None:
                with open(pidf) as f: child = int(f.read())
            par.send_signal(signal.SIGKILL); par.wait()          # 부모만 강제 종료(TerminateProcess 와 같은 꼴)
            t0 = time.time()
            while up():
                self.assertLess(time.time() - t0, 10, "server still answers after its launcher died"); time.sleep(0.2)
        finally:
            if par.poll() is None: par.kill(); par.wait()
            if child is not None and alive(child):
                try: os.kill(child, signal.SIGKILL)   # 실패 시 고아 서버 정리
                except OSError: pass
            shutil.rmtree(tmp, ignore_errors=True)

class ConsoleEncoding(unittest.TestCase):   # v0.1.6 Windows 스모크: cp1252 콘솔에서 '→' 출력 UnicodeEncodeError
    def run_cli(self, *args, entry=False):
        import subprocess
        env = dict(os.environ, PYTHONIOENCODING="cp1252"); env.pop("PYTHONUTF8", None)
        prog = [os.path.join(APP, "packaging", "entry.py")] if entry else [os.path.join(APP, "hanword")]
        r = subprocess.run([sys.executable, "-X", "utf8=0"] + prog + [str(a) for a in args], capture_output=True, timeout=120, env=env)
        self.assertNotIn(b"UnicodeEncodeError", r.stderr + r.stdout, args)
        return r
    def test_smoke_cli_paths_cp1252(self):
        import tempfile, shutil
        tmp = tempfile.mkdtemp(prefix="hw-enc-")
        try:
            src = os.path.join(tmp, "가.html"); hx = os.path.join(tmp, "가.hwpx"); back = os.path.join(tmp, "back.html")
            with open(src, "w", encoding="utf-8") as f: f.write("<p>한글 → 문단 ✓</p><table><tr><td>가</td></tr></table>")
            self.assertEqual(self.run_cli("--json", "formats").returncode, 0)
            self.assertEqual(self.run_cli("formats").returncode, 0)
            self.assertEqual(self.run_cli("convert", src, hx).returncode, 0)
            self.assertEqual(self.run_cli("convert", hx, back).returncode, 0)
            with open(back, encoding="utf-8") as f: self.assertIn("한글 → 문단 ✓", f.read())
            r = self.run_cli("--json", "info", hx); self.assertEqual(r.returncode, 0)
            self.assertTrue(json.loads(r.stdout.decode("ascii").strip().splitlines()[-1]))   # --json = ASCII
            self.assertEqual(self.run_cli("info", hx).returncode, 0)
            self.assertEqual(self.run_cli("--json", "model", hx).returncode, 0)
            self.assertEqual(self.run_cli("check", src).returncode, 0)
            self.assertEqual(self.run_cli("info", os.path.join(tmp, "없음.hwpx")).returncode, 2)          # 한글 오류 문구
            self.assertEqual(self.run_cli("--json", "info", os.path.join(tmp, "없음.hwpx")).returncode, 2)
            self.assertEqual(self.run_cli("--version", entry=True).returncode, 0)
            self.assertEqual(self.run_cli("selfcheck-imports", "hanword_core", "server", entry=True).returncode, 0)
        finally: shutil.rmtree(tmp, ignore_errors=True)

class Linear(unittest.TestCase):   # 2026-11-13 마루 감사: 비신뢰 HTML 정규식 2차시간 회귀
    N = 100000   # 최대 크기(4n). 판정 = n=N/4 → N 배율(tests/timing.py), 절대 초 아님
    def _t(self, f, unit, prefix=""):
        tm.assert_linear(self, f, lambda k: prefix + unit * k, self.N // 4, cap=1.0)
    def test_strip_meta(self): self._t(hm._strip_meta, '<div id="wpmeta"')
    def test_extract_meta(self): self._t(hwpxconv._extract_meta, '<div id="wpmeta"')
    def test_fnotes_open(self): self._t(hwpxconv._extract_fnotes, '<div class="fnotes">')
    def test_fnotes_p(self): self._t(hwpxconv._extract_fnotes, '<p ', '<div class="fnotes">')
    def test_fnotes_p2(self): self._t(hwpxconv._extract_fnotes, '<p>x</p >', '<div class="fnotes">')
    def test_check_lt(self): self._t(core.check_html, '<')
    def test_check_img(self): self._t(core.check_html, '<img ')
    def test_check_table(self): self._t(core.check_html, '<table')
    def test_eof_tail_old_parser(self):   # Windows CI(3.10.11·3.11.9 = CVE-2025-6069 이전 html.parser): close() 때 닫히지 않은 구성마다 끝까지 재탐색
        from hanword_htmlparse import eof_safe
        for u, pre in (('<img ', ''), ('<table', ''), ('<!-- >', '<p>a</p>'), ('<![CDATA[ ]>', '')):
            tm.assert_linear(self, eof_safe, lambda k: pre + u * k, self.N // 4)
        for s in ('<img ' * 1000, '<table' * 1000, '<p>a</p>' + '<!-- >' * 1000, '<![CDATA[ ]>' * 1000, '<p>x</p><img src="a"'):
            r = eof_safe(s)
            self.assertNotIn("<", r[r.rfind(">") + 1:])                    # 마지막 '>' 뒤 여는 구성 없음
            last = max((m.start() for m in re.finditer(r"--\s*>", r)), default=-1)
            self.assertTrue(all(m.start() + 4 <= last for m in re.finditer("<!--", r)))   # 모든 <!-- 는 뒤에 닫는 짝
        for s in ('<p>a<!--c--></p>', '<![if !supportLists]><p>a</p><![endif]>', '<p title="a<b">x</p>'):
            self.assertEqual(eof_safe(s), s)                                # 닫힌 문서는 바이트 그대로
    def test_semantics(self):
        n, h = hwpxconv._extract_fnotes('<p>a</p><div class="fnotes"><p class="fn-e" data-fn="1"><span class="fn-no">1)</span> 주석</p></div>')
        self.assertEqual(n, {"1": "주석"}); self.assertEqual(h, "<p>a</p>")
        m, h = hwpxconv._extract_meta('<div id="wpmeta" data-header="머리 &gt; x"></div><p>b</p>')
        self.assertEqual(m["header"], "머리 > x"); self.assertEqual(h, "<p>b</p>")
        self.assertEqual(hm._strip_meta('<div id="wpmeta" data-x="a>b"></div><p>c</p><div id="wpmeta"></div>'), "<p>c</p>")
        self.assertTrue(any("중첩" in str(x) for x in core.check_html("<table><tr><td><table></table></td></tr></table>")))
        self.assertFalse(any("중첩" in str(x) for x in core.check_html("<table></table><table></table>")))
        self.assertEqual(hm._strip_meta('<div id="wpmeta"><p>BODY</p>'), '<div id="wpmeta"><p>BODY</p>')   # 안 닫힘=보존
        self.assertEqual(hm._strip_meta('<div  id="wpmeta"\n></div>x'), 'x')
        self.assertEqual(hwpxconv._extract_meta('<div id="wpmeta"><p>B</p>')[1], '<div id="wpmeta"><p>B</p>')
        self.assertEqual(hwpxconv._extract_fnotes('<p>A</p><div class="fnotes"><p>x')[1], '<p>A</p><div class="fnotes"><p>x')
        n, _ = hwpxconv._extract_fnotes('<div class="fnotes"><p class="fn-e" data-fn="2"><span class="fn-no">2)</span>a<pre>b</pre>c</p></div>')
        self.assertEqual(n, {"2": "abc"})

class ZipGuard(unittest.TestCase):
    def _zip(self, method, size=10):
        import io, zipfile
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w", method) as z: z.writestr("word/document.xml", b"x" * size)
        return b.getvalue()
    def test_bzip2_lzma_rejected(self):
        import zipfile, docxconv
        for meth in (zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
            d = self._zip(meth)
            with self.assertRaises(docxconv.DocxInputError): docxconv.guard_docx(d)
            with self.assertRaises(hwpxconv.HwpxInputError): hwpxconv.guard_hwpx_zip(d)
    def test_lying_size(self):
        import zipfile, docxconv, struct
        d = bytearray(self._zip(zipfile.ZIP_DEFLATED, 5 << 20))   # 5MB 반복 → 압축비≫200
        # 중앙 디렉터리·로컬 헤더의 file_size를 1로 위조
        cd = d.rfind(b"PK\x01\x02"); struct.pack_into("<I", d, cd + 24, 1)
        struct.pack_into("<I", d, 22, 1)
        with self.assertRaises(docxconv.DocxInputError): docxconv.guard_docx(bytes(d))
        with self.assertRaises(hwpxconv.HwpxInputError): hwpxconv.guard_hwpx_zip(bytes(d))
    def test_flag_bits(self):
        import zipfile, docxconv, struct
        for bit in (0x1, 0x20, 0x40):
            d = bytearray(self._zip(zipfile.ZIP_DEFLATED))
            cd = d.rfind(b"PK\x01\x02"); f = struct.unpack_from("<H", d, cd + 8)[0]
            struct.pack_into("<H", d, cd + 8, f | bit); struct.pack_into("<H", d, 6, f | bit)
            with self.assertRaises(docxconv.DocxInputError): docxconv.guard_docx(bytes(d))
            with self.assertRaises(hwpxconv.HwpxInputError): hwpxconv.guard_hwpx_zip(bytes(d))
    def test_ratio_bomb(self):
        import zipfile, docxconv
        d = self._zip(zipfile.ZIP_DEFLATED, 20 << 20)
        with self.assertRaisesRegex(docxconv.DocxInputError, "압축비"): docxconv.guard_docx(d)

# ───────────── 중첩 목록(수준 0..8) ─────────────
def lsig(m): return [(b["type"], b.get("list"), b.get("level", 0), hm.block_text(b)) for b in m["blocks"]]

NESTED = ('<p>앞</p><ul><li>가<ol><li>하나<ul><li>점</li></ul></li><li>둘</li></ol></li><li>나</li></ul>'
          '<ol><li>n1</li><ol><ol><li>깊이2</li></ol></ol></ol><p>뒤</p>')
NESTED_SIG = [("p", None, 0, "앞"), ("li", "bullet", 0, "가"), ("li", "number", 1, "하나"), ("li", "bullet", 2, "점"),
              ("li", "number", 1, "둘"), ("li", "bullet", 0, "나"), ("li", "number", 0, "n1"), ("li", "number", 2, "깊이2"), ("p", None, 0, "뒤")]

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
def make_lists_docx():
    """손으로 만든 numbering.xml(수준별 decimal/lowerLetter/bullet, numId 2개)을 가진 결정적 .docx — tests/corpus/lists.docx 원본."""
    import io, zipfile
    def lvl(i, fmt, txt): return ('<w:lvl w:ilvl="%d"><w:start w:val="1"/><w:numFmt w:val="%s"/><w:lvlText w:val="%s"/>'
                                  '<w:pPr><w:ind w:left="%d" w:hanging="360"/></w:pPr></w:lvl>' % (i, fmt, txt, 720 * (i + 1)))
    numbering = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering xmlns:w="%s">'
                 '<w:abstractNum w:abstractNumId="3">%s%s%s</w:abstractNum>'
                 '<w:abstractNum w:abstractNumId="4">%s</w:abstractNum>'
                 '<w:num w:numId="5"><w:abstractNumId w:val="3"/></w:num><w:num w:numId="6"><w:abstractNumId w:val="4"/></w:num>'
                 '</w:numbering>') % (_W, lvl(0, "decimal", "%1."), lvl(1, "lowerLetter", "%2)"), lvl(2, "bullet", "-"),
                                      "".join(lvl(i, "bullet", "o") for i in range(9)))
    def para(text, nid=None, il=0):
        ppr = '<w:pPr><w:numPr><w:ilvl w:val="%d"/><w:numId w:val="%d"/></w:numPr></w:pPr>' % (il, nid) if nid else ""
        return '<w:p>%s<w:r><w:t>%s</w:t></w:r></w:p>' % (ppr, text)
    body = "".join([para("Lists"), para("one", 5, 0), para("one-a", 5, 1), para("dash", 5, 2), para("one-b", 5, 1),
                    para("two", 5, 0), para("between"), para("bul", 6, 0), para("bul-1", 6, 1), para("bul-8", 6, 8), para("end")])
    doc = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="%s"><w:body>%s</w:body></w:document>' % (_W, body)
    files = [("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
              '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
              '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/></Types>'),
             ("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
              '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'),
             ("word/_rels/document.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
              '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/></Relationships>'),
             ("word/document.xml", doc), ("word/numbering.xml", numbering)]
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files: hwpxconv.zip_put(z, name, data)   # 결정적(OS 무관 create_system=3)
    return b.getvalue()
LISTS_DOCX_SIG = [("p", None, 0, "Lists"), ("li", "number", 0, "one"), ("li", "number", 1, "one-a"), ("li", "bullet", 2, "dash"),
                  ("li", "number", 1, "one-b"), ("li", "number", 0, "two"), ("p", None, 0, "between"), ("li", "bullet", 0, "bul"),
                  ("li", "bullet", 1, "bul-1"), ("li", "bullet", 8, "bul-8"), ("p", None, 0, "end")]

class Lists(unittest.TestCase):
    def test_model_render_roundtrip(self):
        m = hm.model(NESTED); self.assertEqual(lsig(m), NESTED_SIG)
        r = hm.render(m)
        self.assertIn("<ul><li>가<ol><li>하나<ul><li>점</li></ul></li><li>둘</li></ol></li><li>나</li></ul>", r)   # 표준 중첩형
        self.assertEqual(hm.model(r), m)
        self.assertNotIn("level", m["blocks"][1])                       # 수준 0은 생략(기존 모델 그대로)
    def test_sibling_form(self):   # execCommand indent 형제형 = 같은 모델
        self.assertEqual(lsig(hm.model('<ul><li>a</li><ul><li>b</li><ul><li>c</li></ul></ul><li>d</li></ul>')),
                         [("li", "bullet", 0, "a"), ("li", "bullet", 1, "b"), ("li", "bullet", 2, "c"), ("li", "bullet", 0, "d")])
    def test_level_clamp_and_validate(self):
        m = hm.model("<ul>" * 20 + "<li>x</li>" + "</ul>" * 20)
        self.assertEqual(m["blocks"][0]["level"], 8)
        for bad in ({"type": "li", "list": "bullet", "level": 9, "runs": []}, {"type": "li", "list": "bullet", "level": True, "runs": []},
                    {"type": "li", "list": "bullet", "level": "1", "runs": []}, {"type": "p", "level": 1, "runs": []}):
            self.assertRaises(ModelError, hm.validate, {"version": 1, "blocks": [bad]})
        hm.validate({"version": 1, "blocks": [{"type": "li", "list": "number", "level": 8, "runs": []}]})
    def test_ops_keep_level(self):
        m = hm.model('<ul><li>a<ul><li>bc</li></ul></li></ul>')
        m = core.apply_ops(m, [{"op": "split_paragraph", "pos": [1, 1]}])
        self.assertEqual(lsig(m), [("li", "bullet", 0, "a"), ("li", "bullet", 1, "b"), ("li", "bullet", 1, "c")])
        m = core.apply_ops(m, [{"op": "set_block_type", "index": 2, "type": "li", "list": "number", "level": 3},
                               {"op": "set_block_type", "index": 1, "type": "li", "list": "number"}])
        self.assertEqual(lsig(m)[1:], [("li", "number", 1, "b"), ("li", "number", 3, "c")])
        m = core.apply_ops(m, [{"op": "set_block_type", "index": 2, "type": "p"}])
        self.assertNotIn("level", m["blocks"][2])
        self.assertRaises(ModelError, core.apply_ops, m, [{"op": "set_block_type", "index": 2, "type": "p", "level": 1}])
        self.assertRaises(ModelError, core.apply_ops, m, [{"op": "set_block_type", "index": 1, "type": "li", "level": 9}])
    def test_docx_roundtrip(self):
        import docxconv, zipfile, io
        m = hm.model(NESTED); d = docxconv.html_to_docx(hm.render(m))
        num = zipfile.ZipFile(io.BytesIO(d)).read("word/numbering.xml").decode()
        self.assertIn('w:ilvl="8"', num); self.assertIn("lowerLetter", num)
        doc = zipfile.ZipFile(io.BytesIO(d)).read("word/document.xml").decode()
        self.assertIn('<w:ilvl w:val="2"/>', doc)
        self.assertEqual(lsig(hm.model(docxconv.docx_to_html(d))), NESTED_SIG)
    def test_hwpx_roundtrip(self):
        import hwpx_std
        m = hm.model(NESTED); x = hwpxconv.html_to_hwpx(hm.render(m))
        self.assertEqual(lsig(hm.model(hwpx_std.read(x))), NESTED_SIG)
    def test_corpus_lists_docx(self):
        import docxconv
        with open(os.path.join(HERE, "corpus", "lists.docx"), "rb") as fp: data = fp.read()
        self.assertEqual(data, make_lists_docx())                       # 코퍼스 파일 = 도우미 산출(재생성: test_model.py --make-corpus)
        m = hm.model(docxconv.docx_to_html(data)); self.assertEqual(lsig(m), LISTS_DOCX_SIG)
        self.assertEqual(lsig(hm.model(docxconv.docx_to_html(docxconv.html_to_docx(hm.render(m))))), LISTS_DOCX_SIG)
        import hwpx_std
        self.assertEqual(lsig(hm.model(hwpx_std.read(hwpxconv.html_to_hwpx(hm.render(m))))), LISTS_DOCX_SIG)

    def _docx_parts(self, html):
        import docxconv, zipfile, io, re
        z = zipfile.ZipFile(io.BytesIO(docxconv.html_to_docx(html)))
        return z.read("word/document.xml").decode(), z.read("word/numbering.xml").decode()
    def test_docx_numbering_no_amplification(self):   # 목록 2만 개 → abstractNum 중복 제거·w:num 상한(출력 증폭 DoS)
        src = "<ul><li>x</li></ul><p>y</p>" * 20000
        doc, num = self._docx_parts(src)
        self.assertLess(len(num), len(src))                              # 예전엔 ~35MB(65배)
        self.assertEqual(num.count("<w:abstractNum "), 1)
        self.assertLessEqual(num.count("<w:num "), 5000)
    def test_docx_sublist_keeps_top_numbering(self):   # 종류 다른 하위목록이 와도 상위 번호(1,2,3)는 같은 numId로 이어짐
        import re
        h = '<ol><li>a<ul><li>s</li></ul></li><li>b<ol><li>n</li></ol></li><li>c</li></ol>'
        doc, num = self._docx_parts(h)
        ids = re.findall(r'<w:ilvl w:val="(\d)"/><w:numId w:val="(\d+)"/>', doc)
        top = {n for lv, n in ids if lv == "0"}
        self.assertEqual(len(top), 1, ids)
        import docxconv
        m = hm.model(docxconv.docx_to_html(docxconv.html_to_docx(h)))
        self.assertEqual(lsig(m), [("li", "number", 0, "a"), ("li", "bullet", 1, "s"), ("li", "number", 0, "b"), ("li", "number", 1, "n"), ("li", "number", 0, "c")])
    def test_level_non_numeric(self):   # 모델 정규화: 숫자 아닌 level은 ValueError 없이 0
        self.assertEqual(hm._block_norm({"tag": "li", "list": "bullet", "level": "x", "runs": []}), {"type": "li", "list": "bullet", "runs": []})
        self.assertEqual(hm._block_norm({"tag": "li", "list": "bullet", "level": "99", "runs": []})["level"], 8)
    def test_hwpx_heading_levels(self):   # 목록 수준 = paraPr heading level, idRef는 실제 bullet/numbering을 가리킴
        import zipfile, io, re
        z = zipfile.ZipFile(io.BytesIO(hwpxconv.html_to_hwpx('<ul><li>a<ul><li>b<ul><li>c</li></ul></li></ul></li></ul><ol><li>n<ol><li>m</li></ol></li></ol>')))
        hd = z.read("Contents/header.xml").decode()
        got = sorted(set(re.findall(r'<hh:heading type="(BULLET|NUMBER)" idRef="(\d+)" level="(\d)"/>', hd)))
        self.assertEqual(got, [("BULLET", "1", "0"), ("BULLET", "1", "1"), ("BULLET", "1", "2"), ("NUMBER", "1", "0"), ("NUMBER", "1", "1")])
        self.assertRegex(hd, r'<hh:bullet id="1"[^>]*><hh:paraHead ')        # 글머리표 = paraHead 하나(한글 저장본과 같은 구조)
        self.assertRegex(hd, r'<hh:numbering id="1"[^>]*>(<hh:paraHead [^>]*level="\d+"[^>]*(/>|>[^<]*</hh:paraHead>)){10}')
    @unittest.skipUnless(__import__("importlib").util.find_spec("hwpx"), "python-hwpx 없음(선택)")
    def test_hwpx_python_hwpx_parses_levels(self):
        import io
        from hwpx import HwpxDocument
        doc = HwpxDocument.open(io.BytesIO(hwpxconv.html_to_hwpx('<ul><li>a<ul><li>b</li></ul></li></ul><ol><li>n<ol><li>m</li></ol></li></ol>')))
        self.assertIsNotNone(doc.bullet(1))
        got = []
        for p in doc.paragraphs:
            h = getattr(doc.paragraph_property(p.para_pr_id_ref), "heading", None)
            if h is not None and getattr(h, "type", None) in ("BULLET", "NUMBER"): got.append((p.text, h.type, int(h.level)))
        self.assertEqual(got, [("a", "BULLET", 0), ("b", "BULLET", 1), ("n", "NUMBER", 0), ("m", "NUMBER", 1)])

class CellParas(unittest.TestCase):   # 2026-11-13 표 셀 여러 문단(model·DOCX·HWPX 왕복)
    HTML = ('<table><tr><td style="text-align:center"><p>첫 문단</p><p style="text-align:right;"><b>둘째</b> 문단</p><p><br></p></td>'
            '<td>윗줄<br>아랫줄</td><td>한 문단<br></td><td><p><br></p></td></tr></table>')
    @staticmethod
    def _cells(m): return [{k: v for k, v in c.items() if k in ("runs", "paras", "align")} for c in m["blocks"][0]["rows"][0]]
    def test_model(self):
        m = core.model(self.HTML); hm.validate(m); c = self._cells(m)
        self.assertEqual(c[0], {"align": "center", "paras": [{"runs": [{"text": "첫 문단"}]},
                         {"runs": [{"text": "둘째", "bold": True}, {"text": " 문단"}], "align": "right"}, {"runs": []}]})
        self.assertEqual(c[1]["paras"], [{"runs": [{"text": "윗줄"}]}, {"runs": [{"text": "아랫줄"}]}])
        self.assertEqual(c[2], {"runs": [{"text": "한 문단"}]})      # 1문단·끝 <br> 자리표시 = 구형 runs
        self.assertEqual(c[3], {"runs": []})
        self.assertEqual(core.model(core.render(m)), m)
        self.assertIn("윗줄 아랫줄", core.plain_text(self.HTML))
    def test_validate(self):
        cell = lambda **k: {"type": "table", "rows": [[dict({"colspan": 1, "rowspan": 1}, **k)]]}
        ok = {"version": 1, "blocks": [cell(paras=[{"runs": [{"text": "a"}]}, {"runs": [], "align": "center"}])]}
        hm.validate(ok); self.assertIn("<p>a</p><p style=\"text-align:center;\"><br></p>", hm.render(ok))
        for bad in (cell(paras=[{"runs": []}], runs=[]), cell(paras=[]), cell(paras=[{"align": "left"}]), cell(paras=[{"runs": [], "x": 1}]),
                    cell(paras=[{"runs": [], "align": "middle"}]), cell(paras=[{"runs": [{"text": "a\nb"}]}]), cell(paras="x"),
                    cell(paras=[{"runs": []}] * (hm.MAX_CPARAS + 1))):
            with self.assertRaises(ModelError): hm.validate({"version": 1, "blocks": [bad]})
        hm.validate(BASE)                                    # 구형 runs 셀 그대로 통과
        pm = copy.deepcopy(BASE); pm["blocks"][2] = ok["blocks"][0]   # 여러 문단 셀 문서에서도 연산 정상
        m2 = hm.apply(pm, [{"op": "insert_text", "pos": [3, 0], "text": "X"}, {"op": "delete_block", "index": 0}])
        self.assertEqual(hm.block_text(m2["blocks"][2]), "X끝"); self.assertEqual(m2["blocks"][1], ok["blocks"][0])
    def _rt(self, html):
        m = core.model(html); return self._cells(m)
    def test_docx(self):
        self.assertEqual(self._rt(core.import_bytes(core.export_html(self.HTML, "docx"), "docx")), self._rt(self.HTML))
    def test_hwpx_std(self):
        e = hwpxconv.HWPX_ENGINE; hwpxconv.HWPX_ENGINE = "std"
        try: h = hwpxconv.hwpx_bytes_to_html(hwpxconv.html_to_hwpx(self.HTML))
        finally: hwpxconv.HWPX_ENGINE = e
        self.assertEqual(self._rt(h), self._rt(self.HTML))
    def test_hwpx_std_read_by_pyhwpx(self):   # hwpx-xcheck 방식: std 작성 → python-hwpx 읽기(있을 때만)
        try: import hwpx  # noqa: F401
        except Exception: self.skipTest("python-hwpx 없음")
        e = hwpxconv.HWPX_ENGINE
        try:
            hwpxconv.HWPX_ENGINE = "std"; d = hwpxconv.html_to_hwpx(self.HTML)
            hwpxconv.HWPX_ENGINE = "pyhwpx"; h = hwpxconv.hwpx_bytes_to_html(d)
        finally: hwpxconv.HWPX_ENGINE = e
        self.assertEqual(self._rt(h), self._rt(self.HTML))
    def test_linear(self):
        T = lambda inner: "<table><tr><td>" + inner + "</td></tr></table>"
        for mk in (lambda k: T("a<br>" * k), lambda k: T("<p>a</p>" * k), lambda k: T("<div>" * (k // 2) + "a" + "</div>" * (k // 2))):
            tm.assert_linear(self, core.model, mk, 25000, cap=5.0, reps=1)
            hm.validate(core.model(mk(1000)))
    def test_deep_inline_linear(self):   # 감사: merged()가 텍스트 노드×인라인 깊이(84s 재현) → 단계 캐시로 선형
        import time
        tm.assert_linear(self, core.model, lambda k: "<table><tr><td>" + "<span>" * k + "x<br>" * k + "</td></tr></table>", 5000, cap=2.0, reps=1)
        tm.assert_linear(self, core.model, lambda k: "<p>" + "<b><i>" * k + "y " * k + "</p>", 5000, cap=2.0, reps=1)
        hm.validate(core.model("<table><tr><td>" + "<span>" * 200 + "x<br>" * 200 + "</td></tr></table>"))
    def test_converter_para_cap(self):   # 감사: 변환기 경로도 셀 문단 수 상한(1M <br> → 1M w:p/hp:p 차단)
        import zipfile, io
        n = hwpxconv.MAX_CPARAS + 500
        s = "<table><tr><td>" + "a<br>" * n + "z</td></tr></table>"
        p = hwpxconv._PP(); p.feed(s); p.close(); p.flush()
        c = p.paras[0]["rows"][0][0]
        self.assertEqual(len(c["paras"]), hwpxconv.MAX_CPARAS)
        self.assertEqual(hm.cell_runs({"paras": c["paras"]}) and "".join(r.get("text", "") for r in c["runs"]).count("a"), n)   # 글자 보존
        d = core.export_html(s, "docx")
        with zipfile.ZipFile(io.BytesIO(d)) as z: self.assertLessEqual(z.read("word/document.xml").count(b"<w:p>"), hwpxconv.MAX_CPARAS + 10)
        e = hwpxconv.HWPX_ENGINE; hwpxconv.HWPX_ENGINE = "std"
        try: h = hwpxconv.html_to_hwpx(s)
        finally: hwpxconv.HWPX_ENGINE = e
        with zipfile.ZipFile(io.BytesIO(h)) as z: self.assertLessEqual(z.read("Contents/section0.xml").count(b"<hp:p "), hwpxconv.MAX_CPARAS + 10)
        m = core.model(s); hm.validate(m); self.assertEqual(len(m["blocks"][0]["rows"][0][0]["paras"]), hwpxconv.MAX_CPARAS)
    def test_unclosed_blocks_in_cell(self):
        s = "<table><tr><td>" + "<div>" * 1000 + "a<p style=\"text-align:center\">b</p>c" + "</div>" * 1000 + "</td></tr></table>"
        m = core.model(s); hm.validate(m)
        self.assertEqual(["".join(r["text"] for r in p["runs"]) for p in m["blocks"][0]["rows"][0][0]["paras"]], ["a", "b", "c"])

# ───────────── 2026-11-13 TASK C: 한컴 하이퍼링크·용지 메타·레거시 .doc ─────────────
import io, re, zipfile, random, struct
import xml.etree.ElementTree as ET
import hwpx_std, docxconv, docconv
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
def _fx(name):
    with open(os.path.join(HERE, "corpus", name), "rb") as fp: return fp.read()
def _hrefs(h): return re.findall(r'<a href="([^"]*)"', h)
def _fb(inner, name=""):
    return ET.fromstring('<hp:fieldBegin xmlns:hp="%s" type="HYPERLINK" name="%s">%s</hp:fieldBegin>' % (HP, name, inner))
def _prm(path=None, cmd=None):
    x = '<hp:parameters cnt="2" name="">'
    if cmd is not None: x += '<hp:stringParam name="Command">%s</hp:stringParam>' % cmd
    if path is not None: x += '<hp:stringParam name="Path">%s</hp:stringParam>' % path
    return x + '</hp:parameters>'
def _meta(h):
    m = re.search(r'<div id="wpmeta"[^>]*>', h); return dict(re.findall(r'data-([a-z-]+)="([^"]*)"', m.group(0))) if m else {}

class HancomLink(unittest.TestCase):
    def test_fixture_reads_links(self):
        h = core.import_bytes(_fx("hancom-link.hwpx"), "hwpx")
        self.assertEqual(_hrefs(h), ["https://example.com/a", "mailto:hong@example.com", "https://example.org/q?x=1;y=2"])
        self.assertIn(">예제 사이트</a> 뒤", h)
    def test_param_forms(self):
        f = hwpxconv._field_link_url
        self.assertEqual(f(_fb(_prm(path="https://a.example/p"))), "https://a.example/p")
        self.assertEqual(f(_fb(_prm(cmd=r"https\://b.example/x\;y\\z;1;0;0;"))), r"https://b.example/x;y\z")
        self.assertEqual(f(_fb(_prm(path="mailto:x@y.z"))), "mailto:x@y.z")
        self.assertIsNone(f(_fb(_prm(path="javascript:alert(1)", cmd=r"javascript\:alert(1);1;0;0;"))))
        self.assertIsNone(f(_fb(_prm(path="tel:010"))))                      # 한컴형은 http/https/mailto만
        self.assertIsNone(f(_fb(_prm(path=" jav&#x09;ascript:x"))))
        self.assertIsNone(f(_fb(_prm(path="#bookmark"))))
        self.assertEqual(f(_fb("", name="https://old.example/")), "https://old.example/")   # python-hwpx·구 한워드형(name)
        self.assertIsNone(f(_fb("", name="javascript:x")))
        self.assertIsNone(f(_fb(_prm(path="https://" + "a" * 3000))))
    def test_writer_emits_hancom_form(self):
        hwpxconv.HWPX_ENGINE = "std"
        d = hwpxconv.html_to_hwpx('<p>a <a href="https://ex.com/a;b:c">링크</a> b <a href="tel:0101">전화</a></p>')
        sec = zipfile.ZipFile(io.BytesIO(d)).read("Contents/section0.xml").decode()
        self.assertIn('<hp:stringParam name="Path">https://ex.com/a;b:c</hp:stringParam>', sec)
        self.assertIn(r'<hp:stringParam name="Command">https\://ex.com/a\;b\:c;1;0;0;</hp:stringParam>', sec)
        self.assertEqual(sec.count("<hp:parameters"), 1)                    # tel은 name 속성만
        self.assertEqual(_hrefs(hwpxconv.hwpx_bytes_to_html(d)), ["https://ex.com/a;b:c", "tel:0101"])

class PaperMeta(unittest.TestCase):
    H = '<p>본문</p><div id="wpmeta" hidden="" data-paper="B5" data-orient="landscape" data-margins="10,15,20,25.5"></div>'
    WANT = {"paper": "B5", "orient": "landscape", "margins": "10,15,20,25.5"}
    def test_meta_page_validation(self):
        mp = hwpxconv._meta_page
        self.assertIsNone(mp({}))
        self.assertEqual(mp({"paper": "B5", "orient": "landscape", "margins": "10,15,20,25.5"}),
                         {"paper": "B5", "orient": "landscape", "mt": 10, "mr": 15, "mb": 20, "ml": 25.5})
        self.assertEqual(mp({"paper": "Z9"}), None)
        self.assertEqual(mp({"paper": "Z9", "orient": "landscape"})["paper"], "A4")
        for bad in ("101,0,0,0", "1,2,3", "-1,2,3,4", "1e2,0,0,0", "1.25,0,0,0", "1,2,3,4,5", "", "a,b,c,d"):
            self.assertIsNone(hwpxconv._parse_margins(bad), bad)
    def test_model_strict(self):
        m = hm.model(self.H); self.assertEqual({k: m["meta"][k] for k in self.WANT}, self.WANT)
        self.assertEqual(hm.render(m), self.H)
        self.assertNotIn("paper", hm.model('<p>x</p><div id="wpmeta" hidden="" data-paper="&lt;x" data-orient="up" data-margins="999,0,0,0"></div>')["meta"])
        for k, v in (("paper", "Q1"), ("orient", "sideways"), ("margins", "1,2,3")):
            bad = copy.deepcopy(BASE); bad["meta"] = {k: v}
            with self.assertRaises(ModelError): hm.validate(bad)
    def test_hwpx_roundtrip(self):
        hwpxconv.HWPX_ENGINE = "std"
        d = core.export_html(self.H, "hwpx")
        sec = zipfile.ZipFile(io.BytesIO(d)).read("Contents/section0.xml").decode()
        self.assertRegex(sec, r'<hp:pagePr landscape="NARROWLY" width="72850" height="51591"')
        self.assertEqual({k: v for k, v in _meta(core.import_bytes(d, "hwpx")).items() if k in self.WANT}, self.WANT)
    def test_docx_roundtrip(self):
        d = core.export_html(self.H, "docx")
        doc = zipfile.ZipFile(io.BytesIO(d)).read("word/document.xml").decode()
        self.assertIn('w:orient="landscape"', doc); self.assertIn('w:left="1446"', doc)
        self.assertEqual({k: v for k, v in _meta(core.import_bytes(d, "docx")).items() if k in self.WANT}, self.WANT)
    def test_explicit_page_wins(self):
        d = core.export_html(self.H, "docx", page={"paper": "A4", "orient": "portrait"})
        self.assertNotIn("paper", _meta(core.import_bytes(d, "docx")))
    def test_default_doc_no_meta(self):
        for fmt in ("hwpx", "docx"):
            self.assertEqual({k: v for k, v in _meta(core.import_bytes(core.export_html("<p>x</p>", fmt), fmt)).items()
                              if k in ("paper", "orient", "margins")}, {}, fmt)
    def test_a6_tabloid_export(self):   # hwpx_std._page가 PAPERS_MM 단일 원천 사용(A6·B6·Tabloid 누락 회귀)
        hwpxconv.HWPX_ENGINE = "std"
        for paper, w in (("A6", 29764), ("B6", 36283), ("Tabloid", 79200)):
            d = core.export_html('<p>x</p><div id="wpmeta" hidden="" data-paper="%s"></div>' % paper, "hwpx")
            sec = zipfile.ZipFile(io.BytesIO(d)).read("Contents/section0.xml").decode()
            self.assertIn('width="%d"' % w, sec, paper)
            self.assertEqual(_meta(core.import_bytes(d, "hwpx")).get("paper"), paper)
    def test_no_page_defaults_a4_20mm(self):   # 동작 변경: 용지 미지정 HWPX = 편집기 기본 A4·여백 20mm(골격 30/30/20/15 아님)
        hwpxconv.HWPX_ENGINE = "std"
        sec = zipfile.ZipFile(io.BytesIO(hwpxconv.html_to_hwpx("<p>x</p>"))).read("Contents/section0.xml").decode()
        self.assertIn('width="59528" height="84189"', sec)
        self.assertIn('left="5669" right="5669" top="5669" bottom="5669"', sec)
    def test_nan_page(self):
        hwpxconv.HWPX_ENGINE = "std"
        for bad in (float("nan"), float("inf")):
            for pg in ({"w": bad, "h": 200}, {"ml": bad}):
                self.assertTrue(core.export_html("<p>x</p>", "hwpx", page=pg)[:2] == b"PK")
                self.assertTrue(core.export_html("<p>x</p>", "docx", page=pg)[:2] == b"PK")
        self.assertEqual(docxconv._num(float("nan"), 0, 100, 20), 20)
    def test_import_unknown_size(self):
        self.assertEqual(hwpxconv._page_meta_attrs(200, 200, 20, 20, 20, 20), {})
        self.assertEqual(hwpxconv._page_meta_attrs(297, 210, 20, 20, 20, 20), {"orient": "landscape"})
        self.assertEqual(hwpxconv._page_meta_attrs(215.9, 279.4, 25.4, 25.4, 25.4, 25.4), {"paper": "Letter", "margins": "25.4,25.4,25.4,25.4"})

class LegacyDoc(unittest.TestCase):
    def test_detect_and_text(self):
        d = _fx("word97.doc")
        self.assertEqual(core.detect(d), "doc")
        h = core.import_bytes(d)
        for t in ("<p>첫 문단 Hello</p>", "유니코드 ✓", "<p>링크: 예제 끝</p>", "<p>A1</p>", "<p>마지막</p>"): self.assertIn(t, h)
        self.assertNotIn("HYPERLINK", h)                                   # 필드 코드는 버리고 결과만
    def test_rtf_message(self):
        with self.assertRaisesRegex(core.InputError, "RTF"): core.import_bytes(b"{\\rtf1\\ansi hello}", None, "x.doc")
    def test_not_word_ole(self):
        self.assertEqual(docconv.cfb_kind(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600), "hwp")
    def test_encrypted(self):
        d = bytearray(_fx("word97.doc")); c = docconv._Cfb(bytes(d))
        st = c.dirs[c.names["WordDocument"]][3]; d[512 + st * c.ss + 0x0B] |= 0x01
        with self.assertRaisesRegex(core.InputError, "암호"): docconv.doc_to_html(bytes(d))
    def test_fuzz_only_input_errors(self):
        d = _fx("word97.doc"); rnd = random.Random(7)
        for k in (100, 600, 2000, len(d) // 2):
            with self.assertRaises(core.InputError): docconv.doc_to_html(d[:k])
        self.assertEqual(core.detect(d[:6000]), "doc")                    # 잘린 .doc도 .doc로 판별(hwp 오보 금지)
        with self.assertRaisesRegex(core.InputError, "OLE|Word"): core.import_bytes(d[:6000])
        for _ in range(300):
            b = bytearray(d)
            for _ in range(rnd.randint(1, 8)): b[rnd.randrange(512, len(b))] = rnd.randrange(256)
            try: docconv.doc_to_html(bytes(b))
            except core.InputError: pass
    def test_non_bmp(self):   # UTF-16 조각의 서로게이트 쌍(2코드단위=1글자)도 정상 문서로
        h = core.import_bytes(_fx("word97-nonbmp.doc"))
        self.assertIn("이모지 \U0001F600", h); self.assertIn("<p>끝 문단</p>", h)
    def test_clean_linear(self):   # 필드 중첩 판정 O(1)/글자 — 예전 any(stack) 2차시간 회귀
        import time
        t = time.time(); docconv._clean("\x13" * 60 + "x" * 400000 + "\x15" * 60)
        docconv._clean(("\x13" * 100 + "a\x14b" + "\x15" * 100) * 3000)
        self.assertLess(time.time() - t, tm.limit(1.5))
        self.assertEqual(docconv._clean("a\x13 HYPERLINK x\x14결과\x15b\r"), ["a결과b"])
        self.assertEqual(docconv._clean("\x13" * 70 + "c\x14r" + "\x15" * 70 + "z\r"), ["z"])   # 깊이 64 초과분도 짝 맞춤
    def test_fat_is_array(self):
        import array
        c = docconv._Cfb(_fx("word97.doc")); self.assertIsInstance(c.fat, array.array)
    def test_parse_once(self):   # detect→import가 같은 bytes면 CFB 해석 1회
        d = _fx("word97.doc"); n = [0]; orig = docconv._Cfb.__init__
        def cnt(self, data): n[0] += 1; orig(self, data)
        docconv._Cfb.__init__ = cnt
        try: core.import_bytes(d)
        finally: docconv._Cfb.__init__ = orig
        self.assertEqual(n[0], 1)
    def test_fat_loop(self):   # FAT 순환 체인 → 거부(무한루프 없음)
        d = bytearray(_fx("word97.doc")); c = docconv._Cfb(bytes(d))
        st = c.dirs[c.names["WordDocument"]][3]
        fs = struct.unpack_from("<I", d, 0x4C)[0]; off = 512 + fs * c.ss + st * 4
        struct.pack_into("<I", d, off, st)
        with self.assertRaises(core.InputError): docconv.doc_to_html(bytes(d))

class ZipDeterminism(unittest.TestCase):   # 2026-11-13 Windows CI: create_system 0x00 vs 0x03 차이
    def test_create_system_unix(self):
        import zipfile, io, docxconv
        h = "<p>a</p><table><tr><td>b</td></tr></table>"
        for data in (docxconv.html_to_docx(h), hwpxconv.html_to_hwpx(h), make_lists_docx()):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for i in z.infolist():
                    self.assertEqual(i.create_system, 3, i.filename); self.assertEqual(i.date_time, (1980, 1, 1, 0, 0, 0), i.filename)
    def test_deterministic_bytes(self):
        import docxconv
        h = "<p>a</p>"
        self.assertEqual(docxconv.html_to_docx(h), docxconv.html_to_docx(h)); self.assertEqual(hwpxconv.html_to_hwpx(h), hwpxconv.html_to_hwpx(h))

# ───────────── D11 표·그림·용지 연산 / D12 위·아래 첨자 (2026-11-13) ─────────────
PNG = "data:image/png;base64,iVBORw0KGgo="
def _doc(*blocks): return {"version": 1, "meta": {}, "notes": {}, "blocks": list(blocks)}
def _p(t): return {"type": "p", "runs": [{"text": t}] if t else []}
def _grid(rows, cols, fill=True):
    return {"type": "table", "rows": [[{"colspan": 1, "rowspan": 1, "runs": [{"text": "%d%d" % (r, c)}] if fill else []}
                                       for c in range(cols)] for r in range(rows)]}
def _shape(t):   # [(rowspan, colspan, 글)] 줄별
    return [[(c["rowspan"], c["colspan"], " | ".join(hm.block_text(p) for p in hm._cell_paras(c))) for c in row] for row in t["rows"]]
def _tops(m, *ops): return hm.apply(m, [dict(o) for o in ops])

class TableOps(unittest.TestCase):
    def test_insert_table(self):
        m = _tops(_doc(_p("가나다")), {"op": "insert_table", "pos": [0, 1], "rows": 2, "cols": 3})
        self.assertEqual([b["type"] for b in m["blocks"]], ["p", "table", "p"])
        self.assertEqual(hm.block_text(m["blocks"][0]), "가"); self.assertEqual(hm.block_text(m["blocks"][2]), "나다")
        self.assertEqual(_shape(m["blocks"][1]), [[(1, 1, "")] * 3] * 2)
        m = _tops(_doc(_p("가")), {"op": "insert_table", "pos": [0, 0], "rows": 1, "cols": 1})   # 문단 앞
        self.assertEqual([b["type"] for b in m["blocks"]], ["table", "p"])
        m = _tops(_doc(_p("가")), {"op": "insert_table", "pos": [1, 0], "rows": 1, "cols": 1})   # 문서 끝
        self.assertEqual([b["type"] for b in m["blocks"]], ["p", "table"])
        self.assertEqual(hm.model(hm.render(m)), m)
        for bad in ({"rows": 0, "cols": 1}, {"rows": 201, "cols": 1}, {"rows": 1, "cols": 65}, {"rows": "2", "cols": 2}, {"rows": True, "cols": 2}):
            with self.assertRaises(ModelError): _tops(_doc(_p("가")), dict({"op": "insert_table", "pos": [0, 0]}, **bad))
        with self.assertRaises(ModelError): _tops(_doc(_p("가")), {"op": "insert_table", "pos": [0, 5], "rows": 1, "cols": 1})
        t = _doc(_grid(1, 1))
        with self.assertRaises(ModelError): _tops(t, {"op": "insert_table", "pos": [0, 0, 0, 0, 0], "rows": 1, "cols": 1})   # 중첩 표 없음

    def test_rows(self):
        m = _tops(_doc(_grid(3, 2)), {"op": "table_insert_rows", "index": 0, "at": 1, "n": 2})
        self.assertEqual(_shape(m["blocks"][0]), [[(1, 1, "00"), (1, 1, "01")], [(1, 1, "")] * 2, [(1, 1, "")] * 2,
                                                 [(1, 1, "10"), (1, 1, "11")], [(1, 1, "20"), (1, 1, "21")]])
        m = _tops(_doc(_grid(2, 2)), {"op": "table_insert_rows", "index": 0, "at": 2})   # 끝에 1줄(n 기본 1)
        self.assertEqual(len(m["blocks"][0]["rows"]), 3)
        # 병합 걸친 줄: 안쪽에 넣으면 rowspan 늘림, 경계에 넣으면 그대로
        sp = _tops(_doc(_grid(3, 2)), {"op": "table_merge", "index": 0, "r0": 0, "c0": 0, "r1": 1, "c1": 0})
        m = _tops(sp, {"op": "table_insert_rows", "index": 0, "at": 1, "n": 1})
        self.assertEqual(_shape(m["blocks"][0]), [[(3, 1, "00 | 10"), (1, 1, "01")], [(1, 1, "")], [(1, 1, "11")], [(1, 1, "20"), (1, 1, "21")]])
        m = _tops(sp, {"op": "table_insert_rows", "index": 0, "at": 2, "n": 1})
        self.assertEqual(_shape(m["blocks"][0])[0][0], (2, 1, "00 | 10")); self.assertEqual(len(m["blocks"][0]["rows"]), 4)
        # 지우기: 병합 첫 줄을 지우면 글은 남은 첫 줄로, rowspan 줄임
        m = _tops(sp, {"op": "table_delete_rows", "index": 0, "at": 0, "n": 1})
        self.assertEqual(_shape(m["blocks"][0]), [[(1, 1, "00 | 10"), (1, 1, "11")], [(1, 1, "20"), (1, 1, "21")]])
        m = _tops(sp, {"op": "table_delete_rows", "index": 0, "at": 0, "n": 2})   # 병합 전체가 지워짐
        self.assertEqual(_shape(m["blocks"][0]), [[(1, 1, "20"), (1, 1, "21")]])
        m = _tops(sp, {"op": "table_delete_rows", "index": 0, "at": 1, "n": 2})
        self.assertEqual(_shape(m["blocks"][0]), [[(1, 1, "00 | 10"), (1, 1, "01")]])
        rh = _doc(dict(_grid(2, 1), rowh=[30, 40]))
        self.assertEqual(_tops(rh, {"op": "table_insert_rows", "index": 0, "at": 1})["blocks"][0]["rowh"], [30, 30, 40])
        self.assertEqual(_tops(rh, {"op": "table_delete_rows", "index": 0, "at": 0})["blocks"][0]["rowh"], [40])
        for op in ({"op": "table_insert_rows", "index": 0, "at": 0, "n": 101}, {"op": "table_insert_rows", "index": 0, "at": 0, "n": 0},
                   {"op": "table_insert_rows", "index": 0, "at": 4}, {"op": "table_delete_rows", "index": 0, "at": 0, "n": 3},
                   {"op": "table_delete_rows", "index": 0, "at": 3}, {"op": "table_delete_rows", "index": 0, "at": 2, "n": 2},
                   {"op": "table_insert_rows", "index": 1, "at": 0}):
            with self.assertRaises(ModelError, msg=op): _tops(_doc(_grid(3, 2), _p("x")), op)
        with self.assertRaisesRegex(ModelError, "마지막 줄"): _tops(_doc(_grid(1, 2)), {"op": "table_delete_rows", "index": 0, "at": 0})

    def test_cols_and_widths(self):
        t = _grid(2, 3)
        for row in t["rows"]:
            for c, w in zip(row, (100, 200, 300)): c["width"] = w
        m = _tops(_doc(t), {"op": "table_insert_cols", "index": 0, "at": 1, "n": 1})
        self.assertEqual(_shape(m["blocks"][0])[0], [(1, 1, "00"), (1, 1, ""), (1, 1, "01"), (1, 1, "02")])
        ws = [c["width"] for c in m["blocks"][0]["rows"][0]]
        self.assertEqual(sum(ws), 600); self.assertEqual(ws[1], ws[2] * 150 // 200)   # 이웃 평균 150, 표 너비 유지(비례)
        m = _tops(_doc(t), {"op": "table_delete_cols", "index": 0, "at": 0})
        self.assertEqual(sum(c["width"] for c in m["blocks"][0]["rows"][0]), 600)
        self.assertNotIn("width", _tops(_doc(_grid(1, 2)), {"op": "table_insert_cols", "index": 0, "at": 2})["blocks"][0]["rows"][0][0])
        sp = _tops(_doc(_grid(2, 3)), {"op": "table_merge", "index": 0, "r0": 0, "c0": 0, "r1": 0, "c1": 1})
        m = _tops(sp, {"op": "table_insert_cols", "index": 0, "at": 1, "n": 2})   # 병합 안쪽 = colspan 늘림
        self.assertEqual(_shape(m["blocks"][0]), [[(1, 4, "00 | 01"), (1, 1, "02")], [(1, 1, "10"), (1, 1, ""), (1, 1, ""), (1, 1, "11"), (1, 1, "12")]])
        m = _tops(sp, {"op": "table_delete_cols", "index": 0, "at": 0})
        self.assertEqual(_shape(m["blocks"][0]), [[(1, 1, "00 | 01"), (1, 1, "02")], [(1, 1, "11"), (1, 1, "12")]])
        for op in ({"op": "table_insert_cols", "index": 0, "at": 0, "n": 101}, {"op": "table_insert_cols", "index": 0, "at": 4},
                   {"op": "table_delete_cols", "index": 0, "at": 0, "n": 3}, {"op": "table_delete_cols", "index": 0, "at": 1, "n": 3}):
            with self.assertRaises(ModelError, msg=op): _tops(_doc(_grid(1, 3)), op)
        with self.assertRaisesRegex(ModelError, "칸 과다"): _tops(_doc(_grid(1, 200)), {"op": "table_insert_cols", "index": 0, "at": 0, "n": 57})

    def test_merge_split(self):
        base = _doc(_grid(3, 3))
        m = _tops(base, {"op": "table_merge", "index": 0, "r0": 0, "c0": 0, "r1": 1, "c1": 1})
        self.assertEqual(_shape(m["blocks"][0]), [[(2, 2, "00 | 01 | 10 | 11"), (1, 1, "02")], [(1, 1, "12")], [(1, 1, "20"), (1, 1, "21"), (1, 1, "22")]])
        self.assertEqual(hm.model(hm.render(m)), m)
        s = _tops(m, {"op": "table_split", "index": 0, "r": 0, "c": 0})   # 왕복: 구조 복원, 글은 첫 칸
        self.assertEqual([[(a, b) for a, b, _ in row] for row in _shape(s["blocks"][0])], [[(1, 1)] * 3] * 3)
        self.assertEqual(_shape(s["blocks"][0])[0][0][2], "00 | 01 | 10 | 11"); self.assertEqual(_shape(s["blocks"][0])[1][0][2], "")
        e = copy.deepcopy(base); e["blocks"][0]["rows"][0][0]["runs"] = []; e["blocks"][0]["rows"][0][1]["bg"] = "#FF0000"
        em = _tops(e, {"op": "table_merge", "index": 0, "r0": 0, "c0": 0, "r1": 0, "c1": 1})   # 빈 칸은 건너뜀, 서식 = 첫 칸
        self.assertEqual(em["blocks"][0]["rows"][0][0]["runs"], [{"text": "01"}]); self.assertNotIn("bg", em["blocks"][0]["rows"][0][0])
        for op in ({"r0": 0, "c0": 0, "r1": 0, "c1": 0}, {"r0": 1, "c0": 0, "r1": 0, "c1": 0}, {"r0": 0, "c0": 0, "r1": 3, "c1": 0},
                   {"r0": 1, "c0": 1, "r1": 2, "c1": 2}):   # 마지막 = 걸친 병합(0,0~1,1)이 밖으로 나감
            with self.assertRaises(ModelError, msg=op): _tops(m if op["r0"] == 1 and op["c0"] == 1 else base, dict({"op": "table_merge", "index": 0}, **op))
        with self.assertRaisesRegex(ModelError, "걸침"): _tops(m, {"op": "table_merge", "index": 0, "r0": 0, "c0": 1, "r1": 0, "c1": 2})
        with self.assertRaisesRegex(ModelError, "합친 칸이 아님"): _tops(base, {"op": "table_split", "index": 0, "r": 0, "c": 0})
        with self.assertRaisesRegex(ModelError, "칸 없음"): _tops(m, {"op": "table_split", "index": 0, "r": 1, "c": 1})

    def test_ragged_and_overlap(self):
        rg = _doc({"type": "table", "rows": [[{"colspan": 1, "rowspan": 1, "runs": [{"text": "a"}]}, {"colspan": 1, "rowspan": 1, "runs": []}],
                                             [{"colspan": 1, "rowspan": 1, "runs": [{"text": "b"}]}]]})
        m = _tops(rg, {"op": "table_insert_cols", "index": 0, "at": 2})   # 짧은 줄 끝 빈 자리 = 빈 칸으로 채움
        self.assertEqual([len(r) for r in m["blocks"][0]["rows"]], [3, 3])
        ov = _doc({"type": "table", "rows": [[{"colspan": 1, "rowspan": 1, "runs": []}, {"colspan": 1, "rowspan": 2, "runs": []}],
                                             [{"colspan": 2, "rowspan": 1, "runs": []}]]})   # (1,0) colspan 2 가 (1,1) rowspan과 겹침
        with self.assertRaisesRegex(ModelError, "겹침"): _tops(ov, {"op": "table_insert_rows", "index": 0, "at": 0})

    def test_table_cell(self):
        m = _tops(_doc(_grid(2, 2)), {"op": "table_cell", "index": 0, "r": 1, "c": 1, "runs": [{"text": "굵게", "bold": True}], "bg": "#00ff00", "align": "center"})
        c = m["blocks"][0]["rows"][1][1]
        self.assertEqual(c, {"colspan": 1, "rowspan": 1, "runs": [{"text": "굵게", "bold": True}], "bg": "#00FF00", "align": "center"})
        m = _tops(m, {"op": "table_cell", "index": 0, "r": 1, "c": 1, "paras": [{"runs": [{"text": "a"}]}, {"runs": [], "align": "right"}], "bg": "", "align": ""})
        self.assertEqual(m["blocks"][0]["rows"][1][1], {"colspan": 1, "rowspan": 1, "paras": [{"runs": [{"text": "a"}]}, {"runs": [], "align": "right"}]})
        self.assertEqual(hm.model(hm.render(m)), m)
        for bad in ({}, {"runs": [], "paras": [{"runs": []}]}, {"bg": "red"}, {"bg": "#12345"}, {"align": "middle"},
                    {"runs": [{"img": PNG}]}, {"runs": [{"text": ""}]}, {"paras": []}, {"paras": [{"runs": [], "x": 1}]},
                    {"paras": [{"runs": []}] * (hm.MAX_CPARAS + 1)}, {"r": 0, "c": 5, "bg": "#FFFFFF"}, {"index": 1, "bg": "#FFFFFF"}):
            op = dict({"op": "table_cell", "index": 0, "r": 0, "c": 0}, **bad)
            with self.assertRaises(ModelError, msg=bad): _tops(_doc(_grid(2, 2), _p("x")), op)

    def test_cell_text_ops(self):
        d = _doc(_p("앞"), _grid(2, 2))
        m = _tops(d, {"op": "insert_text", "pos": [1, 1, 0, 0, 2], "text": "가"},
                  {"op": "split_paragraph", "pos": [1, 1, 0, 0, 1]},
                  {"op": "set_style", "start": [1, 1, 0, 0, 0], "end": [1, 1, 0, 1, 1], "attrs": {"bold": True}},
                  {"op": "insert_text", "pos": [0, 1], "text": "!"})
        c = m["blocks"][1]["rows"][1][0]
        self.assertEqual(c["paras"], [{"runs": [{"text": "1", "bold": True}]}, {"runs": [{"text": "0", "bold": True}, {"text": "가"}]}])
        self.assertEqual(hm.block_text(m["blocks"][0]), "앞!")
        m = _tops(m, {"op": "delete_range", "start": [1, 1, 0, 0, 1], "end": [1, 1, 0, 1, 1]})   # 문단 경계 지우기 → 1문단 = runs
        self.assertEqual(m["blocks"][1]["rows"][1][0]["runs"], [{"text": "1", "bold": True}, {"text": "가"}])
        sp = _tops(d, {"op": "table_merge", "index": 1, "r0": 0, "c0": 0, "r1": 1, "c1": 0})
        self.assertEqual(hm.block_text(_tops(sp, {"op": "insert_text", "pos": [1, 0, 0, 1, 0], "text": "Z"})["blocks"][1]["rows"][0][0]["paras"][1]), "Z10")
        for op in ({"op": "insert_text", "pos": [1, 1, 0, 0, 3], "text": "x"}, {"op": "insert_text", "pos": [1, 1, 0, 1, 0], "text": "x"},
                   {"op": "insert_text", "pos": [1, 2, 0, 0, 0], "text": "x"}, {"op": "insert_text", "pos": [0, 0, 0, 0, 0], "text": "x"},
                   {"op": "insert_text", "pos": [1, 0, 0, 0], "text": "x"}, {"op": "insert_text", "pos": [1, 0, 0, 0, 0], "text": "a\nb"},
                   {"op": "delete_range", "start": [1, 0, 0, 0, 0], "end": [1, 0, 1, 0, 1]},
                   {"op": "delete_range", "start": [1, 0, 0, 0, 1], "end": [1, 0, 0, 0, 0]},
                   {"op": "set_style", "start": [0, 0], "end": [1, 0, 0, 0, 1], "attrs": {"bold": True}},
                   {"op": "set_style", "start": [1, 0, 0, 0, 0], "end": [1, 0, 0, 0, 1], "attrs": {"zz": True}},
                   {"op": "insert_pgbreak", "pos": [1, 0, 0, 0, 0]}, {"op": "insert_image", "pos": [1, 0, 0, 0, 0], "src": PNG}):
            with self.assertRaises(ModelError, msg=op): _tops(d, op)
        with self.assertRaisesRegex(ModelError, "칸 없음"): _tops(sp, {"op": "insert_text", "pos": [1, 1, 0, 0, 0], "text": "x"})

    def test_image_page(self):
        m = _tops(_doc(_p("가나")), {"op": "insert_image", "pos": [0, 1], "src": PNG, "width": 320})
        self.assertEqual(m["blocks"][1], {"type": "img", "src": PNG, "width": 320}); self.assertEqual(len(m["blocks"]), 3)
        self.assertEqual(hm.model(hm.render(m)), m)
        fx = dict(m["blocks"][1], place="fixed", left=10, top=20, z=3)
        m2 = _tops(_doc(fx), {"op": "set_image", "index": 0, "width": 99})
        self.assertEqual(m2["blocks"][0], dict(fx, width=99))                          # 위치 값 그대로
        inl = _doc({"type": "p", "runs": [{"text": "a"}, {"img": PNG}, {"text": "b"}]})
        self.assertEqual(_tops(inl, {"op": "set_image", "pos": [0, 1], "width": 50})["blocks"][0]["runs"][1], {"img": PNG, "width": 50})
        self.assertEqual(_tops(m, {"op": "set_image", "pos": [1, 0], "width": 7})["blocks"][1]["width"], 7)
        self.assertEqual([b["type"] for b in _tops(m, {"op": "delete_block", "index": 1})["blocks"]], ["p", "p"])   # 그림 지우기
        for op in ({"op": "insert_image", "pos": [0, 0], "src": "data:image/svg+xml;base64,AA=="}, {"op": "insert_image", "pos": [0, 0], "src": "http://x/a.png"},
                   {"op": "insert_image", "pos": [0, 0], "src": PNG, "width": 0}, {"op": "insert_image", "pos": [0, 0], "src": PNG, "width": 5001},
                   {"op": "insert_image", "pos": [0, 0], "src": 5}, {"op": "set_image", "index": 0, "width": 10},
                   {"op": "set_image", "pos": [1, 0], "width": 10}, {"op": "set_image", "pos": [0, 0], "width": 10},
                   {"op": "set_image", "index": 2, "pos": [2, 0], "width": 10}, {"op": "set_image", "width": 10},
                   {"op": "set_image", "index": 2, "width": 5001}):
            with self.assertRaises(ModelError, msg=op): _tops(_doc(_p("가"), _grid(1, 1), fx), op)
        m = _tops(_doc(_p("x")), {"op": "set_page", "paper": "B5", "orient": "landscape", "margins": "10,15,20,25.5"})
        self.assertEqual(m["meta"], {"paper": "B5", "orient": "landscape", "margins": "10,15,20,25.5"})
        m = _tops(m, {"op": "set_page", "paper": "", "margins": ""}); self.assertEqual(m["meta"], {"orient": "landscape"})
        for bad in ({}, {"paper": "Z9"}, {"orient": "up"}, {"margins": "101,0,0,0"}, {"margins": "1,2,3"}, {"paper": 4}, {"paper": None}):
            with self.assertRaises(ModelError, msg=bad): _tops(_doc(_p("x")), dict({"op": "set_page"}, **bad))

    def test_pure_and_limits(self):
        d = _doc(_grid(2, 2)); keep = copy.deepcopy(d)
        _tops(d, {"op": "table_merge", "index": 0, "r0": 0, "c0": 0, "r1": 1, "c1": 1}, {"op": "set_page", "paper": "A5"})
        self.assertEqual(d, keep)                                                      # 입력 불변(순수)
        big = _doc(_grid(200, 64, fill=False))
        with self.assertRaisesRegex(ModelError, "작업량"):
            hm.apply(big, [{"op": "table_insert_rows", "index": 0, "at": 0}, {"op": "table_delete_rows", "index": 0, "at": 0}] * 150)
        with self.assertRaisesRegex(ModelError, "너무 큼"):
            hm.apply(big, [{"op": "table_insert_cols", "index": 0, "at": 0, "n": 100}])  # 200×164 > 3만 칸
        with self.assertRaisesRegex(ModelError, "줄 과다"):
            hm.apply(_doc(_grid(4990, 1, fill=False)), [{"op": "table_insert_rows", "index": 0, "at": 0, "n": 20}])   # MAX_TROWS 5000

class SupSub(unittest.TestCase):
    def test_model(self):
        m = core.model('<p>H<sub>2</sub>O x<sup>2</sup> <span style="vertical-align:super">a</span><span style="vertical-align:sub"><sup>b</sup></span></p>')
        self.assertEqual(m["blocks"][0]["runs"], [{"text": "H"}, {"text": "2", "sub": True}, {"text": "O x"}, {"text": "2", "sup": True},
                                                  {"text": " "}, {"text": "ab", "sup": True}])
        self.assertEqual(core.model(core.render(m)), m)
        self.assertIn("<sub>2</sub>", core.render(m)); self.assertEqual(core.plain_text(core.render(m)).strip(), "H2O x2 ab")
        self.assertNotIn("sub", hm._run_norm({"text": "a", "sup": True, "sub": True}))
        with self.assertRaises(ModelError): hm.validate(_doc({"type": "p", "runs": [{"text": "a", "sup": 1}]}))
        with self.assertRaises(ModelError): _tops(_doc(_p("ab")), {"op": "set_style", "start": [0, 0], "end": [0, 1], "attrs": {"sup": True, "sub": True}})
        m = _tops(_doc(_p("ab")), {"op": "set_style", "start": [0, 0], "end": [0, 2], "attrs": {"sup": True}},
                  {"op": "set_style", "start": [0, 1], "end": [0, 2], "attrs": {"sub": True}})
        self.assertEqual(m["blocks"][0]["runs"], [{"text": "a", "sup": True}, {"text": "b", "sub": True}])
        m = _tops(m, {"op": "set_style", "start": [0, 0], "end": [0, 2], "attrs": {"sup": False, "sub": None}})
        self.assertEqual(m["blocks"][0]["runs"], [{"text": "ab"}])
        # 미주 표식(sup.fn)은 첨자가 아님
        fm = core.model('<p>a<sup class="fn" contenteditable="false" data-fn="n1">1)</sup>b</p><div class="fnotes"><p class="fn-e" data-fn="n1"><span class="fn-no">1)</span> 노트</p></div>')
        self.assertEqual(fm["blocks"][0]["runs"], [{"text": "a"}, {"endnote": "n1"}, {"text": "b"}])
        tm = core.model('<table><tr><td>x<sup>2</sup>y<sup class="fn" data-fn="1">1)</sup>z</td></tr></table>')
        self.assertEqual(tm["blocks"][0]["rows"][0][0]["runs"], [{"text": "x"}, {"text": "2", "sup": True}, {"text": "y1)z"}])
    M = _doc({"type": "p", "runs": [{"text": "E=mc"}, {"text": "2", "sup": True}, {"text": " H"}, {"text": "2", "sub": True, "bold": True}, {"text": "O"}]},
             {"type": "table", "rows": [[{"colspan": 1, "rowspan": 1, "runs": [{"text": "x"}, {"text": "n", "sub": True}]}]]})
    def _runs(self, m): return [m["blocks"][0]["runs"], m["blocks"][1]["rows"][0][0]["runs"]]
    def test_docx(self):
        d = core.export_html(core.render(self.M), "docx")
        x = zipfile.ZipFile(io.BytesIO(d)).read("word/document.xml").decode()
        self.assertIn('<w:vertAlign w:val="superscript"/>', x); self.assertIn('<w:vertAlign w:val="subscript"/>', x)
        self.assertEqual(self._runs(core.model(core.import_bytes(d, "docx"))), self._runs(self.M))
    def test_hwpx_std(self):
        d = core.export_html(core.render(self.M), "hwpx")
        h = zipfile.ZipFile(io.BytesIO(d)).read("Contents/header.xml").decode()
        self.assertIn("<hh:supscript/></hh:charPr>", h); self.assertIn("<hh:subscript/></hh:charPr>", h)
        self.assertEqual(self._runs(core.model(core.import_bytes(d, "hwpx"))), self._runs(self.M))
        if hwpxconv.HwpxDocument is not None:   # std writer → python-hwpx reader
            self.assertEqual(self._runs(core.model(hwpxconv.import_hwpx(d))), self._runs(self.M))
    def test_txt(self):
        self.assertEqual(core.export_html(core.render(self.M), "txt").decode().split("\n")[0].strip(), "E=mc2 H2O")

class ApplyCLI(unittest.TestCase):
    def test_cli_apply(self):
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "a.html"); ops = os.path.join(td, "ops.json"); out = os.path.join(td, "o.json")
            with open(src, "w") as f: f.write("<p>가나다</p>")
            with open(ops, "w") as f: json.dump([{"op": "insert_table", "pos": [0, 1], "rows": 2, "cols": 2},
                                                 {"op": "table_merge", "index": 1, "r0": 0, "c0": 0, "r1": 0, "c1": 1},
                                                 {"op": "insert_text", "pos": [1, 1, 1, 0, 0], "text": "칸"},
                                                 {"op": "set_style", "start": [0, 0], "end": [0, 1], "attrs": {"sup": True}},
                                                 {"op": "insert_image", "pos": [3, 0], "src": PNG, "width": 10},
                                                 {"op": "set_page", "paper": "A5"}], f)
            r = subprocess.run([sys.executable, os.path.join(APP, "hanword"), "--json", "apply", src, ops, "-o", out], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            with open(out) as f: m = json.load(f)
            self.assertEqual([b["type"] for b in m["blocks"]], ["p", "table", "p", "img"]); self.assertEqual(m["meta"]["paper"], "A5")
            self.assertEqual(m["blocks"][1]["rows"][1][1]["runs"], [{"text": "칸"}]); self.assertTrue(m["blocks"][0]["runs"][0]["sup"])
            with open(ops, "w") as f: json.dump([{"op": "table_delete_rows", "index": 0, "at": 0}], f)
            r = subprocess.run([sys.executable, os.path.join(APP, "hanword"), "--json", "apply", src, ops], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 2); self.assertIn("표가 아님", json.loads(r.stdout.strip().splitlines()[-1])["err"])   # --json = ASCII 이스케이프


class OpsAudit(unittest.TestCase):   # Opus 감사(feat-ops) 재현 박제
    def test_cell_paras_linear(self):   # HIGH: 칸 연산마다 문단 전체 복사·재저장 → 9999 split 117s
        import time
        t = time.time()
        m = hm.apply(_doc(_grid(1, 1, fill=False)), [{"op": "split_paragraph", "pos": [0, 0, 0, 0, 0]}] * 9999)
        self.assertEqual(len(m["blocks"][0]["rows"][0][0]["paras"]), 10000)
        m2 = hm.apply(m, [{"op": "insert_text", "pos": [0, 0, 0, 5000, 0], "text": "가"}] * 2000)
        self.assertEqual(hm.block_text(m2["blocks"][0]["rows"][0][0]["paras"][5000]), "가" * 2000)
        self.assertLess(time.time() - t, tm.limit(3.0))
    def test_cell_at_cached(self):   # MED: 칸 연산마다 격자 재구성 → 5000×6 표 6s
        import time
        d = _doc(_grid(5000, 6, fill=False)); t = time.time()
        m = hm.apply(d, [{"op": "insert_text", "pos": [0, 4999, 5, 0, 0], "text": "x"}] * 3000
                        + [{"op": "table_cell", "index": 0, "r": 4999, "c": 0, "bg": "#FFFFFF"}] * 1000)
        self.assertLess(time.time() - t, tm.limit(3.0))
        self.assertEqual(m["blocks"][0]["rows"][4999][5]["runs"], [{"text": "x" * 3000}])
        m = hm.apply(d, [{"op": "table_delete_rows", "index": 0, "at": 0, "n": 4998},   # 구조 연산 뒤 캐시 무효
                         {"op": "insert_text", "pos": [0, 1, 0, 0, 0], "text": "y"}])
        self.assertEqual(m["blocks"][0]["rows"][1][0]["runs"], [{"text": "y"}])
    def test_collapse_keeps_align(self):   # LOW: 1문단으로 줄 때 문단 정렬 유지
        d = _doc({"type": "table", "rows": [[{"colspan": 1, "rowspan": 1, "align": "left",
                  "paras": [{"runs": [{"text": "a"}], "align": "right"}, {"runs": [{"text": "b"}]}]}]]})
        m = hm.apply(d, [{"op": "delete_range", "start": [0, 0, 0, 0, 1], "end": [0, 0, 0, 1, 1]}])
        self.assertEqual(m["blocks"][0]["rows"][0][0], {"colspan": 1, "rowspan": 1, "align": "right", "runs": [{"text": "a"}]})
    def test_full_row_merge_exports(self):   # LOW: 줄 전체 병합 → 빈 [] 행 없음, DOCX·HWPX 행 수 일치
        m = hm.apply(_doc(_p("x"), dict(_grid(3, 2), rowh=[10, 20, 30])),
                     [{"op": "table_merge", "index": 1, "r0": 0, "c0": 0, "r1": 1, "c1": 1}])
        t = m["blocks"][1]
        self.assertEqual(_shape(t), [[(1, 2, "00 | 01 | 10 | 11")], [(1, 1, "20"), (1, 1, "21")]]); self.assertEqual(t["rowh"], [10, 30])
        m = hm.apply(m, [{"op": "table_insert_rows", "index": 1, "at": 2},
                         {"op": "table_merge", "index": 1, "r0": 1, "c0": 0, "r1": 2, "c1": 0}])   # 부분 병합 = rowspan 2 유지
        self.assertEqual(_shape(m["blocks"][1]), [[(1, 2, "00 | 01 | 10 | 11")], [(2, 1, "20"), (1, 1, "21")], [(1, 1, "")]])
        h = core.render(m)
        x = zipfile.ZipFile(io.BytesIO(core.export_html(h, "docx"))).read("word/document.xml").decode()
        trs = re.findall(r"<w:tr[ >].*?</w:tr>", x, re.S)
        self.assertTrue(trs); self.assertTrue(all("<w:tc>" in tr or "<w:tc " in tr for tr in trs))
        s = zipfile.ZipFile(io.BytesIO(core.export_html(h, "hwpx"))).read("Contents/section0.xml").decode()
        for tbl in re.findall(r"<hp:tbl .*?</hp:tbl>", s, re.S):
            self.assertEqual(int(re.search(r'rowCnt="(\d+)"', tbl).group(1)), tbl.count("<hp:tr>") + tbl.count("<hp:tr "))
        self.assertEqual(core.model(h)["blocks"], m["blocks"])
    def test_internal_typeerror_not_hidden(self):   # LOW: 인자 묶기 오류만 ModelError
        with self.assertRaisesRegex(ModelError, "인자 오류"): hm.apply(_doc(_p("x")), [{"op": "set_page", "papr": "A4"}])
        orig = hm.OPS["set_page"]
        def boom(m, paper=None, orient=None, margins=None): raise TypeError("내부 버그")
        hm.OPS["set_page"] = boom
        try:
            with self.assertRaises(TypeError): hm.apply(_doc(_p("x")), [{"op": "set_page", "paper": "A4"}])
        finally: hm.OPS["set_page"] = orig


if __name__ == "__main__":
    if sys.argv[1:] == ["--make-corpus"]:
        with open(os.path.join(HERE, "corpus", "lists.docx"), "wb") as fp: fp.write(make_lists_docx())
        sys.exit(0)
    unittest.main()

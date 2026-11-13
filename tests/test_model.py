#!/usr/bin/env python3
"""문서모델·렌더·편집연산 단위시험(stdlib unittest). 실행: python3 -m unittest tests/test_model.py
   python-hwpx/lxml 없는 환경(-s -I, Maru Alpine)에서도 전부 통과해야 함(.hwp만 pyhwp 필요 시 생략)."""
import os, sys, json, glob, unittest, copy
HERE = os.path.dirname(os.path.abspath(__file__)); APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
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
        t = time.time(); core.apply_ops(big, [{"op": "insert_text", "pos": [0, 5], "text": "y"}]); self.assertLess(time.time() - t, 3)
        self.bad(lambda: core.apply_ops({"version": 1, "blocks": [{"type": "p", "runs": [{"text": "a"}]}]},
                                        [{"op": "insert_text", "pos": [0, 0], "text": "x" * 100000}] * 700))
        many = {"version": 1, "blocks": [{"type": "p", "runs": [{"text": "a"}]} for _ in range(5000)]}
        t = time.time()
        with self.assertRaises(ModelError):
            core.apply_ops(many, [{"op": "set_style", "start": [0, 0], "end": [4999, 1], "attrs": {"bold": True}}] * 1000)
        self.assertLess(time.time() - t, 20)
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

class Linear(unittest.TestCase):   # 2026-11-13 마루 감사: 비신뢰 HTML 정규식 2차시간 회귀
    N = 100000
    def _t(self, f, s):
        import time; t0 = time.time(); f(s); dt = time.time() - t0
        self.assertLess(dt, 1.0, "%.2fs" % dt)
    def test_strip_meta(self): self._t(hm._strip_meta, '<div id="wpmeta"' * self.N)
    def test_extract_meta(self): self._t(hwpxconv._extract_meta, '<div id="wpmeta"' * self.N)
    def test_fnotes_open(self): self._t(hwpxconv._extract_fnotes, '<div class="fnotes">' * self.N)
    def test_fnotes_p(self): self._t(hwpxconv._extract_fnotes, '<div class="fnotes">' + '<p ' * self.N)
    def test_fnotes_p2(self): self._t(hwpxconv._extract_fnotes, '<div class="fnotes">' + '<p>x</p >' * self.N)
    def test_check_lt(self): self._t(core.check_html, '<' * self.N)
    def test_check_img(self): self._t(core.check_html, '<img ' * self.N)
    def test_check_table(self): self._t(core.check_html, '<table' * self.N)
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
        for name, data in files: z.writestr(zipfile.ZipInfo(name, (2026, 11, 13, 0, 0, 0)), data, zipfile.ZIP_DEFLATED)
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
        import time
        for s in ("<table><tr><td>" + "a<br>" * 100000 + "</td></tr></table>", "<table><tr><td>" + "<p>a</p>" * 100000 + "</td></tr></table>",
                  "<table><tr><td>" + "<div>" * 50000 + "a" + "</div>" * 50000 + "</td></tr></table>"):
            t0 = time.time(); m = core.model(s); dt = time.time() - t0
            self.assertLess(dt, 5.0, "%.2fs" % dt); hm.validate(m)
    def test_deep_inline_linear(self):   # 감사: merged()가 텍스트 노드×인라인 깊이(84s 재현) → 단계 캐시로 선형
        import time
        s = "<table><tr><td>" + "<span>" * 20000 + "x<br>" * 20000 + "</td></tr></table>"
        t0 = time.time(); m = core.model(s); dt = time.time() - t0
        self.assertLess(dt, 2.0, "%.2fs" % dt); hm.validate(m)
        s2 = "<p>" + "<b><i>" * 20000 + "y " * 20000 + "</p>"
        t0 = time.time(); core.model(s2); self.assertLess(time.time() - t0, 2.0)
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
        self.assertLess(time.time() - t, 1.5)
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

if __name__ == "__main__":
    if sys.argv[1:] == ["--make-corpus"]:
        with open(os.path.join(HERE, "corpus", "lists.docx"), "wb") as fp: fp.write(make_lists_docx())
        sys.exit(0)
    unittest.main()

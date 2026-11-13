#!/usr/bin/env python3
"""원본 XML 되씀(K2 덩이·허용 파트) 시험(stdlib unittest). 실행: python3 tests/test_keep.py  (python3 -s -I 도 통과해야 함)"""
import os, sys, io, re, glob, json, copy, time, zipfile, unittest, subprocess, base64
HERE = os.path.dirname(os.path.abspath(__file__)); APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
import hanword_core as core
import hanword_keep as hk

PNG = "data:image/png;base64," + base64.b64encode(
    bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                  "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")).decode()

def corpus():
    return sorted(glob.glob(os.path.join(HERE, "corpus", "*.hwpx")) + glob.glob(os.path.join(HERE, "corpus", "*.docx")))

def load(f):
    with open(f, "rb") as fp: return fp.read()

def fmt_of(f): return f.rsplit(".", 1)[1]
def model_of(data, fmt): return core.model(core.import_bytes(data, fmt))
def parts(data):
    z = zipfile.ZipFile(io.BytesIO(data)); return {n: z.read(n) for n in z.namelist()}
def body_names(p, fmt):
    return ["word/document.xml"] if fmt == "docx" else sorted(n for n in p if re.fullmatch(r"Contents/section\d+\.xml", n))
def frags(data, fmt):
    ix = core.keep_index(data, fmt); p = parts(data)
    return [p[g["part"]][g["start"]:g["end"]] for g in ix["groups"]]

def zip_replace(data, repl, drop=()):
    zin = zipfile.ZipFile(io.BytesIO(data)); buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i in zin.infolist():
            if i.filename in drop: continue
            z.writestr(i, repl.get(i.filename, zin.read(i)))
        for n, d in repl.items():
            if n not in zin.namelist(): z.writestr(n, d)
    return buf.getvalue()

def first_text_block(m, start=1):
    for i, b in enumerate(m["blocks"]):
        if i >= start and b["type"] == "p" and any(r.get("text", "").strip() for r in b.get("runs") or []): return i
    raise AssertionError("문단 없음")

class Corpus(unittest.TestCase):
    def test_unchanged_roundtrip(self):
        for f in corpus():
            d = load(f); fm = fmt_of(f)
            out, rep = core.export_keep(d, model_of(d, fm), fm)
            self.assertEqual(rep["level"], "blocks", (f, rep["why"]))
            self.assertEqual(rep["regenerated"], 0, f)
            po, pn = parts(d), parts(out)
            for n in body_names(po, fm): self.assertEqual(po[n], pn[n], "본문 바이트 다름: %s %s" % (f, n))
            for n, v in po.items():
                if n in ("Preview/PrvImage.png", "Preview/PrvText.txt", "[Content_Types].xml", "docProps/core.xml"): continue
                self.assertIn(n, pn, (f, n)); self.assertEqual(v, pn[n], "파트 다름: %s %s" % (f, n))
            self.assertNotIn("Preview/PrvImage.png", pn)
            self.assertEqual(core.model(core.import_bytes(out, fm)), model_of(d, fm), f)
    def test_whole_file_identical_when_possible(self):
        # 미리보기 그림이 없고 [Content_Types] 선언이 정규형과 같으면 파일째 같음(zip 압축 바이트는 zlib 판에 따름)
        for name in ("hancom-link.hwpx", "rich.docx", "lists.docx"):
            d = load(os.path.join(HERE, "corpus", name)); fm = fmt_of(name)
            out, rep = core.export_keep(d, model_of(d, fm), fm)
            self.assertEqual(parts(out), parts(d), name)

class Edits(unittest.TestCase):
    def check(self, f, mutate, expect_level="blocks"):
        d = load(f); fm = fmt_of(f); m = model_of(d, fm); m2 = copy.deepcopy(m); mutate(m2)
        out, rep = core.export_keep(d, m2, fm)
        self.assertEqual(rep["level"], expect_level, (f, rep["why"]))
        full = model_of(core.export_html(core.render(m2), fm), fm)     # 전체 다시 만들기와 같은 결과(쓰기기 고유 손실 포함)
        self.assertEqual(hk.block_hashes(model_of(out, fm)), hk.block_hashes(full), f)
        self.assertEqual(rep["counts"]["lossy"], sum(1 for x, y in zip(hk.block_hashes(full), hk.block_hashes(core.model(core.render(m2)))) if x != y), f)
        return d, out, rep, m, m2
    def test_edit_one_paragraph(self):
        for f in corpus():
            fm = fmt_of(f)
            def mut(m):
                i = first_text_block(m); m["blocks"][i]["runs"][-1]["text"] += "EDIT"
            d, out, rep, m, m2 = self.check(f, mut)
            self.assertEqual(rep["regenerated"], 1, f)
            a, b = frags(d, fm), frags(out, fm)
            self.assertEqual(len(a), len(b), f)
            self.assertEqual(sum(1 for x, y in zip(a, b) if x != y), 1, "바뀐 조각은 하나: %s" % f)
    def test_insert_delete(self):
        for f in corpus():
            fm = fmt_of(f)
            d, out, rep, m, _ = self.check(f, lambda m: m["blocks"].insert(2, {"type": "p", "runs": [{"text": "새 문단", "bold": True}]}))
            self.assertEqual(rep["regenerated"], 1); self.assertEqual(rep["kept_blocks"], len(m["blocks"]), f)
            a, b = frags(d, fm), frags(out, fm)
            self.assertEqual(len(b), len(a) + 1); self.assertEqual(sum(1 for x in b if x not in a), 1, f)
            d, out, rep, m, _ = self.check(f, lambda m: m["blocks"].pop(1))
            self.assertEqual(rep["regenerated"], 0); self.assertEqual(rep["kept_blocks"], len(m["blocks"]) - 1, f)
            self.assertTrue(set(frags(out, fm)) <= set(frags(d, fm)), f)
            self.check(f, lambda m: m["blocks"].insert(0, {"type": "h1", "runs": [{"text": "맨 앞 제목"}]}))
            self.check(f, lambda m: m["blocks"].__setitem__(0, {"type": "p", "runs": [{"text": "첫 문단 바뀜"}]}))
            self.check(f, lambda m: m["blocks"].insert(3, {"type": "pgbreak"}))
            self.check(f, lambda m: m["blocks"].append({"type": "img", "src": PNG, "width": 40}))
            self.check(f, lambda m: m["blocks"].insert(2, {"type": "table", "rows": [[{"colspan": 1, "rowspan": 1, "runs": [{"text": "칸"}]}]]}))
            self.check(f, lambda m: m["blocks"].insert(2, {"type": "p", "runs": [{"text": "링크", "link": "https://example.org/"}, {"text": " 그림"}, {"img": PNG}]}))
    def test_images_new_parts(self):
        for f in corpus():
            fm = fmt_of(f)
            d, out, rep, m, _ = self.check(f, lambda m: m["blocks"].append({"type": "img", "src": PNG, "width": 40}))
            new = set(parts(out)) - set(parts(d))
            self.assertTrue(any(n.startswith(("BinData/HWK", "word/media/hwk_")) for n in new), (f, new))
    def test_list_item_continues_numbering(self):
        f = os.path.join(HERE, "corpus", "lists.docx"); d = load(f); m = model_of(d, "docx")
        i = next(i for i, b in enumerate(m["blocks"]) if b["type"] == "li" and b["list"] == "number")
        m2 = copy.deepcopy(m); m2["blocks"].insert(i + 1, dict(m["blocks"][i], runs=[{"text": "새 항목"}]))
        out, rep = core.export_keep(d, m2, "docx"); self.assertEqual(rep["level"], "blocks", rep["why"])
        a, b = frags(d, "docx"), frags(out, "docx")
        nid = lambda x: re.search(rb'numId w:val="(\d+)"', x).group(1)
        self.assertEqual(nid(b[i + 1]), nid(a[i]), "이웃 목록 번호(numId) 이어 씀")
    def test_edit_note_paragraph(self):   # 미주 든 문단 고침 → 미주를 원본 endnotes 뒤에 새 id로
        for f in corpus():
            fm = fmt_of(f); d = load(f); m = model_of(d, fm)
            i = next((i for i, b in enumerate(m["blocks"]) if any("endnote" in r for r in b.get("runs") or [])), None)
            if i is None: continue
            d, out, rep, m, m2 = self.check(f, lambda m: m["blocks"][i]["runs"][0].__setitem__("text", m["blocks"][i]["runs"][0].get("text", "") + "N"))
            self.assertEqual(rep["regenerated"], 1, f)
            self.assertEqual(core.model(core.import_bytes(out, fm))["notes"], core.model(core.render(m2))["notes"], f)
    def test_meta_change_falls_back_to_parts(self):
        f = os.path.join(HERE, "corpus", "rich.docx"); d = load(f); m = model_of(d, "docx"); m["meta"]["header"] = "새 머리말"
        out, rep = core.export_keep(d, m, "docx")
        self.assertEqual(rep["level"], "parts"); self.assertIn("meta", rep["why"])
        self.assertEqual(core.model(core.import_bytes(out, "docx"))["meta"].get("header"), "새 머리말")

class Unknown(unittest.TestCase):
    EQ = (b'<hp:run charPrIDRef="0"><hp:equation id="77" zOrder="0" numberingType="EQUATION" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" '
          b'dropcapstyle="None" version="Equation Version 60" baseLine="85" textColor="#000000" baseUnit="1000" lineMode="CHAR" font="HYhwpEQ">'
          b'<hp:sz width="1000" widthRelTo="ABSOLUTE" height="1000" heightRelTo="ABSOLUTE" protect="0"/><hp:script>x^2</hp:script></hp:equation></hp:run>'
          b'<hp:run charPrIDRef="0"><hp:rect id="78" zOrder="1" numberingType="PICTURE" textWrap="IN_FRONT_OF_TEXT" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" instid="78" ratio="0">'
          b'<hp:offset x="0" y="0"/><hp:orgSz width="7500" height="3750"/><hp:curSz width="7500" height="3750"/></hp:rect></hp:run>')
    def hwpx_fixture(self):
        d = load(os.path.join(HERE, "corpus", "hancom-link.hwpx")); p = parts(d)
        s = p["Contents/section0.xml"]
        ps = [m.start() for m in re.finditer(rb"<hp:p ", s)]
        k = s.index(b"</hp:p>", ps[1])                       # 두 번째 최상위 문단 끝에 수식·사각형
        s2 = s[:k] + self.EQ + s[k:]
        return zip_replace(d, {"Contents/section0.xml": s2})
    def test_hwpx_equation_rect_kept(self):
        d = self.hwpx_fixture(); m = model_of(d, "hwpx")
        out, rep = core.export_keep(d, m, "hwpx")
        self.assertEqual(rep["level"], "blocks"); self.assertIn(self.EQ, parts(out)["Contents/section0.xml"])
        m2 = copy.deepcopy(m); j = first_text_block(m2, 2); m2["blocks"][j]["runs"][0]["text"] += "X"   # 다른 문단 고침
        out, rep = core.export_keep(d, m2, "hwpx"); self.assertEqual(rep["level"], "blocks")
        self.assertIn(self.EQ, parts(out)["Contents/section0.xml"]); self.assertEqual(rep["counts"]["unkept"], 0)
        ix = core.keep_index(d, "hwpx")
        gi = next(i for i, g in enumerate(ix["groups"]) if self.EQ in parts(d)[g["part"]][g["start"]:g["end"]])
        bi = sum(len(g["blocks"]) for g in ix["groups"][:gi])
        m3 = copy.deepcopy(m); m3["blocks"][bi]["runs"][-1]["text"] += "Y"     # 수식 든 문단 고침 → 빠지고 셈
        out, rep = core.export_keep(d, m3, "hwpx"); self.assertEqual(rep["level"], "blocks", rep["why"])
        self.assertNotIn(b"hp:equation", parts(out)["Contents/section0.xml"]); self.assertEqual(rep["counts"]["unkept"], 2)
    FLD = (b'<w:bookmarkStart w:id="7" w:name="bm"/><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> DATE </w:instrText></w:r>'
           b'<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>2026</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r><w:bookmarkEnd w:id="7"/>')
    def test_docx_field_bookmark_kept(self):
        d = load(os.path.join(HERE, "corpus", "rich.docx")); p = parts(d); s = p["word/document.xml"]
        k = s.index(b"</w:p>", s.index(b"<w:p>", s.index(b"<w:body>") + 20) + 5)
        d = zip_replace(d, {"word/document.xml": s[:k] + self.FLD + s[k:]})
        m = model_of(d, "docx")
        out, rep = core.export_keep(d, m, "docx"); self.assertEqual(rep["level"], "blocks"); self.assertIn(self.FLD, parts(out)["word/document.xml"])
        ix = core.keep_index(d, "docx")
        gi = next(i for i, g in enumerate(ix["groups"]) if self.FLD in parts(d)[g["part"]][g["start"]:g["end"]])
        bi = sum(len(g["blocks"]) for g in ix["groups"][:gi])
        m3 = copy.deepcopy(m); m3["blocks"][bi]["runs"][0]["text"] += "Y"
        out, rep = core.export_keep(d, m3, "docx"); self.assertEqual(rep["level"], "blocks", rep["why"])
        self.assertNotIn(b"fldChar", parts(out)["word/document.xml"]); self.assertGreaterEqual(rep["counts"]["unkept"], 2)
    def test_two_sections(self):
        d = load(os.path.join(HERE, "corpus", "hancom-link.hwpx")); p = parts(d)
        hpf = p["Contents/content.hpf"].replace(b'<opf:itemref idref="section0" linear="yes"/>', b'<opf:itemref idref="section0" linear="yes"/><opf:itemref idref="section1" linear="yes"/>')
        hpf = hpf.replace(b"</opf:manifest>", b'<opf:item id="section1" href="Contents/section1.xml" media-type="application/xml"/></opf:manifest>')
        s1 = p["Contents/section0.xml"].replace("한컴".encode(), "둘째".encode())
        d = zip_replace(d, {"Contents/content.hpf": hpf, "Contents/section1.xml": s1})
        m = model_of(d, "hwpx"); n0 = len(core.keep_index(d, "hwpx")["groups"]) // 2
        nb0 = sum(len(g["blocks"]) for g in core.keep_index(d, "hwpx")["groups"][:n0])
        m2 = copy.deepcopy(m); m2["blocks"][nb0] = {"type": "p", "runs": [{"text": "둘째 구역 첫 문단 새로"}]}
        out, rep = core.export_keep(d, m2, "hwpx"); self.assertEqual(rep["level"], "blocks", rep["why"])
        po = parts(out); self.assertIn(b"secPr", po["Contents/section1.xml"]); self.assertEqual(po["Contents/section0.xml"], p["Contents/section0.xml"])
        self.assertEqual(hk.block_hashes(model_of(out, "hwpx")), hk.block_hashes(core.model(core.render(m2))))

class Hostile(unittest.TestCase):
    def setUp(self):
        self.f = os.path.join(HERE, "corpus", "lo-libreoffice.docx"); self.d = load(self.f); self.m = model_of(self.d, "docx")
    def test_sha_mismatch(self):
        out, rep = core.export_keep(self.d, self.m, "docx", orig_sha256="0" * 64)
        self.assertEqual(rep["level"], "none"); self.assertIn("sha256", rep["why"])
        out, rep = core.export_keep(self.d, self.m, "docx", orig_sha256=hk.sha256(self.d)); self.assertEqual(rep["level"], "blocks")
    def test_keep_off_and_format(self):
        self.assertEqual(core.export_keep(self.d, self.m, "docx", keep=False)[1]["level"], "none")
        r = core.export_keep(self.d, self.m, "hwpx")[1]; self.assertEqual(r["level"], "none")
        r = core.export_keep(b"not a zip", self.m, "docx")[1]; self.assertEqual(r["level"], "none")
    def test_dtd_in_kept_part(self):
        th = parts(self.d)["word/theme/theme1.xml"]
        evil = th.replace(b"?>", b'?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>', 1)
        d = zip_replace(self.d, {"word/theme/theme1.xml": evil})
        out, rep = core.export_keep(d, self.m, "docx")
        self.assertEqual(rep["level"], "none", rep); self.assertNotIn(b"ENTITY", b"".join(parts(out).values()))
    def test_dtd_in_body(self):
        s = parts(self.d)["word/document.xml"].replace(b"?>", b"?><!DOCTYPE w:document>", 1)
        out, rep = core.export_keep(zip_replace(self.d, {"word/document.xml": s}), self.m, "docx")
        self.assertNotEqual(rep["level"], "blocks"); self.assertNotIn(b"DOCTYPE", parts(out)["word/document.xml"])
    def test_huge_part_and_fragment_caps(self):
        old = hk.MAX_PART
        try:
            hk.MAX_PART = 1000
            out, rep = core.export_keep(self.d, self.m, "docx"); self.assertNotEqual(rep["level"], "blocks"); self.assertIn("너무 큼", rep["why"])
        finally: hk.MAX_PART = old
        old = hk.MAX_FRAG
        try:
            hk.MAX_FRAG = 200
            out, rep = core.export_keep(self.d, self.m, "docx"); self.assertEqual(rep["level"], "blocks")
            self.assertGreater(rep["counts"]["orig"], 0); self.assertLess(rep["kept_blocks"], len(self.m["blocks"]))
            self.assertEqual(hk.block_hashes(model_of(out, "docx")), hk.block_hashes(self.m))
        finally: hk.MAX_FRAG = old
    def test_disallowed_parts_dropped(self):
        p = parts(self.d)
        rels = p["word/_rels/document.xml.rels"].replace(b"</Relationships>",
            b'<Relationship Id="rIdX" Type="http://schemas.microsoft.com/office/2006/relationships/vbaProject" Target="vbaProject.bin"/>'
            b'<Relationship Id="rIdT" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="javascript:alert(1)" TargetMode="External"/></Relationships>')
        pr = p["_rels/.rels"].replace(b"</Relationships>", b'<Relationship Id="rIdTh" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail" Target="docProps/thumbnail.jpeg"/></Relationships>')
        d = zip_replace(self.d, {"word/_rels/document.xml.rels": rels, "_rels/.rels": pr, "word/vbaProject.bin": b"MACRO", "docProps/thumbnail.jpeg": b"\xff\xd8\xff old", "junk/other.xml": b"<a/>"})
        out, rep = core.export_keep(d, self.m, "docx"); self.assertEqual(rep["level"], "blocks", rep["why"])
        po = parts(out)
        for n in ("word/vbaProject.bin", "docProps/thumbnail.jpeg", "junk/other.xml"): self.assertNotIn(n, po)
        self.assertNotIn(b"javascript:", po["word/_rels/document.xml.rels"]); self.assertNotIn(b"vbaProject", po["[Content_Types].xml"])
    def test_hwpx_scripts_preview_dropped(self):
        d = load(os.path.join(HERE, "corpus", "rich.hwpx"))
        d2 = zip_replace(d, {"Scripts/headerScripts": b"function x(){}"})
        out, rep = core.export_keep(d2, model_of(d, "hwpx"), "hwpx"); self.assertEqual(rep["level"], "blocks")
        po = parts(out); self.assertNotIn("Scripts/headerScripts", po); self.assertNotIn("Preview/PrvImage.png", po)
    def test_zip_bomb_guard(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for n, v in parts(self.d).items(): z.writestr(n, v)
            z.writestr("customXml/item1.xml", b"<a>" + b" " * (30 << 20) + b"</a>")
        out, rep = core.export_keep(buf.getvalue(), self.m, "docx")
        self.assertEqual(rep["level"], "none")

REL = b'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>'
EXTIMG = b'<Relationship Id="rIdEv" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="file://attacker/share/a.png" TargetMode="External"/>'

class Audit(unittest.TestCase):   # 감사(2026-11-13) 지적 사항별 회귀
    def setUp(self):
        self.d = load(os.path.join(HERE, "corpus", "rich.docx")); self.m = model_of(self.d, "docx")
        self.h = load(os.path.join(HERE, "corpus", "rich.hwpx"))
    def test_added_part_rels_filtered(self):
        for part, blk in (("numbering", {"type": "li", "list": "number", "runs": [{"text": "새 항목"}]}),
                          ("styles", {"type": "h3", "runs": [{"text": "새 제목"}]}),
                          ("endnotes", {"type": "p", "runs": [{"text": "n"}, {"endnote": "1"}]})):
            d = zip_replace(self.d, {"word/_rels/%s.xml.rels" % part: REL % EXTIMG})
            m = model_of(d, "docx"); m["blocks"].insert(1, blk)
            if part == "endnotes": m["notes"]["1"] = m["notes"].get("1", "x")
            out, rep = core.export_keep(d, m, "docx")
            self.assertFalse(any(b"attacker" in v for v in parts(out).values()), (part, rep))
    def test_mimetype_first_and_checked(self):
        p = parts(self.h); names = [n for n in zipfile.ZipFile(io.BytesIO(self.h)).namelist() if n != "mimetype"] + ["mimetype"]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for n in names: z.writestr(n, p[n])
        out, rep = core.export_keep(buf.getvalue(), model_of(self.h, "hwpx"), "hwpx"); self.assertEqual(rep["level"], "blocks")
        zi = zipfile.ZipFile(io.BytesIO(out)).infolist()[0]
        self.assertEqual((zi.filename, zi.compress_type), ("mimetype", zipfile.ZIP_STORED))
        out, rep = core.export_keep(zip_replace(self.h, {"mimetype": b"application/x-evil"}), model_of(self.h, "hwpx"), "hwpx")
        self.assertNotEqual(rep["level"], "blocks")
    def test_bin_names_unique(self):
        p = parts(self.h)
        hpf = p["Contents/content.hpf"].replace(b"opf:", b"op:").replace(b"xmlns:opf=", b"xmlns:op=")
        d = zip_replace(self.h, {"Contents/content.hpf": hpf, "BinData/HWK0001.png": b"\x89PNG\r\n\x1a\nOLD"})
        m = model_of(d, "hwpx"); m["blocks"].insert(1, {"type": "img", "src": PNG, "width": 10})
        out, rep = core.export_keep(d, m, "hwpx"); self.assertEqual(rep["level"], "blocks", rep["why"])
        names = zipfile.ZipFile(io.BytesIO(out)).namelist(); self.assertEqual(len(names), len(set(names)))
        self.assertRaises(hk.KeepFail, hk._zip, [("a", b"1"), ("a", b"2")], {})
    def test_probe_caps_and_broad_fallback(self):
        old = hk.MAX_KEEP_KIDS
        try:
            hk.MAX_KEEP_KIDS = 3
            out, rep = core.export_keep(self.d, self.m, "docx"); self.assertNotEqual(rep["level"], "blocks"); self.assertIn("상한", rep["why"])
        finally: hk.MAX_KEEP_KIDS = old
        old = hk._index
        def boom(*a): raise MemoryError()
        try:
            hk._index = boom
            out, rep = core.export_keep(self.d, self.m, "docx"); self.assertIn("MemoryError", rep["why"])
            self.assertRaises(core.InputError, core.keep_index, self.d)
        finally: hk._index = old
        self.assertRaises(core.InputError, core.keep_index, b"PK\x03\x04garbage", "docx")
    def test_comments_notes_core_privacy(self):
        p = parts(self.d)
        COM = (b'<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:comment w:id="0" w:author="Boss">'
               b'<w:p><w:r><w:t>OLDSECRET</w:t></w:r></w:p></w:comment></w:comments>')
        s = p["word/document.xml"]; k = s.index(b"</w:p>", s.index(b"<w:body>"))
        s = s[:k] + b'<w:r><w:commentReference w:id="0"/></w:r>' + s[k:]
        rels = p["word/_rels/document.xml.rels"].replace(b"</Relationships>", b'<Relationship Id="rIdC1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/></Relationships>')
        core_old = b'<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>OLDAUTHOR</dc:creator></cp:coreProperties>'
        d = zip_replace(self.d, {"word/document.xml": s, "word/comments.xml": COM, "word/_rels/document.xml.rels": rels, "docProps/core.xml": core_old})
        m = model_of(d, "docx")
        out, rep = core.export_keep(d, m, "docx"); po = parts(out)
        self.assertEqual(rep["level"], "blocks"); self.assertIn("word/comments.xml", po); self.assertNotIn(b"OLDAUTHOR", po["docProps/core.xml"])
        m2 = copy.deepcopy(m); del m2["blocks"][0]                  # 메모 단 덩이 지움 → 메모 파트도 빠짐
        out, rep = core.export_keep(d, m2, "docx"); self.assertEqual(rep["level"], "blocks", rep["why"])
        self.assertFalse(any(b"OLDSECRET" in v for v in parts(out).values()))
        i = next(i for i, b in enumerate(self.m["blocks"]) if any("endnote" in r for r in b.get("runs") or []))
        note = self.m["notes"][next(r["endnote"] for r in self.m["blocks"][i]["runs"] if "endnote" in r)]
        m3 = copy.deepcopy(self.m); del m3["blocks"][i]               # 미주 단 덩이 지움 → endnotes.xml에서도 빠짐
        out, rep = core.export_keep(self.d, m3, "docx"); self.assertEqual(rep["level"], "blocks", rep["why"])
        self.assertNotIn(note.encode("utf-8"), parts(out)["word/endnotes.xml"])
    def test_hwpx_ole_not_kept(self):
        p = parts(self.h); s = p["Contents/section0.xml"]
        g = core.keep_index(self.h, "hwpx")["groups"][2]; k = s.rindex(b"</hp:p>", g["start"], g["end"])   # 셋째 최상위 문단 끝
        OLE = b'<hp:run charPrIDRef="0"><hp:ole id="91" binaryItemIDRef="OLE1" objectType="EMBEDDED"/></hp:run>'
        hpf = p["Contents/content.hpf"].replace(b"</opf:manifest>", b'<opf:item id="OLE1" href="BinData/OLE1.ole" media-type="application/ole" isEmbeded="1"/></opf:manifest>')
        d = zip_replace(self.h, {"Contents/section0.xml": s[:k] + OLE + s[k:], "Contents/content.hpf": hpf, "BinData/OLE1.ole": b"\xd0\xcf\x11\xe0OLE"})
        out, rep = core.export_keep(d, model_of(d, "hwpx"), "hwpx"); self.assertEqual(rep["level"], "blocks", rep["why"])
        po = parts(out); self.assertNotIn(b"hp:ole", po["Contents/section0.xml"]); self.assertNotIn("BinData/OLE1.ole", po)
        self.assertGreaterEqual(rep["counts"]["orig"], 1); self.assertGreaterEqual(rep["counts"]["unkept"], 1)
    def test_single_quoted_rid_in_secondary_part(self):
        p = parts(self.d)
        hdr = p["word/header1.xml"].replace(b"</w:p>", b"<w:r><w:drawing><a:blip xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main' "
                                            b"xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships' r:embed='rIdEv'/></w:drawing></w:r></w:p>", 1)
        d = zip_replace(self.d, {"word/header1.xml": hdr, "word/_rels/header1.xml.rels": REL % EXTIMG})
        out, rep = core.export_keep(d, model_of(d, "docx"), "docx")
        self.assertNotEqual(rep["level"], "blocks"); self.assertFalse(any(b"attacker" in v for v in parts(out).values()))
    def test_k1_orphan_parts_not_copied(self):
        d = load(os.path.join(HERE, "corpus", "lo-libreoffice.docx")); m = model_of(d, "docx"); m["meta"]["header"] = "새 머리말"
        d2 = zip_replace(d, {"customXml/item1.xml": b"<secret>old</secret>"})
        out, rep = core.export_keep(d2, m, "docx"); self.assertEqual(rep["level"], "parts")
        self.assertNotIn("customXml/item1.xml", parts(out)); self.assertIn("word/theme/theme1.xml", parts(out))
    def test_fullmatch_names(self):
        self.assertIsNone(hk._K1_DOCX.fullmatch("docProps/app.xml\n")); self.assertIsNone(hk._HWPX_KEEP.fullmatch("version.xml\n"))
        self.assertIsNotNone(hk._HWPX_KEEP.fullmatch("BinData/BIN0001.png"))
    def test_docpr_ids_all_parts(self):
        p = parts(self.d)
        hdr = p["word/header1.xml"].replace(b"</w:p>", b"<w:r><w:drawing><wp:docPr xmlns:wp='http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing' id='900' name='x'/></w:drawing></w:r></w:p>", 1)
        d = zip_replace(self.d, {"word/header1.xml": hdr})
        m = model_of(d, "docx"); m["blocks"].insert(1, {"type": "img", "src": PNG, "width": 10})
        out, rep = core.export_keep(d, m, "docx"); self.assertEqual(rep["level"], "blocks", rep["why"])
        ids = [int(x) for x in hk._attr_values(parts(out)["word/document.xml"], "docPr", ("id",))]
        self.assertTrue(ids and max(ids) > 900, ids)
    def test_dde_field_not_kept(self):
        p = parts(self.d); s = p["word/document.xml"]; k = s.index(b"</w:p>", s.index(b"<w:p>", s.index(b"<w:body>") + 20) + 5)
        DDE = (b'<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> DDE</w:instrText></w:r><w:r><w:instrText>AUTO c:\\x "a" </w:instrText></w:r>'
               b'<w:r><w:fldChar w:fldCharType="end"/></w:r>')
        d = zip_replace(self.d, {"word/document.xml": s[:k] + DDE + s[k:]})
        out, rep = core.export_keep(d, model_of(d, "docx"), "docx"); self.assertEqual(rep["level"], "blocks", rep["why"])
        self.assertNotIn(b"instrText", parts(out)["word/document.xml"]); self.assertGreaterEqual(rep["counts"]["orig"], 1)
        s2 = s[:k] + b'<w:fldSimple w:instr="INCLUDEPICTURE &quot;http://x/a.png&quot;"><w:r><w:t>p</w:t></w:r></w:fldSimple>' + s[k:]
        out, rep = core.export_keep(zip_replace(self.d, {"word/document.xml": s2}), model_of(zip_replace(self.d, {"word/document.xml": s2}), "docx"), "docx")
        self.assertNotIn(b"INCLUDEPICTURE", parts(out)["word/document.xml"])

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
class FieldAllowlist(unittest.TestCase):   # 감사(2026-11-14): 필드 허용 목록 우회 회귀
    BAD_WORDS = (b"INCLUDE", b"LINK ", b"IMPORT", b"DATABASE", b"AUTOTEXT", b"evil", b"attacker", b"DDEAUTO", b"MACROBUTTON")
    def setUp(self):
        self.d = load(os.path.join(HERE, "corpus", "rich.docx")); self.p = parts(self.d); s = self.p["word/document.xml"]
        self.s = s; self.k = s.index(b"</w:p>", s.index(b"<w:p>", s.index(b"<w:body>") + 20) + 5)
    def run_body(self, frag, expect_kept_other=True):
        d = zip_replace(self.d, {"word/document.xml": self.s[:self.k] + frag + self.s[self.k:]})
        out, rep = core.export_keep(d, model_of(d, "docx"), "docx")
        allx = b"".join(v for n, v in parts(out).items() if n.endswith(".xml"))
        for w in self.BAD_WORDS: self.assertNotIn(w, allx, (w, rep))
        if expect_kept_other: self.assertEqual(rep["level"], "blocks", rep["why"])
        return rep
    def fld(self, *instr, nested=b""):
        runs = b"".join(b"<w:r><w:instrText xml:space=\"preserve\">%s</w:instrText></w:r>" % i for i in instr)
        return (b'<w:r><w:fldChar w:fldCharType="begin"/></w:r>' + runs + nested +
                b'<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>res</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>')
    def test_unit_allowlist(self):
        ok = (" PAGE ", "NUMPAGES", ' HYPERLINK "https://a.b/c" ', ' HYPERLINK \\l "bm" ', "=SUM(ABOVE)", ' REF bm1 \\h ', ' hyperlink "mailto:a@b.c"')
        bad = ('INCLUDETEXT "x"', 'LINK Excel.Sheet.8 "c:\\\\a.xls" "S1"', 'INCLUDE "x"', 'IMPORT "x"', "DATABASE \\d x", 'RD "x.docx"',
               "AUTOTEXT foo", "AUTOTEXTLIST x", "DDEAUTO a b", 'MACROBUTTON M x', 'MERGEFIELD f', 'FILLIN "q"', "USERNAME",
               ' HYPERLINK "file:///c:/x" ', ' HYPERLINK "\\\\\\\\evil\\\\s" ', ' HYPERLINK "javascript:x" ', ' REF "\\\\\\\\srv\\\\x" ',
               '"INCLUDETEXT" "x"', "'INCLUDETEXT' x", "", "   ", " HYPERLINK ")
        for i in ok: self.assertTrue(hk.docx_field_ok(i), i)
        for i in bad: self.assertFalse(hk.docx_field_ok(i), i)
    def test_split_instr_text(self):   # instrText 를 여러 run 으로 쪼갬(" INCL" "UDETEXT ...")
        self.run_body(self.fld(b" INCL", b"UDETEXT &quot;\\\\evil\\s\\a.docx&quot; "))
        self.run_body(self.fld(b" LI", b"NK Word.Document.12 &quot;c:\\\\x.docx&quot; "))
    def test_del_instr_text(self):
        frag = (b'<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:delInstrText> IMPORT &quot;http://evil/x.png&quot; </w:delInstrText></w:r>'
                b'<w:r><w:fldChar w:fldCharType="end"/></w:r>')
        self.run_body(frag)
    def test_nested_kind_from_inner_field(self):   # 바깥 종류를 안쪽 필드 결과로 만드는 경우
        self.run_body(self.fld(b" ", nested=self.fld(b' QUOTE &quot;INCLUDETEXT&quot; ')))
    def test_single_quoted_and_other_prefix(self):
        self.run_body(b"<w:fldSimple w:instr='INCLUDETEXT \"x\"'><w:r><w:t>p</w:t></w:r></w:fldSimple>")
        self.run_body(b'<ww:fldSimple xmlns:ww="%s" ww:instr="AUTOTEXT evil"><ww:r><ww:t>p</ww:t></ww:r></ww:fldSimple>' % W.encode())
        self.run_body(b'<w:r><x:fldChar xmlns:x="%s" x:fldCharType="begin"/></w:r><w:r><w:instrText> DATABASE \\d evil </w:instrText></w:r>'
                      b'<w:r><w:fldChar w:fldCharType="end"/></w:r>' % W.encode())
    def test_strict_namespace(self):
        st = b"http://purl.oclc.org/ooxml/wordprocessingml/main"
        self.run_body(b'<s:fldSimple xmlns:s="%s" s:instr="INCLUDEPICTURE evil"><w:r><w:t>p</w:t></w:r></s:fldSimple>' % st)
    def test_unclosed_field_across_blocks(self):
        self.run_body(b'<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> PAGE </w:instrText></w:r>')
    def test_hyperlink_targets(self):
        self.run_body(b'<w:fldSimple w:instr=" HYPERLINK &quot;\\\\attacker\\share&quot; "><w:r><w:t>p</w:t></w:r></w:fldSimple>')
        d = zip_replace(self.d, {"word/document.xml": self.s[:self.k] + b'<w:fldSimple w:instr=" HYPERLINK &quot;https://ok.example/&quot; "><w:r><w:t>q</w:t></w:r></w:fldSimple>' + self.s[self.k:]})
        out, rep = core.export_keep(d, model_of(d, "docx"), "docx")
        self.assertEqual(rep["level"], "blocks"); self.assertIn(b"https://ok.example/", parts(out)["word/document.xml"])   # 허용 필드는 그대로 되씀
    def test_nested_quote_builds_kind(self):   # 감사 HIGH1: { {QUOTE INCLUDEPICTURE} {QUOTE "http://evil"} PAGE }
        q = lambda t: self.fld(t)
        self.run_body(self.fld(b" ", nested=q(b" QUOTE INCLUDEPICTURE ") + q(b' QUOTE &quot;http://evil.example/a.png&quot; ')) +
                      b"")
        frag = (b'<w:r><w:fldChar w:fldCharType="begin"/></w:r>' + q(b" QUOTE 68 68 69 ") + b'<w:r><w:instrText> PAGE </w:instrText></w:r>'
                b'<w:r><w:fldChar w:fldCharType="end"/></w:r>')
        d = zip_replace(self.d, {"word/document.xml": self.s[:self.k] + frag + self.s[self.k:]})
        out, rep = core.export_keep(d, model_of(d, "docx"), "docx")
        self.assertNotIn(b"QUOTE 68", parts(out)["word/document.xml"])
        self.assertTrue(hk.fields_bad(b'<w:p xmlns:w="%s"><w:fldSimple w:instr="PAGE"/><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                                      b'<w:fldSimple w:instr="QUOTE x"/><w:r><w:instrText>PAGE</w:instrText></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>' % W.encode(), "docx"))
    def test_ambiguous_attrs_and_text_in_code(self):   # 감사 HIGH3·LOW: 이중 속성, 명령부 w:t, 양식 매크로, \m
        st = b"http://purl.oclc.org/ooxml/wordprocessingml/main"
        pre = b'<w:p xmlns:w="%s" xmlns:s="%s">' % (W.encode(), st)
        self.assertTrue(hk.fields_bad(pre + b'<w:fldSimple w:instr="INCLUDEPICTURE x" s:instr="PAGE"/></w:p>', "docx"))
        self.assertTrue(hk.fields_bad(pre + b'<w:r><w:fldChar w:fldCharType="begin" s:fldCharType="end"/></w:r><w:r><w:instrText>INCLUDETEXT x</w:instrText></w:r></w:p>', "docx"))
        self.assertTrue(hk.fields_bad(pre + b'<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:t>INCLUDETEXT x</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>', "docx"))
        self.assertTrue(hk.fields_bad(pre + b'<w:r><w:fldChar w:fldCharType="begin"><w:ffData><w:entryMacro w:val="AutoExec"/></w:ffData></w:fldChar></w:r>'
                                      b'<w:r><w:instrText> FORMTEXT </w:instrText></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>', "docx"))
        self.assertFalse(hk.docx_field_ok(' HYPERLINK \\m "evil.exe" \\l "a" '))
        self.assertFalse(hk.fields_bad(pre + b'<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> PAGE </w:instrText></w:r>'
                                       b'<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>', "docx"))
    def test_renamed_part_extension(self):   # 감사 HIGH2: header1.XML / .bin 으로 확장자 바꿔 검사 우회
        p = self.p
        for newn in ("word/header1.XML", "word/header1.bin"):
            hdr = p["word/header1.xml"].replace(b"</w:p>", b'<w:fldSimple w:instr="INCLUDEPICTURE &quot;http://evil.example/a&quot;"><w:r><w:t>x</w:t></w:r></w:fldSimple></w:p>', 1)
            rels = p["word/_rels/document.xml.rels"].replace(b'Target="header1.xml"', b'Target="%s"' % newn.split("/")[1].encode())
            ct = p["[Content_Types].xml"].replace(b'PartName="/word/header1.xml"', b'PartName="/%s"' % newn.encode())
            repl = {"word/_rels/document.xml.rels": rels, "[Content_Types].xml": ct, newn: hdr}
            if "word/_rels/header1.xml.rels" in p: repl["word/_rels/%s.rels" % newn.split("/")[1]] = p["word/_rels/header1.xml.rels"]
            d = zip_replace(self.d, repl, drop=("word/header1.xml", "word/_rels/header1.xml.rels"))
            try: m = model_of(d, "docx")
            except Exception: continue
            out, rep = core.export_keep(d, m, "docx")
            self.assertFalse(any(b"evil.example" in v for v in parts(out).values()), (newn, rep))
    def test_mailmerge_settings_stripped(self):   # 감사 MED: settings 편지 병합(ODBC·UNC) 제거
        st = self.p["word/settings.xml"]
        mm = b'<w:mailMerge><w:mainDocumentType w:val="formLetters"/><w:connectString w:val="DSN=x;DBQ=\\\\evil\\db"/><w:query w:val="SELECT * FROM t"/></w:mailMerge>'
        i = st.index(b">", st.index(b"<w:settings")) + 1
        d = zip_replace(self.d, {"word/settings.xml": st[:i] + mm + st[i:]})
        out, rep = core.export_keep(d, model_of(d, "docx"), "docx")
        self.assertEqual(rep["level"], "blocks", rep["why"])
        self.assertFalse(any(b"mailMerge" in v or b"evil" in v for v in parts(out).values()))
    def test_utf16_and_renamed_settings(self):   # 재감사: UTF-16 파트·설정 파트 개명으로 필드·mailMerge 검사 우회
        hdr = self.p["word/header1.xml"].decode("utf-8").replace("</w:p>", '<w:fldSimple w:instr="INCLUDEPICTURE &quot;http://evil.example/a&quot;"><w:r><w:t>x</w:t></w:r></w:fldSimple></w:p>', 1)
        hdr = hdr.replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf-16")
        d = zip_replace(self.d, {"word/header1.xml": hdr})
        out, rep = core.export_keep(d, model_of(d, "docx"), "docx")
        self.assertFalse(any(b"evil" in v or b"e\x00v\x00i\x00l" in v for v in parts(out).values()), rep)
        st = self.p["word/settings.xml"]; i = st.index(b">", st.index(b"<w:settings")) + 1
        st = st[:i] + b'<w:mailMerge><w:connectString w:val="DSN=evil"/></w:mailMerge>' + st[i:]
        rels = self.p["word/_rels/document.xml.rels"].replace(b'Target="settings.xml"', b'Target="conf.xml"')
        ct = self.p["[Content_Types].xml"].replace(b'PartName="/word/settings.xml"', b'PartName="/word/conf.xml"')
        d = zip_replace(self.d, {"word/conf.xml": st, "word/_rels/document.xml.rels": rels, "[Content_Types].xml": ct}, drop=("word/settings.xml",))
        out, rep = core.export_keep(d, model_of(d, "docx"), "docx")
        self.assertFalse(any(b"mailMerge" in v or b"evil" in v for v in parts(out).values()), rep)
    def test_hwpx_foreign_ns_and_long_param(self):   # 감사 MED: 이름공간 무관 fieldBegin, 매개변수 이차 시간
        self.assertTrue(hk.fields_bad(b'<x:p xmlns:x="urn:x"><x:fieldBegin type="MAILMERGE"/></x:p>', "hwpx"))
        big = b'<hp:fieldBegin xmlns:hp="urn:x" type="HYPERLINK" name=""><hp:parameters><hp:stringParam name="Path">' + b"&#65;" * 100000 + b'</hp:stringParam></hp:parameters></hp:fieldBegin>'
        t = time.time(); self.assertTrue(hk.fields_bad(b"<r>" + big + b"</r>", "hwpx")); self.assertLess(time.time() - t, 2.0)
    def test_fields_in_comments_header_part(self):   # 메모·머리말 파트의 필드
        p = self.p; s = self.s
        COM = (b'<w:comments xmlns:w="%s"><w:comment w:id="0" w:author="a"><w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
               b'<w:r><w:instrText> INCLUDETEXT &quot;\\\\attacker\\x&quot; </w:instrText></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:comment></w:comments>') % W.encode()
        k = s.index(b"</w:p>", s.index(b"<w:body>"))
        s2 = s[:k] + b'<w:r><w:commentReference w:id="0"/></w:r>' + s[k:]
        rels = p["word/_rels/document.xml.rels"].replace(b"</Relationships>", b'<Relationship Id="rIdC1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/></Relationships>')
        d = zip_replace(self.d, {"word/document.xml": s2, "word/comments.xml": COM, "word/_rels/document.xml.rels": rels})
        out, rep = core.export_keep(d, model_of(d, "docx"), "docx")
        self.assertFalse(any(b"INCLUDETEXT" in v or b"attacker" in v for v in parts(out).values()), rep)
        hdr = p["word/header1.xml"].replace(b"</w:p>", b'<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> LINK x &quot;evil&quot; </w:instrText></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>', 1)
        d = zip_replace(self.d, {"word/header1.xml": hdr})
        out, rep = core.export_keep(d, model_of(d, "docx"), "docx")
        self.assertFalse(any(b"LINK x" in v for v in parts(out).values()), rep)
    def test_hwpx_field_kinds(self):
        h = load(os.path.join(HERE, "corpus", "rich.hwpx")); p = parts(h); s = p["Contents/section0.xml"]
        g = core.keep_index(h, "hwpx")["groups"][2]; k = s.rindex(b"</hp:p>", g["start"], g["end"])
        def run(frag):
            d = zip_replace(h, {"Contents/section0.xml": s[:k] + frag + s[k:]})
            out, rep = core.export_keep(d, model_of(d, "hwpx"), "hwpx")
            allx = b"".join(v for n, v in parts(out).items() if n.endswith(".xml"))
            self.assertNotIn(b"evil", allx, rep); return rep, allx
        run(b'<hp:run charPrIDRef="0"><hp:ctrl><hp:fieldBegin id="77" type="MAILMERGE" name="evil"/></hp:ctrl></hp:run>')
        run(b'<hp:run charPrIDRef="0"><hp:ctrl><hp:fieldBegin id="77" type="HYPERLINK" name="file://evil/x"/></hp:ctrl></hp:run>')
        run(b'<hp:run charPrIDRef="0"><hp:ctrl><q:fieldBegin xmlns:q="http://www.hancom.co.kr/hwpml/2011/paragraph" id="77" type="HYPERLINK" name="">'
            b'<q:parameters cnt="1" name=""><q:stringParam name="Command">\\\\evil\\x;1;0;0;</q:stringParam></q:parameters></q:fieldBegin></hp:ctrl></hp:run>')
        rep, allx = run(b'<hp:run charPrIDRef="0"><hp:ctrl><hp:fieldBegin id="77" type="HYPERLINK" name="https://ok.example/"/></hp:ctrl></hp:run>')
        self.assertIn(b"https://ok.example/", allx)

class CellCap(unittest.TestCase):   # 감사(2026-11-14): 표 연산 작업량·문서 전체 칸 상한
    def test_doc_cell_cap(self):
        import hanword_model as hm
        m = {"blocks": [{"type": "p", "runs": [{"text": "a"}]}], "meta": {}, "notes": {}}
        ops = [{"op": "insert_table", "pos": [0, 0], "rows": 200, "cols": 64}] * 10   # 128,000칸 > 100,000
        with self.assertRaises(hm.ModelError) as cm: hm.apply(m, ops)
        self.assertIn("칸", str(cm.exception))
        t = {"blocks": [{"type": "table", "rows": [[{"runs": []}, {"runs": []}]]}, {"type": "p", "runs": [{"text": "a"}]}], "meta": {}, "notes": {}}
        ops = [{"op": "table_cell", "index": 0, "r": 0, "c": 0, "bg": "#FFFFFF"}] * 3001
        with self.assertRaises(hm.ModelError) as cm: hm.apply(t, ops)   # 작은 표라도 연산당 기본 작업량(TABLE_OP_COST) 셈
        self.assertIn("작업량", str(cm.exception))
        big = {"blocks": [{"type": "table", "rows": [[{"runs": []} for _ in range(100)] for _ in range(300)]} for _ in range(4)], "meta": {}, "notes": {}}
        with self.assertRaises(hm.ModelError): hm.validate(big)   # 불러온 문서도 120,000칸 = 거절
        ok = hm.apply(t, [{"op": "table_insert_rows", "index": 0, "at": 1, "n": 2}, {"op": "table_insert_cols", "index": 0, "at": 0, "n": 1}])
        self.assertEqual(sum(len(r) for r in ok["blocks"][0]["rows"]), 9)

class Mechanics(unittest.TestCase):
    def test_align_linear(self):
        n = 100000; a = ["h%d" % (i % 997) for i in range(n)]; b = list(a); del b[500]; b.insert(70000, "new"); b[99000] = "chg"
        t = time.time(); ma = hk.align(a, b); dt = time.time() - t
        self.assertLess(dt, 5.0); self.assertGreater(sum(1 for x in ma if x >= 0), n - 10)
        js = [j for j in ma if j >= 0]; self.assertEqual(js, sorted(js))
    def test_hash_note_by_text(self):
        m1 = {"notes": {"1": "가"}, "blocks": [{"type": "p", "runs": [{"text": "a"}, {"endnote": "1"}]}]}
        m2 = {"notes": {"9": "가"}, "blocks": [{"type": "p", "runs": [{"text": "a"}, {"endnote": "9"}]}]}
        self.assertEqual(hk.block_hashes(m1), hk.block_hashes(m2))
        m2["notes"]["9"] = "나"; self.assertNotEqual(hk.block_hashes(m1), hk.block_hashes(m2))
    def test_hash_future_attr(self):   # 나중에 속성(sup 등)이 늘어도 정의가 그대로 — 다른 블록으로 셈
        b = {"type": "p", "runs": [{"text": "x"}]}
        self.assertNotEqual(hk.block_hashes({"blocks": [b]}), hk.block_hashes({"blocks": [{"type": "p", "runs": [{"text": "x", "sup": True}]}]}))
    def test_html_input(self):
        f = os.path.join(HERE, "corpus", "rich.hwpx"); d = load(f)
        out, rep = core.export_keep(d, core.import_bytes(d, "hwpx"), "hwpx"); self.assertEqual(rep["level"], "blocks")
    def test_keep_index(self):
        d = load(os.path.join(HERE, "corpus", "rich.docx")); ix = core.keep_index(d)
        self.assertEqual(ix["sha256"], hk.sha256(d)); self.assertEqual([h for g in ix["groups"] for h in g["blocks"]], ix["blocks"])

class CLI(unittest.TestCase):
    def test_render_keep(self):
        import tempfile
        f = os.path.join(HERE, "corpus", "rich.hwpx"); hw = os.path.join(APP, "hanword")
        with tempfile.TemporaryDirectory() as td:
            mj = os.path.join(td, "m.json"); o = os.path.join(td, "o.hwpx")
            subprocess.run([sys.executable, hw, "model", f], stdout=open(mj, "wb"), check=True)
            r = subprocess.run([sys.executable, hw, "--json", "render", mj, o, "--keep", f], capture_output=True, check=True)
            j = json.loads(r.stdout); self.assertEqual(j["kept"]["level"], "blocks")
            r = subprocess.run([sys.executable, hw, "--json", "convert", f, o, "--keep", f, "--no-keep"], capture_output=True, check=True)
            self.assertNotIn("kept", json.loads(r.stdout))
            r = subprocess.run([sys.executable, hw, "--json", "keep-index", f], capture_output=True, check=True)
            self.assertEqual(json.loads(r.stdout)["format"], "hwpx")

class PythonHwpx(unittest.TestCase):
    def test_parse_keep_output(self):
        try:
            from hwpx.document import HwpxDocument
        except Exception: self.skipTest("python-hwpx 없음")
        import tempfile
        for f in glob.glob(os.path.join(HERE, "corpus", "*.hwpx")):
            d = load(f); m = model_of(d, "hwpx"); m["blocks"].insert(1, {"type": "p", "runs": [{"text": "새", "bold": True}]})
            out, rep = core.export_keep(d, m, "hwpx"); self.assertEqual(rep["level"], "blocks")
            with tempfile.NamedTemporaryFile(suffix=".hwpx") as t:
                t.write(out); t.flush()
                doc = HwpxDocument.open(t.name)
                txt = "".join(p.text or "" for p in doc.paragraphs)
                self.assertIn("새", txt)

if __name__ == "__main__":
    unittest.main()

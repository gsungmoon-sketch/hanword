# Third-party components

hanword's own code is MIT-licensed (see `../LICENSE`). The files below are redistributed
unchanged under their own licences.

| File(s) | Component | Licence | Text |
|---|---|---|---|
| `html2canvas.min.js` | html2canvas 1.4.1 — Niklas von Hertzen | MIT | `html2canvas-LICENSE.txt` |
| `jspdf.min.js` | jsPDF 2.5.1 — James Hall, yWorks GmbH and contributors (the minified bundle also contains its own MIT/zlib-licensed helpers, whose notices are kept in the file header) | MIT | `jsPDF-LICENSE.txt` |
| `hwpx_skeleton.hwpx` | empty HWPX document skeleton (`hwpx/data/Skeleton.hwpx`) from **python-hwpx** | Apache-2.0 | `Apache-2.0.txt`, `../NOTICE-hwpx_skeleton.txt` |
| `font/NanumGothic-*.ttf`, `font/NanumMyeongjo-*.ttf`, `font/NotoSansKR-*.otf`, `font/Pretendard-*.woff2` | fonts — see the table below | SIL OFL 1.1 | `fonts/` |

### Fonts (unmodified upstream binaries)

Each file below is byte-identical to the upstream release (verified by `scripts/make_public.py`;
`sha256sum font/*` to check). Pretendard files are only renamed. No font was subset, converted or
otherwise modified, so the Reserved Font Names are used as published.

| File | Font | Copyright / RFN | Source | sha256 |
|---|---|---|---|---|
| `font/NanumGothic-Regular.ttf` | NanumGothic 3.020 | © 2010-2011 NAVER Corp. (NHN); RFN Nanum, NanumGothic, … | google/fonts@1c96438 `ofl/nanumgothic/NanumGothic-Regular.ttf` | `76f45ef4a6bcff344c837c95a7dcc26e017e38b5846d5ae0cdcb5b86be2e2d31` |
| `font/NanumGothic-Bold.ttf` | NanumGothic Bold 3.020 | same | `ofl/nanumgothic/NanumGothic-Bold.ttf` | `f96298f9fb18e364d2370f4c3ce948ac67a2b61af992d7234bc15c42b033c674` |
| `font/NanumMyeongjo-Regular.ttf` | NanumMyeongjo 2.032 | © 2010 NAVER Corp. (NHN); RFN Nanum, NanumMyeongjo, … | google/fonts@1c96438 `ofl/nanummyeongjo/NanumMyeongjo-Regular.ttf` | `7ed9e8653a8ed04285d51dc343ffea6eb3d9c73afc27383ea8929ee4ffd03205` |
| `font/NanumMyeongjo-Bold.ttf` | NanumMyeongjo Bold 2.032 | same | `ofl/nanummyeongjo/NanumMyeongjo-Bold.ttf` | `bc9ed8e60d93fe6db054b8fb988481b625f2eef8cb2317ad0e9834681b8fe3f3` |
| `font/NotoSansKR-Regular.otf` | Noto Sans KR (Region-specific Subset OTF) | © 2014-2021 Adobe; RFN "Source" | notofonts/noto-cjk@165c01b `Sans/SubsetOTF/KR/NotoSansKR-Regular.otf` | `69975a0ac8472717870aefeab0a4d52739308d90856b9955313b2ad5e0148d68` |
| `font/NotoSansKR-Bold.otf` | Noto Sans KR Bold | same | `Sans/SubsetOTF/KR/NotoSansKR-Bold.otf` | `5a6ceb287ed2fc6cfc6213144ebea68cbd94b20fc9eb873d8486493bf02d9bda` |
| `font/Pretendard-400.woff2` | Pretendard Regular 1.3.9 | © 2021 Kil Hyung-jin; RFN "Pretendard" | orioncactus/pretendard v1.3.9 release zip `web/static/woff2/Pretendard-Regular.woff2` | `fad853f7f47c6c8b103171e7193fa095708cdcd70850a71d93aa5379e8a61d63` |
| `font/Pretendard-700.woff2` | Pretendard Bold 1.3.9 | same | `web/static/woff2/Pretendard-Bold.woff2` | `4609c3356e536fafe38f4add0daeceb3d8595d3057bce13c428c33ddbd43d362` |

Upstream licence files: `fonts/Nanum-OFL.txt`, `fonts/NanumMyeongjo-OFL.txt` (google/fonts),
`fonts/NotoCJK-LICENSE.txt` (noto-cjk), `fonts/Pretendard-LICENSE.txt` (pretendard v1.3.9); generic text `OFL-1.1.txt`.
URLs: `https://raw.githubusercontent.com/google/fonts/1c96438dec81b2b5078557d91315e31fb29b9462/ofl/…`,
`https://raw.githubusercontent.com/notofonts/noto-cjk/165c01b46ea533872e002e0785ff17e44f6d97d8/…`,
`https://github.com/orioncactus/pretendard/releases/tag/v1.3.9`.

Not bundled (the editor falls back to the fonts above; see the manual, "Fonts", to add them):
Noto Serif KR, D2Coding, 함초롬바탕·함초롬돋움, 은바탕.

## Not bundled (optional, installed by the user)

| Component | Used for | Licence | Notes |
|---|---|---|---|
| pyhwp (`hwp5html`, `hwp5txt`) | importing legacy `.hwp` (HWP 5) files | **AGPL-3.0** | Run as a separate program; never vendored. Without it `.hwp` import reports "not supported". |
| python-hwpx + lxml | alternative HWPX engine (`WP_HWPX_ENGINE=pyhwpx`) | Apache-2.0 / BSD | The default engine is the stdlib `hwpx_std.py`. |
| cryptography | password-protected edit history | Apache-2.0 / BSD | |
| poppler-utils | PDF import | GPL-2.0 | separate program |
| ImageMagick | server-side raster PDF assembly | ImageMagick licence | separate program |
| Node.js + Playwright | vector PDF export (`htmlpdf.js`) | MIT / Apache-2.0 | separate program |
| 함초롬바탕·함초롬돋움 (Hancom), 은바탕 (UnBatang, GPL) | optional fonts | vendor terms / GPL | download from the official source; see the manual, "Fonts". |

Binary releases additionally contain the CPython runtime (PSF licence), the PyInstaller
bootloader (GPL-2.0 with bootloader exception) and, on Windows, WinSW (MIT); see
`packaging/THIRD-PARTY-NOTICES.txt`.

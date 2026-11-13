# hanword

[![tests](https://github.com/gsungmoon-sketch/hanword/actions/workflows/ci.yml/badge.svg)](https://github.com/gsungmoon-sketch/hanword/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)

**Korean web word processor — HWPX/DOCX open & save, tables, print/PDF. Python stdlib server, any OS.**
Editing follows the conventions of the Korean word processor Hangul (HWP); documents are saved as
self-contained HTML and can be opened from / saved to HWPX (OWPML, KS X 6101) and DOCX.
The server and the document core use only the Python 3.10+ standard library. [한국어 README](README.md)

## Download (no Python needed)
From [Releases](https://github.com/gsungmoon-sketch/hanword/releases): install the file for your OS; it registers
a service and serves the editor on `http://127.0.0.1:8088/`.

| OS | File | Install |
|---|---|---|
| Windows 10/11 x64 | `hanword-<ver>-windows-x64-setup.exe` | double-click (unsigned: SmartScreen → More info → Run anyway) |
| macOS (Apple silicon / Intel) | `hanword-<ver>-macos-<arm64·x64>.pkg` | right-click → Open (Gatekeeper) |
| Linux x64 (systemd) | `hanword-<ver>-linux-x64.tar.gz` | extract, `sudo ./install.sh` |
| anywhere with Python 3.10+ | `hanword-<ver>.pyz` | `python3 hanword-<ver>.pyz serve` |

Manual: [English](docs/manual/en/index.html) · [한국어](docs/manual/ko/index.html). Verify downloads with `SHA256SUMS`.

## Quick start (from source)
```sh
git clone https://github.com/gsungmoon-sketch/hanword.git && cd hanword
python3 server.py                          # http://127.0.0.1:8088/, documents in ~/hanword-documents
python3 server.py --port 8090 --data ./my-docs
```

## Command line (same document core, no browser)
```sh
python3 hanword formats
python3 hanword convert report.docx report.hwpx
python3 hanword check doc.hwpx                    # exit 1 on defects
python3 hanword roundtrip doc.docx --via hwpx     # exit 1 on loss
python3 hanword --json model doc.hwpx > m.json
python3 hanword apply m.json ops.json -o new.json
python3 hanword render new.json out.docx
```
Installed builds: `hanword serve`, `hanword convert …`, `hanword --version`.

## Formats
HWPX, DOCX, HTML, TXT: open + save (stdlib). PDF: save (browser print / raster), import as text or page
images (needs poppler). Word 97 `.doc`: text only. Legacy `.hwp` (HWP 5): only with the optional **pyhwp**
(AGPL-3.0, installed separately, called as an external program — not bundled).

## Optional extras
`pyhwp` (.hwp import) · `cryptography` (password-protected edit history) · poppler-utils (PDF import) ·
Node.js + Playwright (vector PDF, `WP_PDF_LOCAL=1`) · `python-hwpx` + `lxml` (alternative HWPX engine,
`WP_HWPX_ENGINE=pyhwpx`). None is needed for the core features.

## Configuration
`WP_HOST`/`--host` (127.0.0.1), `WP_PORT`/`--port` (8088), `WP_DOCS`/`--data` (~/hanword-documents),
`WP_PUBLIC=1` (stateless public converter: no server-side storage), `WP_PUBLIC_HOST`, `WP_SITE_URL`
(robots/sitemap/canonical), `WP_ALLOW_REMOTE=1` (non-loopback bind in local mode — trusted LAN only),
`WP_ALLOWED_HOSTS`, `WP_BOARD_ENABLE=1` (anonymous feedback board), `WP_DEBUG=1` (local debug bridge), `WP_MAX_BODY` (POST size limit, 64 MB).
Full list in the manual.

## Security
Local mode has no login: keep the default loopback bind. To serve on the internet use `WP_PUBLIC=1`
behind an HTTPS reverse proxy. See [SECURITY.md](SECURITY.md).

## Tests
```sh
cd tests && python -m unittest discover -v -p "test_*.py"
```

## Licence
[MIT](LICENSE) © 2026 GSUNGMOON. Bundled third-party files (html2canvas, jsPDF, HWPX skeleton from
python-hwpx, fonts under SIL OFL 1.1) keep their own licences — see [licenses/](licenses/README.md).
"Hangul", "HWP" and "HWPX" are trademarks of Hancom Inc.; this project is not affiliated with Hancom.

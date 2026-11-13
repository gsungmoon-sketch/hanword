# hanword — 한워드

[![tests](https://github.com/gsungmoon-sketch/hanword/actions/workflows/ci.yml/badge.svg)](https://github.com/gsungmoon-sketch/hanword/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![stdlib only](https://img.shields.io/badge/core%20dependencies-none-brightgreen)

**브라우저에서 쓰는 한국어 워드프로세서.** 편집 방식은 아래한글(HWP)을 따르고, 문서는 표준 HTML로 저장하며
**HWPX·DOCX 열기/저장**, 표, 그림, 쪽 설정, 찾기/바꾸기, 인쇄·PDF를 지원합니다.
서버는 Python 3.10+ **표준 라이브러리만**으로 동작 — Windows / macOS / Linux 어디서나 같습니다.

> **English:** see [README.en.md](README.en.md). Korean web word processor — HWPX/DOCX open & save, tables, print/PDF. Python stdlib server, any OS.

## 내려받기 (Python 설치 불필요)
[Releases](https://github.com/gsungmoon-sketch/hanword/releases) 에서 OS에 맞는 파일을 받아 설치하면 서비스로 등록되고
브라우저에서 `http://127.0.0.1:8088/` 로 엽니다.

| OS | 파일 | 설치 |
|---|---|---|
| Windows 10/11 x64 | `hanword-<버전>-windows-x64-setup.exe` | 더블클릭 (서명 전이라 SmartScreen → 추가 정보 → 실행) |
| macOS (Apple silicon / Intel) | `hanword-<버전>-macos-<arm64·x64>.pkg` | 우클릭 → 열기 (Gatekeeper) |
| Linux x64 (systemd) | `hanword-<버전>-linux-x64.tar.gz` | 풀고 `sudo ./install.sh` |
| Python 3.10+ 있는 곳 | `hanword-<버전>.pyz` | `python3 hanword-<버전>.pyz serve` |

설명서 / Manual: [한국어](docs/manual/ko/index.html) · [English](docs/manual/en/index.html) — 설치 패키지에도 들어 있습니다.
무결성 확인: 릴리스의 `SHA256SUMS`.

## 빠른 시작 (소스에서)
```sh
git clone https://github.com/gsungmoon-sketch/hanword.git && cd hanword
python3 server.py                       # http://127.0.0.1:8088/  문서 폴더: ~/hanword-documents
python3 server.py --port 8090 --data ./my-docs
```
Windows 는 `python server.py` / `py server.py`.

## 명령줄 (브라우저 없이 같은 문서 코어 사용)
```sh
python3 hanword formats                          # 지원 형식
python3 hanword convert 보고서.docx 보고서.hwpx    # 형식 변환 (html/hwpx/docx/txt/pdf…)
python3 hanword check 문서.hwpx                   # 파싱+검증, 결함 있으면 종료코드 1
python3 hanword roundtrip 문서.docx --via hwpx    # 왕복 손실 검사
python3 hanword --json model 문서.hwpx > m.json   # 문서모델(JSON)
python3 hanword apply m.json ops.json -o new.json # 편집 연산 적용 → render 로 다시 문서로
python3 hanword render new.json 새.hwpx --keep 문서.hwpx  # 같은 형식 저장: 안 바뀐 문단·표 = 원본 XML 그대로(도형·수식·필드째)
```
설치판에서는 `hanword serve`, `hanword convert …` 처럼 씁니다.

## 지원 형식
| 형식 | 열기 | 저장 | 비고 |
|---|---|---|---|
| HWPX (한글 2014+) | ✓ | ✓ | 표준 라이브러리 엔진 (`hwpx_std.py`) |
| DOCX (Word) | ✓ | ✓ | |
| HTML / TXT | ✓ | ✓ | 한워드 문서 = 자족형 HTML |
| PDF | 텍스트·쪽 이미지 | ✓ (인쇄·래스터) | 가져오기는 poppler 필요 |
| DOC (Word 97) | 텍스트만 | — | |
| HWP 5 (.hwp) | 선택 | — | **pyhwp(AGPL) 별도 설치 시** |

## 선택 기능 (Optional extras — 기본 기능엔 불필요)
| 기능 | 필요한 것 |
|---|---|
| `.hwp` 가져오기 | `pip install pyhwp` (AGPL-3.0, 별도 프로그램으로 호출 — 저장소에 포함하지 않음) |
| 편집 역사 암호 보관 | `pip install cryptography` |
| PDF 가져오기 | poppler-utils (`pdftotext`, `pdftoppm`) |
| 벡터 PDF 내보내기 | Node.js + Playwright, `WP_PDF_LOCAL=1` |
| 다른 HWPX 엔진 | `pip install python-hwpx lxml`, `WP_HWPX_ENGINE=pyhwpx` |

브라우저 인쇄와 "PDF로 저장"(html2canvas+jsPDF 동봉)은 추가 설치 없이 됩니다.

## 설정 (환경변수 / 플래그)
| 변수 | 기본 | 뜻 |
|---|---|---|
| `WP_HOST` / `--host` | `127.0.0.1` | 바인드 주소. 로컬 모드는 로그인이 없으므로 루프백 외 주소는 거부(아래 두 변수 중 하나 필요) |
| `WP_PORT` / `--port` | `8088` | 포트 |
| `WP_DOCS` / `--data` | `~/hanword-documents` | 문서 폴더 |
| `WP_PUBLIC` | `0` | `1` = 무상태 공개 변환 모드(서버 저장 없음, 업로드/다운로드만) — 인터넷 공개용 |
| `WP_PUBLIC_HOST` | — | 공개 모드에서 허용할 Origin 호스트(쉼표 구분) |
| `WP_SITE_URL` | — | 공개 사이트 주소 → robots.txt·sitemap.xml·canonical |
| `WP_ALLOW_REMOTE` | `0` | `1` = 로컬 모드 비루프백 바인딩 허용(**신뢰할 수 있는 LAN만**) |
| `WP_ALLOWED_HOSTS` | — | 로컬 모드에서 추가 허용할 Host 헤더 이름 |
| `WP_BOARD_ENABLE` | `0` | `1` = 익명 의견 게시판 |
| `WP_DEBUG` | `0` | `1` = 로컬 디버그 브리지(`hanword debug`) — 공용 기기에서 켜지 마세요 |
| `WP_MAX_BODY` | `67108864` | POST 본문 상한(바이트) |

## 보안
로컬 모드에는 로그인이 없습니다. 기본값(127.0.0.1)대로 쓰고, 인터넷에 올릴 때는 `WP_PUBLIC=1` + HTTPS 리버스 프록시를 쓰세요.
자세한 내용: [SECURITY.md](SECURITY.md), 설명서 "보안".

## 시험
```sh
cd tests && python -m unittest discover -v -p "test_*.py"
```

## 라이선스
[MIT](LICENSE) © 2026 GSUNGMOON. 동봉한 제3자 파일(html2canvas, jsPDF, HWPX 골격, 글꼴)은 각자의 라이선스를 따릅니다 — [licenses/](licenses/README.md).
"한글", "HWP", "HWPX"는 한글과컴퓨터의 상표이며, 이 프로젝트는 한글과컴퓨터와 관계가 없습니다.

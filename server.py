#!/usr/bin/env python3
# 한워드(hanword) 서버 — 브라우저 WYSIWYG 문서 편집기 서빙 + 문서 저장/불러오기 + HWPX/DOCX/PDF 변환.
#   표준 라이브러리만으로 동작(HWPX·DOCX·TXT·HTML). 선택 기능은 README "Optional extras" 참고.
#   설정(환경변수, 일부는 플래그 --host/--port/--data):
#     WP_HOST(기본 127.0.0.1) WP_PORT(기본 8088) WP_DOCS(문서 폴더, 기본 ~/hanword-documents) WP_FONT WP_DEBUG(기본 0)
#     WP_PUBLIC=1(무상태 공개 변환 모드) WP_PUBLIC_HOST(허용 Origin 호스트, 쉼표 목록) WP_SITE_URL(robots/sitemap/canonical)
#     WP_BOARD_ENABLE=1(익명 게시판) WP_ALLOW_REMOTE=1(로컬 모드 비루프백 바인딩 허용) WP_ALLOWED_HOSTS(추가 Host 허용)
#     WP_MAX_BODY(POST 본문 상한, 기본 64MB) WP_REMOTE_SSH(선택: ssh 원격 변환 폴백 호스트) PRN_BIN/QUITNAG_BIN(기기 전용, 기본 꺼짐)
import os, sys, json, re, posixpath, urllib.parse, subprocess, base64, threading, importlib, secrets, tempfile, shutil, errno, shlex
import html as htmlmod, hashlib, ipaddress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if __name__ == "__main__":   # 플래그 → 환경변수(아래 모듈 상수 계산 전에): server.py --host H --port P --data DIR
    import argparse as _argparse
    _p = _argparse.ArgumentParser(description="hanword server (see README for WP_* environment variables)")
    _p.add_argument("--host", help="bind address (default 127.0.0.1, env WP_HOST)")
    _p.add_argument("--port", type=int, help="port (default 8088, env WP_PORT)")
    _p.add_argument("--data", help="documents folder (env WP_DOCS, default ~/hanword-documents)")
    _a = _p.parse_args()
    for _k, _v in (("WP_HOST", _a.host), ("WP_PORT", _a.port), ("WP_DOCS", _a.data)):
        if _v is not None: os.environ[_k] = str(_v)

# ── 선택: ssh 원격 변환 폴백 ─────────────────────────────────────────────
#   WP_REMOTE_SSH=<ssh 대상>일 때만 사용. 기본=원격 없음(모든 변환은 이 프로세스 안).
#   원격 쪽에는 WP_REMOTE_APP(기본 ~/hanword)에 hwpxconv.py·htmlpdf.js 가 있어야 함.
REMOTE_SSH  = os.environ.get("WP_REMOTE_SSH", "").strip()
REMOTE_APP  = os.environ.get("WP_REMOTE_APP", "~/hanword")
def _rq(path):   # 원격 셸용 경로 인용(~/ 접두는 $HOME 으로 펼침)
    return '"$HOME"/' + shlex.quote(path[2:]) if path.startswith("~/") else shlex.quote(path)
REMOTE_HOME = os.environ.get("WP_REMOTE_HOME", "")   # ssh 키를 다른 HOME에서 찾아야 할 때(기기 등)

def _remote_run(cmd, data, timeout):
    env = {**os.environ}
    if REMOTE_HOME: env["HOME"] = REMOTE_HOME
    return subprocess.run(["ssh", "-o", "ConnectTimeout=6", "-o", "BatchMode=yes", "--", REMOTE_SSH, cmd],
                          input=data, capture_output=True, timeout=timeout, env=env)

def remote_conv(mode, data):
    """원격 HWPX 변환. mode='export'(html→hwpx) | 'import'(hwpx→html). (ok, out, err)"""
    if not REMOTE_SSH or mode not in ("export", "import"):
        return False, b"", "원격 변환 없음"
    try:
        p = _remote_run("python3 %s %s" % (_rq(REMOTE_APP.rstrip("/") + "/hwpxconv.py"), mode), data, 40)
        if p.returncode == 0 and p.stdout:
            return True, p.stdout, ""
        return False, b"", (p.stderr.decode("utf-8", "replace")[-400:] or "원격 변환 실패")
    except Exception as e:
        return False, b"", "원격 연결 실패: %s" % e

def remote_pdf(html_bytes):
    """원격 node(htmlpdf.js) → A4 PDF. (ok, pdf, err)"""
    if not REMOTE_SSH:
        return False, b"", "벡터 PDF 변환기 미설정(WP_PDF_LOCAL=1 + node/playwright 필요)"
    try:
        p = _remote_run("node %s" % _rq(REMOTE_APP.rstrip("/") + "/htmlpdf.js"), html_bytes, 90)
        if p.returncode == 0 and p.stdout[:4] == b"%PDF":
            return True, p.stdout, ""
        return False, b"", (p.stderr.decode("utf-8", "replace")[-400:] or "PDF 변환 실패")
    except Exception as e:
        return False, b"", "원격 연결 실패: %s" % e

def local_pdf(html_bytes):
    """이 컴퓨터에서 node(htmlpdf.js)를 직접 실행 → A4 PDF. (ok, pdf, err)"""
    try:
        env = {**os.environ}
        if NODE_PATH: env["NODE_PATH"] = NODE_PATH
        if not env.get("WP_FONT_URL"):   # htmlpdf.js 가 폰트를 이 서버에서 받도록(포트 설정 반영)
            _fh = "127.0.0.1" if HOST in ("0.0.0.0", "", "localhost") else ("::1" if HOST == "::" else HOST)
            env["WP_FONT_URL"] = "http://%s:%d/font" % ("[%s]" % _fh if ":" in _fh else _fh, PORT)
        p = subprocess.run(["node", HTMLPDF], input=html_bytes, capture_output=True, timeout=90, env=env)
        if p.returncode == 0 and p.stdout[:4] == b"%PDF":
            return True, p.stdout, ""
        return False, b"", (p.stderr.decode("utf-8", "replace")[-400:] or "PDF 변환 실패")
    except Exception as e:
        return False, b"", "로컬 PDF 오류: %s" % e

def to_pdf(html_bytes):
    """PDF 변환: WP_PDF_LOCAL=1 이면 로컬 node, 아니면 원격(WP_REMOTE_SSH, 미설정이면 실패 안내)."""
    return local_pdf(html_bytes) if PDF_LOCAL else remote_pdf(html_bytes)

APP   = os.path.dirname(os.path.abspath(__file__))            # 스크립트 위치
DOCS  = os.path.realpath(os.path.expanduser(os.environ.get("WP_DOCS") or os.path.join("~", "hanword-documents")))   # 절대경로화: 상대 WP_DOCS면 docpath의 commonpath 검증이 ValueError→저장 500(2026-07-06 e2e에서 발견)
FONT  = os.environ.get("WP_FONT") or os.path.join(APP, "font", "NotoSansKR.ttf")
FONTDIR = os.environ.get("WP_FONTDIR", os.path.join(APP, "font"))   # 추가 웹폰트(woff2/ttf) 디렉토리
FONT_CT = {"woff2":"font/woff2","woff":"font/woff","ttf":"font/ttf","otf":"font/otf","ttc":"font/collection"}
def _env_int(k, default, lo, hi):
    v = (os.environ.get(k) or "").strip() or str(default)
    try:
        n = int(v)
        if not lo <= n <= hi: raise ValueError
        return n
    except ValueError:
        sys.stderr.write("hanword: bad %s=%r (expected an integer %d..%d)\n" % (k, v, lo, hi)); sys.exit(2)
PORT  = _env_int("WP_PORT", 8088, 0, 65535)
HOST  = (os.environ.get("WP_HOST") or "127.0.0.1").strip()
ALLOW_REMOTE = os.environ.get("WP_ALLOW_REMOTE", "0") != "0"   # 로컬 모드 비루프백 바인딩 허용(신뢰 LAN 전용)
_HOST_OK = {"127.0.0.1", "localhost", "::1"} | {h.strip().lower() for h in os.environ.get("WP_ALLOWED_HOSTS", "").split(",") if h.strip()}
SITE_URL = os.environ.get("WP_SITE_URL", "").strip().rstrip("/")   # 공개 사이트 주소(robots/sitemap/canonical), 없으면 생략
BOARD_ON = os.environ.get("WP_BOARD_ENABLE", "0") != "0"           # 익명 게시판(기본 꺼짐 → /api/board/* 404)
MAX_BODY = _env_int("WP_MAX_BODY", 64 * 1024 * 1024, 0, 1 << 40)   # POST 본문 상한(바이트, 이미지 포함 문서 여유)
def _hw_version():
    try:
        import hanword_version; return hanword_version.__version__
    except Exception: return "0"
os.makedirs(DOCS, exist_ok=True)

# ── 공개(멀티유저) 모드 ──────────────────────────────────────────────
#   WP_PUBLIC=1 이면 인터넷 공개 서비스로 동작:
#   서버측 공유 문서 저장/목록을 막고, 무상태 변환 엔드포인트(업로드→html, html→hwpx/pdf)만 노출.
#   문서 보존은 전적으로 사용자 브라우저의 업로드(load)·다운로드(save)로 처리(개인정보·동시성 안전).
PUBLIC      = os.environ.get("WP_PUBLIC", "0") != "0"
PUBLIC_HOST = os.environ.get("WP_PUBLIC_HOST", "")            # 허용 Origin 호스트, 쉼표 목록(예: docs.example.com,www.example.com)
PDF_LOCAL   = os.environ.get("WP_PDF_LOCAL", "0") != "0"      # 벡터 PDF: 이 컴퓨터의 node(htmlpdf.js) 실행
HTMLPDF     = os.environ.get("WP_HTMLPDF", os.path.join(APP, "htmlpdf.js"))
NODE_PATH   = os.environ.get("WP_NODE_PATH", "")

# ── 하드닝(#18): 변환 동시실행 상한 + 응답 보안헤더/CSP ──
CONV_MAX    = max(1, int(os.environ.get("WP_CONV_MAX", "2")))     # 동시 변환(PDF·HWPX) 슬롯 수 — 초과 시 503
_CONV_SEM   = threading.BoundedSemaphore(CONV_MAX)
_CONV_DELAY = float(os.environ.get("WP_CONV_TESTDELAY", "0"))     # 테스트 전용: 슬롯 점유 지연(기본 0=무동작)
# 문서 외 응답(JSON/JS/CSS/폰트)용 기본 CSP. index.html은 nonce 포함 문서 CSP로 별도 지정.
CSP_DEFAULT = "default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"

_hx = [None]; _hxlock = threading.Lock()
def _get_hx():
    """문서 코어(hanword_core → hwpxconv·docxconv)를 상주 모듈로 lazy-import(lxml+hwpx 1회만 로드→이후 변환 즉시).
       CLI(hanword)·maru-ui와 같은 함수를 쓴다 — 서버 라우트는 얇은 래퍼."""
    if _hx[0] is None:
        with _hxlock:
            if _hx[0] is None:
                import sys as _s
                if APP not in _s.path: _s.path.insert(0, APP)
                _hx[0] = importlib.import_module("hanword_core")
    return _hx[0]

def local_conv(mode, data):
    """상주 in-process 변환(오프라인, 콜드스타트 1회뿐). (ok, out, err)"""
    try:
        core = _get_hx()
        if mode == "export":
            return True, core.export_html(data.decode("utf-8", "replace"), "hwpx", page=_PAGE.get()), ""
        if mode == "export-docx":
            return True, core.export_html(data.decode("utf-8", "replace"), "docx", page=_PAGE.get()), ""
        if mode == "import":   # hwpx/hwp/docx(내용 매직으로 판별)
            fmt = core.detect(data)
            if fmt not in ("hwpx", "hwp", "docx", "doc", "rtf"): raise core.InputError("지원하지 않는 형식")   # doc=텍스트만, rtf=안내 오류
            return True, core.import_bytes(data, fmt).encode("utf-8"), ""
        raise ValueError("unknown mode")
    except Exception as e:
        tag = "INPUT:" if isinstance(e, ValueError) and type(e).__name__ in ("HwpxInputError", "DocxInputError") else ""   # 악성/손상 입력은 폴백 불필요 표식
        return False, b"", "%s로컬 변환 오류: %s" % (tag, e)

class _PageTL(threading.local):   # 요청별 용지 설정(docx 내보내기) — 스레드 로컬
    page = None
    def get(self): return self.page
_PAGE = _PageTL()

def conv(mode, data):
    """HWPX/DOCX 변환: 로컬(오프라인) 우선, 실패 시 원격 폴백(WP_REMOTE_SSH 설정 시, hwpx만 — docx는 로컬 전용)."""
    ok, out, err = local_conv(mode, data)
    if ok: return ok, out, err
    if err.startswith("INPUT:") or mode == "export-docx" or not REMOTE_SSH:   # 사용자 입력 문제(악성/손상 hwpx)는 원격 폴백 생략(자원 증폭 차단)
        return False, b"", err
    ok2, out2, err2 = remote_conv(mode, data)
    if ok2: return ok2, out2, err2
    return False, b"", "로컬:%s / 원격:%s" % (err, err2)

def _bad_leaf(name):
    """파일 이름 하나(경로 아님)로 쓸 수 없는 이름? — 경로 구분자(/ \\), 드라이브·스트림(:), ., .., 숨김, 제어문자."""
    return (not isinstance(name, str) or not name or name in (".", "..") or name.startswith(".")
            or any(c in name for c in "/\\:\0") or any(ord(c) < 32 for c in name))

def _leaf_path(base, name):
    """base 폴더 바로 아래의 name 경로, 아니면 None(realpath 의 부모가 base 와 같아야 함 — 심링크 탈출 차단)."""
    if _bad_leaf(name): return None
    rb = os.path.realpath(base); fp = os.path.join(rb, name)
    if os.path.dirname(os.path.realpath(fp)) != rb: return None
    return fp

IMAGES = os.path.join(DOCS, "images"); os.makedirs(IMAGES, exist_ok=True)
IMG_EXT = {"png":"png","jpg":"jpeg","jpeg":"jpeg","gif":"gif","webp":"webp","bmp":"bmp"}
def image_datauri(name):
    fp = _leaf_path(IMAGES, name)
    if not fp or not os.path.isfile(fp):
        return None
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else "png"
    mime = IMG_EXT.get(ext, "png"); tok = "jpg" if mime == "jpeg" else mime
    try:   # 800px 이내로 축소(문서 크기 절감)
        r = subprocess.run(["magick"] + IM_LIMITS + [fp, "-resize", "800x800>", tok + ":-"],
                           capture_output=True, timeout=20)
        data = r.stdout if (r.returncode == 0 and r.stdout) else open(fp, "rb").read()
    except Exception:
        data = open(fp, "rb").read()
    return "data:image/%s;base64,%s" % (mime, base64.b64encode(data).decode())

MEDIA = os.path.join(DOCS, "media"); os.makedirs(MEDIA, exist_ok=True)
MED_EXT = {"mp4":"video/mp4","webm":"video/webm","ogv":"video/ogg","mov":"video/mp4","m4v":"video/mp4",
           "mp3":"audio/mpeg","wav":"audio/wav","m4a":"audio/mp4","oga":"audio/ogg","ogg":"audio/ogg","aac":"audio/aac","flac":"audio/flac"}
def media_datauri(name):   # 문서/media 폴더의 영상·소리를 data URI로(문서=미디어, 표준 HTML 자족)
    fp = _leaf_path(MEDIA, name)
    if not fp or not os.path.isfile(fp):
        return None, None
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    mime = MED_EXT.get(ext)
    if not mime:
        return None, None
    try:
        data = open(fp, "rb").read()
    except Exception:
        return None, None
    kind = "audio" if mime.startswith("audio") else "video"
    return "data:%s;base64,%s" % (mime, base64.b64encode(data).decode()), kind
def media_ref(name):   # 큰 영상=파일 참조(문서엔 경로만·가벼움, 스킴이 /media/로 스트리밍). (상대경로, kind)
    fp = _leaf_path(MEDIA, name)
    if not fp or not os.path.isfile(fp):
        return None, None
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    mime = MED_EXT.get(ext)
    if not mime:
        return None, None
    return "media/" + name, ("audio" if mime.startswith("audio") else "video")

# ── 디버그/헤드리스 테스트 브리지 (127.0.0.1 전용, WP_DEBUG=0 이면 비활성) ──
import itertools, time
DEBUG  = (not PUBLIC) and os.environ.get("WP_DEBUG", "0") != "0"  # 기본 꺼짐. 공개모드는 디버그 브리지 강제 차단
DBGLOG = os.path.join(DOCS, ".wp-debug.log")
_dlock = threading.Lock()
_state = {}            # 페이지가 보고한 최신 에디터 상태
_cmdq  = []            # 테스터가 적재한 대기 명령(FIFO)
_results = {}          # id -> 실행 결과
_ids = itertools.count(1)

SAFE = re.compile(r"[^0-9A-Za-z가-힣 ._-]")
def safe_name(n):
    n = (n or "").strip().replace("/", "")
    n = SAFE.sub("", n)[:80]
    return n or "제목없음"

def docpath(name, ext=".html"):
    p = os.path.join(DOCS, safe_name(name) + ext)
    # DOCS 바로 아래만(심링크 탈출 포함 차단)
    if os.path.dirname(os.path.realpath(p)) != DOCS:
        raise ValueError("bad path")
    return p

def atomic_write(path, data):
    """원자 저장: 같은 폴더에 고유 임시파일 → flush+fsync → os.replace. 실패 시 기존 파일은 그대로."""
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path)[:40] + ".", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        try: mode = os.stat(path).st_mode & 0o777
        except OSError: mode = 0o644
        try: os.chmod(tmp, mode)
        except OSError: pass
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise
    _fsync_dir(d)

def _fsync_dir(d):   # 이름 변경을 디스크에 확정(POSIX; Windows 등은 무시)
    try:
        dfd = os.open(d, os.O_RDONLY)
        try: os.fsync(dfd)
        finally: os.close(dfd)
    except OSError:
        pass

_LINK_UNSUPPORTED = {errno.EPERM, errno.EMLINK, errno.ENOSYS, errno.EXDEV,
                     getattr(errno, "ENOTSUP", -1), getattr(errno, "EOPNOTSUPP", -1)}

def rename_noclobber(src, dst):
    """src → dst 이름변경, dst 가 이미 있으면 덮어쓰지 않고 False. 경합 안전: 하드링크(dst 가 있으면 실패) 후 src 해제.
       하드링크 불가 파일시스템이면 O_EXCL 로 자리를 선점한 뒤 os.replace."""
    try:
        os.link(src, dst)
    except FileExistsError:
        if _case_only(src, dst):   # 대소문자만 바꾸는 이름변경(대소문자 무시 파일시스템)
            os.replace(src, dst); return True
        return False
    except OSError as e:
        if e.errno not in _LINK_UNSUPPORTED: raise   # 원본 없음 등은 그대로 오류(빈 dst 를 남기지 않음)
        if not os.path.isfile(src): raise FileNotFoundError(errno.ENOENT, "no such file", src)
        try: fd = os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError: return False
        os.close(fd)
        try:
            os.replace(src, dst)
        except BaseException:
            try: os.unlink(dst)
            except OSError: pass
            raise
        _fsync_dir(os.path.dirname(dst) or ".")
        return True
    os.unlink(src)
    _fsync_dir(os.path.dirname(dst) or ".")
    return True

def _case_only(src, dst):
    """dst 가 src 와 같은 파일이고 이름이 대소문자만 다른가(대소문자 무시 파일시스템의 이름변경)."""
    if src == dst or src.lower() != dst.lower(): return False
    try: return os.path.samefile(src, dst)
    except OSError: return False

# ── #28 인쇄(프린터)·로컬 래스터 PDF (docs/print-spec.md) ──────────────────
PRN_BIN  = os.environ.get("PRN_BIN", "")        # 인쇄 CLI(rc0=성공/rc2=미등록, -x=취소). 기본 ""=인쇄 꺼짐. e2e는 스텁 주입
QUITNAG_BIN = os.environ.get("QUITNAG_BIN", "")  # #29 기기 종료 확인창 명령(인자 "0"). 기본 ""=꺼짐. e2e는 스텁 주입
PRINTDIR = os.path.join(DOCS, "print")          # 기기판 산출물 폴더(파일매니저 문서폴더에서 열람·재인쇄)
MAX_RASTER_PAGES = 300
MAX_PIXELS = 40_000_000                         # 쪽 PNG 한 장 픽셀 상한(IHDR w*h, 40MP) — 픽셀 폭탄 차단
MAX_PIXELS_TOTAL = 400_000_000                  # 한 요청의 쪽 픽셀 합 상한(400MP)
IM_LIMITS = ["-limit", "memory", "256MiB", "-limit", "map", "512MiB", "-limit", "area", "128MP",
             "-limit", "disk", "512MiB", "-limit", "list-length", str(MAX_RASTER_PAGES), "-limit", "time", "110"]

def _asset_ver():
    """정적 자산(.js/.css) mtime 최대값 → 캐시버스팅 버전. 코드 갱신·재배포 시 자동 변경 → 브라우저·CF 엣지 캐시 무효화."""
    try:
        return str(int(max(os.path.getmtime(os.path.join(APP, x)) for x in os.listdir(APP) if x.endswith((".js", ".css")))))
    except Exception:
        return "1"

_im = [None]
def _get_im():
    """ImageMagick 실행기: v7 'magick' 우선, 구판 'convert'(IM6) 폴백. 1회 탐지 캐시."""
    if _im[0] is None:
        for c in (("magick",) if os.name == "nt" else ("magick", "convert")):   # Windows convert.exe = 디스크 변환 도구
            if shutil.which(c): _im[0] = c; break
        else: _im[0] = ""
    return _im[0]

def pages_to_pdf(pages):
    """클라 캡처 PNG dataURL 배열 → 래스터 PDF (ok, pdf_bytes, err).
       sheet do_pdf와 동일 패턴: magick p*.png -units PixelsPerInch -density N out.pdf
       density = 1쪽 픽셀폭/8.27in(A4 폭 210mm) → PDF 쪽 크기가 A4로 떨어짐."""
    if not isinstance(pages, list) or not (1 <= len(pages) <= MAX_RASTER_PAGES):
        return False, b"", "잘못된 쪽 배열"
    im = _get_im()
    if not im: return False, b"", "ImageMagick 없음"
    tmpd = tempfile.mkdtemp(prefix="wpprint-")
    try:
        files, width, total = [], 0, 0
        for i, du in enumerate(pages):
            if not isinstance(du, str) or not du.startswith("data:image/png;base64,"):
                return False, b"", "PNG dataURL 아님(%d쪽)" % (i + 1)
            try: raw = base64.b64decode(du.split(",", 1)[1])
            except Exception: return False, b"", "base64 오류(%d쪽)" % (i + 1)
            if raw[:8] != b"\x89PNG\r\n\x1a\n":
                return False, b"", "PNG 아님(%d쪽)" % (i + 1)
            if len(raw) < 24 or raw[12:16] != b"IHDR": return False, b"", "PNG 아님(%d쪽)" % (i + 1)
            _w, _h = int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")   # IHDR
            if _w * _h > MAX_PIXELS: return False, b"", "쪽 이미지가 너무 큼(%d쪽)" % (i + 1)   # 픽셀 폭탄 차단
            total += _w * _h
            if total > MAX_PIXELS_TOTAL: return False, b"", "쪽 이미지 합계가 너무 큼(%d쪽까지)" % (i + 1)
            if not width: width = _w
            fp = os.path.join(tmpd, "p%04d.png" % i)
            with open(fp, "wb") as f: f.write(raw)
            files.append(fp)
        dpi = max(72, round(width / 8.27)) if width else 200
        out = os.path.join(tmpd, "out.pdf")
        p = subprocess.run([im] + IM_LIMITS + files + ["-units", "PixelsPerInch", "-density", str(dpi), out],
                           capture_output=True, timeout=120)
        if p.returncode != 0 or not os.path.isfile(out):
            return False, b"", "magick 실패: " + p.stderr.decode("utf-8", "replace")[-300:]
        with open(out, "rb") as f: pdf = f.read()
        if pdf[:4] != b"%PDF": return False, b"", "PDF 생성 실패"
        return True, pdf, ""
    except subprocess.TimeoutExpired:
        return False, b"", "magick 시간 초과"
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)

def save_print_pdf(name, pdf):
    """print/<문서명>-<YYMMDD-HHMMSS>.pdf 원자 저장(tmp→rename). (파일명, 절대경로)"""
    os.makedirs(PRINTDIR, exist_ok=True)
    fn = "%s-%s.pdf" % (safe_name(name), time.strftime("%y%m%d-%H%M%S"))
    fp = os.path.join(PRINTDIR, fn)
    atomic_write(fp, pdf)
    return fn, fp

def run_prn(args, timeout):
    """prn 실행 공통: (rc, 마지막 출력줄). 미설치=FileNotFoundError는 호출부 처리."""
    p = subprocess.run([PRN_BIN] + args, capture_output=True, timeout=timeout)
    txt = (p.stdout or p.stderr).decode("utf-8", "replace").strip()
    return p.returncode, (txt.splitlines()[-1] if txt else "")

# ── 무상태 TXT/PDF 열기 변환(2026-07-22, 기기 embed 선반영분 웹 이식) ──────────
#   웹은 문서폴더 목록·경로기반 열기가 없음(무상태) → 업로드 바이트를 그대로 변환만 한다.
#   pypdf 폴백은 웹 미사용(poppler 있음). 사용자 노출 err는 안전한 한국어 안내만, 내부상세는 stderr 로그.

# 구현은 hanword_core로 이관(2026-11-13, CLI 공용). 서버는 이름만 재노출.
import hanword_core as _core
read_txt_bytes, text_to_html, pdf_text, pdf_render_pages, pdf_pages_html = (
    _core.read_txt_bytes, _core.text_to_html, _core.pdf_text, _core.pdf_render_pages, _core.pdf_pages_html)

# ── 익명 게시판(버그 신고/건의, 2026-07-25) ─────────────────────────────────
#   로그인 없이 누구나 작성·열람. 저장=서버측 jsonl(한 줄=한 글). 공개(PUBLIC)에서도 동작.
#   방어: 제목·내용 길이 제한 + 빈 글 거부 + 파일 상한(스팸 폭주 시 신규 작성 차단).
BOARD_FILE      = os.environ.get("WP_BOARD", os.path.join(DOCS, "board.jsonl"))
BOARD_ADMIN     = os.environ.get("WP_BOARD_ADMIN", "")   # 관리자 삭제키(설정 시에만 관리자 삭제 허용)
BOARD_TITLE_MAX = 200
BOARD_BODY_MAX  = 4000
BOARD_CMT_MAX   = 1000
BOARD_NICK_MAX  = 24
BOARD_PW_MAX    = 128
BOARD_LIST_MAX  = 300          # 목록 최대 반환 수
BOARD_CMT_LIMIT = 500          # 글당 댓글 상한
BOARD_FILE_MAX  = 32 * 1024 * 1024   # 게시판 파일 상한(초과 시 신규 작성 거부)
BOARD_TAGS      = ("버그", "문의", "의견", "기타")
_board_lock = threading.Lock()

def _pw_hash(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", (pw or "").encode("utf-8"), salt, 120000).hex()
def _pw_make(pw):
    salt = secrets.token_bytes(16)
    return {"salt": salt.hex(), "pw": _pw_hash(pw, salt)}
def _pw_check(rec, pw):
    try:
        salt = bytes.fromhex(rec.get("salt", ""))
    except Exception:
        return False
    return bool(rec.get("pw")) and secrets.compare_digest(rec["pw"], _pw_hash(pw, salt))
def _is_admin(key):
    # 바이트 비교: compare_digest는 비ASCII str(한글 등)에서 TypeError → 오답 admin 키가 500/연결리셋 유발(2026-07-25 수정)
    return bool(BOARD_ADMIN) and bool(key) and secrets.compare_digest(str(key).encode("utf-8"), BOARD_ADMIN.encode("utf-8"))
def _clean_nick(nick):
    nick = (nick or "").strip()[:BOARD_NICK_MAX]
    return nick or "익명"

def board_read_all():
    """jsonl → 전체 게시글 리스트(파일 순서). 손상 줄 건너뜀."""
    posts = []
    try:
        with open(BOARD_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try: posts.append(json.loads(line))
                except Exception: continue
    except OSError:
        return []
    return posts

def _board_write_all(posts):
    """호출부가 _board_lock 을 잡은 상태에서 부른다."""
    d = os.path.dirname(BOARD_FILE)
    if d: os.makedirs(d, exist_ok=True)
    atomic_write(BOARD_FILE, "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in posts).encode("utf-8"))

def _pub_post(p):   # 목록용 공개 필드(본문·해시 제외)
    return {"id": p.get("id"), "title": p.get("title", ""), "tag": p.get("tag", "기타"),
            "nick": p.get("nick", "익명"), "ts": p.get("ts", 0), "private": bool(p.get("private")),
            "ncomments": len(p.get("comments", []))}
def _view_post(p):  # 개별 글 보기용(본문·댓글 포함, 해시 제외)
    return {"id": p.get("id"), "title": p.get("title", ""), "body": p.get("body", ""),
            "tag": p.get("tag", "기타"), "nick": p.get("nick", "익명"), "ts": p.get("ts", 0),
            "private": bool(p.get("private")),
            "comments": [{"id": c.get("id"), "nick": c.get("nick", "익명"), "body": c.get("body", ""), "ts": c.get("ts", 0)}
                         for c in p.get("comments", [])]}

def board_list(tag="", q=""):
    """공개 목록(비공개 제외, 최신순). tag/검색어(제목·별명) 필터."""
    tag = (tag or "").strip(); q = (q or "").strip().lower()
    out = []
    for p in board_read_all():
        if p.get("private"): continue
        if tag and tag != "전체" and p.get("tag") != tag: continue
        if q and q not in (p.get("title", "") + " " + p.get("nick", "")).lower(): continue
        out.append(_pub_post(p))
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out[:BOARD_LIST_MAX]

def board_get(pid):
    for p in board_read_all():
        if p.get("id") == pid:
            return _view_post(p)
    return None

def board_add(title, body, tag, nick, password, private):
    """검증 후 원자 append. (ok, id | 오류문구)."""
    title = (title or "").strip(); body = (body or "").strip()
    if not title or not body:
        return False, "제목과 내용을 모두 입력하세요."
    if not (password or "").strip():
        return False, "비밀번호를 입력하세요(수정·삭제에 필요)."
    if len(title) > BOARD_TITLE_MAX: return False, "제목이 너무 깁니다(최대 %d자)." % BOARD_TITLE_MAX
    if len(body) > BOARD_BODY_MAX:   return False, "내용이 너무 깁니다(최대 %d자)." % BOARD_BODY_MAX
    if len(password) > BOARD_PW_MAX: return False, "비밀번호가 너무 깁니다."
    tag = tag if tag in BOARD_TAGS else "기타"
    with _board_lock:
        try:
            if os.path.isfile(BOARD_FILE) and os.path.getsize(BOARD_FILE) > BOARD_FILE_MAX:
                return False, "게시판이 가득 찼습니다. 나중에 다시 시도하세요."
        except OSError:
            pass
        rec = {"id": secrets.token_hex(8), "title": title, "body": body, "tag": tag,
               "nick": _clean_nick(nick), "private": bool(private), "ts": int(time.time() * 1000), "comments": []}
        rec.update(_pw_make(password))
        try:
            d = os.path.dirname(BOARD_FILE)
            if d: os.makedirs(d, exist_ok=True)
            with open(BOARD_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError as e:
            sys.stderr.write("[board] %s\n" % str(e)[:200]); sys.stderr.flush()
            return False, "저장에 실패했습니다."
        return True, rec["id"]

def board_edit(pid, password, title, body, tag, private):
    title = (title or "").strip(); body = (body or "").strip()
    if not title or not body: return False, "제목과 내용을 모두 입력하세요."
    if len(title) > BOARD_TITLE_MAX: return False, "제목이 너무 깁니다."
    if len(body) > BOARD_BODY_MAX:   return False, "내용이 너무 깁니다."
    with _board_lock:
        posts = board_read_all()
        for p in posts:
            if p.get("id") == pid:
                if not _pw_check(p, password): return False, "비밀번호가 일치하지 않습니다."
                p["title"] = title; p["body"] = body
                p["tag"] = tag if tag in BOARD_TAGS else p.get("tag", "기타")
                p["private"] = bool(private)
                try: _board_write_all(posts)
                except OSError: return False, "저장에 실패했습니다."
                return True, pid
        return False, "글을 찾을 수 없습니다."

def board_delete(pid, password, admin=""):
    with _board_lock:
        posts = board_read_all(); keep = []; found = False
        for p in posts:
            if p.get("id") == pid:
                found = True
                if not (_pw_check(p, password) or _is_admin(admin)):
                    return False, "비밀번호가 일치하지 않습니다."
                continue
            keep.append(p)
        if not found: return False, "글을 찾을 수 없습니다."
        try: _board_write_all(keep)
        except OSError: return False, "저장에 실패했습니다."
        return True, pid

def comment_add(pid, nick, body, password):
    body = (body or "").strip()
    if not body: return False, "댓글 내용을 입력하세요."
    if not (password or "").strip(): return False, "비밀번호를 입력하세요(삭제에 필요)."
    if len(body) > BOARD_CMT_MAX: return False, "댓글이 너무 깁니다(최대 %d자)." % BOARD_CMT_MAX
    with _board_lock:
        posts = board_read_all()
        for p in posts:
            if p.get("id") == pid:
                p.setdefault("comments", [])
                if len(p["comments"]) >= BOARD_CMT_LIMIT: return False, "댓글이 너무 많습니다."
                c = {"id": secrets.token_hex(6), "nick": _clean_nick(nick), "body": body, "ts": int(time.time() * 1000)}
                c.update(_pw_make(password))
                p["comments"].append(c)
                try: _board_write_all(posts)
                except OSError: return False, "저장에 실패했습니다."
                return True, c["id"]
        return False, "글을 찾을 수 없습니다."

def comment_delete(pid, cid, password, admin=""):
    with _board_lock:
        posts = board_read_all()
        for p in posts:
            if p.get("id") == pid:
                cs = p.get("comments", []); kept = []; found = False
                for c in cs:
                    if c.get("id") == cid:
                        found = True
                        if not (_pw_check(c, password) or _is_admin(admin)):
                            return False, "비밀번호가 일치하지 않습니다."
                        continue
                    kept.append(c)
                if not found: return False, "댓글을 찾을 수 없습니다."
                p["comments"] = kept
                try: _board_write_all(posts)
                except OSError: return False, "저장에 실패했습니다."
                return True, cid
        return False, "글을 찾을 수 없습니다."

class H(BaseHTTPRequestHandler):
    timeout = int(os.environ.get("WP_SOCK_TIMEOUT", "60"))   # 느린/정지 클라이언트가 스레드를 무기한 점유하지 않게(slowloris 완화)
    def log_message(self, *a): pass  # 조용히

    def _sec_headers(self, csp=None, frame_self=False):
        # 하드닝(#18): 모든 응답에 공통 보안헤더. csp 미지정이면 문서 외 응답용 기본 CSP.
        #   frame_self = 임베드(?embed=1) 문서: 같은 출처 부모의 iframe만 허용(그 외 출처 프레이밍은 계속 차단)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN" if frame_self else "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", csp or CSP_DEFAULT)

    def _send(self, code, body, ctype="application/json; charset=utf-8", cors=False, csp=None, frame_self=False):
        if isinstance(body, str): body = body.encode("utf-8", "replace")   # 고립 서로게이트 → UnicodeEncodeError 크래시 방지
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._sec_headers(csp, frame_self)
        if cors: self.send_header("Access-Control-Allow-Origin", "*")   # PDF(Chromium null-origin)서 폰트 cross-origin 로드 허용
        self.end_headers()
        try: self.wfile.write(body)
        except BrokenPipeError: pass

    def _busy(self):    # 변환 동시 상한 초과 → 503 + Retry-After
        body = json.dumps({"ok": False, "err": "변환 서버가 혼잡합니다. 잠시 후 다시 시도하세요."}, ensure_ascii=False).encode("utf-8")
        self.send_response(503)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Retry-After", "2")
        self._sec_headers()
        self.end_headers()
        try: self.wfile.write(body)
        except BrokenPipeError: pass

    def _fail_conv(self, err):   # 변환 실패: 내부 상세는 로그로만, 사용자에겐 일반 문구(정보 노출 차단)
        try: sys.stderr.write("[convert] %s\n" % str(err)[:500]); sys.stderr.flush()
        except Exception: pass
        msg = "변환에 실패했습니다. 파일 형식을 확인하세요."
        m = re.match(r"^INPUT:로컬 변환 오류: (.{1,120})$", str(err), re.S)   # 우리가 만든 입력오류 문구(HWP3 미지원 등)만 노출
        if m and not re.search(r"[/\\]|Traceback|File \"", m.group(1)): msg = "열 수 없는 파일: " + m.group(1)
        return self._send(502, json.dumps({"ok": False, "err": msg}, ensure_ascii=False))

    def _file(self, path, ctype, cors=False):
        try:
            with open(path, "rb") as f: data = f.read()
        except OSError:
            return self._send(404, "not found", "text/plain")
        self._send(200, data, ctype, cors=cors)

    def do_GET(self):
        if self._bad_host():
            return self._send(421, "misdirected request", "text/plain")
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        path = u.path
        if path == "/healthz":               # 상태 확인(설치 스모크·모니터링)
            return self._send(200, json.dumps({"ok": True, "app": "hanword", "version": _hw_version(),
                                               "public": PUBLIC}))
        if path == "/robots.txt":            # SEO: 크롤러 허용, WP_SITE_URL 이 있으면 사이트맵 고지
            _rb = "User-agent: *\nAllow: /\nDisallow: /api/\n"
            if SITE_URL: _rb += "\nSitemap: %s/sitemap.xml\n" % SITE_URL
            return self._send(200, _rb, "text/plain; charset=utf-8")
        if path == "/sitemap.xml" and SITE_URL:   # SEO: 색인 대상 URL 목록(WP_SITE_URL 설정 시에만)
            _e = htmlmod.escape(SITE_URL, quote=True)
            _sm = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                   '  <url><loc>%s/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>\n'
                   '  <url><loc>%s/guide.html</loc><changefreq>monthly</changefreq><priority>0.6</priority></url>\n'
                   '</urlset>\n') % (_e, _e)
            return self._send(200, _sm, "application/xml; charset=utf-8")
        if path.startswith("/api/board/") and not BOARD_ON:
            return self._send(404, json.dumps({"ok": False, "err": "게시판이 꺼져 있습니다(WP_BOARD_ENABLE=1)"}, ensure_ascii=False))
        if path == "/api/board/list":       # 익명 게시판 목록(비공개 제외·최신순, tag/검색 필터) — 공개/비공개 모두 허용
            items = board_list((q.get("tag") or [""])[0], (q.get("q") or [""])[0])
            return self._send(200, json.dumps({"ok": True, "posts": items, "tags": list(BOARD_TAGS)}, ensure_ascii=False))
        if path == "/api/board/get":        # 개별 글(본문·댓글 포함, id=열람 자격 — 비공개 글도 id로 조회 가능)
            post = board_get((q.get("id") or [""])[0])
            if post is None:
                return self._send(404, json.dumps({"ok": False, "err": "글을 찾을 수 없습니다."}, ensure_ascii=False))
            return self._send(200, json.dumps({"ok": True, "post": post}, ensure_ascii=False))
        if PUBLIC and path.startswith("/api/"):   # 공개모드: 서버측 문서목록/불러오기/디버그 GET 전면 차단
            return self._send(404, json.dumps({"ok": False, "err": "disabled in public mode"}))
        if path == "/" or path == "/index.html" or path == "/embed.html":
            entry = "embed.html" if path == "/embed.html" else "index.html"   # embed.html = 임베드 전용 입구(SEO·인라인 스크립트 없음, scripts/build_embed.py 생성)
            try:
                with open(os.path.join(APP, entry), "r", encoding="utf-8") as f: html = f.read()
            except OSError:
                return self._send(404, "not found", "text/plain")
            embed = entry == "embed.html" or bool(re.search(r"(?:^|&)embed=1(?:&|$)", u.query))   # wp-core.js 판정과 같은 원문 규칙(%31 등 인코딩 형태 불인정)   # 임베드(같은 출처 iframe 허용)
            nonce = secrets.token_urlsafe(16)                 # CSP nonce(요청마다 새로) → 인라인 script 허용, 주입 XSS 차단
            html = html.replace("<script", '<script nonce="%s"' % nonce)   # 기존 태그(외부·인라인) 전부 nonce 부착
            _ver = _asset_ver()   # 자산 mtime 버전 → 코드 갱신 시 URL 변경으로 캐시(브라우저·CF 엣지) 무효화
            html = re.sub(r'((?:src|href)="/?(?:wp-[a-z]+\.js|editor\.css))"', r'\1?v=' + _ver + '"', html)   # 자산 경로는 상대(하위 경로 /editor/ 배포 대응)
            if SITE_URL and entry == "index.html":   # 정규 주소(검색엔진): WP_SITE_URL 설정 시에만 — 기존 canonical 은 교체, 없으면 추가
                _cl = '<link rel="canonical" href="%s/">' % htmlmod.escape(SITE_URL, quote=True)
                html, _n = re.subn(r'<link rel="canonical"[^>]*>', lambda _m: _cl, html, count=1)
                if not _n: html = html.replace("</head>", _cl + "\n</head>", 1)
            if PUBLIC and entry == "index.html":   # 공개모드: 플래그 주입 + wp-public.js 로드(메뉴를 업로드/다운로드로 전환)
                inj = ('<script nonce="%s">window.WP_PUBLIC=true;</script>\n'
                       '<script nonce="%s" defer src="/wp-public.js?v=%s"></script>\n') % (nonce, nonce, _ver)
                html = html.replace("</head>", inj + "</head>", 1) if "</head>" in html else inj + html
            csp = ("default-src 'self'; script-src 'self' 'nonce-%s'; style-src 'self' 'unsafe-inline'; "
                   "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
                   "media-src 'self' blob: data:; "   # P10: IndexedDB Blob 재생(blob:) + 안내서 인라인 동영상(data: — 사진 img-src data:와 대칭, 인라인이라 네트워크 egress 없음). connect/fetch는 계속 차단
                   "object-src 'none'; frame-ancestors %s; base-uri 'none'; form-action 'self'") % (nonce, "'self'" if embed else "'none'")
            return self._send(200, html, "text/html; charset=utf-8", csp=csp, frame_self=embed)
        if path == "/editor.js" or re.match(r"^/wp-[a-z]+\.js$", path):
            return self._file(os.path.join(APP, path.lstrip("/")), "application/javascript; charset=utf-8")
        if path == "/html2canvas.min.js":   # #28 래스터 캡처 벤더 라이브러리(오프라인 동봉, 지연 로드)
            return self._file(os.path.join(APP, "html2canvas.min.js"), "application/javascript; charset=utf-8")
        if path == "/jspdf.min.js":   # 클라이언트 PDF 조립(래스터 이미지→PDF, 서버 무전송)
            return self._file(os.path.join(APP, "jspdf.min.js"), "application/javascript; charset=utf-8")
        if path == "/guide.html":           # 첫 실행 안내문 원본(공개 첫 방문 자동 로드, 감독 지시 07-17) — 정적 자산(무상태)
            return self._file(os.path.join(APP, "guide.html"), "text/html; charset=utf-8")
        if path == "/editor.css":
            return self._file(os.path.join(APP, "editor.css"), "text/css; charset=utf-8")
        if path.startswith("/font/"):
            fn = posixpath.basename(path)                         # traversal 방지(basename만)
            if fn == "NotoSansKR.ttf" and os.path.isfile(FONT):
                return self._file(FONT, "font/ttf", cors=True)
            fp = os.path.join(FONTDIR, fn)
            try: inside = os.path.commonpath([os.path.realpath(fp), os.path.realpath(FONTDIR)]) == os.path.realpath(FONTDIR)
            except Exception: inside = False
            if fn and inside and os.path.isfile(fp):
                ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
                return self._file(fp, FONT_CT.get(ext, "application/octet-stream"), cors=True)
            return self._send(404, "not found", "text/plain")
        if path == "/api/list":
            items = []
            for fn in sorted(os.listdir(DOCS)):
                if fn.endswith(".html"):
                    fp = os.path.join(DOCS, fn)
                    items.append({"name": fn[:-5], "mtime": int(os.path.getmtime(fp)),
                                  "size": os.path.getsize(fp)})
            items.sort(key=lambda x: -x["mtime"])
            return self._send(200, json.dumps(items, ensure_ascii=False))
        if path == "/api/hist/has":       # 히스토리 사이드카 존재 여부(2026-07-19 암호화 역사보존)
            name = safe_name((q.get("name") or [""])[0])
            has = os.path.isfile(os.path.join(DOCS, ".hist", name + ".hist"))
            return self._send(200, json.dumps({"ok": True, "has": has}))
        if path == "/api/images":         # 삽입용 이미지 목록 (문서/images/)
            items = [{"name": fn} for fn in sorted(os.listdir(IMAGES))
                     if "." in fn and fn.rsplit(".", 1)[-1].lower() in IMG_EXT]
            return self._send(200, json.dumps(items, ensure_ascii=False))
        if path == "/api/image":          # 이미지 → base64 data URI(리사이즈)
            src = image_datauri((q.get("name") or [""])[0])
            return self._send(200, json.dumps({"ok": bool(src), "src": src or ""}, ensure_ascii=False))
        if path == "/api/list/media":     # 삽입용 미디어 목록 (문서/media/)
            items = [{"name": fn} for fn in sorted(os.listdir(MEDIA))
                     if "." in fn and fn.rsplit(".", 1)[-1].lower() in MED_EXT] if os.path.isdir(MEDIA) else []
            return self._send(200, json.dumps(items, ensure_ascii=False))
        if path == "/api/media":          # 미디어 → 같은 서버 /media/ 경로참조(문서 경량, 아래 range 스트리밍)
            name = (q.get("name") or [""])[0]
            src, kind = media_ref(name)
            if src:
                src = "/media/" + urllib.parse.quote(name)
            return self._send(200, json.dumps({"ok": bool(src), "src": src or "", "kind": kind or "video"}, ensure_ascii=False))
        if path.startswith("/media/"):    # 영상·소리 파일 스트리밍(HTTP Range 206 지원 → <video> 재생)
            if PUBLIC:                    # 공개모드: 서버측 저장소(documents/media) 노출 차단(무상태 원칙)
                self.send_error(404); return
            fn = urllib.parse.unquote(posixpath.basename(path))
            ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
            mime = MED_EXT.get(ext); fp = os.path.join(MEDIA, fn)
            if not (mime and os.path.isfile(fp) and os.path.commonpath([os.path.realpath(fp), os.path.realpath(MEDIA)]) == os.path.realpath(MEDIA)):
                self.send_error(404); return
            size = os.path.getsize(fp); start, end, status = 0, size - 1, 200
            rng = self.headers.get("Range")
            if rng:
                mm = re.match(r"bytes=(\d*)-(\d*)", rng.strip())
                if mm:
                    if mm.group(1):
                        start = int(mm.group(1))
                        if mm.group(2): end = min(int(mm.group(2)), size - 1)   # 파일 끝 초과 요청=끝으로 절단(Content-Length 불일치 방지)
                    elif mm.group(2):                                          # 접미 범위 bytes=-N = 마지막 N바이트(예전: 0..N으로 오해석)
                        start = max(0, size - int(mm.group(2)))
                    if start > end or start >= size:
                        self.send_response(416); self.send_header("Content-Range", "bytes */%d" % size); self.end_headers(); return
                    status = 206
            length = end - start + 1
            self.send_response(status)
            self.send_header("Content-Type", mime); self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if status == 206: self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
            self.end_headers()
            try:
                with open(fp, "rb") as f:
                    f.seek(start); rem = length
                    while rem > 0:
                        chunk = f.read(min(262144, rem))
                        if not chunk: break
                        self.wfile.write(chunk); rem -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, OSError): pass
            return
        if path == "/api/list/hwpx":      # 불러오기용 .hwpx/.hwp 목록
            items = []
            for fn in sorted(os.listdir(DOCS)):
                if fn.lower().endswith((".hwpx", ".hwp", ".docx", ".doc")):
                    fp = os.path.join(DOCS, fn)
                    items.append({"name": fn, "mtime": int(os.path.getmtime(fp)), "size": os.path.getsize(fp)})
            items.sort(key=lambda x: -x["mtime"])
            return self._send(200, json.dumps(items, ensure_ascii=False))
        if path == "/api/load":
            name = (q.get("name") or [""])[0]
            try:
                with open(docpath(name), "r", encoding="utf-8") as f: html = f.read()
            except (OSError, ValueError):
                html = ""
            return self._send(200, json.dumps({"name": safe_name(name), "html": html},
                                              ensure_ascii=False))
        if path == "/debug.js":
            return self._file(os.path.join(APP, "debug.js"), "application/javascript; charset=utf-8")
        if path.startswith("/api/debug/") and self._bad_fetch_site():   # 다른 사이트 페이지가 디버그 브리지를 읽지 못하게
            return self._send(403, json.dumps({"ok": False, "err": "cross-site"}))
        if DEBUG and path == "/api/debug/state":
            with _dlock: return self._send(200, json.dumps(_state, ensure_ascii=False))
        if DEBUG and path == "/api/debug/cmd":          # 페이지가 대기명령 1개 dequeue
            with _dlock: cmd = _cmdq.pop(0) if _cmdq else {}
            return self._send(200, json.dumps(cmd, ensure_ascii=False))
        if DEBUG and path == "/api/debug/result":       # 테스터가 결과 조회
            cid = (q.get("id") or ["0"])[0]
            with _dlock: r = _results.get(int(cid)) if cid.isdigit() else None
            return self._send(200, json.dumps(r if r is not None else {"pending": True}, ensure_ascii=False))
        if DEBUG and path == "/api/debug/log":           # 로그 tail(끝 32KB만 seek=전체적재 방지)
            try:
                with open(DBGLOG, "rb") as f:
                    f.seek(0, 2); sz = f.tell(); f.seek(max(0, sz - 32768))
                    lines = f.read().decode("utf-8", "replace").splitlines(keepends=True)[-200:]
            except OSError: lines = []
            return self._send(200, "".join(lines), "text/plain; charset=utf-8")
        return self._send(404, "not found", "text/plain")

    def _bad_host(self):
        # DNS 리바인딩 차단: 로컬 모드에서는 Host 헤더가 루프백/바인드 주소/허용 목록(WP_ALLOWED_HOSTS)일 때만 응답.
        # WP_ALLOW_REMOTE=1 이면 IP 리터럴(리바인딩 불가)도 허용.
        if PUBLIC: return False
        h = (self.headers.get("Host") or "").strip().lower()
        if h.startswith("["): h = h[1:].split("]", 1)[0]
        elif h.count(":") == 1: h = h.rsplit(":", 1)[0]
        h = h.rstrip(".")
        if h in _HOST_OK: return False
        if ALLOW_REMOTE and h:
            try:
                ipaddress.ip_address(h); return False
            except ValueError:
                pass
        return True

    def _bad_origin(self):
        # CSRF 차단: 브라우저의 교차 사이트 표식 거부, Origin 이 있으면 같은 출처(host:port = Host 헤더)
        # 또는 공개 허용 호스트(WP_PUBLIC_HOST 쉼표 목록)만. Origin 없음 = 도구/동일출처 단순요청 → 허용.
        # 로컬 모드: same-origin/none(주소창·북마크) 외 Sec-Fetch-Site(same-site 포함) 전부 거부.
        if self._bad_fetch_site(): return True
        o = self.headers.get("Origin")
        if not o: return False
        try:
            pu = urllib.parse.urlparse(o.strip()); host = (pu.hostname or "").lower(); netloc = (pu.netloc or "").lower()
            scheme = (pu.scheme or "").lower(); port = pu.port
        except Exception:
            return True
        if not host or "@" in netloc or scheme not in ("http", "https"): return True
        if netloc == (self.headers.get("Host") or "").strip().lower(): return False
        for ent in (x.strip().lower().rstrip("/") for x in (PUBLIC_HOST or "").split(",")):
            if not ent: continue
            if "://" in ent:   # 항목에 scheme(포트)까지 적었으면 그대로 비교
                if ent == "%s://%s" % (scheme, netloc): return False
            elif scheme == "https" and host == ent and port in (None, 443):   # 호스트만 적은 항목 = https 기본 포트만
                return False
        return True

    def _bad_fetch_site(self):
        sfs = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if not sfs: return False
        if sfs == "cross-site": return True
        return (not PUBLIC) and sfs not in ("same-origin", "none")

    def do_POST(self):
        if self._bad_host():
            return self._send(421, "misdirected request", "text/plain")
        u = urllib.parse.urlparse(self.path)
        if self._bad_origin():
            return self._send(403, json.dumps({"ok": False, "err": "cross-origin 거부"}))
        _cl = (self.headers.get("Content-Length") or "0").strip()
        ln = int(_cl) if re.fullmatch(r"[0-9]{1,15}", _cl) else -1   # 숫자만(부호·공백·16진 등 거부)
        if ln < 0:                                   # 비정상 길이(음수/비숫자): 예전엔 read(-1)=EOF까지 대기·ValueError 크래시
            return self._send(400, json.dumps({"ok": False, "err": "bad length"}))
        if ln > MAX_BODY:                            # 본문 상한(WP_MAX_BODY, 기본 64MB)
            return self._send(413, json.dumps({"ok": False, "err": "too large"}))
        raw = self.rfile.read(ln) if ln else b""
        # ── 공개(무상태) 변환 엔드포인트: 디스크 저장 없이 바이트를 그대로 응답(다운로드) ──
        if u.path == "/api/convert/import":      # 업로드된 .hwpx/.hwp 바이트 → HTML(json)
            if not _CONV_SEM.acquire(blocking=False): return self._busy()
            try:
                if _CONV_DELAY: time.sleep(_CONV_DELAY)
                ok, out, err = conv("import", raw)
            finally: _CONV_SEM.release()
            if not ok: return self._fail_conv(err)
            return self._send(200, json.dumps({"ok": True, "html": out.decode("utf-8", "replace")}, ensure_ascii=False))
        if u.path in ("/api/convert/hwpx", "/api/convert/docx", "/api/convert/pdf"):   # 현재 HTML → 파일 바이트(첨부 다운로드)
            try: d = json.loads(raw.decode("utf-8") or "{}")
            except Exception: d = {}
            if not isinstance(d, dict): d = {}         # 배열/숫자 JSON → .get AttributeError 크래시 방지
            html = d.get("html", "") or ""
            html = (html if isinstance(html, str) else "").encode("utf-8", "replace")
            if not _CONV_SEM.acquire(blocking=False): return self._busy()
            try:
                if _CONV_DELAY: time.sleep(_CONV_DELAY)
                if u.path.endswith("hwpx"):
                    _PAGE.page = d.get("page") if isinstance(d.get("page"), dict) else None
                    try: ok, out, err = conv("export", html)
                    finally: _PAGE.page = None
                    ct = "application/octet-stream"
                elif u.path.endswith("docx"):   # MS Word(.docx) — 용지(page: mm)는 클라 paperInfo
                    _PAGE.page = d.get("page") if isinstance(d.get("page"), dict) else None
                    try: ok, out, err = conv("export-docx", html)
                    finally: _PAGE.page = None
                    ct = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                elif d.get("pages"):   # 방식 A: 클라 래스터 캡처(PNG dataURL) → 이미지 조립(화면 그대로)
                    ok, out, err = pages_to_pdf(d.get("pages")); ct = "application/pdf"
                else:
                    ok, out, err = to_pdf(html); ct = "application/pdf"
            finally: _CONV_SEM.release()
            if not ok: return self._fail_conv(err)
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(out)))
            self.send_header("Cache-Control", "no-store")
            self._sec_headers()
            self.end_headers()
            try: self.wfile.write(out)
            except BrokenPipeError: pass
            return
        if u.path == "/api/convert/text":    # 업로드 .txt 바이트 → 에디터 HTML(무상태, 공개 허용). CP949 등 인코딩 자동판별.
            if not _CONV_SEM.acquire(blocking=False): return self._busy()
            try:
                if _CONV_DELAY: time.sleep(_CONV_DELAY)
                out = text_to_html(read_txt_bytes(raw).split("\f"))   # 폼피드=쪽 나누기(우리 TXT 저장 표식)
            finally: _CONV_SEM.release()
            return self._send(200, json.dumps({"ok": True, "html": out}, ensure_ascii=False))
        if u.path == "/api/convert/pdf-import":   # 업로드 PDF 바이트 → 에디터 HTML(mode=image|text, 무상태, 공개 허용)
            mode = (urllib.parse.parse_qs(u.query).get("mode") or ["text"])[0]
            if not _CONV_SEM.acquire(blocking=False): return self._busy()
            tf, ok, err, out = None, False, "변환 오류", None
            try:
                if _CONV_DELAY: time.sleep(_CONV_DELAY)
                tf = tempfile.NamedTemporaryFile(prefix="wp-pdfin-", suffix=".pdf", delete=False)
                tf.write(raw); tf.close()
                if mode == "image":
                    ok, uris, err = pdf_render_pages(tf.name)
                    if ok: out = pdf_pages_html(uris)
                else:
                    ok, pages, err = pdf_text(tf.name)
                    if ok: out = text_to_html(pages)
            finally:
                _CONV_SEM.release()
                if tf:
                    try: os.remove(tf.name)
                    except OSError: pass
            if not ok:   # err는 사용자 안전 안내(스캔 PDF 등) — 마스킹 없이 그대로 전달(200 ok:false)
                return self._send(200, json.dumps({"ok": False, "err": err}, ensure_ascii=False))
            return self._send(200, json.dumps({"ok": True, "html": out}, ensure_ascii=False))
        if u.path.startswith("/api/board/") and not BOARD_ON:
            return self._send(404, json.dumps({"ok": False, "err": "게시판이 꺼져 있습니다(WP_BOARD_ENABLE=1)"}, ensure_ascii=False))
        if u.path.startswith("/api/board/"):   # 익명 게시판 작성/수정/삭제/댓글(공개·비공개 모두 허용, 무상태 아님=서버 파일 보존)
            try: d = json.loads(raw.decode("utf-8") or "{}")
            except Exception: d = {}
            if not isinstance(d, dict): d = {}         # 배열/숫자 JSON → .get AttributeError 크래시 방지
            d = {k: (v if v is None or isinstance(v, bool) else str(v).encode("utf-8", "replace").decode("utf-8")) for k, v in d.items()}   # 비문자열·서로게이트 정리   # 비문자열 값 → .strip 크래시 방지
            act = u.path[len("/api/board/"):]
            if act == "post":
                ok, res = board_add(d.get("title"), d.get("body"), d.get("tag"), d.get("nick"), d.get("password"), d.get("private"))
            elif act == "edit":
                ok, res = board_edit(d.get("id"), d.get("password"), d.get("title"), d.get("body"), d.get("tag"), d.get("private"))
            elif act == "delete":
                ok, res = board_delete(d.get("id"), d.get("password"), d.get("admin"))
            elif act == "comment":
                ok, res = comment_add(d.get("postId"), d.get("nick"), d.get("body"), d.get("password"))
            elif act == "comment-delete":
                ok, res = comment_delete(d.get("postId"), d.get("commentId"), d.get("password"), d.get("admin"))
            else:
                return self._send(404, json.dumps({"ok": False, "err": "not found"}))
            if not ok:
                return self._send(400, json.dumps({"ok": False, "err": res}, ensure_ascii=False))
            return self._send(200, json.dumps({"ok": True, "id": res}, ensure_ascii=False))
        if (PUBLIC or not PRN_BIN) and u.path in ("/api/print", "/api/print-cancel"):   # #28 공개판·인쇄 미설정: 명시적 403(스펙 §1c 게이트)
            return self._send(403, json.dumps({"ok": False, "err": "공개 서비스에서는 인쇄를 지원하지 않습니다" if PUBLIC else "인쇄 명령이 설정되지 않았습니다(PRN_BIN)"}, ensure_ascii=False))
        if (PUBLIC or not QUITNAG_BIN) and u.path == "/api/quit":     # #29 공개판·종료 명령 미설정: 명시적 403(클라는 종전 토스트 경로)
            return self._send(403, json.dumps({"ok": False, "err": "공개 서비스에서는 종료를 지원하지 않습니다" if PUBLIC else "종료 명령이 설정되지 않았습니다(QUITNAG_BIN)"}, ensure_ascii=False))
        if PUBLIC:   # 공개모드: 서버측 공유 저장/삭제/디스크변환 전면 차단(무상태 변환만 허용)
            return self._send(404, json.dumps({"ok": False, "err": "disabled in public mode"}))
        try: data = json.loads(raw.decode("utf-8") or "{}")
        except Exception: data = {}
        if not isinstance(data, dict): data = {}
        if u.path == "/api/save":
            name = safe_name(data.get("name"))
            html = data.get("html", "")
            if not isinstance(html, str):
                return self._send(400, json.dumps({"ok": False, "err": "html must be a string"}))
            try:
                atomic_write(docpath(name), html.encode("utf-8", "replace"))   # 실패해도 기존 문서 보존
                return self._send(200, json.dumps({"ok": True, "name": name}, ensure_ascii=False))
            except (OSError, ValueError) as e:
                return self._send(500, json.dumps({"ok": False, "err": str(e)}))
        if u.path == "/api/hist/save":    # 히스토리 암호화 저장(PBKDF2 20만회→Fernet). 파일=WPH1+salt16+token
            name = safe_name(data.get("name") or ""); pw = data.get("pw") or ""
            if not name or not pw:
                return self._send(200, json.dumps({"ok": False, "err": "이름/암호 필요"}, ensure_ascii=False))
            try:
                payload = json.dumps(data.get("data"), ensure_ascii=False).encode()
                if len(payload) > 8*1024*1024:
                    return self._send(200, json.dumps({"ok": False, "err": "히스토리가 8MB를 넘어 보존 생략"}, ensure_ascii=False))
                import hashlib, base64 as _b64
                from cryptography.fernet import Fernet
                salt = os.urandom(16)
                key = _b64.urlsafe_b64encode(hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200000, dklen=32))
                tok = Fernet(key).encrypt(payload)
                hd = os.path.join(DOCS, ".hist"); os.makedirs(hd, exist_ok=True)
                fin = os.path.join(hd, name + ".hist"); bak = fin + ".bak"
                if os.path.isfile(fin):   # 한 세대 보관 — 암호 분실 상태로 덮어써도 직전 역사 회수 여지(새 파일 쓰기 전 보관, 원본은 그대로)
                    try: os.unlink(bak)
                    except FileNotFoundError: pass
                    try: os.link(fin, bak)
                    except OSError: shutil.copy2(fin, bak)
                atomic_write(fin, b"WPH1" + salt + tok)
                return self._send(200, json.dumps({"ok": True}))
            except Exception as e:
                return self._send(200, json.dumps({"ok": False, "err": str(e)}, ensure_ascii=False))
        if u.path == "/api/hist/load":    # 히스토리 복호(암호 불일치=거부)
            name = safe_name(data.get("name") or ""); pw = data.get("pw") or ""
            fp = os.path.join(DOCS, ".hist", name + ".hist")
            if not os.path.isfile(fp):
                return self._send(200, json.dumps({"ok": False, "err": "역사 파일 없음"}, ensure_ascii=False))
            try:
                with open(fp, "rb") as f: raw = f.read()
                if raw[:4] != b"WPH1":
                    return self._send(200, json.dumps({"ok": False, "err": "형식 오류"}, ensure_ascii=False))
                import hashlib, base64 as _b64
                from cryptography.fernet import Fernet, InvalidToken
                key = _b64.urlsafe_b64encode(hashlib.pbkdf2_hmac("sha256", pw.encode(), raw[4:20], 200000, dklen=32))
                try:
                    payload = Fernet(key).decrypt(raw[20:])
                except InvalidToken:
                    return self._send(200, json.dumps({"ok": False, "err": "암호가 일치하지 않습니다"}, ensure_ascii=False))
                return self._send(200, json.dumps({"ok": True, "data": json.loads(payload.decode())}, ensure_ascii=False))
            except Exception as e:
                return self._send(200, json.dumps({"ok": False, "err": str(e)}, ensure_ascii=False))
        if u.path == "/api/delete":
            name = safe_name(data.get("name"))
            try: os.remove(docpath(name))
            except (OSError, ValueError): pass
            return self._send(200, json.dumps({"ok": True}))
        if u.path == "/api/rename":
            old = safe_name(data.get("old")); new = safe_name(data.get("new"))
            try:
                po, pn = docpath(old), docpath(new)
                if os.path.exists(po) and po != pn:
                    if not rename_noclobber(po, pn):
                        return self._send(200, json.dumps({"ok": False, "err": "같은 이름이 이미 있습니다"}, ensure_ascii=False))
                return self._send(200, json.dumps({"ok": True, "name": new}, ensure_ascii=False))
            except (OSError, ValueError) as e:
                return self._send(500, json.dumps({"ok": False, "err": str(e)}))
        if u.path == "/api/media/rename":   # 미디어 파일 이름변경(파일핸들 편집, 2026-07-19). 문서/media 안에서만
            old = data.get("old") or ""; new = data.get("new") or ""
            if _bad_leaf(old) or _bad_leaf(new):   # 경로 구분자(/ \\)·드라이브(:)·..·숨김 이름 거부(basename 으로 고쳐 쓰지 않음)
                return self._send(200, json.dumps({"ok": False, "err": "이름이 올바르지 않습니다"}, ensure_ascii=False))
            oe = old.rsplit(".", 1)[-1].lower() if "." in old else ""
            if "." not in new: new = new + "." + oe          # 확장자 생략=원본 확장자 유지
            if new.rsplit(".", 1)[-1].lower() not in MED_EXT:
                return self._send(200, json.dumps({"ok": False, "err": "지원 형식이 아닙니다"}, ensure_ascii=False))
            srcp = _leaf_path(MEDIA, old); dstp = _leaf_path(MEDIA, new)
            if not dstp:
                return self._send(200, json.dumps({"ok": False, "err": "이름이 올바르지 않습니다"}, ensure_ascii=False))
            try:
                if not srcp or not os.path.isfile(srcp):
                    return self._send(200, json.dumps({"ok": False, "err": "원본 파일이 없습니다"}, ensure_ascii=False))
                if (os.path.lexists(dstp) and not _case_only(srcp, dstp)) or not rename_noclobber(srcp, dstp):
                    return self._send(200, json.dumps({"ok": False, "err": "같은 이름이 이미 있습니다"}, ensure_ascii=False))
                return self._send(200, json.dumps({"ok": True, "name": new}, ensure_ascii=False))
            except OSError as e:
                return self._send(500, json.dumps({"ok": False, "err": str(e)}))
        if u.path == "/api/export/hwpx":     # 현재 문서(HTML) → .hwpx
            name = safe_name(data.get("name")); html = data.get("html", "")
            if not isinstance(html, str): return self._send(400, json.dumps({"ok": False, "err": "html must be a string"}))
            if not _CONV_SEM.acquire(blocking=False): return self._busy()
            try: ok, out, err = conv("export", html.encode("utf-8", "replace"))
            finally: _CONV_SEM.release()
            if not ok: return self._fail_conv(err)
            try:
                atomic_write(docpath(name, ".hwpx"), out)
                return self._send(200, json.dumps({"ok": True, "file": name + ".hwpx", "size": len(out)}, ensure_ascii=False))
            except (OSError, ValueError) as e:
                return self._send(500, json.dumps({"ok": False, "err": str(e)}))
        if u.path == "/api/export/pdf" and data.get("pages"):   # #28 로컬 래스터(클라 캡처 PNG 배열)→magick 조립→documents/print/
            name = safe_name(data.get("name"))
            if not _CONV_SEM.acquire(blocking=False): return self._busy()
            try: ok, pdf, err = pages_to_pdf(data.get("pages"))
            finally: _CONV_SEM.release()
            if not ok: return self._fail_conv(err)
            try:
                fn, fp = save_print_pdf(name, pdf)
                return self._send(200, json.dumps({"ok": True, "file": fn, "path": "print/" + fn, "size": len(pdf)}, ensure_ascii=False))
            except OSError as e:
                return self._send(500, json.dumps({"ok": False, "err": str(e)}))
        if u.path == "/api/print":           # #28 인쇄(프린터): 래스터 PDF 조립 → print/ 저장 → prn 실행
            name = safe_name(data.get("name"))
            if not _CONV_SEM.acquire(blocking=False): return self._busy()
            try: ok, pdf, err = pages_to_pdf(data.get("pages"))
            finally: _CONV_SEM.release()
            if not ok: return self._fail_conv(err)
            try: fn, fp = save_print_pdf(name, pdf)
            except OSError as e:
                return self._send(500, json.dumps({"ok": False, "err": str(e)}))
            try:
                rc, last = run_prn([fp], 60)
                if rc == 0:
                    return self._send(200, json.dumps({"ok": True, "file": fn, "path": "print/" + fn, "msg": last}, ensure_ascii=False))
                err = "프린터 미등록(prn 설정 필요)" if rc == 2 else (last or ("인쇄 실패(rc=%d)" % rc))
            except FileNotFoundError:
                err = "인쇄 명령(prn) 없음"
            except subprocess.TimeoutExpired:
                err = "인쇄 응답 시간 초과"
            # 실패해도 PDF는 print/에 남김(파일매니저에서 재인쇄 가능) — path 동봉
            return self._send(200, json.dumps({"ok": False, "err": err, "file": fn, "path": "print/" + fn}, ensure_ascii=False))
        if u.path == "/api/quit":            # #29 끝 메뉴 실제화: `wp-quitnag 0` = 조이패드 Home→닫기와 동일 저장확인창 종료
            try:                             # 확인창이 사용자 응답까지 떠 있으므로 대기 없이 발사(Popen) 후 즉시 응답
                subprocess.Popen([QUITNAG_BIN, "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return self._send(200, json.dumps({"ok": True, "msg": "종료 확인창 호출"}, ensure_ascii=False))
            except (FileNotFoundError, PermissionError):
                return self._send(200, json.dumps({"ok": False, "err": "종료 명령(wp-quitnag) 없음"}, ensure_ascii=False))
        if u.path == "/api/print-cancel":    # #28 인쇄 취소: prn -x (다른 앱들과 동일 규약)
            try:
                rc, last = run_prn(["-x"], 30)
                if rc == 0:
                    return self._send(200, json.dumps({"ok": True, "msg": last}, ensure_ascii=False))
                return self._send(200, json.dumps({"ok": False, "err": last or ("취소 실패(rc=%d)" % rc)}, ensure_ascii=False))
            except FileNotFoundError:
                return self._send(200, json.dumps({"ok": False, "err": "인쇄 명령(prn) 없음"}, ensure_ascii=False))
            except subprocess.TimeoutExpired:
                return self._send(200, json.dumps({"ok": False, "err": "취소 응답 시간 초과"}, ensure_ascii=False))
        if u.path == "/api/export/pdf":      # 벡터 경로(HTML→Chromium) — node/Playwright 가용 환경용
            name = safe_name(data.get("name")); html = data.get("html", "")
            if not isinstance(html, str): return self._send(400, json.dumps({"ok": False, "err": "html must be a string"}))
            if not _CONV_SEM.acquire(blocking=False): return self._busy()
            try: ok, out, err = to_pdf(html.encode("utf-8", "replace"))
            finally: _CONV_SEM.release()
            if not ok: return self._fail_conv(err)
            try:
                atomic_write(docpath(name, ".pdf"), out)
                return self._send(200, json.dumps({"ok": True, "file": name + ".pdf", "size": len(out)}, ensure_ascii=False))
            except (OSError, ValueError) as e:
                return self._send(500, json.dumps({"ok": False, "err": str(e)}))
        if u.path == "/api/import/hwpx":     # 문서 폴더의 .hwpx/.hwp/.docx 파일 → HTML
            fn = posixpath.basename((data.get("name") or "").replace("\\", "/"))   # 경로조작 차단(basename만)
            fp = os.path.join(DOCS, fn)
            try: inside = os.path.commonpath([os.path.realpath(fp), DOCS]) == DOCS
            except Exception: inside = False
            if not (fn.lower().endswith((".hwpx", ".hwp", ".docx", ".doc")) and inside and os.path.isfile(fp)):
                return self._send(404, json.dumps({"ok": False, "err": "파일 없음"}, ensure_ascii=False))
            with open(fp, "rb") as f: raw = f.read()
            if not _CONV_SEM.acquire(blocking=False): return self._busy()
            try: ok, out, err = conv("import", raw)   # 매직바이트로 hwpxconv가 hwpx/hwp 분기
            finally: _CONV_SEM.release()
            if not ok: return self._fail_conv(err)
            base = re.sub(r"\.(hwpx|hwp|docx|doc)$", "", fn, flags=re.I)
            return self._send(200, json.dumps({"ok": True, "name": base, "html": out.decode("utf-8", "replace")}, ensure_ascii=False))
        if DEBUG and u.path == "/api/debug/state":       # 페이지 상태 하트비트
            with _dlock: _state.clear(); _state.update(data if isinstance(data, dict) else {})
            return self._send(200, json.dumps({"ok": True}))
        if DEBUG and u.path == "/api/debug/log":         # 페이지 콘솔/에러 수집
            line = "%s %s %s\n" % (time.strftime("%H:%M:%S"), data.get("level", "log"),
                                   str(data.get("msg", ""))[:2000])
            try:
                with open(DBGLOG, "a", encoding="utf-8") as f: f.write(line)
            except OSError: pass
            return self._send(200, json.dumps({"ok": True}))
        if DEBUG and u.path == "/api/debug/cmd":         # 테스터가 명령 적재 → id 반환
            cid = next(_ids); cmd = dict(data); cmd["id"] = cid
            with _dlock: _cmdq.append(cmd)
            return self._send(200, json.dumps({"id": cid}))
        if DEBUG and u.path == "/api/debug/result":      # 페이지가 결과 반환
            cid = data.get("id")
            try: cid = int(cid) if cid is not None else None
            except (TypeError, ValueError): cid = None
            with _dlock:
                if cid is not None: _results[cid] = data.get("result")
            return self._send(200, json.dumps({"ok": True}))
        return self._send(404, "not found", "text/plain")

def _prewarm():
    try: _get_hx()   # lxml+hwpx 사전 로드 → 첫 HWPX 변환도 즉시(콜드 2.3s 제거)
    except Exception: pass

def _is_loopback(h):
    if h == "localhost": return True
    try: return ipaddress.ip_address(h).is_loopback
    except ValueError: return False

def serve(host=None, port=None):
    """서버 실행. 로컬(저장 가능) 모드는 인증이 없으므로 비루프백 바인딩은 WP_PUBLIC=1 또는 WP_ALLOW_REMOTE=1 일 때만."""
    host = host or HOST; port = int(port or PORT)
    if host.startswith("[") and host.endswith("]"): host = host[1:-1]
    if not _is_loopback(host) and not (PUBLIC or ALLOW_REMOTE):
        sys.stderr.write("hanword: refusing to listen on %s — the local (save/load) mode has no login.\n"
                         "  Use 127.0.0.1, or set WP_PUBLIC=1 (stateless converter) or WP_ALLOW_REMOTE=1 (trusted LAN only).\n" % host)
        sys.exit(2)
    _HOST_OK.add(host.lower())
    threading.Thread(target=_prewarm, daemon=True).start()
    cls = ThreadingHTTPServer
    if ":" in host:
        import socket
        class _S6(ThreadingHTTPServer): address_family = socket.AF_INET6
        cls = _S6
    httpd = cls((host, port), H)
    shown = "[%s]" % host if ":" in host else host
    print(f"hanword {_hw_version()} on http://{shown}:{port}/  docs={DOCS}  public={PUBLIC} debug={DEBUG}", flush=True)
    try: httpd.serve_forever()
    except KeyboardInterrupt: pass
    finally: httpd.server_close()

if __name__ == "__main__":
    serve()

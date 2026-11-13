"""Single entry point for the packaged hanword program (PyInstaller binary and .pyz).

    hanword serve [--host H] [--port P] [--data DIR]   run the web editor (default http://127.0.0.1:8088/)
    hanword --version                                  print the version
    hanword [--json] <formats|convert|info|check|roundtrip|model|render|apply|debug> ...
                                                       the document CLI (same as the `hanword` script)

Run with no arguments it prints a short hint, and on Windows waits for Enter so a
double-clicked console window does not vanish at once.

The application directory (static files, fonts, hwpx_skeleton.hwpx, the `hanword` CLI script)
is sys._MEIPASS when frozen, HANWORD_APPDIR when set (the .pyz sets it to its extraction dir),
otherwise the repository root (so `python packaging/entry.py serve` works from a checkout).
"""
import os
import sys

CLI_COMMANDS = ("formats", "convert", "info", "check", "roundtrip", "model", "render", "apply", "debug")

HINT = """hanword (한워드 - 브라우저 문서 편집기 / web word processor)

  hanword serve                       편집기 서버 실행 / run the editor server (http://127.0.0.1:8088/)
  hanword serve --port 8090 --data DIR    다른 포트·문서 폴더 / other port, documents folder
  hanword convert IN OUT              문서 변환 / convert a document (hwpx, docx, html, txt, pdf ...)
  hanword formats | info | check | roundtrip | model | render | apply
  hanword --version | --help

서비스로 설치했다면 브라우저에서 http://127.0.0.1:8088/ 을 여세요.
If you installed the service, open http://127.0.0.1:8088/ in a browser.
"""


def app_dir() -> str:
    d = getattr(sys, "_MEIPASS", None) or os.environ.get("HANWORD_APPDIR")
    if not d:
        d = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.abspath(d)


def _setup_path() -> str:
    d = app_dir()
    if d not in sys.path:
        sys.path.insert(0, d)
    return d


def version() -> str:
    _setup_path()
    try:
        import hanword_version
        return hanword_version.__version__
    except Exception:
        return "0"


def _serve(argv) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="hanword serve",
                                description="Run the hanword editor server (local mode: this machine only).")
    p.add_argument("--host", help="bind address (default 127.0.0.1, env WP_HOST)")
    p.add_argument("--port", type=int, help="port (default 8088, env WP_PORT)")
    p.add_argument("--data", help="documents folder (env WP_DOCS, default ~/hanword-documents)")
    a = p.parse_args(argv)
    # server.py reads its settings from the environment at import time: set them first.
    for k, v in (("WP_HOST", a.host), ("WP_PORT", a.port), ("WP_DOCS", a.data)):
        if v is not None:
            os.environ[k] = str(v)
    _setup_path()
    import server
    server.serve()
    return 0


def _cli(argv) -> int:
    import runpy
    script = os.path.join(_setup_path(), "hanword")
    if not os.path.isfile(script):
        sys.stderr.write("hanword: CLI script not found: %s\n" % script)
        return 2
    old = sys.argv
    sys.argv = [script] + list(argv)
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as e:
        code = e.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        sys.stderr.write("%s\n" % code)
        return 1
    finally:
        sys.argv = old
    return 0


def _stdio_safe() -> None:
    """Windows consoles (cp1252, ...) cannot encode '→' or Hangul: replace instead of crashing."""
    for s in (sys.stdout, sys.stderr):
        enc = (getattr(s, "encoding", None) or "").lower().replace("-", "").replace("_", "")
        if enc not in ("utf8", "utf8sig") and hasattr(s, "reconfigure"):
            try:
                s.reconfigure(errors="replace")
            except Exception:
                pass


def run(argv=None) -> int:
    _stdio_safe()
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv:
        print(HINT)
        if os.name == "nt" and sys.stdin is not None and sys.stdin.isatty():
            try:
                input("Enter 키를 누르면 닫힙니다 / press Enter to close...")
            except EOFError:
                pass
        return 0
    if argv[0] in ("--version", "-V", "version"):
        print("hanword " + version())
        return 0
    if argv[0] == "serve":
        return _serve(argv[1:])
    if argv[0] == "selfcheck-imports":   # smoke test: every runtime module is in the bundle
        import importlib
        _setup_path()
        bad = []
        for m in argv[1:]:
            try:
                importlib.import_module(m)
            except Exception as e:
                bad.append("%s: %s: %s" % (m, type(e).__name__, e))
        print("imports OK %d" % (len(argv) - 1 - len(bad)))
        for b in bad:
            print("MISSING " + b)
        return 1 if bad else 0
    if argv[0] in ("-h", "--help", "help"):
        print(HINT)
        return _cli(["--help"])
    return _cli(argv)   # formats/convert/... and global options such as --json


if __name__ == "__main__":
    sys.exit(run())

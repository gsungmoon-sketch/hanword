#!/usr/bin/env python3
"""Build hanword-<version>.pyz: one file for machines that already have Python 3.10+.

    python scripts/build_zipapp.py [--version X.Y.Z] [--out dist]
    python3 dist/hanword-<ver>.pyz serve            # run it (Windows: py hanword-<ver>.pyz serve)
    python3 dist/hanword-<ver>.pyz convert a.docx a.hwpx

Pure standard library, so the same file runs on Windows, macOS and Linux. The server reads its
web files (index.html, scripts, fonts, hwpx_skeleton.hwpx) from disk, so on first run the .pyz
unpacks its payload to a per-version cache directory and runs from there:
    Linux   $XDG_CACHE_HOME/hanword/<ver>-<hash>   (default ~/.cache/hanword/...)
    macOS   ~/Library/Caches/hanword/<ver>-<hash>
    Windows %LOCALAPPDATA%\\hanword\\Cache\\<ver>-<hash>
HANWORD_CACHE=<dir> overrides the base directory. Old versions can simply be deleted.
"""
import argparse
import hashlib
import re
import shutil
import sys
import tempfile
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "hanword"
sys.path.insert(0, str(ROOT / "packaging"))
import manifest  # noqa: E402  single source of the runtime modules (also packaging/build.py)
MODULES = [m + ".py" for m in manifest.modules(ROOT)] + [manifest.CLI_SCRIPT]
STATIC_GLOBS = ["*.html", "*.css", "*.js", "hwpx_skeleton.hwpx", "NOTICE-*.txt", "LICENSE"]
DIRS = ["font", "licenses"]

MAIN = r'''# hanword .pyz launcher: unpack the payload once per version, then run from disk.
import os, sys, zipfile
if sys.version_info < (3, 10):
    sys.exit("hanword needs Python 3.10 or newer (found %d.%d)" % sys.version_info[:2])
VERSION = @VERSION@
DIGEST = @DIGEST@
PREFIX = "payload/"


def cache_base():
    env = os.environ.get("HANWORD_CACHE")
    if env:
        return env
    home = os.path.expanduser("~")
    if os.name == "nt":
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local"), "hanword", "Cache")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Caches", "hanword")
    return os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache"), "hanword")


def unpack():
    target = os.path.join(cache_base(), "%s-%s" % (VERSION, DIGEST[:12]))
    marker = os.path.join(target, ".complete")
    if os.path.isfile(marker):
        return target
    os.makedirs(os.path.dirname(target), exist_ok=True)
    archive = os.path.dirname(os.path.abspath(__file__))
    tmp = "%s.tmp-%d" % (target, os.getpid())
    shutil_rm(tmp)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if not info.filename.startswith(PREFIX) or info.is_dir():
                continue
            rel = info.filename[len(PREFIX):]
            if not rel or rel.startswith("/") or ".." in rel.split("/"):
                continue
            dest = os.path.join(tmp, *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                out.write(src.read())
    open(os.path.join(tmp, ".complete"), "w").close()
    try:
        os.rename(tmp, target)
    except OSError:          # another process won the race, or a stale incomplete dir is in the way
        if not os.path.isfile(marker):
            shutil_rm(target)
            os.rename(tmp, target)
        else:
            shutil_rm(tmp)
    return target


def shutil_rm(p):
    import shutil
    shutil.rmtree(p, ignore_errors=True)


app = unpack()
os.environ["HANWORD_APPDIR"] = app
sys.path.insert(0, app)
import hanword_entry
sys.exit(hanword_entry.run())
'''


def payload_files() -> list:
    files = []
    for m in MODULES:
        p = ROOT / m
        if not p.is_file():
            sys.exit(f"missing {m}")
        files.append((m, p))
    seen = {m for m, _ in files}
    for g in STATIC_GLOBS:
        for p in sorted(ROOT.glob(g)):
            if p.is_file() and p.name not in seen:
                seen.add(p.name)
                files.append((p.name, p))
    for d in DIRS:
        base = ROOT / d
        if base.is_dir():
            for p in sorted(base.rglob("*")):
                if p.is_file() and "__pycache__" not in p.parts:
                    files.append((p.relative_to(ROOT).as_posix(), p))
    files.append(("hanword_entry.py", ROOT / "packaging" / "entry.py"))
    if (ROOT / "packaging" / "THIRD-PARTY-NOTICES.txt").is_file():
        files.append(("THIRD-PARTY-NOTICES.txt", ROOT / "packaging" / "THIRD-PARTY-NOTICES.txt"))
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", help="version in the file name (default: hanword_version.py)")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    a = ap.parse_args()
    ver = a.version
    if not ver:
        m = re.search(r'__version__\s*=\s*["\']([^"\']+)', (ROOT / "hanword_version.py").read_text(encoding="utf-8"))
        ver = m.group(1)
    ver = ver.lstrip("v")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{NAME}-{ver}.pyz"
    files = payload_files()
    h = hashlib.sha256()
    for rel, p in files:
        h.update(rel.encode() + b"\0" + p.read_bytes() + b"\0")
    digest = h.hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "app"
        for rel, p in files:
            dst = stage / "payload" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
        (stage / "__main__.py").write_text(MAIN.replace("@VERSION@", repr(ver)).replace("@DIGEST@", repr(digest)),
                                           encoding="utf-8")
        zipapp.create_archive(stage, target, interpreter="/usr/bin/env python3", compressed=True)
    print(f"built {target} ({target.stat().st_size:,} bytes, {len(files)} payload files, payload {digest[:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

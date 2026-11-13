#!/usr/bin/env python3
"""Build the hanword one-file binary (PyInstaller) and, on Linux, the install tarball.

Usage (from the root of the public tree, in a venv with `pip install pyinstaller==6.22.3`):
    python packaging/build.py                  # -> dist/hanword/  (binary + LICENSE + notices + VERSION)
    python packaging/build.py --tarball        # Linux: also dist/hanword-<ver>-linux-<arch>.tar.gz
    python packaging/build.py --version 1.2.3  # override (CI passes the tag without the leading 'v')
    python packaging/build.py --strict         # fail if a licence file / the manual is missing (CI)

The binary is PyInstaller one-file: everything (Python, the modules, static web files, fonts,
hwpx_skeleton.hwpx and the `hanword` CLI script) is in one executable that unpacks to a temp
directory at start; server.py serves its static files from there (APP = dirname(__file__)).
dist/hanword/ holds that executable next to the licence files; the installers copy the folder.
"""
import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packaging"
NAME = "hanword"
EXE = NAME + (".exe" if os.name == "nt" else "")

# Python modules of the flat layout (bundled explicitly: the CLI script is run via runpy, so
# PyInstaller cannot see its imports, and some converters import lazily). Single source: manifest.py.
sys.path.insert(0, str(PKG))
import manifest  # noqa: E402
MODULES = manifest.modules(ROOT)
# Static files served by server.py / read by the converters (relative to ROOT).
STATIC_GLOBS = ["*.html", "*.css", "*.js", "hwpx_skeleton.hwpx", "NOTICE-*.txt"]
LICENCE_FILES = ["LICENSE", "NOTICE-hwpx_skeleton.txt"]


def version_from_source() -> str:
    text = (ROOT / "hanword_version.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not m:
        sys.exit("cannot find __version__ in hanword_version.py")
    return m.group(1)


def arch_tag() -> str:
    m = platform.machine().lower()
    return {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(m, m)


def os_tag() -> str:
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def data_args() -> list:
    sep = os.pathsep  # PyInstaller --add-data SRC{os.pathsep}DEST
    args, seen = [], set()
    for g in STATIC_GLOBS:
        for f in sorted(ROOT.glob(g)):
            if f.is_file() and f.name not in seen:
                seen.add(f.name)
                args += ["--add-data", f"{f}{sep}."]
    for f in (ROOT / "hanword", ROOT / "LICENSE"):
        if f.is_file():
            args += ["--add-data", f"{f}{sep}."]
    for d in ("font", "licenses"):
        if (ROOT / d).is_dir():
            args += ["--add-data", f"{ROOT / d}{sep}{d}"]
    if not (ROOT / "font").is_dir():
        sys.exit("font/ directory missing")
    return args


def run_pyinstaller(work: Path) -> Path:
    out = work / "dist"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console",
           "--name", NAME, "--paths", str(ROOT),
           "--exclude-module", "tkinter", "--exclude-module", "_tkinter"]
    for m in MODULES:
        cmd += ["--hidden-import", m]
    cmd += data_args()
    cmd += ["--distpath", str(out), "--workpath", str(work / "work"), "--specpath", str(work),
            str(PKG / "entry.py")]
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)
    return out / EXE


def assemble(binary: Path, app: Path, version: str, strict: bool) -> None:
    shutil.rmtree(app, ignore_errors=True)
    app.mkdir(parents=True)
    shutil.copy2(binary, app / EXE)
    missing = []
    for f in LICENCE_FILES:
        src = ROOT / f
        if src.is_file():
            shutil.copy2(src, app / (f + ".txt" if f == "LICENSE" else f))
        else:
            missing.append(f)
    shutil.copy2(PKG / "THIRD-PARTY-NOTICES.txt", app / "THIRD-PARTY-NOTICES.txt")
    if (ROOT / "licenses").is_dir():
        shutil.copytree(ROOT / "licenses", app / "licenses")
    else:
        missing.append("licenses/")
    (app / "VERSION").write_text(version + "\n", encoding="utf-8")
    man = ROOT / "docs" / "manual"
    if man.is_dir():
        shutil.copytree(man, app / "manual")
    for m in missing:
        msg = f"{m} not found - package has no copy of it"
        if strict:
            sys.exit("error: " + msg)
        print("warning: " + msg, file=sys.stderr)


def self_check(exe: Path, version: str) -> None:
    r = subprocess.run([str(exe), "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or version.split("-")[0] not in r.stdout:
        # the binary reports hanword_version.__version__ (tags like 1.2.3-rc1 keep 1.2.3 there)
        sys.exit(f"built binary failed `--version` (rc={r.returncode}): {r.stdout} {r.stderr}")
    r = subprocess.run([str(exe), "--json", "formats"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0:
        sys.exit(f"built binary failed `--json formats` (rc={r.returncode}):\n{r.stdout}\n{r.stderr}")
    print(f"self-check ok: {r.stdout.strip()[:120]}")


def make_tarball(app: Path, version: str, out: Path) -> Path:
    base = f"{NAME}-{version}-linux-{arch_tag()}"
    tgz = out / f"{base}.tar.gz"
    lin = PKG / "linux"

    def norm(ti: tarfile.TarInfo) -> tarfile.TarInfo:
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = "root"
        return ti

    with tarfile.open(tgz, "w:gz") as tf:
        tf.add(app, arcname=f"{base}/{NAME}", filter=norm)
        for f in ("install.sh", "uninstall.sh", "hanword.service.in", "README.txt"):
            ti = norm(tf.gettarinfo(str(lin / f), arcname=f"{base}/{f}"))
            ti.mode = 0o755 if f.endswith(".sh") else 0o644
            with open(lin / f, "rb") as fh:
                tf.addfile(ti, fh)
    return tgz


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", default=None, help="package version (default: hanword_version.py)")
    ap.add_argument("--out", default=str(ROOT / "dist"), help="output directory (default: dist/)")
    ap.add_argument("--tarball", action="store_true", help="Linux: also build the install tarball")
    ap.add_argument("--strict", action="store_true", help="fail if LICENSE / licenses/ / notices are missing")
    a = ap.parse_args()
    version = (a.version or version_from_source()).lstrip("v")
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "build" / "pyinstaller"
    binary = run_pyinstaller(work)
    app = out / NAME
    assemble(binary, app, version, a.strict)
    self_check(app / EXE, version)
    print(f"built {app / EXE} ({os_tag()}-{arch_tag()}, version {version})")
    if a.tarball:
        if os_tag() != "linux":
            sys.exit("--tarball is for Linux only")
        print("tarball:", make_tarball(app, version, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

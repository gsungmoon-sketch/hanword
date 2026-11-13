#!/usr/bin/env python3
"""Smoke test for built hanword packages (used by the release workflow).

    python packaging/smoke_test.py linux   dist/hanword-0.1.0-linux-x64.tar.gz
    python packaging/smoke_test.py macos   dist/hanword-0.1.0-macos-arm64.pkg
    python packaging/smoke_test.py windows dist/hanword-0.1.0-windows-x64-setup.exe
    python packaging/smoke_test.py pyz     dist/hanword-0.1.0.pyz        # runs it with this Python
    python packaging/smoke_test.py binary  dist/hanword/hanword           # the bare PyInstaller binary
    python packaging/smoke_test.py http    --port 8088                    # HTTP checks only, running server

linux/macos/windows REALLY install a system service (needs admin/sudo) - meant for throw-away CI
runners. Steps: install silently -> GET /healthz == 200 -> service runs as its unprivileged account
-> static files (/, a script, a font) are served -> POST /api/save + GET /api/load round trip ->
POST /api/convert/hwpx then /api/convert/import round trip -> CLI `hanword convert` + `info` on a
sample -> uninstall silently -> port closed, service and program gone, data directory kept.
pyz/binary run `serve` on a free port with a temp documents folder instead of installing.
"""
import argparse
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

HOST = "127.0.0.1"
MARK = "hanword-smoke 한글 문단 ✓"
SAMPLE = ("<p>%s</p><p><b>굵게</b> 그리고 <i>기울임</i></p>"
          "<table><tr><td>가</td><td>나</td></tr><tr><td>1</td><td>2</td></tr></table>") % MARK


def log(msg):
    print(f"[smoke] {msg}", flush=True)


def sh(cmd, check=True, **kw):
    log("$ " + " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], text=True, encoding="utf-8", errors="replace",
                       capture_output=True, **kw)
    if r.stdout.strip():
        print(r.stdout.rstrip()[-3000:], flush=True)
    if r.stderr.strip():
        print(r.stderr.rstrip()[-3000:], file=sys.stderr, flush=True)
    if check and r.returncode != 0:
        raise SystemExit(f"command failed (rc={r.returncode})")
    return r


def request(port, method, path, body=None, headers=None, timeout=30):
    c = http.client.HTTPConnection(HOST, port, timeout=timeout)
    try:
        h = {"Host": f"127.0.0.1:{port}"}
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
    finally:
        c.close()


def post_json(port, path, obj):
    return request(port, "POST", path, body=json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   headers={"Content-Type": "application/json"})


def free_port():
    s = socket.socket()
    s.bind((HOST, 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_health(port, timeout=120, proc=None):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        if proc is not None and proc.poll() is not None:
            raise SystemExit(f"server exited early (rc={proc.returncode})")
        try:
            st, _, body = request(port, "GET", "/healthz", timeout=5)
            if st == 200:
                info = json.loads(body.decode("utf-8"))
                assert info.get("ok") is True and info.get("app") == "hanword", info
                assert info.get("public") is False, f"package must run in local mode: {info}"
                log(f"/healthz 200 {info} after {time.time() - t0:.1f}s")
                return info
            last = st
        except (OSError, ValueError) as e:
            last = e
        time.sleep(1)
    raise SystemExit(f"/healthz did not answer 200 within {timeout}s (last: {last})")


def wait_down(port, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            request(port, "GET", "/healthz", timeout=2)
        except OSError:
            log("port closed - server is down")
            return
        time.sleep(1)
    raise SystemExit("server still answers after uninstall/stop")


def check_http(port):
    """Static files + save/load + HWPX export/import over HTTP."""
    st, h, body = request(port, "GET", "/")
    assert st == 200 and b"<html" in body.lower()[:2000], f"GET / -> {st}"
    for path in ("/wp-core.js", "/editor.css", "/font/NotoSansKR-Regular.otf"):
        st, _, body = request(port, "GET", path)
        assert st == 200 and len(body) > 100, f"GET {path} -> {st} ({len(body)} bytes)"
    log("static files OK (/, wp-core.js, editor.css, font)")
    st, _, _ = request(port, "GET", "/healthz", headers={"Host": "evil.example"})
    assert st == 421, f"foreign Host header not refused: {st}"

    name = "smoke-%d" % os.getpid()
    st, _, body = post_json(port, "/api/save", {"name": name, "html": SAMPLE})
    r = json.loads(body.decode("utf-8"))
    assert st == 200 and r.get("ok"), f"/api/save -> {st} {r}"
    st, _, body = request(port, "GET", "/api/load?name=" + name)
    r = json.loads(body.decode("utf-8"))
    assert st == 200 and MARK in r.get("html", ""), f"/api/load -> {st} {str(r)[:200]}"
    log(f"save/load OK ({r.get('name')})")

    st, h, hwpx = post_json(port, "/api/convert/hwpx", {"html": SAMPLE})
    assert st == 200 and hwpx[:2] == b"PK", f"/api/convert/hwpx -> {st} {hwpx[:200]!r}"
    with zipfile.ZipFile(__import__("io").BytesIO(hwpx)) as z:
        assert "mimetype" in z.namelist(), "hwpx without mimetype"
    st, _, body = request(port, "POST", "/api/convert/import", body=hwpx,
                          headers={"Content-Type": "application/octet-stream"})
    r = json.loads(body.decode("utf-8"))
    assert st == 200 and r.get("ok") and MARK in r.get("html", ""), f"/api/convert/import -> {st} {str(r)[:300]}"
    st, _, docx = post_json(port, "/api/convert/docx", {"html": SAMPLE})
    assert st == 200 and docx[:2] == b"PK", f"/api/convert/docx -> {st}"
    log(f"convert OK (hwpx {len(hwpx)} bytes round trip, docx {len(docx)} bytes)")
    return name


def check_cli(cmd):
    """`hanword convert` + `info` + `--version` with the packaged program (cmd = argv prefix)."""
    tmp = Path(tempfile.mkdtemp(prefix="hw-cli-"))
    try:
        src = tmp / "sample.html"
        src.write_text("<!doctype html><html><body>%s</body></html>" % SAMPLE, encoding="utf-8")
        sh(cmd + ["--version"])
        sh(cmd + ["--json", "formats"])
        sh(cmd + ["convert", src, tmp / "sample.hwpx"])
        sh(cmd + ["convert", tmp / "sample.hwpx", tmp / "back.html"])
        back = (tmp / "back.html").read_text(encoding="utf-8")
        assert MARK in back, "CLI hwpx -> html lost the text"
        r = sh(cmd + ["--json", "info", tmp / "sample.hwpx"])
        assert json.loads(r.stdout.strip().splitlines()[-1]), "info returned nothing"
        log("CLI convert/info OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- per-OS install/uninstall

class Windows:
    name = "hanword"
    port = 8088

    def __init__(self, artifact):
        self.artifact = Path(artifact).resolve()
        self.app = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / self.name
        self.data = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / self.name
        self.cli = [self.app / "hanword.exe"]

    def install(self):
        sh([self.artifact, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
            f"/LOG={Path(tempfile.gettempdir()) / 'hanword-install.log'}"])

    def check_service(self):
        q = sh(["sc.exe", "query", self.name]).stdout
        assert "RUNNING" in q, "service not running"
        qc = sh(["sc.exe", "qc", self.name]).stdout
        assert "LocalService" in qc, "service does not run as NT AUTHORITY\\LocalService"

    def check_saved(self, doc):
        # the data dir is ACL-restricted to SYSTEM/Administrators/LOCAL SERVICE; the runner is admin
        assert (self.data / "documents" / (doc + ".html")).is_file(), "saved document not on disk"

    def uninstall(self):
        sh([self.app / "unins000.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
        # unins000.exe hands over to a temp copy and returns at once: wait for the real work
        t0 = time.time()
        while time.time() - t0 < 180:
            if sh(["sc.exe", "query", self.name], check=False).returncode != 0 \
                    and not (self.app / "hanword.exe").exists():
                break
            time.sleep(2)
        else:
            raise SystemExit("uninstall did not finish")

    def check_gone(self):
        assert sh(["sc.exe", "query", self.name], check=False).returncode != 0, "service still registered"
        assert not (self.app / "hanword.exe").exists(), "program files left"
        assert self.data.is_dir(), "data directory was deleted (should be kept)"


class MacOS:
    label = "com.hanword.server"
    lib = Path("/usr/local/hanword")
    data = Path("/Library/Application Support/hanword")
    port = 8088
    cli = ["/usr/local/bin/hanword"]

    def __init__(self, artifact):
        self.artifact = Path(artifact).resolve()

    def install(self):
        sh(["sudo", "installer", "-pkg", self.artifact, "-target", "/"])

    def check_service(self):
        out = sh(["sudo", "launchctl", "print", f"system/{self.label}"]).stdout
        assert "state = running" in out, "daemon not running"
        pid = next(ln.split("=")[1].strip() for ln in out.splitlines() if ln.strip().startswith("pid ="))
        uid = sh(["ps", "-o", "uid=", "-p", pid]).stdout.strip()
        assert uid == sh(["id", "-u", "_hanword"]).stdout.strip(), f"daemon runs as uid {uid}"
        mode = sh(["sudo", "stat", "-f", "%Sp %Su", str(self.data)]).stdout.strip()
        assert mode.startswith("drwx------") and mode.endswith("_hanword"), f"data dir perms: {mode}"

    def check_saved(self, doc):
        p = self.data / "documents" / (doc + ".html")
        assert sh(["sudo", "test", "-f", str(p)], check=False).returncode == 0, f"{p} missing"

    def uninstall(self):
        sh(["sudo", self.lib / "uninstall.sh"])

    def check_gone(self):
        assert sh(["sudo", "launchctl", "print", f"system/{self.label}"], check=False).returncode != 0, \
            "daemon still loaded"
        assert not self.lib.exists() and not Path(f"/Library/LaunchDaemons/{self.label}.plist").exists()
        assert not Path("/usr/local/bin/hanword").exists(), "symlink left"
        assert sh(["sudo", "test", "-d", str(self.data)], check=False).returncode == 0, "data deleted"


class Linux:
    unit = "hanword"
    prefix = Path("/opt/hanword")
    data = "/var/lib/hanword"
    port = 8088
    cli = ["/usr/local/bin/hanword"]

    def __init__(self, artifact):
        self.artifact = Path(artifact).resolve()

    def install(self):
        tmp = Path(tempfile.mkdtemp(prefix="hanword-"))
        with tarfile.open(self.artifact) as tf:
            if hasattr(tarfile, "tar_filter"):
                tf.extractall(tmp, filter="tar")
            else:
                tf.extractall(tmp)
        top = next(tmp.iterdir())
        sh(["sudo", top / "install.sh"])

    def check_service(self):
        sh(["systemctl", "is-active", self.unit])
        pid = sh(["systemctl", "show", "-p", "MainPID", "--value", self.unit]).stdout.strip()
        uid = sh(["ps", "-o", "uid=", "-p", pid]).stdout.strip()
        assert uid == sh(["id", "-u", "hanword"]).stdout.strip(), f"service runs as uid {uid}"
        mode = sh(["sudo", "stat", "-c", "%a %U", self.data]).stdout.strip()
        assert mode == "700 hanword", f"data dir perms: {mode}"

    def check_saved(self, doc):
        p = f"{self.data}/documents/{doc}.html"
        assert sh(["sudo", "test", "-f", p], check=False).returncode == 0, f"{p} missing"

    def uninstall(self):
        sh(["sudo", self.prefix / "uninstall.sh"])

    def check_gone(self):
        assert sh(["systemctl", "cat", self.unit], check=False).returncode != 0, "unit still present"
        assert not self.prefix.exists(), "program dir left"
        assert not Path("/usr/local/bin/hanword").exists(), "symlink left"
        assert sh(["sudo", "test", "-d", self.data], check=False).returncode == 0, "data deleted"


def run_local(cmd, label):
    """pyz / bare binary: serve on a free port with a temp documents folder, test, stop."""
    port = free_port()
    tmp = Path(tempfile.mkdtemp(prefix="hw-smoke-"))
    docs = tmp / "docs"
    env = dict(os.environ)
    env["HANWORD_CACHE"] = str(tmp / "cache")     # pyz: exercise a fresh unpack
    logf = open(tmp / "server.log", "w+", encoding="utf-8", errors="replace")
    argv = [str(c) for c in cmd] + ["serve", "--port", str(port), "--data", str(docs)]
    log("$ " + " ".join(argv))
    proc = subprocess.Popen(argv, stdout=logf, stderr=subprocess.STDOUT, env=env)
    try:
        info = wait_health(port, timeout=90, proc=proc)
        doc = check_http(port)
        assert (docs / (doc + ".html")).is_file(), "saved document not in --data folder"
        os.environ["HANWORD_CACHE"] = env["HANWORD_CACHE"]
        check_cli(list(cmd))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        logf.seek(0)
        out = logf.read()
        logf.close()
        print("---- server log (tail) ----\n" + out[-2000:], flush=True)
        shutil.rmtree(tmp, ignore_errors=True)
    wait_down(port, timeout=20)
    log(f"PASS {label} (server version {info.get('version')})")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["windows", "macos", "linux", "pyz", "binary", "http"])
    ap.add_argument("artifact", nargs="?")
    ap.add_argument("--port", type=int, default=8088)
    a = ap.parse_args()
    if a.kind == "http":
        wait_health(a.port, timeout=10)
        check_http(a.port)
        log("PASS (http only)")
        return 0
    if not a.artifact:
        ap.error("artifact required")
    art = Path(a.artifact).resolve()
    if a.kind == "pyz":
        return run_local([sys.executable, "-s", "-I", art], art.name)
    if a.kind == "binary":
        return run_local([art], art.name)
    pkg = {"windows": Windows, "macos": MacOS, "linux": Linux}[a.kind](art)
    pkg.install()
    info = wait_health(pkg.port)
    pkg.check_service()
    doc = check_http(pkg.port)
    pkg.check_saved(doc)
    check_cli(list(pkg.cli))
    pkg.uninstall()
    wait_down(pkg.port)
    pkg.check_gone()
    log(f"PASS {a.kind} {art.name} (server version {info.get('version')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

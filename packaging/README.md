# Packaging hanword

Release builds are made by `.github/workflows/release.yml` on a `v*` tag (or by hand with
*Run workflow*, which builds and smoke-tests but does not publish). This file explains how to build
the same artefacts locally.

| Artefact | Built by | Contents |
|---|---|---|
| `hanword-<ver>-linux-x64.tar.gz` | `packaging/build.py --tarball` | binary + `install.sh` (systemd service) |
| `hanword-<ver>-macos-<arm64\|x64>.pkg` | `packaging/build.py` + `packaging/macos/build_pkg.sh` | binary + LaunchDaemon |
| `hanword-<ver>-windows-x64-setup.exe` | `packaging/build.py` + Inno Setup (`packaging/windows/hanword.iss`) | binary + WinSW service |
| `hanword-<ver>.pyz` | `scripts/build_zipapp.py` | pure-Python zipapp, needs Python 3.10+ |

All of them run the same entry point, `packaging/entry.py`:

```
hanword serve [--host 127.0.0.1] [--port 8088] [--data DIR]   # editor server
hanword --version
hanword [--json] formats|convert|info|check|roundtrip|model|render|apply|debug ...   # document CLI
```

Installed services listen on `127.0.0.1:8088` only: the local (save/load) mode has no login,
and the server refuses a non-loopback address unless `WP_ALLOW_REMOTE=1` / `WP_PUBLIC=1`.

## Binary (PyInstaller, one-file)

```sh
python -m venv /tmp/hw-build && . /tmp/hw-build/bin/activate
pip install pyinstaller==6.22.3
python packaging/build.py            # -> dist/hanword/hanword(.exe) + LICENSE.txt, notices, licenses/, VERSION
python packaging/build.py --tarball  # Linux: also dist/hanword-<ver>-linux-x64.tar.gz
python packaging/smoke_test.py binary dist/hanword/hanword
```

The one-file binary unpacks itself to a temporary directory at start; `server.py` serves its web
files, fonts and `hwpx_skeleton.hwpx` from there. `--strict` (used in CI) fails when `LICENSE`,
`licenses/` or `NOTICE-hwpx_skeleton.txt` is missing. Build each OS on that OS (no cross-building);
the Linux build should be made on the oldest glibc you want to support (CI uses Ubuntu 22.04).

## Linux tarball

`install.sh` (root) installs to `/opt/hanword`, links `/usr/local/bin/hanword`, creates the system
user `hanword`, stores documents in `/var/lib/hanword/documents` (0700) and installs the hardened
unit `hanword.service`. Options: `--port N`, `--no-start`, `--dest DIR` (stage files only, for testing).
Uninstall: `sudo /opt/hanword/uninstall.sh [--purge]`.

## macOS .pkg

```sh
python packaging/build.py && packaging/macos/build_pkg.sh 0.1.0 dist
```

Installs `/usr/local/hanword/`, `/usr/local/bin/hanword`, the LaunchDaemon
`/Library/LaunchDaemons/com.hanword.server.plist` (hidden user `_hanword`), documents in
`/Library/Application Support/hanword/documents`, logs in `/Library/Logs/hanword`.
Uninstall: `sudo /usr/local/hanword/uninstall.sh [--purge]`. The package is not signed or
notarised; users open it with right-click → Open. To sign, add `--sign "Developer ID Installer: …"`
to `productbuild` and notarise with `xcrun notarytool`.

## Windows installer

1. `python packaging\build.py`
2. Put WinSW v2.12.0 `WinSW.NET461.exe` and its `LICENSE.txt` in `build\winsw\` (the workflow
   downloads them and checks the SHA-256 values pinned in `release.yml`).
3. `iscc /DAppVersion=0.1.0 packaging\windows\hanword.iss` → `dist\hanword-0.1.0-windows-x64-setup.exe`

Installs `C:\Program Files\hanword\`, the service `hanword` (NT AUTHORITY\LocalService), documents in
`%ProgramData%\hanword\documents` (SYSTEM / Administrators / LOCAL SERVICE only) and a Start-menu
"hanword 열기" shortcut. Silent: `/VERYSILENT`; uninstall keeps documents unless asked (`/PURGEDATA`
when silent). No firewall rule is created because the service only listens on 127.0.0.1.

## .pyz

```sh
python scripts/build_zipapp.py              # -> dist/hanword-<ver>.pyz
python3 dist/hanword-<ver>.pyz serve
python packaging/smoke_test.py pyz dist/hanword-<ver>.pyz
```

On first run the .pyz unpacks its files into a per-version cache directory
(`~/.cache/hanword/`, `~/Library/Caches/hanword/`, `%LOCALAPPDATA%\hanword\Cache\`; override with
`HANWORD_CACHE`) and runs from there, because the server reads its web files from disk.

## Smoke test

`packaging/smoke_test.py <linux|macos|windows> <artefact>` really installs the package as a system
service, checks `/healthz`, static files, save/load, HWPX/DOCX export and import, the CLI, then
uninstalls and checks that the service is gone and the documents are kept. Run it only on
throw-away machines (CI runners). `binary` and `pyz` modes run `serve` on a free port instead.

#!/bin/sh
# Build the macOS installer package from the PyInstaller output (run packaging/build.py first).
#   packaging/macos/build_pkg.sh <version> [dist-dir]
# -> <dist-dir>/hanword-<version>-macos-<arm64|x64>.pkg   (unsigned; see packaging/README.md)
set -eu
VERSION="${1:?usage: build_pkg.sh <version> [dist-dir]}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
DIST="${2:-$ROOT/dist}"
APP="$DIST/hanword"
[ -x "$APP/hanword" ] || { echo "missing $APP/hanword - run packaging/build.py first" >&2; exit 1; }

case "$(uname -m)" in
    arm64) ARCH=arm64; HOSTARCH=arm64; MINOS=11.0 ;;
    x86_64) ARCH=x64; HOSTARCH=x86_64; MINOS=10.15 ;;
    *) echo "unsupported arch $(uname -m)" >&2; exit 1 ;;
esac

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PAYLOAD="$WORK/root"
mkdir -p "$PAYLOAD/usr/local" "$PAYLOAD/Library/LaunchDaemons" "$WORK/resources"
cp -R "$APP" "$PAYLOAD/usr/local/hanword"
install -m 0755 "$HERE/uninstall.sh" "$PAYLOAD/usr/local/hanword/uninstall.sh"
install -m 0644 "$HERE/com.hanword.server.plist" "$PAYLOAD/Library/LaunchDaemons/"
plutil -lint "$PAYLOAD/Library/LaunchDaemons/com.hanword.server.plist"

pkgbuild --root "$PAYLOAD" --scripts "$HERE/scripts" --identifier com.hanword.server \
    --version "$VERSION" --install-location / --ownership recommended "$WORK/component.pkg"

cp "$APP/LICENSE.txt" "$WORK/resources/LICENSE.txt" 2>/dev/null || cp "$ROOT/LICENSE" "$WORK/resources/LICENSE.txt"
cp "$HERE/resources/conclusion.html" "$WORK/resources/"
sed -e "s/@VERSION@/$VERSION/g" -e "s/@HOSTARCH@/$HOSTARCH/g" -e "s/@MINOS@/$MINOS/g" \
    "$HERE/distribution.xml.in" > "$WORK/distribution.xml"
OUT="$DIST/hanword-$VERSION-macos-$ARCH.pkg"
productbuild --distribution "$WORK/distribution.xml" --resources "$WORK/resources" \
    --package-path "$WORK" "$OUT"
echo "built $OUT"

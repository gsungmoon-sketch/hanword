#!/usr/bin/env bash
# hanword Linux installer (run from the extracted tarball directory).
#
#   sudo ./install.sh                 # install/upgrade, start the service on 127.0.0.1:8088 (this machine only)
#   sudo ./install.sh --port 8090     # different port
#   sudo ./install.sh --no-start      # install but do not enable/start the service
#   ./install.sh --dest /tmp/stage    # test mode: stage files under a directory, no user/systemd changes
#
# Layout: /opt/hanword (program + licences), /var/lib/hanword (data, 0700, owned by the system
# user hanword; documents in /var/lib/hanword/documents), /etc/systemd/system/hanword.service,
# /usr/local/bin/hanword (symlink). Upgrades keep the data. Remove with /opt/hanword/uninstall.sh [--purge].
# There is no LAN option: the local (save/load) mode has no login and only listens on 127.0.0.1.
set -euo pipefail

NAME=hanword
SVC_USER=hanword
PREFIX=/opt/hanword
DATA=/var/lib/hanword
UNIT=/etc/systemd/system/$NAME.service
BINDIR=/usr/local/bin

DEST=""
PORT=8088
START=1

die() { echo "error: $*" >&2; exit 1; }
usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case "$1" in
        --port) shift; PORT="${1:-}" ;;
        --port=*) PORT="${1#--port=}" ;;
        --no-start) START=0 ;;
        --dest) shift; DEST="${1:-}"; [ -n "$DEST" ] || die "--dest needs a directory" ;;
        --dest=*) DEST="${1#--dest=}" ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1 (see --help)" ;;
    esac
    shift
done
case "$PORT" in *[!0-9]*|"") die "--port must be a number" ;; esac
[ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die "--port out of range"

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/$NAME"
[ -x "$SRC/$NAME" ] || die "program directory not found: $SRC (run install.sh from the extracted tarball)"

if [ -n "$DEST" ]; then
    mkdir -p "$DEST"
    DEST="$(cd "$DEST" && pwd)"
    echo "TEST MODE: staging under $DEST (no user, no systemd changes)"
else
    [ "$(id -u)" -eq 0 ] || die "run as root: sudo $0 $*"
    [ "$(uname -s)" = Linux ] || die "Linux only"
    command -v systemctl >/dev/null 2>&1 || die "systemd (systemctl) is required"
fi
R="$DEST"   # path prefix: empty for a real install

# ---- 1. system user -------------------------------------------------------------------------
if [ -z "$DEST" ] && ! id -u "$SVC_USER" >/dev/null 2>&1; then
    NOLOGIN="$(command -v nologin || echo /usr/sbin/nologin)"
    [ -x "$NOLOGIN" ] || NOLOGIN=/bin/false
    useradd --system --user-group --home-dir "$DATA" --no-create-home --shell "$NOLOGIN" \
        --comment "hanword server" "$SVC_USER"
    echo "created system user $SVC_USER"
fi

# ---- 2. stop a running instance (upgrade) ----------------------------------------------------
WAS_ACTIVE=0
if [ -z "$DEST" ] && systemctl is-active --quiet "$NAME" 2>/dev/null; then
    WAS_ACTIVE=1
    systemctl stop "$NAME"
fi

# ---- 3. program files (replace atomically, nothing user-owned in PREFIX) -----------------------
mkdir -p "$R$(dirname "$PREFIX")"
rm -rf "$R$PREFIX.new"
cp -a "$SRC" "$R$PREFIX.new"
cp "$HERE/uninstall.sh" "$HERE/install.sh" "$HERE/$NAME.service.in" "$R$PREFIX.new/"
[ -f "$HERE/README.txt" ] && cp "$HERE/README.txt" "$R$PREFIX.new/"
chmod -R u=rwX,go=rX "$R$PREFIX.new"
chmod 0755 "$R$PREFIX.new/$NAME" "$R$PREFIX.new/uninstall.sh" "$R$PREFIX.new/install.sh"
[ -z "$DEST" ] && chown -R root:root "$R$PREFIX.new"
rm -rf "$R$PREFIX.old"
[ -e "$R$PREFIX" ] && mv "$R$PREFIX" "$R$PREFIX.old"
mv "$R$PREFIX.new" "$R$PREFIX"
rm -rf "$R$PREFIX.old"

mkdir -p "$R$BINDIR"
ln -sfn "$PREFIX/$NAME" "$R$BINDIR/$NAME"

# ---- 4. data directory -----------------------------------------------------------------------
mkdir -p "$R$DATA/documents"
chmod 0700 "$R$DATA" "$R$DATA/documents"
[ -z "$DEST" ] && chown "$SVC_USER:$SVC_USER" "$R$DATA" "$R$DATA/documents"

# ---- 5. systemd unit -------------------------------------------------------------------------
mkdir -p "$R$(dirname "$UNIT")"
sed -e "s|@PREFIX@|$PREFIX|g" -e "s|@DATA@|$DATA|g" -e "s|@USER@|$SVC_USER|g" -e "s|@PORT@|$PORT|g" \
    "$HERE/$NAME.service.in" > "$R$UNIT"
chmod 0644 "$R$UNIT"

# ---- 6. enable/start ------------------------------------------------------------------------
if [ -z "$DEST" ]; then
    systemctl daemon-reload
    if [ "$START" = 1 ]; then
        systemctl enable "$NAME" >/dev/null 2>&1
        systemctl restart "$NAME"
    elif [ "$WAS_ACTIVE" = 1 ]; then
        echo "note: service was running before the upgrade and is now stopped (--no-start)"
    fi
fi

VER="$(cat "$R$PREFIX/VERSION" 2>/dev/null || echo '?')"
cat <<EOF

hanword $VER installed.
  open    : http://127.0.0.1:$PORT/   (this machine only)
  program : $PREFIX        documents: $DATA/documents (user $SVC_USER)
  service : systemctl status $NAME      logs: journalctl -u $NAME
  CLI     : hanword --help             (e.g. hanword convert in.docx out.hwpx)
Uninstall: sudo $PREFIX/uninstall.sh   (add --purge to also delete all documents)
EOF

#!/usr/bin/env bash
# hanword Linux uninstaller.
#
#   sudo /opt/hanword/uninstall.sh            # remove program + service, KEEP documents and the system user
#   sudo /opt/hanword/uninstall.sh --purge    # also delete /var/lib/hanword and the system user
#   ./uninstall.sh --dest /tmp/stage [--purge]  # test mode (counterpart of install.sh --dest)
set -euo pipefail

NAME=hanword
SVC_USER=hanword
PREFIX=/opt/hanword
DATA=/var/lib/hanword
UNIT=/etc/systemd/system/$NAME.service
DROPIN_DIR=/etc/systemd/system/$NAME.service.d
BINDIR=/usr/local/bin

DEST=""
PURGE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --purge) PURGE=1 ;;
        --dest) shift; DEST="${1:-}" ;;
        --dest=*) DEST="${1#--dest=}" ;;
        -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "error: unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done
if [ -z "$DEST" ] && [ "$(id -u)" -ne 0 ]; then
    echo "error: run as root: sudo $0 $*" >&2; exit 1
fi
R="$DEST"

if [ -z "$DEST" ] && command -v systemctl >/dev/null 2>&1; then
    systemctl disable --now "$NAME" >/dev/null 2>&1 || true
fi
rm -f "$R$UNIT"
rm -rf "$R$DROPIN_DIR"
if [ -z "$DEST" ] && command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload || true
fi

# only remove the symlink if it still points to us
if [ -L "$R$BINDIR/$NAME" ] && [ "$(readlink "$R$BINDIR/$NAME")" = "$PREFIX/$NAME" ]; then
    rm -f "$R$BINDIR/$NAME"
fi
cd /
rm -rf "$R$PREFIX" "$R$PREFIX.new" "$R$PREFIX.old"

if [ "$PURGE" = 1 ]; then
    rm -rf "$R$DATA"
    if [ -z "$DEST" ] && id -u "$SVC_USER" >/dev/null 2>&1; then
        userdel "$SVC_USER" >/dev/null 2>&1 || true
        if getent group "$SVC_USER" >/dev/null 2>&1; then groupdel "$SVC_USER" >/dev/null 2>&1 || true; fi
    fi
    echo "hanword removed, including all documents."
else
    echo "hanword removed. Documents kept in $DATA/documents (delete with: sudo rm -rf $DATA)."
    echo "Reinstalling later reuses them."
fi

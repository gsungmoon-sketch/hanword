#!/bin/sh
# hanword macOS uninstaller (installed as /usr/local/hanword/uninstall.sh).
#   sudo /usr/local/hanword/uninstall.sh          # remove program + daemon, KEEP documents
#   sudo /usr/local/hanword/uninstall.sh --purge  # also delete documents, logs and the _hanword user
set -u
LABEL=com.hanword.server
DATA="/Library/Application Support/hanword"
U=_hanword
USERS_DIR=/Users      # directory-service nodes (dscl)
GROUPS_DIR=/Groups
PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1
if [ "$(id -u)" -ne 0 ]; then
    exec sudo -- "$0" "$@"
fi
cd /
launchctl bootout "system/$LABEL" >/dev/null 2>&1 || true
rm -f "/Library/LaunchDaemons/$LABEL.plist"
if [ "$(readlink /usr/local/bin/hanword 2>/dev/null)" = /usr/local/hanword/hanword ]; then
    rm -f /usr/local/bin/hanword
fi
rm -rf /usr/local/hanword
pkgutil --forget "$LABEL" >/dev/null 2>&1 || true
if [ "$PURGE" = 1 ]; then
    rm -rf "$DATA" /Library/Logs/hanword
    dscl . -delete "$USERS_DIR/$U" >/dev/null 2>&1 || true
    dscl . -delete "$GROUPS_DIR/$U" >/dev/null 2>&1 || true
    echo "hanword removed, including all documents."
else
    echo "hanword removed. Documents kept in $DATA/documents (logs: /Library/Logs/hanword)."
fi
exit 0

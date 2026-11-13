#!/bin/sh
# 코퍼스 회귀: 각 문서 check + roundtrip(via hwpx, docx). tests/private/(git 제외, 개인 실문서)도 있으면 포함.
# 사용: tests/run-corpus.sh [--json]   종료코드=실패 수(0=전부 통과)
cd "$(dirname "$0")/.." || exit 2
HW=./hanword; fails=0; n=0
for f in tests/corpus/* tests/private/*; do
  [ -f "$f" ] || continue
  case "$f" in *.html|*.htm|*.txt|*.hwpx|*.hwp|*.docx|*.doc) ;; *) continue;; esac
  case "$f" in *evil*) $HW $1 check "$f" >/dev/null; [ $? -eq 1 ] && echo "ok   check(악성 감지) $f" || { echo "FAIL check(악성 미감지) $f"; fails=$((fails+1)); }; continue;; esac
  n=$((n+1))
  $HW $1 check "$f" >/tmp/hw-corpus.$$ 2>&1 || { echo "FAIL check $f"; cat /tmp/hw-corpus.$$; fails=$((fails+1)); }
  for v in hwpx docx; do
    if out=$($HW $1 roundtrip "$f" --via $v 2>&1); then echo "ok   $v  $f"; else echo "FAIL $v  $f"; echo "$out" | head -8; fails=$((fails+1)); fi
  done
done
rm -f /tmp/hw-corpus.$$
echo "corpus: $n docs, $fails fail"
exit $fails

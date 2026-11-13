#!/usr/bin/env python3
"""index.html → embed.html (임베드 전용 입구, docs/embed.md).

임베드(결재 등 호스트 앱이 같은 출처 iframe 으로 띄움)용으로 공개 사이트 전용 줄을 뺀다:
  SEO(description·keywords·robots·사이트 인증·canonical·og:*·twitter:*·ld+json) → robots noindex 1줄,
  인라인 디버그 로더 <script> 제거, <html data-wp-embed>(wp-core.js 가 ?embed=1 없이도 임베드로 판정).
인라인 스크립트가 하나도 없어 호스트가 nonce 없는 CSP(script-src 'self')로 그대로 서빙할 수 있다.

  python3 scripts/build_embed.py           # embed.html 다시 만들기
  python3 scripts/build_embed.py --check   # 최신인지 검사(다르면 종료코드 1) — tests/test_embed.py 가 사용
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC, DST = os.path.join(ROOT, "index.html"), os.path.join(ROOT, "embed.html")
HEAD_DROP = re.compile(r'^\s*(<meta (name|property)="(description|keywords|robots|google-site-verification|naver-site-verification|og:[a-z:]+|twitter:[a-z:]+)"[^>]*>'
                       r'|<link rel="canonical"[^>]*>|<!--.*?-->|<script type="application/ld\+json">.*</script>)\s*$')

def build(src):
    src = re.sub(r"<script(?![^>]*\bsrc=)[^>]*>.*?</script>[ \t]*\n?", "", src, flags=re.S | re.I)   # 인라인 스크립트(여러 줄 포함) 통째 제거
    out, in_head = [], False
    for line in src.splitlines(keepends=True):
        if re.match(r"\s*<head\b", line): in_head = True
        elif line.strip() == "</head>": in_head = False
        if in_head and HEAD_DROP.match(line): continue
        out.append(line)
    s = "".join(out)
    s, n1 = re.subn(r'<html lang="ko">', '<!-- 생성 파일: scripts/build_embed.py (index.html 에서) — 직접 고치지 말 것 -->\n<html lang="ko" data-wp-embed>', s, count=1)
    s, n2 = re.subn(r"<title>[^<]*</title>", '<title>한워드 편집기</title>\n<meta name="robots" content="noindex, nofollow">', s, count=1)
    if not (n1 and n2): raise SystemExit("build_embed: index.html 구조가 바뀜(html/title 태그) — 스크립트 갱신 필요")
    bad = [p for p in (r"<script(?![^>]*\bsrc=)", r"sys" "plays", r"hwd\.", r"canonical", r'property="og:', r"ld\+json", r"twitter:",
                       r"site-verification", r'name="(description|keywords)"', r'content="index') if re.search(p, s, re.I)]
    if len(re.findall(r"<script\b", s, re.I)) != len(re.findall(r"</script>", s, re.I)) or len(re.findall(r'name="robots"', s)) != 1:
        bad.append("script/robots 개수")
    if bad: raise SystemExit("build_embed: 임베드 입구에 남은 공개 전용 내용: %s" % bad)
    return s

def main():
    with open(SRC, encoding="utf-8") as f: s = build(f.read())
    if "--check" in sys.argv:
        try:
            with open(DST, encoding="utf-8") as f: cur = f.read()
        except OSError: cur = None
        if cur != s: print("embed.html 이 index.html 과 맞지 않음 — python3 scripts/build_embed.py 실행"); return 1
        print("embed.html ok"); return 0
    with open(DST, "w", encoding="utf-8", newline="\n") as f: f.write(s)
    print("wrote", DST); return 0

if __name__ == "__main__":
    sys.exit(main())

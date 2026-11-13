#!/usr/bin/env python3
"""임베드(결재 등 호스트 앱) 벤더링용 사본 만들기 — docs/embed.md.

  python3 scripts/export_embed.py DST [--ref HEAD]

ref(기본 HEAD)의 git 추적 파일 중 .publicignore 에 걸리지 않는 것만 DST 에 복사한다(작업 트리의
미커밋 변경·내부 문서·재배포 불명 폰트는 나가지 않음). 복사 뒤 검사:
  - font/ 에 licenses/README.md 의 배포 목록(SHIPPED_FONTS) 밖 파일이 없을 것
  - embed.html 이 최신이고 인라인 스크립트·공개 주소가 없을 것(scripts/build_embed.py --check)
  - tests/test_hygiene.py 의 내부 호스트·경로 패턴이 없을 것
DST 는 비어 있거나 없어야 한다.
"""
import fnmatch, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests")); sys.path.insert(0, os.path.join(ROOT, "scripts"))
import fontcss
SHIPPED_FONTS = ("Pretendard-", "NotoSansKR", "NotoSerifKR-", "D2Coding-", "NanumGothic-Regular.ttf", "NanumGothic-Bold.ttf",
                 "NanumMyeongjo-Regular.ttf", "NanumMyeongjo-Bold.ttf")   # licenses/README.md "Shipped" 표와 같게


def git(*a, binary=False):
    r = subprocess.run(["git", "-C", ROOT, *a], capture_output=True, check=True)
    return r.stdout if binary else r.stdout.decode("utf-8")


def ignore_patterns(ref):
    pats = []
    try: lst = git("show", "%s:.publicignore" % ref)
    except subprocess.CalledProcessError: return pats   # 공개 사본(make_public 결과)엔 .publicignore 없음 = 이미 걸러짐
    for ln in lst.splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"): pats.append(ln)
    return pats


def ignored(path, pats):
    return any((p.endswith("/") and path.startswith(p)) or path == p or fnmatch.fnmatchcase(path, p) for p in pats)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ref = sys.argv[sys.argv.index("--ref") + 1] if "--ref" in sys.argv else "HEAD"
    if "--ref" in sys.argv: args.remove(ref)
    if len(args) != 1: sys.exit(__doc__)
    dst = os.path.abspath(args[0])
    if os.path.exists(dst) and os.listdir(dst): sys.exit("DST 가 비어 있지 않음: %s" % dst)
    pats = ignore_patterns(ref)
    files = [f for f in git("ls-tree", "-r", "--name-only", ref).splitlines() if not ignored(f, pats)]
    for f in files:
        out = os.path.join(dst, f)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as fh: fh.write(git("show", "%s:%s" % (ref, f), binary=True))
    bad_fonts = [f for f in files if f.startswith("font/") and not os.path.basename(f).startswith(SHIPPED_FONTS)]
    if bad_fonts: sys.exit("배포 목록 밖 폰트: %s" % bad_fonts)
    shipped = {os.path.basename(f) for f in files if f.startswith("font/")}
    css_p = os.path.join(dst, "editor.css")
    if os.path.isfile(css_p):   # 없는 폰트의 @font-face 제거(404 요청 없음)
        with open(css_p, encoding="utf-8") as fh: css = fontcss.prune_font_faces(fh.read(), shipped)
        missing = set(fontcss.font_urls(css)) - shipped
        if missing: sys.exit("editor.css 가 없는 폰트를 부름: %s" % sorted(missing))
        with open(css_p, "w", encoding="utf-8", newline="\n") as fh: fh.write(css)
    r = subprocess.run([sys.executable, os.path.join(dst, "scripts", "build_embed.py"), "--check"], capture_output=True, text=True)
    if r.returncode: sys.exit("embed.html 검사 실패: " + r.stdout + r.stderr)
    try: import test_hygiene
    except ImportError: test_hygiene = None   # 공개 사본엔 없음(내부 패턴 목록) — make_public 누출 검사를 이미 거침
    if test_hygiene:
        leaks = test_hygiene.scan(dst, files)
        if leaks: sys.exit("내부 호스트·경로 흔적: %s" % leaks[:10])
    print("exported %d files to %s (ref %s)" % (len(files), dst, git("rev-parse", ref).strip()))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""editor.css @font-face 를 배포 폰트에 맞춤 — 배포 사본(make_public·export_embed)에서 없는 폰트 요청(404)이 없게.

prune_font_faces(css, shipped): src 목록에서 font/ 아래 배포 안 된 파일 url 은 빼고, 남는 게 없으면 @font-face 규칙째 뺀다.
font/ 밖 url·local() 은 그대로. 개발 트리의 editor.css 는 바꾸지 않는다.
"""
import re

_FACE = re.compile(r"@font-face\s*\{[^{}]*\}")
_SRC = re.compile(r"(\bsrc\s*:\s*)([^;}]*)")
_URL = re.compile(r"""url\(\s*(['"]?)(?:\./|/)?font/([^'")\s?#]+)[^'")\s]*\1\s*\)""")   # ./font/·/font/·font/, ?v=·#frag 꼬리 허용


def font_urls(css):
    """css 안 font/ 파일 이름 목록."""
    return [m.group(2) for m in _URL.finditer(css)]


def prune_font_faces(css, shipped):
    shipped = set(shipped)

    def face(m):
        rule = m.group(0)
        sm = _SRC.search(rule)
        if not sm: return rule
        parts = [p.strip() for p in sm.group(2).split(",")]
        keep = [p for p in parts if not (_URL.search(p) and _URL.search(p).group(2) not in shipped)]
        if not keep: return ""
        return rule[:sm.start(2)] + ", ".join(keep) + rule[sm.end(2):]

    out = _FACE.sub(face, css)
    return re.sub(r"\n[ \t]*\n(?=[ \t]*\n)", "\n", out)

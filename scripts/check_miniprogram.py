#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 静态检查：每个展开入口（class="q" 的文字）必须处在某个带 bindtap 的元素之内。
# 上一版 bug 就是「打分逻辑 ›」写在 .met 里，而 bindtap 绑在兄弟元素 .sig-head 上，
# 点了没反应——而单测直接调 toggle()，绕开了绑定，测不出来。
import io, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = io.open(os.path.join(ROOT, "miniprogram/pages/index/index.wxml"), encoding="utf-8").read()
tok = re.compile(r'<(/?)(view|text|block|canvas)\b([^>]*?)(/?)>')
stack, problems, found = [], [], 0

for m in tok.finditer(src):
    closing, tag, attrs, selfclose = m.groups()
    line = src[:m.start()].count("\n") + 1
    if closing:
        if stack: stack.pop()
        continue
    has_tap = "bindtap" in attrs
    if 'class="q"' in attrs or "class=\"q " in attrs:
        found += 1
        if not (has_tap or any(stack)):
            problems.append("  ✗ 第 %d 行的展开入口没有任何祖先绑定 bindtap，点了不会有反应" % line)
    if not selfclose:
        stack.append(has_tap)

print("展开入口绑定检查：共找到 %d 个 class=\"q\" 入口" % found)
if problems:
    print("\n".join(problems)); sys.exit(1)
print("  全部处在可点击元素内 ✓")

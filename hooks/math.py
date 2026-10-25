import re

# 源文件用 GitHub 友好的写法书写公式：行内 $`...`$，块级 ```math 围栏。
# 构建站点时：行内改写成 \(...\) 交给 arithmatex（站点只识别 \( \) 与 \[ \]，
# 不识别 $，避免把 shell 代码里的 $ 误当成公式）；围栏内容里的 "<" 换成 \lt，
# 否则 G_{<i} 里的 "<i" 会被浏览器当成 HTML 标签。
_INLINE = re.compile(r"\$`([^`\n]+?)`\$")
_OPEN = re.compile(r"^((?:> ?)*)```math\s*$")
_CLOSE = re.compile(r"^((?:> ?)*)```\s*$")


def on_page_markdown(markdown, **kwargs):
    out, in_math = [], False
    for line in markdown.split("\n"):
        if not in_math and _OPEN.match(line):
            in_math = True
        elif in_math and _CLOSE.match(line):
            in_math = False
        elif in_math:
            line = line.replace("<", r"\lt ")
        out.append(line)
    return _INLINE.sub(lambda m: "\\(" + m.group(1) + "\\)", "\n".join(out))

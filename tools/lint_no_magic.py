"""tools/lint_no_magic.py —— 常驻复查①「grep 全仓无轴参数魔法数字」的自动化落地（T03 交付）。

⚠️ 本脚本是 99 验收流程的常驻复查工具，**其他单不得修改其判定规则**（04 §4 归属矩阵）。

判据（04 §5.5-①）：轴参数字段名**可以**出现在代码里（core/config 的字段定义与校验消息
就需要它），但同一处**不得伴随数值字面量**——行程／零点／方向／容差／速度等数值只允许
存在于 config/machine.yaml；代码里出现即「现场参数硬编码进代码」（规程 §13 失败模式 3）。
字段名清单与 04 §5.5-① 的正则逐字一致（含 2026-09-15 补的三项，漏扫等于白扫）。

两侧判定精度不同，**不是同一口径**，局限写在这里：
- `.py` 走 ast，只看**数值字面量节点**所在行是否含字段名 → 注释与 docstring 里引用文档
  章节（「03 §4」「T04」「契约 §7.4」）不会误判。
- `.js`／`.html`／`.css`：stdlib 无 JS 解析器，退化为**行级近似**——跳过整行注释（行首
  `//`、`*`、`/*`、`<!--`、`#`），其余行同时含字段名与独立数字 token 即命中。故**行尾
  内联注释可能误报**；命中须人工看一眼再判（宁可误报，不可漏报）。

扫描范围 app/ core/ comm/ view/；`view/vendor/**` 属第三方打包件白名单（04 §4.5-④、
03 §8 准入清单），**不扫**——three.module.js 内 direction 等词与数字极多，扫它全是噪声。

跑法（仓根）：`python tools/lint_no_magic.py`；退出码 0＝合规、1＝有命中（逐条打印）。
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

FIELDS = re.compile(r"(travel|zero_offset|direction|coupling|sync_tol|clearance_warn"
                    r"|speed_max|collision_envelope_mm|tessellate_deflection_mm|modes)")
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
SCAN_DIRS = ("app", "core", "comm", "view")
SUFFIXES = (".py", ".js", ".html", ".css")
SKIP_PREFIX = "view/vendor/"
COMMENT_LEAD = ("//", "*", "/*", "<!--", "#")
ROOT = pathlib.Path(__file__).resolve().parent.parent


def _py_hits(relative: str, lines: list[str]) -> list[str]:
    """`.py`：数值字面量节点所在行若含轴参数字段名即命中（注释／docstring 不参与）。"""
    hits = []
    for node in ast.walk(ast.parse("\n".join(lines))):
        if not isinstance(node, ast.Constant) or isinstance(node.value, bool):
            continue
        if not isinstance(node.value, (int, float)):
            continue
        line = lines[node.lineno - 1]
        if FIELDS.search(line):
            hits.append(f"{relative}:{node.lineno}: 数值字面量 {node.value!r} 与轴参数字段名"
                        f"同行 → {line.strip()}")
    return hits


def _text_hits(relative: str, lines: list[str]) -> list[str]:
    """`.js`／`.html`／`.css`：行级近似判定（跳过整行注释，见模块 docstring 的局限说明）。"""
    hits = []
    for index, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(COMMENT_LEAD):
            continue
        if FIELDS.search(line) and NUMBER.search(line):
            hits.append(f"{relative}:{index}: 字段名与数字同行（近似判定，须人工复核）"
                        f" → {stripped}")
    return hits


def scan() -> tuple[list[str], int]:
    """扫全部在范围内的源文件，返回（命中明细，已扫文件数）。"""
    hits: list[str] = []
    scanned = 0
    for name in SCAN_DIRS:
        for path in sorted((ROOT / name).rglob("*")):
            relative = path.relative_to(ROOT).as_posix()
            if not path.is_file() or path.suffix not in SUFFIXES:
                continue
            if relative.startswith(SKIP_PREFIX):
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            scanned += 1
            hits.extend(_py_hits(relative, lines) if path.suffix == ".py"
                        else _text_hits(relative, lines))
    return hits, scanned


def main() -> int:
    """入口：命中即退出码 1（04 §5.5-①「输出非零退出码即视为不合规」）。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # 本机控制台 GBK，不转 UTF-8 会自身抛错
    hits, scanned = scan()
    scope = f"扫描 {scanned} 个文件（{'、'.join(SCAN_DIRS)}/ 下 {('/'.join(SUFFIXES))}，" \
            f"{SKIP_PREFIX} 白名单除外）"
    if hits:
        print(f"[FAIL] 轴参数魔法数字命中 {len(hits)} 处；{scope}")
        for hit in hits:
            print("  " + hit)
        print("处置：把数值移进 config/machine.yaml，代码里只留字段名（03 §4 界面零硬编码）。")
        return 1
    print(f"[OK] 无轴参数魔法数字；{scope}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

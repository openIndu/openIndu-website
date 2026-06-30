"""
studio.py — openIndu-Website 端的 openIndu-Studio 调用封装

用法（在 openIndu-website 根目录执行）：

    # 列出 studio 中所有可用模板
    python studio.py list

    # 运行指定模板（产物输出到 openIndu-studio/templates/<name>/output/）
    python studio.py run fx_5u

    # 自定义输出目录（绝对路径 或 相对于 openIndu-website 根目录）
    python studio.py run fx_5u --outdir output/fx_5u_result

本脚本代理到 openIndu-studio/converters/cli.py，
openIndu-studio 作为 git submodule 挂载于同级目录。
"""

from __future__ import annotations

import os
import sys

_WEBSITE_ROOT = os.path.dirname(os.path.abspath(__file__))
_STUDIO_CLI = os.path.join(_WEBSITE_ROOT, "openIndu-studio", "converters", "cli.py")

if not os.path.isfile(_STUDIO_CLI):
    print(
        "ERROR: openIndu-studio submodule not found.\n"
        "Run:  git submodule update --init openIndu-studio"
    )
    sys.exit(1)

# 将 studio 根目录加入 path 并代理调用
_STUDIO_ROOT = os.path.join(_WEBSITE_ROOT, "openIndu-studio")
sys.path.insert(0, _STUDIO_ROOT)

# 重写 sys.argv[0] 为更友好的名字，然后直接调用 cli.main()
sys.argv[0] = "studio.py"

# 将 'run fx_5u' 展开为 'run templates/fx_5u'（允许省略 templates/ 前缀）
args = sys.argv[1:]
if len(args) >= 2 and args[0] == "run" and not args[1].startswith("templates"):
    args = ["run", f"templates/{args[1]}"] + args[2:]
    sys.argv = [sys.argv[0]] + args

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("converters.cli", _STUDIO_CLI)
cli_mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(cli_mod)  # type: ignore[union-attr]

sys.exit(cli_mod.main())

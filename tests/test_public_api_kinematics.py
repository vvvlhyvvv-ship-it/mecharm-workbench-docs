"""tests/test_public_api_kinematics.py —— `core/kinematics/` 包根 API 守卫（T04，04 §4.5-⑦ 硬要求 3）。

`core/kinematics.py` 实测 428 行超 04 §4.5-① 的 300 行上限，按 **§4.5-⑦ 预授权预案**包化为
`__init__/fk/transform/limits` 四件（未自创文件名）。本文件锁死两件事，防后续会话（尤其 T07
补 `ik`）悄悄改掉调用形态或把业务逻辑塞回 `__init__.py`：
  ① 03 §3 表里 kinematics 的公开符号**必须能从包根导入**（硬要求 2）；
  ② `__init__.py` 只有 docstring／import／`__all__`，**禁写业务逻辑**（硬要求 1）。
⚠️ `ik` 属 **T07**，本单不做（T04 卡禁止事项），故此处**不断言** ik 存在。
"""

from __future__ import annotations

import ast
import pathlib

import core.kinematics as pkg

ROOT = pathlib.Path(pkg.__file__).resolve().parent

# 03 §3 签名表的 kinematics 行（fk／check_limits）＋表内出现的类型 ＋ T04 卡步骤 2/5 的三函数与换算
PUBLIC = ("fk", "check_limits", "raw_to_eng", "Transform4x4", "Violation",
          "model_to_device", "device_to_model", "device_to_scene", "scene_to_device")
SUBMODULES = ("__init__.py", "fk.py", "transform.py", "limits.py", "ik.py")


def test_public_symbols_import_from_package_root():
    """`from core.kinematics import fk, check_limits` 成立（签名与调用形态一字不变）。"""
    missing = [name for name in PUBLIC if not hasattr(pkg, name)]
    assert missing == []
    assert set(PUBLIC) <= set(pkg.__all__)


def test_package_layout_follows_the_preauthorized_plan():
    """包内文件名照 §4.5-⑦ 预案，未自创（`ik.py` 由 T07 新增，故此处只查不多不少的四件）。"""
    assert sorted(p.name for p in ROOT.glob("*.py")) == sorted(SUBMODULES)


def test_card_step7_types_are_defined_in_their_assigned_files():
    """T04 卡步骤 7（2026-09-16 后补）：两个类型由本单定型，且落位有明文规定。

    `Transform4x4` 落 `transform.py`、`Violation` 落 `limits.py`，⛔ 禁写进 `__init__.py`。
    判据是**定义所在文件的源码**（包根只是 re-export，故 `vars(pkg)` 看不出落位）。
    """
    from core.kinematics import Transform4x4, Violation, check_limits, fk  # noqa: F401
    home = {"Transform4x4": ("transform.py", "Transform4x4 = tuple"),
            "Violation": ("limits.py", "class Violation")}
    for name, (filename, marker) in home.items():
        source = (ROOT / filename).read_text(encoding="utf-8")
        assert marker in source, name
        assert marker not in (ROOT / "__init__.py").read_text(encoding="utf-8")
    assert not hasattr(pkg, "CollisionResult")  # 与 T08 的不合并


def test_kinematics_does_not_depend_on_collision():
    """卡片明文：与 T08 的 `CollisionResult{verdict, cases}` **不互引**，本单不得反向依赖
    `core.collision`（该包由 T08 建；此处按 import 源文本判，不依赖它是否存在）。"""
    sources = "".join((ROOT / name).read_text(encoding="utf-8") for name in SUBMODULES)
    assert "core.collision" not in sources and "import collision" not in sources


def test_init_only_reexports():
    """`__init__.py` 顶层只允许 docstring／import／`__all__` 赋值——否则只是换个巨文件。"""
    tree = ast.parse((ROOT / "__init__.py").read_text(encoding="utf-8"))
    for index, node in enumerate(tree.body):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if index == 0 and isinstance(getattr(node, "value", None), ast.Constant):
            continue  # 模块 docstring
        assert isinstance(node, ast.Assign) and node.targets[0].id == "__all__", ast.dump(node)

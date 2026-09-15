"""core.kinematics —— 运动学正解与坐标变换（T04；03 §3 签名的落码件）。

本包是**拆包形态**：原单文件 `core/kinematics.py` 实测 **428 行**，超 04 §4.5-① 的 300 行
上限，故按 T04 派单卡②**预授权**的结构直接包化（04 §4.5-⑦，照预案不自创文件名）：

    transform.py  4x4 位姿运算、Frame、三坐标系正逆变换（无依赖，最底层）
    fk.py         Joint／KinematicModel／build_model／fk／resolve_positions／raw_to_eng
    limits.py     Violation／check_limits（行程逐项＋sync 双驱偏差）

依赖方向单向：fk → transform、limits → fk，**无回环**。本文件**只做 re-export 与 __all__，
禁写任何业务逻辑**（04 §4.5-⑦ 硬要求 1）；拆分前后调用形态一字不变——
`from core.kinematics import fk, check_limits` 照旧成立（硬要求 2），下游 T05／T07／T08
无需知道内部拆分。T07 的解析逆解 `ik` 到单后加进 fk.py（或按届时实测行数另拆），
**本单不做 ik**（T04 卡禁止事项）。
"""

from core.kinematics.fk import (PRISMATIC, REVOLUTE, Joint, KinematicModel, build_model, fk,
                                raw_to_eng, resolve_positions)
from core.kinematics.limits import Violation, check_limits
from core.kinematics.transform import (AXES_XYZ, ZERO_POINT, Frame, Point, Transform4x4,
                                       axis_swap_frame, device_to_model, device_to_scene,
                                       identity, model_to_device, multiply, rotation,
                                       scene_to_device, to_column_major, transform_point,
                                       translation)

__all__ = [
    # 03 §3 对外签名
    "fk", "check_limits", "raw_to_eng", "model_to_device", "device_to_model", "device_to_scene",
    "scene_to_device", "Violation", "Transform4x4",
    # 链定义与位姿运算（T05／T07／T08 直接消费）
    "Joint", "KinematicModel", "build_model", "resolve_positions", "Frame", "axis_swap_frame",
    "identity", "multiply", "translation", "rotation", "transform_point", "to_column_major",
    "Point", "AXES_XYZ", "ZERO_POINT", "PRISMATIC", "REVOLUTE",
]

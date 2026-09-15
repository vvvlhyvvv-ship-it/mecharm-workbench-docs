"""core.kinematics.transform —— 4x4 位姿运算与三坐标系变换（T04）。

单位与坐标系（S-1 契约第 7 章）：长度 **mm**、角度 **deg**；设备坐标系与场景坐标系均为
**右手系**、Z 竖直向上为正（§7.1）；回转正方向＝从该轴正端向原点看去逆时针（§7.3），
即标准右手定则。

`Transform4x4` ＝ **16 元素行主序**扁平元组（03 §5 `pose.update` 的「每部件 4x4 扁平矩阵」）。
⚠️ three.js 的 `Matrix4.fromArray()` 要**列主序**，上屏前必须过 `to_column_major()`：转置后
位置看着还行、姿态是错的，属静默错，故单独立函数并在测试里锁死。

设备↔场景的**原点与轴对应**在契约 §7.1 里两条都标「待确认」（原点＝设备基础／产线基准还是
甲方图纸全局原点；X 向＝是否取大车行走方向），故一律由调用方以 `Frame` 显式给定，
**代码内不写死**；回执后只改调用方给的配置，不改本文件。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

Transform4x4 = tuple[float, ...]  # 16 元素、行主序（元素下标 = row * 4 + col）
Point = tuple[float, float, float]
AXES_XYZ = ("x", "y", "z")  # 设备坐标系的三个单位轴名（右手系，Z 竖直向上）
ZERO_POINT: Point = (0.0, 0.0, 0.0)
_ORTHO_TOL = 1e-9  # 判旋转阵正交归一的数值容差（纯数学量、非机台参数，不进 machine.yaml）

_ROTATION_ROWS = {
    "x": lambda c, s: ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c)),
    "y": lambda c, s: ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c)),
    "z": lambda c, s: ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0)),
}


def identity() -> Transform4x4:
    """单位位姿：平移 0 mm、旋转为单位阵，即本框与其上层框完全重合。"""
    out = [0.0] * 16
    for index in range(4):
        out[index * 4 + index] = 1.0
    return tuple(out)


def multiply(a: Transform4x4, b: Transform4x4) -> Transform4x4:
    """位姿乘法 a∘b（行主序，右手系）：b 是 a 的子框，返回子框在 a 的上层框内的位姿。"""
    return tuple(sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4))
                 for r in range(4) for c in range(4))


def translation(x_mm: float, y_mm: float, z_mm: float) -> Transform4x4:
    """纯平移位姿（三参单位 mm，设备坐标系右手系）；旋转部分为单位阵。"""
    out = list(identity())
    out[3] = float(x_mm)
    out[7] = float(y_mm)
    out[11] = float(z_mm)
    return tuple(out)


def rotation(motion: str, angle_deg: float) -> Transform4x4:
    """绕设备坐标系 x／y／z 轴转 angle_deg（单位 deg），正方向按契约 §7.3＝右手定则。

    motion 不在 AXES_XYZ 内即 ValueError——**禁静默按某个轴处理**（那会让姿态错得看不出来）。
    """
    if motion not in AXES_XYZ:
        raise ValueError(f"motion 应为 {AXES_XYZ} 之一，实得 {motion!r}")
    angle = math.radians(angle_deg)
    rows = _ROTATION_ROWS[motion](math.cos(angle), math.sin(angle))
    out = list(identity())
    for row in range(3):
        for col in range(3):
            out[row * 4 + col] = rows[row][col]
    return tuple(out)


def transform_point(matrix: Transform4x4, point: Point) -> Point:
    """用位姿变换一个点（mm，右手系）：p' = R·p + t。"""
    return tuple(sum(matrix[r * 4 + c] * point[c] for c in range(3)) + matrix[r * 4 + 3]
                 for r in range(3))


def to_column_major(matrix: Transform4x4) -> Transform4x4:
    """行主序 → 列主序（three.js `Matrix4.fromArray()` 的约定），供上屏前调用。"""
    return tuple(matrix[(index % 4) * 4 + index // 4] for index in range(16))


@dataclass(frozen=True)
class Frame:
    """一个坐标框相对其**上层框**的定位。

    origin_mm＝原点在上层框内的位置（mm）；rotation＝9 元素**行主序正交阵**（把本框内的
    向量映到上层框）。设备↔场景的原点与轴向属契约 §7.1「待确认」项，故一律由调用方给定。
    """

    origin_mm: Point
    rotation: tuple[float, ...]

    def __post_init__(self) -> None:
        """建框即校验：9 元素且三行正交归一。否则逆变换按转置算会**静默出错**，故直接拒。"""
        if len(self.rotation) != 9:
            raise ValueError(f"rotation 应为 9 元素行主序，实得 {len(self.rotation)} 个")
        rows = [self.rotation[index * 3:(index + 1) * 3] for index in range(3)]
        for i in range(3):
            for j in range(3):
                product = _dot(rows[i], rows[j])
                target = 1.0 if i == j else 0.0
                if abs(product - target) > _ORTHO_TOL:
                    raise ValueError(f"rotation 第 {i} 行与第 {j} 行不正交归一（点积 {product}）"
                                     "——逆变换按转置算会静默出错，故建框即拒")

    def matrix(self) -> Transform4x4:
        """本框 → 上层框的 4x4 位姿（行主序，mm）；要变换**位姿**（不只是点）时用。"""
        out = list(identity())
        for row in range(3):
            for col in range(3):
                out[row * 4 + col] = self.rotation[row * 3 + col]
        out[3], out[7], out[11] = self.origin_mm
        return tuple(out)


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    """三维向量点积（无量纲；仅用于正交性判定）。"""
    return sum(left[index] * right[index] for index in range(3))


def _determinant(rotation: Sequence[float]) -> float:
    """3x3 行列式（行主序 9 元素）；只为判手性：+1 右手系、−1 镜像。"""
    a, b, c = rotation[0:3]
    d, e, f = rotation[3:6]
    g, h, i = rotation[6:9]
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def axis_swap_frame(mapping: Mapping[str, str], origin_mm: Point = ZERO_POINT) -> Frame:
    """按「本框轴 → 上层框轴（**必须带符号**）」造一个纯换轴 Frame（原点另给，mm）。

    用途＝契约 §7.1 的警告「STEP 默认 Z 向上，工厂／建筑类软件常导出 Y 向上，**模型导入后
    必须先核对朝向，不得假定**」：核对出模型是 Y-up 时给 {"x": "+x", "y": "+z", "z": "-y"}。
    行列式为 −1（镜像）即拒——两框都必须右手系，手性翻了姿态会静默镜像。
    """
    columns: dict[str, tuple[float, int]] = {}
    for source, target in mapping.items():
        name = target.lstrip("+-")
        if source not in AXES_XYZ or name not in AXES_XYZ or len(target) != len(name) + 1:
            raise ValueError(f"mapping 应为「x／y／z → 带符号的 x／y／z」，实得 {source!r}: "
                             f"{target!r}")
        sign = -1.0 if target[0] == "-" else 1.0
        columns[source] = (sign, AXES_XYZ.index(name))
    if len(columns) != len(AXES_XYZ):
        raise ValueError(f"mapping 的键应恰为 {AXES_XYZ} 三个，实得 {sorted(mapping)}")
    rotation = [0.0] * 9
    for source, (sign, row) in columns.items():
        rotation[row * 3 + AXES_XYZ.index(source)] = sign
    if _determinant(rotation) < 0.0:
        raise ValueError(f"mapping {dict(mapping)} 构成镜像（行列式 −1）：两框都须右手系")
    return Frame(origin_mm, tuple(rotation))


def model_to_device(point: Point, frame: Frame) -> Point:
    """文件坐标系（模型自带）→ 设备坐标系（mm，右手系）。

    frame 描述**模型框在设备框内**的定位；模型朝向须先按契约 §7.1 核对，**不得假定 Z-up**。
    """
    return transform_point(frame.matrix(), point)


def device_to_model(point: Point, frame: Frame) -> Point:
    """设备坐标系 → 文件坐标系（mm）；`model_to_device` 的逆，往返误差见测试用例④。"""
    return _unapply(frame, point)


def device_to_scene(point: Point, frame: Frame) -> Point:
    """设备坐标系 → 场景坐标系（mm，右手系、Z 竖直向上为正，契约 §7.1）。

    frame 描述**设备框在场景框内**的定位；场景原点与 X 向该条标「待确认」→ 由 frame 给定。
    """
    return transform_point(frame.matrix(), point)


def scene_to_device(point: Point, frame: Frame) -> Point:
    """场景坐标系 → 设备坐标系（mm）；`device_to_scene` 的逆，往返误差见测试用例④。"""
    return _unapply(frame, point)


def _unapply(frame: Frame, point: Point) -> Point:
    """上层框 → 本框：Rᵀ·(p − origin)（mm）。R 正交（建框已校验）故转置即逆。"""
    delta = tuple(point[index] - frame.origin_mm[index] for index in range(3))
    rows = frame.rotation
    return tuple(sum(rows[col * 3 + row] * delta[col] for col in range(3)) for row in range(3))

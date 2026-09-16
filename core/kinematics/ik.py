"""core.kinematics.ik —— 解析逆解（T07；03 §3「逆解」行，⛔ 禁数值迭代）。

单位与坐标系（S-1 契约第 7 章）：长度 **mm**、角度 **deg**；位姿在**设备坐标系**（右手系、
Z 竖直向上为正），`Transform4x4` 为 16 元素**行主序**（平移在 3／7／11）——与 `fk` 的输出
同口径，故 `fk(ik(pose, chain), chain.model)` 往返回到 pose。返回值的**键语义与 fk 的入参
一致**：普通轴＝工程位置，`ratio` 自指轴（X3 三级筒）＝**驱动位移**（倍率读配置，禁写死）。

链拓扑、驱动绑定、运动方向**全部读 `machine.yaml`**（`links.parent` ＋ G18 的 `links.axis`／
`links.motion`），代码内不写死任何机台事实、也不复制 tests 里的合成绑定——这正是 G18 立案时
点名的两条失败模式（04 §7.2-G18）。

⚠️ **两处范围限制，都是数据缺口造成的、不是偷懒**（详见 T07 交付汇报）：
  ① **≥2 根回转副（球腕）不解**。球腕三角解要腕的连杆偏置与三轴交点，而 11 根臂专用轴
     （ZA1／ZA2／RA／ZB／FB1／FB2／ZC／FC／RC／ZD／KE）在 links 表里**没有连杆**，G19 明令
     「属问甲方动作、⛔ 不得由任何会话自行补链」⇒ 现配置产生不出腕。遇到即 IkError。
  ② **末端连杆是推导、不是配置事实**。machine.yaml 没有 tool／tcp 一类键，`tool_link` 只能按
     「驱动链最深的叶节点」推导，并列即拒（挑错即整条路径算在错的面上）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from core.config.schema import AXIS_TYPES, Axis, Link, MachineConfig
from core.kinematics.fk import Joint, KinematicModel, build_model, resolve_positions
from core.kinematics.transform import AXES_XYZ, Transform4x4, identity, rotation

PRISMATIC, REVOLUTE = AXIS_TYPES  # 同 fk：取自 schema 常量，不在代码里散写字面量
_POSE_TOL = 1e-9        # 判位姿分量一致（纯数学量、非机台参数，故不进 machine.yaml，同 transform）
_FULL_TURN_DEG = 360.0  # 回转副一整圈（deg，纯几何量）：θ 与 θ±一整圈是同姿态的多解
_ATAN2_INDEX = {"x": (9, 5), "y": (2, 10), "z": (4, 0)}  # 各转轴的 (正弦元, 余弦元) 下标


class IkError(Exception):
    """逆解失败：超行程／姿态不可达／构型不支持。消息一律人话、含轴号与数值（供路径标红该段）。"""


@dataclass(frozen=True)
class Chain:
    """`derive_chain` 的产物：fk 可复用的 model ＋ ik 要用的驱动路径与末端对应关系。

    path＝根→末端的**存活**连杆 id 序（被动连杆已摘除）；end_link＝请求的末端连杆（可能正是
    被摘掉的那个，如现场链的 flange）；effective_end＝位姿与 end_link 相同的存活连杆（如 tube3）。
    """

    model: KinematicModel
    path: tuple[str, ...]
    end_link: str
    effective_end: str


def tool_link(cfg: MachineConfig) -> str:
    """推导末端连杆（工具安装面）＝驱动链里**最深的叶节点**；并列即 IkError。

    现场链上 flange（快接法兰＝当前所挂多功能臂的挂载点）深 8 级、五个安装架深 5 级 ⇒ 唯一。
    ⚠️ 推导而非配置事实（见模块 docstring ②）：并列时**绝不静默挑一个**，裁决补键后改读该键。
    """
    by_id = {link.id: link for link in cfg.links}
    parents = {link.parent for link in cfg.links if link.parent is not None}
    depths = {link.id: len(_path_to(by_id, link.id)) for link in cfg.links if link.id not in parents}
    deepest = max(depths.values())
    tied = sorted(name for name, depth in depths.items() if depth == deepest)
    if len(tied) != 1:
        raise IkError(f"末端连杆推导不唯一：{tied} 同为最深叶节点（{deepest} 级）"
                      f"——须由配置显式指定，禁静默挑一个")
    return tied[0]


def derive_chain(cfg: MachineConfig, end_link: str | None = None) -> Chain:
    """从配置推导 ik 用的链（G18 两键即绑定来源），返回可反复复用的 `Chain`。

    `end_link` 省略时按 `tool_link` 推导。**被动连杆**（无驱动轴的非根连杆，如 flange）被摘除、
    其子级重挂到最近的存活祖先：fk 对无绑定的连杆只能给 identity（没有 motion 就无从施加
    length_mm），故摘除等价——但**仅当其 length_mm 为 0**；非零即 IkError，因为静默丢掉一段
    偏置＝静默算错位置（现场 13 条连杆的 length_mm 现全为占位 0.0，故当前恒等价）。
    """
    target = tool_link(cfg) if end_link is None else end_link
    by_id = {link.id: link for link in cfg.links}
    if target not in by_id:
        raise IkError(f"末端连杆 `{target}` 不在 links 表内（表内：{sorted(by_id)}）")
    kept = _driven_links(cfg, by_id)
    joints = [Joint(link.id, link.motion, link.axis) for link in kept if link.axis is not None]
    model = build_model(replace(cfg, links=kept), joints)
    path = tuple(name for name in _path_to(by_id, target) if name in model.links)
    return Chain(model, path, target, path[-1])


def _path_to(by_id: Mapping[str, Link], end_link: str) -> tuple[str, ...]:
    """根→end_link 的连杆 id 序（含两端）；parent 无环连通已由加载器保证，仍设轮次上限兜底。"""
    path = [end_link]
    for _ in range(len(by_id) + 1):
        parent = by_id[path[-1]].parent
        if parent is None:
            return tuple(reversed(path))
        path.append(parent)
    raise IkError(f"links 的 parent 关系成环，无法自 `{end_link}` 上溯到根")


def _driven_links(cfg: MachineConfig, by_id: Mapping[str, Link]) -> tuple[Link, ...]:
    """摘掉被动连杆、把其子级重挂到最近的存活祖先，返回 `build_model` 能接受的 links 表。

    重挂要沿 parent **上溯到最近的存活者**（不能只挂一层）：被动连杆可能连着被动连杆。
    """
    kept: list[Link] = []
    for link in cfg.links:
        if link.parent is None:
            kept.append(link)                    # 根：fk 本就允许无绑定
            continue
        if link.axis is None:
            if link.length_mm != 0.0:
                raise IkError(f"连杆 `{link.id}` 无驱动轴却有 length_mm={link.length_mm:g} mm："
                              f"没有运动方向就无从施加这段偏置，摘除即静默算错位置——须先裁决"
                              f"被动偏置怎么表达（详见 T07 汇报的登记项）")
            continue
        parent = link.parent
        while by_id[parent].axis is None and by_id[parent].parent is not None:
            parent = by_id[parent].parent
        kept.append(replace(link, parent=parent))
    return tuple(kept)


def ik(target_pose: Transform4x4, chain: Chain,
       seed: Mapping[str, float] | None = None) -> dict[str, float]:
    """解析逆解：目标位姿 → 各轴输入值（闭式，⛔ 无牛顿／雅可比／CCD 一类数值迭代）。

    解法＝桁架与腕解耦（03 §3）。**位置**：链上移动副沿设备轴平移、后缀之前无旋转累积，故每个
    方向就是一条线性方程；方程欠定（现场 x 向有 X1／X2／X3 三根轴、z 向有 Z1／Z2 两根）⇒ 按
    `_allocate` 取「离 seed 最近且全在行程内」的那一组，即卡的「多解按行程／连续性选解」。
    **姿态**：见 `_solve_orientation`（0 根回转＝只能是单位阵；1 根＝atan2 闭式；≥2 根＝拒）。

    `seed`＝上一次解（fk 入参语义，缺省全零位），只用于在无穷多解里选连续的那一支，**不参与
    可达性判定**。解不出一律 IkError，消息含轴号与数值。
    """
    if len(target_pose) != 16:
        raise IkError(f"target_pose 应为 16 元素行主序位姿，实得 {len(target_pose)} 个")
    axes = chain.model.cfg.axes
    start = resolve_positions(seed or {}, chain.model.cfg)
    values = _solve_positions(target_pose, chain, axes, start)
    values.update(_solve_orientation(target_pose, chain, axes, start))
    return _to_input(values, axes)


def _solve_positions(pose: Transform4x4, chain: Chain, axes: Mapping[str, Axis],
                     start: Mapping[str, float]) -> dict[str, float]:
    """逐方向攒出并解位置方程，返回各移动副轴的**工程位置**（mm）；不可达即 IkError。

    方程依据＝fk._local_transform 的语义：每级先沿 motion 偏 length_mm（常量），再叠加移动副位移
    （未知量）或绕 motion 的回转（只影响姿态，其 length_mm 仍算常量）。根连杆无绑定 ⇒ fk 给
    identity、其 length_mm 不参与，故这里也跳过——与 fk 逐字同口径，往返才闭合。系数与常量
    **全部读配置**，不写死任何机台事实。
    """
    links, joints = chain.model.links, chain.model.joints
    offsets: dict[str, float] = {}
    tally: dict[str, dict[str, int]] = {}
    for link_id in chain.path:
        joint = joints.get(link_id)
        if joint is None:
            continue
        offsets[joint.motion] = offsets.get(joint.motion, 0.0) + links[link_id].length_mm
        axis = axes[joint.axis_id] if joint.axis_id is not None else None
        if axis is None or axis.type != PRISMATIC:
            continue
        coupling = axis.coupling
        # 跨轴 `ratio` 从动轴的工程位置被主动轴定死（resolve_positions 覆盖入参）⇒ 不是自由
        # 未知量，遇到即拒并交裁决，⛔ 不静默按某个值处理（错的约束会一路带到现场）。现配置无
        # 此情形：X3 的 master 指向**自身**＝驱动级倍速，是可解的（03 §4／T04 定案口径）。
        if coupling is not None and coupling.type == "ratio" and coupling.master != axis.id:
            raise IkError(f"轴 {axis.id} 是跨轴倍速从动轴（master={coupling.master}），工程位置由"
                          f"主动轴定死、不是自由未知量——该构型的逆解须先裁决链定义")
        counts = tally.setdefault(joint.motion, {})
        counts[axis.id] = counts.get(axis.id, 0) + 1
    out: dict[str, float] = {}
    for motion in AXES_XYZ:
        offset = offsets.get(motion, 0.0)
        want = pose[AXES_XYZ.index(motion) * 4 + 3] - offset
        entries = sorted(tally.get(motion, {}).items())
        if not entries:
            if abs(want) > _POSE_TOL:
                raise IkError(f"链上没有沿 {motion} 的移动副，达不到该方向分量 {want:g} mm"
                              f"（当前构型只能到 {offset:g} mm）")
            continue
        names = [name for name, _ in entries]
        counts = [count for _, count in entries]
        # 令 u ＝ 出现次数 × 工程位置：方程化为 Σu = want，而 u 的可用区间按同一次数等比放大
        # 即可（次数恒为正，上下界不翻转）；解出 u 再除回次数得工程位置。
        spans = [axes[name].travel for name in names]
        bounds = [(low * count, high * count) for (low, high), count in zip(spans, counts)]
        seeds = [start.get(name, 0.0) * count for name, count in zip(names, counts)]
        for name, count, value in zip(names, counts, _allocate(want, names, seeds, bounds)):
            out[name] = value / count
    return out


def _allocate(total: float, names: Sequence[str], seeds: Sequence[float],
              bounds: Sequence[tuple[float, float]]) -> list[float]:
    """解「Σx = total、low ≤ x ≤ high，使 Σ(x − seed)² 最小」——闭式、有限步、无收敛判据。

    这是带一个等式约束的可分离二次规划，KKT 给出 x_i = clamp(seed_i + λ, low_i, high_i)，只剩
    一个 λ 待定。求 λ 用「越界者钳到边界、余量在自由者间均分」：每轮**至少钉住一根轴**，故至多
    n 轮精确结束——没有容差判停、没有残差下降、没有最大迭代次数，⛔ 不是 T07 卡与 03 §3 禁的
    那类数值迭代。钳位一律赋**边界原值**（不做加减），故解落在行程边界上时不会被浮点误差推出界
    ——出界一根轴，T08 的 check_limits 就会把一个本可达的点判成越界。

    ⚠️ seed 先**投影进行程**再均分：seed 是偏好、不是可行点（`resolve_positions` 出来的工程位置
    可能在行程外——自指倍速轴把驱动位移放大后尤甚，travel 下界 > 0 的轴给零位 seed 亦然）。按
    不可行的 seed 和算 residual，λ 的方向与量级都会判错，把本该动的轴钉死在边界上，**静默返回
    Σ≠total 的解**＝静默算错位姿。可行性只由上面的行程合计判定，投影不改变它。
    """
    lows = [bound[0] for bound in bounds]
    highs = [bound[1] for bound in bounds]
    if total < sum(lows) - _POSE_TOL or total > sum(highs) + _POSE_TOL:
        raise IkError(f"{'／'.join(names)} 合不出 {total:g} mm：行程合计只到 "
                      f"[{sum(lows):g}, {sum(highs):g}] mm（各轴行程见 machine.yaml）")
    values = [min(max(seed, low), high) for seed, low, high in zip(seeds, lows, highs)]
    free = set(range(len(seeds)))
    for _ in range(len(seeds) + 1):
        residual = total - sum(values)
        if not free or abs(residual) <= _POSE_TOL:
            return values
        share = residual / len(free)
        pinned = False
        for index in sorted(free):
            candidate = values[index] + share
            if candidate < lows[index] or candidate > highs[index]:
                values[index] = lows[index] if candidate < lows[index] else highs[index]
                free.discard(index)
                pinned = True
            else:
                values[index] = candidate
        if not pinned:
            return values
    return values


def _solve_orientation(pose: Transform4x4, chain: Chain, axes: Mapping[str, Axis],
                       start: Mapping[str, float]) -> dict[str, float]:
    """姿态：0 根回转副 ⇒ 只能是单位阵（现场桁架链即此支）；1 根 ⇒ atan2 闭式并按行程／
    seed 在 θ 与 θ±一整圈里选解；≥2 根 ⇒ IkError（球腕，见模块 docstring ①）。

    回转副须构成链的**后缀**：一旦出现回转副、其后不得再有移动副——fk 是 multiply(parent,
    local) 的链式累积，移动副排在回转之后，其平移就被旋到别的方向、位置方程不再线性 ⇒ 解析解
    不成立，遇到即 IkError。
    """
    spinning: list[tuple[str, str]] = []
    for link_id in chain.path:
        joint = chain.model.joints.get(link_id)
        if joint is None or joint.axis_id is None:
            continue
        if axes[joint.axis_id].type == REVOLUTE:
            spinning.append((joint.axis_id, joint.motion))
        elif spinning:
            raise IkError(f"连杆 `{link_id}` 的移动副排在回转副之后：其平移会被前面的旋转到"
                          f"别的方向，位置方程不再线性 ⇒ 该构型的解析逆解不成立")
    if len(spinning) > 1:
        raise IkError(f"链上有 {len(spinning)} 根回转副（{[name for name, _ in spinning]}）："
                      f"球腕三角解要腕的连杆偏置与三轴交点，而臂专用轴在 links 表里没有连杆、"
                      f"G19 明禁自行补链 ⇒ 本单不解该构型")
    if not spinning:
        _require_rotation(pose, identity(),
                          "链上没有回转副（工具姿态由安装固定），达不到带旋转的目标姿态"
                          "——若确需姿态，须先由甲方回执补齐臂链（G19）")
        return {}
    axis_id, motion = spinning[0]
    sine, cosine = _ATAN2_INDEX[motion]
    theta = math.degrees(math.atan2(pose[sine], pose[cosine]))
    _require_rotation(pose, rotation(motion, theta),
                      f"绕 {motion} 的单回转轴合不出目标姿态（回代 9 元不符）——需 ≥2 根回转副")
    low, high = axes[axis_id].travel
    turns = (theta, theta - _FULL_TURN_DEG, theta + _FULL_TURN_DEG)
    picks = [value for value in turns if low <= value <= high]
    if not picks:
        raise IkError(f"轴 {axis_id} 的姿态解 {theta:g}°（及 ±一整圈）全在行程 "
                      f"[{low:g}, {high:g}]° 之外")
    return {axis_id: min(picks, key=lambda value: abs(value - start.get(axis_id, 0.0)))}


def _require_rotation(pose: Transform4x4, reference: Transform4x4, why: str) -> None:
    """核对目标位姿的旋转 9 元与 reference 一致，不一致即 IkError(why)。

    单回转轴的闭式解只用了两个矩阵元，故必须回代核对全 9 元——否则「姿态其实要两根轴」会被
    静默当成可达（⛔ 静默丢姿态是最难查的一类错）。
    """
    if any(abs(pose[row * 4 + col] - reference[row * 4 + col]) > _POSE_TOL
           for row in range(3) for col in range(3)):
        raise IkError(why)


def _to_input(eng: Mapping[str, float], axes: Mapping[str, Axis]) -> dict[str, float]:
    """工程位置 → fk 的入参语义：`ratio` 自指轴（X3）返回**驱动位移**＝工程位置 ÷ ratio。

    倍率一律读配置（⛔ 禁在代码里写死），其余轴工程位置即入参；如此 fk(ik(pose)) 才往返闭合。
    """
    out: dict[str, float] = {}
    for axis_id, value in eng.items():
        coupling = axes[axis_id].coupling
        driven = coupling is not None and coupling.type == "ratio" and coupling.master == axis_id
        out[axis_id] = value / coupling.ratio if driven else value
    return out

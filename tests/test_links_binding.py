"""tests/test_links_binding.py —— G18 links 驱动绑定两键（axis／motion）的校验用例（T07 代 T03）。

凭据＝04 §7.2-G18 行＋§4 矩阵「第二授权例外」（@user 2026-09-16 22:10 授权 T07 跨归属落地）。
G18 硬约束 (b)(c) 要求 `tests/test_config.py` 的 24 条用例**全绿且不改断言**、各 `bad_*` 的
「共 N 项问题」计数不变——故 G18 的新增覆盖**全部落在本文件**，test_config.py 一个字不动。

三条纪律（承 tests/test_config.py 与 04 §5.5 附7）：
  ① 缺陷注入一律在 tmp_path 现场生成变体，**禁写死仓内绝对路径**（仓根随 worktree／合并位置变）；
  ② 断言「共 N 项问题」的**计数**而不只关键词——一处缺陷必须只出一条消息，计数虚高即误导现场；
  ③ 缺陷注入在 ok_minimal 的 `links` 节（该节不被 axes／modes 引用），避免一处缺陷级联出多条。
"""

from __future__ import annotations

import pathlib
import re
from collections.abc import Callable

import pytest
import yaml

from core.config import LINK_KEYS, MOTIONS, REPO_ROOT, ConfigError, Link, load_machine

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
BASELINE = FIXTURES / "ok_minimal.yaml"
SAMPLE = REPO_ROOT / "config" / "machine.yaml"
COUNT = re.compile(r"共 (\d+) 项问题")
DROP = object()          # 哨兵：mutate 里用它表示「把这个键整条删掉」（区别于显式写 null）

# 现场样例 13 条连杆的绑定预期（G18 **占位**口径：按轴代号字母填 motion，理由与反例见
# config/machine.yaml 的 links 注释块——X2 名为「升降架」却代号 X，故字母不足以定方向，
# 踏勘第 7 项回执到后只改 yaml、不改 fk／ik，届时本表随之更新）。
SAMPLE_BINDINGS: tuple[tuple[str, str | None, str | None], ...] = (
    ("base", None, None), ("gantry", "X1", "x"), ("frame", "Z1", "z"),
    ("carriage", "Y1", "y"), ("arm_lift", "X2", "x"), ("arm", "Z2", "z"),
    ("tube3", "X3", "x"), ("flange", None, None), ("mount_a", "YA", "y"),
    ("mount_b", "YB", "y"), ("mount_c", "YC", "y"), ("mount_d", "YD", "y"),
    ("mount_e", "YE", "y"),
)
DRIVEN_COUNT = len(SAMPLE_BINDINGS) - 2      # 减去 base／flange 两条无驱动轴的


def _variant(tmp_path: pathlib.Path, mutate: Callable[[dict], None]) -> pathlib.Path:
    """以 ok_minimal.yaml 为基线改一处后写到 tmp_path（纪律 ①：不写死仓内路径）。"""
    data = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
    mutate(data)
    out = tmp_path / "links_variant.yaml"
    out.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return out


def _edit_gantry(**fields: object) -> Callable[[dict], None]:
    """造一个只改 gantry（第 2 条连杆）绑定键的 mutate；值为 DROP 表示删键、None 表示写 null。"""
    def mutate(data: dict) -> None:
        for key, value in fields.items():
            if value is DROP:
                data["links"][1].pop(key)
            else:
                data["links"][1][key] = value
    return mutate


def _problems(path: pathlib.Path) -> tuple[int, str]:
    """加载 path 并断言必抛 ConfigError，返回（问题项数，消息全文）供逐项断言。"""
    with pytest.raises(ConfigError) as caught:
        load_machine(str(path))
    message = str(caught.value)
    found = COUNT.search(message)
    assert found, f"消息未按「共 N 项问题」格式汇总：\n{message}"
    return int(found.group(1)), message


# (缺陷描述, mutate, 期望问题项数, 消息里必须出现的片段)
ILLEGAL_BINDINGS = [
    ("axis 指向不存在的轴", _edit_gantry(axis="GHOST"), 1, ("links[gantry].axis", "axes 表内")),
    ("axis 类型错（数字）", _edit_gantry(axis=5), 1, ("links[gantry].axis", "5")),
    ("motion 取值非法", _edit_gantry(motion="q"), 1, ("links[gantry].motion", "x|y|z")),
    ("motion 类型错（数字）", _edit_gantry(motion=7), 1, ("links[gantry].motion", "7")),
    ("axis 有值而 motion 写 null", _edit_gantry(motion=None), 1, ("同时有值或同时为 null",)),
    ("axis 写 null 而 motion 有值", _edit_gantry(axis=None), 1, ("同时有值或同时为 null",)),
    ("缺 axis 键", _edit_gantry(axis=DROP), 1, ("缺必填字段 `axis`",)),
    ("缺 motion 键", _edit_gantry(motion=DROP), 1, ("缺必填字段 `motion`",)),
    ("两键都缺", _edit_gantry(axis=DROP, motion=DROP), 2,
     ("缺必填字段 `axis`", "缺必填字段 `motion`")),
]


# --------------------------------------------------------------------------
# ① 合法侧：占位口径钉死 ＋ 两键的解析形态
# --------------------------------------------------------------------------

def test_sample_bindings_match_the_ruling() -> None:
    """现场样例 13 条连杆的 axis／motion 必须与 G18 裁决的占位表**逐条逐序**一致。

    钉死它是为了防后续会话「顺手把 motion 改成看着对的方向」——回执未到前任何改动都是
    把占位值伪装成实测值（同 length_mm 全 0.0 的口径）。
    """
    cfg = load_machine(str(SAMPLE))
    assert [(link.id, link.axis, link.motion) for link in cfg.links] == list(SAMPLE_BINDINGS)


def test_bare_yaml_motion_letters_stay_strings() -> None:
    """YAML 1.1 把 yes／no／on／off 解析成 bool ⇒ 裸写的 `y` 必须是字符串，否则 motion 会被误拒。

    这条是**实测出来的陷阱**而非假想：若解析成 True，`motion not in MOTIONS` 即成立、样例直接拒载。
    """
    cfg = load_machine(str(SAMPLE))
    assert MOTIONS == ("x", "y", "z")
    assert all(isinstance(link.motion, str) for link in cfg.links if link.motion is not None)


def test_link_keys_cover_the_two_new_fields() -> None:
    """两键列入 LINK_KEYS ⇒ test_config.py「必填键逐个显式写出」用例自动成为 G18 的守卫。"""
    assert LINK_KEYS == ("id", "length_mm", "parent", "axis", "motion")


def test_new_fields_default_to_none_so_t04_positional_build_holds() -> None:
    """T04 已验收用例以 ``Link(id, length_mm, parent)`` 位置构造 ⇒ 两新字段必须带 None 默认值。

    这不是可有可无的便利：`tests/test_kinematics.py` 有四处这样构造，缺默认值即 T04 用例全红。
    """
    link = Link("tool", 120.0, "flange")
    assert link.axis is None and link.motion is None


def test_undriven_link_with_both_null_loads(tmp_path: pathlib.Path) -> None:
    """axis／motion 双 null 是合法的「无驱动轴连杆」（base／flange 那类），不得拒载。"""
    cfg = load_machine(str(_variant(tmp_path, _edit_gantry(axis=None, motion=None))))
    assert cfg.links[1].axis is None and cfg.links[1].motion is None


def test_all_eight_fixtures_carry_the_two_keys() -> None:
    """G18 硬约束 (b)：8 个样例全部补齐两键——漏一个即 test_config.py 的必填键用例红。"""
    paths = sorted(FIXTURES.glob("*.yaml"))
    assert len(paths) == 8, f"样例数变了（原 8 个）：{[path.name for path in paths]}"
    for path in paths:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for index, link in enumerate(data["links"]):
            assert {"axis", "motion"} <= set(link), f"{path.name} 第 {index} 条连杆缺 G18 两键"


# --------------------------------------------------------------------------
# ② 非法侧：逐类拒载，且**一处缺陷只出一条消息**
# --------------------------------------------------------------------------

@pytest.mark.parametrize("label,mutate,count,tokens", ILLEGAL_BINDINGS,
                         ids=[case[0] for case in ILLEGAL_BINDINGS])
def test_one_defect_yields_exactly_one_problem(tmp_path: pathlib.Path, label: str,
                                               mutate: Callable[[dict], None], count: int,
                                               tokens: tuple[str, ...]) -> None:
    """每类绑定缺陷都必须拒载，且问题项数与注入缺陷数一致（纪律 ②：计数虚高＝误导现场）。"""
    total, message = _problems(_variant(tmp_path, mutate))
    assert total == count, f"{label}：期望 {count} 项，实得消息：\n{message}"
    for token in tokens:
        assert token in message, f"{label}：消息缺 `{token}`：\n{message}"


def test_missing_key_does_not_also_report_pairing(tmp_path: pathlib.Path) -> None:
    """缺键与「配对错」本质是同一处要改 ⇒ 只报缺键一条，不得再报一条配对（否则计数翻倍）。

    实现手法＝缺任一键的连杆**不进** links 表（validate.links_section），故跨节校验看不到它。
    """
    total, message = _problems(_variant(tmp_path, _edit_gantry(axis=DROP)))
    assert total == 1, f"缺 axis 键应只报一条，实得：\n{message}"
    assert "同时有值或同时为 null" not in message


def test_wrong_axis_type_reports_once_not_twice(tmp_path: pathlib.Path) -> None:
    """axis 写成数字只走「不在 axes 表内」这一条，不再另报类型错（同为一处缺陷）。"""
    total, message = _problems(_variant(tmp_path, _edit_gantry(axis=5)))
    assert total == 1, f"axis 类型错应只报一条，实得：\n{message}"
    assert "应为 axes 表内 id 或 null" in message


# --------------------------------------------------------------------------
# ③ 跨节不变量（对现场样例直接断言，防后续改 yaml 改坏）
# --------------------------------------------------------------------------

def test_every_bound_axis_exists_and_motion_in_domain() -> None:
    """凡 axis 非 null 的连杆，其轴必在 axes 表内、motion 必在取值域内（加载器的跨节判据同源）。"""
    cfg = load_machine(str(SAMPLE))
    driven = [link for link in cfg.links if link.axis is not None]
    assert len(driven) == DRIVEN_COUNT, "13 条里只有 base／flange 无驱动轴"
    for link in driven:
        assert link.axis in cfg.axes, f"{link.id} 绑的 {link.axis} 不在 axes 表内"
        assert link.motion in MOTIONS, f"{link.id} 的 motion={link.motion!r} 不在取值域内"


def test_setup_axes_drive_only_the_mount_links() -> None:
    """工序级轴（role=setup，软件只读）只能绑安装架连杆，不得混进轨迹链——否则 ik 会把
    只读轴当未知量解，而它根本不进下发段（03 §4「实机轴系口径」）。"""
    cfg = load_machine(str(SAMPLE))
    for link in cfg.links:
        if link.axis is None:
            continue
        role = cfg.axes[link.axis].role
        if role == "setup":
            assert link.id.startswith("mount_"), f"工序级轴 {link.axis} 绑到了 {link.id}"
        else:
            assert not link.id.startswith("mount_"), f"轨迹级轴 {link.axis} 绑到了安装架 {link.id}"


def test_no_axis_drives_two_links() -> None:
    """一根轴至多驱动一根连杆（占位口径下如此）。

    ⚠️ 这**不是**物理定律而是当前拓扑的核记：若回执后确有一轴驱两连杆，ik 的位置方程仍按方向
    求和（同一未知量出现两次），本断言须随配置一起改——属配置变更，不是代码缺陷。
    """
    cfg = load_machine(str(SAMPLE))
    bound = [link.axis for link in cfg.links if link.axis is not None]
    assert len(bound) == len(set(bound)), f"有轴被重复绑定：{sorted(bound)}"


def test_flange_is_a_leaf_and_the_last_driven_link() -> None:
    """flange（快接法兰＝当前所挂多功能臂的挂载点）无驱动轴、且是驱动链的末端。

    ik 解到 flange 即工具安装面：它无自己的未知量，故其位姿与父级 tube3 相同（length_mm 占位
    0.0 时严格相等）——T07 的 ik 正是靠这点把「无驱动的被动连杆」从链里摘出去而不失真。
    """
    cfg = load_machine(str(SAMPLE))
    by_id = {link.id: link for link in cfg.links}
    flange = by_id["flange"]
    assert flange.axis is None and flange.motion is None
    assert flange.parent == "tube3" and by_id["tube3"].axis == "X3"
    assert not [link for link in cfg.links if link.parent == "flange"], "flange 应为叶节点"

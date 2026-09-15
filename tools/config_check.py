"""tools/config_check.py —— machine.yaml 命令行校验器（T03；现场排障用）。

跑法（仓根）：`python tools/config_check.py config/machine.yaml`
退出码：0＝校验通过；1＝校验不通过（ConfigError 消息原文打印，含**全部**问题项）；2＝用法错。

通过时打印「当前生效值摘要」：现场当面核对软件用的是哪份参数（轴数／角色分布／工作模式
轴子集／限值／缓存目录），也是「界面零硬编码、参数只在 yaml」的现场证据。pending 占位轴
按加载器口径**只告警不拒绝**，告警原文一并打印。

⚠️ 摘要里不含任何甲方几何数据，可截图入库；但若同时截了三维视口画面，按 04 §4 矩阵
`evidence/` 行的规定，含甲方名称或工件尺寸的画面一律不入库。
"""

from __future__ import annotations

import os
import sys

# `python tools/config_check.py` 的 sys.path[0] 是 tools/ 而非仓根，故先补仓根才能 import core.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import ConfigError, load_machine  # noqa: E402
from core.config.schema import MachineConfig  # noqa: E402


def _print_axes(cfg: MachineConfig) -> None:
    """轴表摘要：总数、角色分布、耦合轴、pending 轴。"""
    axes = list(cfg.axes.values())
    trajectory = [a.id for a in axes if a.role == "trajectory"]
    setup = [a.id for a in axes if a.role == "setup"]
    print(f"轴数 {len(axes)}：轨迹级 {len(trajectory)}（{'、'.join(trajectory)}）")
    print(f"          工序级 {len(setup)}（{'、'.join(setup)}）—— 软件只读，不进下发段")
    for axis in axes:
        if axis.coupling:
            detail = (f"group={axis.coupling.group} sync_tol_mm={axis.coupling.sync_tol_mm}"
                      if axis.coupling.type == "sync"
                      else f"master={axis.coupling.master} ratio={axis.coupling.ratio}")
            print(f"  耦合 {axis.id}: {axis.coupling.type} {detail}")


def _print_modes(cfg: MachineConfig) -> None:
    """工作模式摘要：每模式的轴子集与其中轨迹级轴计数（上限见 schema.TRAJECTORY_AXES_MAX）。"""
    for mode in cfg.modes:
        count = sum(1 for axis_id in mode.axes if cfg.axes[axis_id].role == "trajectory")
        print(f"  {mode.id}（{mode.name}）: {len(mode.axes)} 轴，其中轨迹级 {count} → "
              f"{'、'.join(mode.axes)}")


def _print_runtime(cfg: MachineConfig) -> None:
    """限值、OPC UA 与落盘路径摘要。"""
    print("限值 limits：")
    for key, value in vars(cfg.limits).items():
        print(f"  {key} = {value}")
    read_nodes, write_nodes = cfg.opcua.read_nodes, cfg.opcua.write_nodes
    print(f"OPC UA：{cfg.opcua.endpoint_url}  策略={cfg.opcua.security_policy}  "
          f"ns={cfg.opcua.ns_index}  pack_profile={cfg.opcua.pack_profile}")
    print(f"  回读节点：axis_pos {len(read_nodes['axis_pos'])} 个、status、heartbeat；"
          f"下发节点：cmd、seg_count、seg_array")
    print(f"  publish_interval_ms = {cfg.opcua.publish_interval_ms}")
    print(f"连杆 links：{len(cfg.links)} 节（{', '.join(link.id for link in cfg.links)}）")
    print(f"缓存目录 paths.cache_dir = {cfg.paths.cache_dir}（仓外，校验通过）")


def main(argv: list[str]) -> int:
    """入口：argv[1] 为配置文件路径（缺失即用法错，退出码 2）。"""
    for stream in (sys.stdout, sys.stderr):  # 本机控制台 GBK，不转 UTF-8 中文即乱码／自身抛错
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if len(argv) != 2:
        print("用法：python tools/config_check.py <machine.yaml 路径>", file=sys.stderr)
        return 2
    path = argv[1]
    try:
        cfg = load_machine(path)
    except ConfigError as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(f"[OK] {path} 校验通过")
    print(f"machine：{cfg.machine.name}  schema_ver={cfg.machine.schema_ver}")
    _print_axes(cfg)
    print("工作模式 modes：")
    _print_modes(cfg)
    _print_runtime(cfg)
    for warning in cfg.warnings:
        print(f"[WARN] {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

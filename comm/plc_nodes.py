"""comm.plc_nodes —— 把 machine.yaml 的点表镜像成 OPC UA 地址空间（T09 模拟器的建树半边）。

从 ``comm/simulator.py`` 拆出（该件实测 404→322 行，仍超 04 §4.5-① 的 300 行上限）：那边管 Server 装配与
循环扫描，本件只管**地址空间的形状**——按什么命名空间、什么层级、什么 PLC 类型建出契约 §5.1／§6.1 那两个
块的镜像节点。

**零硬编码点表**（T09 完成标准第 5 条）：节点一律用配置里的 NodeId 字符串 ``ua.NodeId.from_string`` 原样
建成，故客户端按同一个字符串 ``get_node`` 必然命中；代码里**不出现任何 ``"DB_PLC_to_SW"."Pos[0]"`` 一类
符号名字面量**——换点表只改 machine.yaml。文件里出现的 ``axis_pos``／``cmd`` 等是 **machine.yaml 的键名**
（属 ``core/config/schema.py`` 的 SPEC），不是 PLC 符号名。

层级只为可读：S7 侧符号名形如 ``"DB"."Var"``，本件按点号拆出 DB 名建文件夹、变量挂其下（``split_symbol``），
拆不出 DB 名就挂在一个防呆文件夹下——**层级不影响寻址**，寻址只认 NodeId。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from asyncua import Server, ua

from comm.opcua_client import SEG_SLOTS, WRITE_NODE_TYPES, pack_segments

log = logging.getLogger(__name__)

# §6.1 上行块的 PLC 类型。**按 machine.yaml 的键**定、不按 NodeId 里的符号名（同 WRITE_NODE_TYPES 口径）：
# Status／Ack 为 BYTE、AlarmWord 为 WORD、SeqID／CurSeg 为 INT、Heartbeat 为 DINT、Pos／Vel 为 REAL。
PUBLISH_NODE_TYPES = {"axis_pos": ua.VariantType.Float, "axis_vel": ua.VariantType.Float,
                      "status": ua.VariantType.Byte, "ack": ua.VariantType.Byte,
                      "alarm_word": ua.VariantType.UInt16, "seq_id": ua.VariantType.Int16,
                      "cur_seg": ua.VariantType.Int16, "heartbeat": ua.VariantType.Int32}
FALLBACK_DB = "Symbols"          # NodeId 不带 DB 前缀时的挂载夹名（现点表用不到，防呆）
NS_PAD_URI = "urn:mecharm:ns-pad:"   # 只为把命名空间表撑到配置的 ns_index，URI 本身无业务含义


def split_symbol(node_id: str) -> tuple[str, str]:
    """NodeId 字符串 → (DB 名, 变量名)，只用于建镜像树的层级；引号按 S7 符号写法剥掉。"""
    parts = [part.strip().strip('"')
             for part in ua.NodeId.from_string(node_id).Identifier.split(".")]
    return (parts[0], parts[-1]) if len(parts) > 1 else ("", parts[0])


def initial_value(vtype: ua.VariantType, blank: bytes = b"") -> Any:
    """建节点的初值：REAL→0.0、ByteString→整批 0 段、其余整数→0（§5.2「不得留空或填随机值」）。"""
    if vtype == ua.VariantType.Float:
        return 0.0
    return blank if vtype == ua.VariantType.ByteString else 0


def check_shape(rd: Mapping[str, list], axis_slots: int) -> None:
    """点表与 ``pack_profile`` 的形状一致性：配置错了就在这里说清楚，别等运行时槽位错位。

    加载器已按 ``PACK_PROFILE_AXIS_COUNT`` 校验过节点数（T03 的 G17 扩表），此处是**第二道**：模拟器的
    槽位数由同一个 profile 推出，两边不符即点表与 profile 只改了一边。
    """
    for key in ("axis_pos", "axis_vel"):
        found = len(rd.get(key, ()))
        if found != axis_slots:
            raise ValueError(f"read_nodes.{key} 有 {found} 个节点，但 pack_profile 定的是 "
                             f"{axis_slots} 个槽位——节点表与 profile 禁只改一边")


class NodeMirror:
    """按配置建镜像树并返回两侧句柄：``rd`` 为 键→NodeId 列表，``wr`` 为 键→单个 NodeId。"""

    def __init__(self, server: Server, ns_index: int, axis_slots: int) -> None:
        self._server = server
        self._ns = ns_index
        self._slots = axis_slots

    async def build(self, read_nodes: Mapping[str, Any],
                    write_nodes: Mapping[str, str]) -> tuple[dict[str, list[ua.NodeId]],
                                                             dict[str, ua.NodeId]]:
        """补命名空间 → 建上行块（只读）→ 建下发块（可写）→ 形状校验。"""
        await self._register_ns()
        rd = await self._mirror(read_nodes, PUBLISH_NODE_TYPES)
        blank = pack_segments((), self._slots)
        wr = await self._mirror(write_nodes, WRITE_NODE_TYPES, blank, writable=True)
        check_shape(rd, self._slots)
        log.info("镜像节点树已建：上行 %d 个键／%d 个节点，下发 %d 个键，整批段数组 %d B",
                 len(rd), sum(len(nodes) for nodes in rd.values()), len(wr), len(blank))
        return rd, {key: nodes[0] for key, nodes in wr.items()}

    async def _register_ns(self) -> None:
        """把命名空间表撑到配置的 ``ns_index``：asyncua 初始只有 2 项（实测），故按差值补注册。

        补位 URI 无业务含义——真 PLC 的 ns 表由服务器自己定，客户端只认 ns 序号与符号名。
        """
        while True:
            table = await self._server.get_namespace_array()
            if len(table) > self._ns:
                return
            await self._server.register_namespace(f"{NS_PAD_URI}{len(table)}")

    async def _mirror(self, table: Mapping[str, Any], types: Mapping[str, ua.VariantType],
                      blank: bytes = b"", writable: bool = False) -> dict[str, list[ua.NodeId]]:
        """按 NodeId 字符串建镜像节点（``"DB"."Var"`` → DB 文件夹下的变量），返回 键→NodeId 列表。

        ``writable`` 只对**下发块**为真：asyncua 建出的变量默认只读（实测客户端写即
        ``BadUserAccessDenied``），而 §5.1 的下发块由软件侧写、PLC 侧读。上行块保持只读——§6.1 的值由
        PLC 单方产生，软件侧不得写回。
        """
        objects = self._server.nodes.objects
        folders: dict[str, Any] = {}
        out: dict[str, list[ua.NodeId]] = {}
        for key, value in table.items():
            if key not in types:
                raise ValueError(f"machine.yaml 的节点键 {key!r} 在类型表里没有对应项——"
                                 f"本模拟器不猜 PLC 类型")
            items = (value,) if isinstance(value, str) else tuple(value)
            nodes = []
            for item in items:
                db, symbol = split_symbol(item)
                if db not in folders:
                    name = db or FALLBACK_DB
                    folders[db] = await objects.add_folder(ua.NodeId(name, self._ns), name)
                node = await folders[db].add_variable(
                    ua.NodeId.from_string(item), symbol, initial_value(types[key], blank),
                    varianttype=types[key])
                if writable:
                    await node.set_writable()
                nodes.append(node.nodeid)
            out[key] = nodes
        return out

"""comm.opcua_client.connect —— 会话装配、安全策略与 ``connect()`` 工厂。

**零硬编码点表**：本模块不出现任何 PLC 符号名（``"DB_SW_to_PLC"."Cmd"`` 一类字面量）。全部 NodeId 取自
``cfg.opcua``，即 machine.yaml 的 ``opcua:`` 节——改点表只改配置文件、代码零改动（T09 完成标准第 5 条）。
文中出现的 ``cmd``／``axis_pos`` 等是 **machine.yaml 的键名**（属 ``core/config/schema.py`` 的 SPEC），
不是 PLC 符号名；键名 ↔ NodeId 字符串的对应关系全在配置里。

**只连 127.0.0.1**：Q 回执冻结前禁连真 PLC（D-6）。``connect()`` 留 endpoint 覆写口子只为自测能用临时
端口起模拟器，现场口径仍是配置文件里那一个地址。

职责切分见包 ``__init__.py``：握手在 handshake.py（本模块以混入合进 ``Session``）、收数在 subscribe.py、
链路态与重连在 reconnect.py、下发编解码在 write.py、异常在 errors.py。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from asyncua import Client

from comm.opcua_client.errors import CommError
from comm.opcua_client.handshake import Handshake
from comm.opcua_client.reconnect import (HEARTBEAT_LOSS_CYCLES, OFFLINE_AFTER_S, LinkState,
                                         LinkWatchdog)
from comm.opcua_client.subscribe import MS_PER_S, Frame, ReadbackBuffer
from comm.opcua_client.write import axis_slots_of
from core.config import MachineConfig

log = logging.getLogger(__name__)

POLICY_NONE = "None"         # §3.3 安全策略「不加密」的策略名（machine.yaml 里就是这个字面量）


def apply_security(client: Client, policy: str) -> None:
    """安全策略可切换设计（T09 步骤 4）：策略名**只从 machine.yaml 读**，默认 None＝不加密＋匿名接入。

    ⚠️ 非 None 策略目前**做不到「只改配置不改码」**：认证要的用户名／密码／证书路径在 opcua 节里没有
    对应键（``OPCUA_KEYS`` 归 T03，本单无权扩）。故此处直接报错并点名 `电Q-2`（OPC UA 接入参数／安全
    策略，属《沟通单》体系；⚠️ 契约表里的同名编号指「运动控制由谁实现」，两者不是一回事，见 04 §5.7）——
    回执后须同时补配置键，已登记为 T09 遗留问题。**用户名占位**即 ``POLICY_NONE`` 分支：策略为 None 时
    匿名接入、不需要用户名，占位值无处可用也无处可写，故本模块不存任何凭据字面量。
    """
    if policy == POLICY_NONE:
        return
    raise CommError(f"security_policy={policy!r} 需要认证参数（用户名／证书），而 machine.yaml 的 "
                    f"opcua 节无对应键——待 `电Q-2`（《沟通单》体系）回执后扩键，本单不自行加")


class Session(Handshake):
    """一次 OPC UA 会话（03 §3 定死的 ``connect(endpoint,cfg)->Session`` 的返回物）。

    本类只管**连接与状态装配**：建句柄、建订阅、把回读交给 ``ReadbackBuffer``、把链路态交给
    ``LinkWatchdog``；契约 §9.1 的九步握手由混入基类 ``Handshake`` 提供，调用时同属一个对象。
    """

    def __init__(self, endpoint: str, cfg: MachineConfig, *,
                 on_frames: Callable[[list[Frame]], None] | None = None,
                 on_state: Callable[[LinkState], None] | None = None,
                 offline_after_s: float = OFFLINE_AFTER_S) -> None:
        opcua = cfg.opcua
        self.endpoint = endpoint or opcua.endpoint_url
        self.axis_slots = axis_slots_of(opcua.pack_profile)
        self._policy = opcua.security_policy
        self._interval_ms = opcua.publish_interval_ms
        self._write_nodes = opcua.write_nodes
        self._on_state = on_state
        self._buffer = ReadbackBuffer(opcua.read_nodes, on_frames=on_frames, on_rx=self._on_rx)
        # §9.1 步骤 7 的「200 ms（3 个周期）」不写死：由配置的发布周期 ×3 算出，改周期即跟着改。
        self._watchdog = LinkWatchdog(
            stale_after_s=HEARTBEAT_LOSS_CYCLES * self._interval_ms / MS_PER_S,
            offline_after_s=offline_after_s, reconnect=self._reestablish,
            on_state=self._forward_state)
        self._client: Client | None = None
        self._sub: object | None = None
        self._rd: dict[str, list] = {}
        self._wr: dict[str, object] = {}
        self._notify = asyncio.Event()
        self._seq_id = 0
        self.closed = False

    @property
    def link_state(self) -> LinkState:
        return self._watchdog.state

    @property
    def last_frame(self) -> Frame | None:
        return self._buffer.last_frame

    @property
    def frame_count(self) -> int:
        return self._buffer.frame_count

    @property
    def seq_id(self) -> int:
        return self._seq_id

    def _on_rx(self) -> None:
        """收到任何回读：刷新看门狗的新鲜度基准，并唤醒正在等应答位的握手协程。"""
        self._watchdog.touch()
        self._notify.set()

    def _forward_state(self, state: LinkState) -> None:
        if self._on_state is not None:
            self._on_state(state)

    # ── 连接与订阅 ────────────────────────────────────────────────────────────────────────

    async def open(self) -> None:
        """连接 → 建句柄 → 订阅 → 起看门狗（§9.1 步骤 7 的 20 Hz 回读由此开始）。"""
        await self._connect_once()
        self._watchdog.report(LinkState.ONLINE)
        self._watchdog.start()

    async def _connect_once(self) -> None:
        """建一次连接：节点**全部按 NodeId 取**（§3.3 禁按字节偏移读写），订阅周期取配置值。"""
        client = Client(url=self.endpoint)
        apply_security(client, self._policy)
        await client.connect()
        self._client = client
        groups = self._buffer.node_groups()
        self._rd = {key: [client.get_node(item) for item in items] for key, items in groups.items()}
        self._wr = {key: client.get_node(item) for key, item in self._write_nodes.items()}
        self._buffer.reset()
        self._sub = await client.create_subscription(self._interval_ms, self._buffer)
        await self._sub.subscribe_data_change([node for group in self._rd.values() for node in group])

    async def _teardown(self) -> None:
        if self._sub is not None:
            await self._sub.delete()
            self._sub = None
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    async def _reestablish(self) -> None:
        """§10：拆链重建，并**重新读取全部状态**（不可假设回到断线前）。看门狗注入本协程。"""
        await self._teardown()
        await self._connect_once()
        await self._resync()

    async def _resync(self) -> None:
        """逐键主动读一次：订阅只推变化量，断线期间没变的节点靠订阅永远补不回来。"""
        for key, group in self._rd.items():
            self._buffer.seed(key, await asyncio.gather(*(node.read_value() for node in group)))
        self._seq_id = self._buffer.integer("seq_id")   # §10：SeqID 不匹配→拒绝结果、重新同步
        self._buffer.emit()

    async def close(self) -> None:
        """停看门狗 → 退订 → 断开。幂等：对端已消失时再 close 也不得抛给调用方。"""
        self.closed = True
        await self._watchdog.stop()
        try:
            await self._teardown()
        except Exception as caught:
            log.warning("关闭会话时出错（已忽略）：%s: %s", type(caught).__name__, caught)
        self._watchdog.report(LinkState.OFFLINE)


async def connect(endpoint: str, cfg: MachineConfig, *,
                  on_frames: Callable[[list[Frame]], None] | None = None,
                  on_state: Callable[[LinkState], None] | None = None,
                  offline_after_s: float = OFFLINE_AFTER_S) -> Session:
    """03 §3 定死签名 ``connect(endpoint,cfg)->Session``；``endpoint`` 传空串则用配置里的地址。"""
    session = Session(endpoint, cfg, on_frames=on_frames, on_state=on_state,
                      offline_after_s=offline_after_s)
    await session.open()
    return session

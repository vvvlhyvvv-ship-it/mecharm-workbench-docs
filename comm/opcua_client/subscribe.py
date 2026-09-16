"""comm.opcua_client.subscribe —— 上行协议与回读收数：契约 §6 的状态／应答／报警字与 ``Frame``。

**回读值不做工程值换算**：§7.4「回读 ``Pos`` 是工程值还是原始计数」＝`契约 Q-10`，未回执；换算四要素
（scale／zero_offset／direction）属 T04 的 ``raw_to_eng``。comm 层照 PLC 原值上抛，**不抢在回执前定口径**。

**帧节拍取 heartbeat**（§9.1 步骤 7：PLC 每周期 ``Heartbeat`` +1）：20 个回读节点里只有它保证每周期必变；
轴静止时 ``Pos``／``Vel`` 值不变、OPC UA 不会推 datachange，若以它们为节拍会把 20 Hz 误测成 0 Hz。

**禁外推（§9.3-③）**：快照未收齐就不出帧——宁可少一帧，也不拿上一帧或零值顶（那等于预测实机位置）。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

# ── 契约 §6.2 状态字／§6.3 应答字／§6.4 报警字的位定义 ───────────────────────────────────
ST_IDLE, ST_READY, ST_RUNNING, ST_PAUSED, ST_DONE, ST_ALARM, ST_HOMED, ST_COMM_OK = (
    1 << i for i in range(8))
ACK_LOAD_OK, ACK_LOAD_NG, ACK_START_OK, ACK_START_NG, ACK_STOP_DONE, ACK_RESET_DONE, ACK_HOME_DONE = (
    1 << i for i in range(7))
ALARM_LIMIT, ALARM_SERVO, ALARM_FOLLOW, ALARM_SYNC, ALARM_UNREACHABLE, ALARM_RANGE, ALARM_SAFETY, \
    ALARM_ESTOP = (1 << i for i in range(8))

# §6.4 报警位的中文说明（§10「显示报警位对应中文说明＋建议动作」）。键用上面的位常量，不写数字。
# ⚠️ bit3「双驱同步误差超限」按 §6.4 在 `契约 Q-9` 确认前**不启用**，故本包不产生该位。
ALARM_TEXT = {ALARM_LIMIT: "软限位超程", ALARM_SERVO: "伺服报警", ALARM_FOLLOW: "跟随误差超限",
              ALARM_SYNC: "双驱同步误差超限", ALARM_UNREACHABLE: "目标点不可达",
              ALARM_RANGE: "数据越界", ALARM_SAFETY: "安全回路动作", ALARM_ESTOP: "急停"}

HEARTBEAT_KEY = "heartbeat"  # 帧节拍取自这个**配置键**（不是 PLC 符号名）
MS_PER_S = 1000.0            # §7.2 时间单位 ms；配置里的 publish_interval_ms 换算成秒用


def describe_alarm(word: int) -> tuple[str, ...]:
    """§6.4 报警字 → 中文说明元组（按位序）。无报警位时返回空元组。"""
    return tuple(text for bit, text in sorted(ALARM_TEXT.items()) if word & bit)


@dataclass(frozen=True)
class Frame:
    """03 §3 定死的回读数据单元：``Frame`` ＝ 时间戳 ＋ 各轴工程值。

    ``t`` 取 ``time.monotonic()``——只用于频率与新鲜度统计，不受系统钟跳变影响；上屏显示的墙钟时刻由
    调用方自行换算，comm 层不碰。位字段（status／ack／alarm_word）按原值给出，判位用本模块的常量。
    """

    t: float
    heartbeat: int
    pos: tuple[float, ...]
    vel: tuple[float, ...]
    status: int
    ack: int
    alarm_word: int
    seq_id: int
    cur_seg: int

    @property
    def running(self) -> bool:
        return bool(self.status & ST_RUNNING)

    @property
    def done(self) -> bool:
        return bool(self.status & ST_DONE)

    @property
    def alarms(self) -> tuple[str, ...]:
        return describe_alarm(self.alarm_word)


class ReadbackBuffer:
    """订阅侧收数器：NodeId→(键, 槽位) 反查、最新值快照、按 heartbeat 节拍出帧。

    本对象**就是** asyncua 的 datachange 回调宿主（``create_subscription`` 的 handler 参数）。回调在
    asyncua 内部任务里同步执行，故只做「存值＋唤醒＋出帧」，重活留给等待方。

    反查表由 machine.yaml 的 NodeId 字符串直接建（``node.nodeid.to_string()`` 与其逐字相同，已实测），
    因此本类不认任何具体符号名——换点表只改配置文件。
    """

    def __init__(self, read_nodes: Mapping[str, object],
                 on_frames: Callable[[list[Frame]], None] | None = None,
                 on_rx: Callable[[], None] | None = None) -> None:
        self._on_frames, self._on_rx = on_frames, on_rx
        self._key_by_node: dict[str, tuple[str, int]] = {}
        self._snap: dict[str, list] = {}
        self._groups: dict[str, tuple[str, ...]] = {}
        for key, value in read_nodes.items():
            items = (value,) if isinstance(value, str) else tuple(value)
            self._groups[key] = items
            for index, item in enumerate(items):
                self._key_by_node[item] = (key, index)
            self._snap[key] = [None] * len(items)
        self.last_frame: Frame | None = None
        self.frame_count = 0          # 只计数不留帧：长跑会话不得无界攒数据

    def node_groups(self) -> dict[str, tuple[str, ...]]:
        """节点表统一成「键 → NodeId 元组」（标量键也归一成单元素元组）。

        Session 建句柄与重连后逐键重读都按这个形状走，``str``／``tuple`` 的分支只在本类判一次。
        """
        return self._groups

    def reset(self) -> None:
        """把快照清回「未收齐」。重连时必调——订阅只推变化量，旧值沿用等于拿过期数据当真值。

        ⚠️ 此处**不**触发 on_rx：清快照不是「收到数据」，若顺手刷新新鲜度基准，看门狗的离线判定
        就会被一次次推迟，T09 完成标准第 4 条的「5 s 内判离线」直接失效。
        """
        for slots in self._snap.values():
            for index in range(len(slots)):
                slots[index] = None

    def _data_arrived(self) -> None:
        if self._on_rx is not None:
            self._on_rx()

    def value(self, key: str, index: int = 0) -> object:
        """取某配置键的最新值（数组键给槽位号）。未收到过则为 None。"""
        return self._snap[key][index]

    def integer(self, key: str) -> int:
        """取标量键的整值；未收到过按 0（判位时 0 即「无任何位」，不会误判成 OK）。"""
        return int(self._snap[key][0] or 0)

    def seed(self, key: str, values: Sequence) -> None:
        """灌入主动读回的一批值（§10「通讯恢复：重新读取全部状态」用）。"""
        self._snap[key] = list(values)
        self._data_arrived()

    def datachange_notification(self, node, val, data) -> None:
        """asyncua 回调入口（方法名与三参数签名由 asyncua 定死，不可改）。"""
        entry = self._key_by_node.get(node.nodeid.to_string())
        if entry is None:
            return
        key, index = entry
        self._snap[key][index] = val
        self._data_arrived()
        if key == HEARTBEAT_KEY:
            self.emit()

    @property
    def complete(self) -> bool:
        return not any(slot is None for slots in self._snap.values() for slot in slots)

    def emit(self) -> Frame | None:
        """出一帧并回调 ``on_frames([frame])``；快照未收齐则返回 None 且不回调。"""
        if not self.complete:
            return None
        frame = Frame(t=time.monotonic(), heartbeat=self.integer(HEARTBEAT_KEY),
                      pos=tuple(float(v) for v in self._snap["axis_pos"]),
                      vel=tuple(float(v) for v in self._snap["axis_vel"]),
                      status=self.integer("status"), ack=self.integer("ack"),
                      alarm_word=self.integer("alarm_word"), seq_id=self.integer("seq_id"),
                      cur_seg=self.integer("cur_seg"))
        self.last_frame, self.frame_count = frame, self.frame_count + 1
        if self._on_frames is not None:
            self._on_frames([frame])
        return frame

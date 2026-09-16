"""comm.opcua_client —— asyncua 客户端包（T09）。

**拆包形态**：原单文件 ``comm/opcua_client.py`` 实测 **536 行**，超 04 §4.5-① 的 300 行上限，故按 T09
派单卡（04 §6.4）预授权的「按职责拆 ``comm/opcua_client/`` 子模块」处置（§4.5-②③ 的去重复→抽函数→
拆文件），拆成六件：

    errors.py      本包异常体系（CommError 家族；单独成件以免 connect↔handshake 成环）
    write.py       下行协议：契约 §5 的 ST_Seg 打包／解包、段布局常量、命令字位、下发节点 PLC 类型
    subscribe.py   上行协议：契约 §6 的状态／应答／报警位、Frame 定型、按 heartbeat 出帧的收数器
    handshake.py   契约 §9.1 九步握手（Session 的混入基类）
    reconnect.py   链路态 LinkState、stale 看门狗、§10 的指数退避重连
    connect.py     安全策略、Session 装配、connect() 工厂

派单卡点名的是「连接／订阅／写入／重连」四件；``errors.py`` 与 ``handshake.py`` 是拆分实测后补报的两件
（前者为断环、后者因握手与连接合在一件时实测 340 行仍超限）。

本文件**只做 re-export 与 ``__all__``，禁写任何业务逻辑**（照 §4.5-⑦ 硬要求 1 的口径，虽然该条的预授权
范围只限 ``core/kinematics`` 与 ``core/geometry`` 两包）。拆分前后**调用形态一字不变**——
``from comm.opcua_client import connect, Session, Segment`` 照旧成立（硬要求 2），03 §3 定死的
``connect(endpoint,cfg)->Session`` 签名不受影响。

包根 re-export 的断言放在 ``tests/test_opcua.py``，**不另建** ``tests/test_public_api_opcua_client.py``：
沿用 T03 已登记的同类规避（04 §4.5-⑦ 硬要求 3 的追注）——包根断言随本包首个单交付即可。
"""

from comm.opcua_client.connect import POLICY_NONE, Session, apply_security, connect
from comm.opcua_client.errors import (AckTimeout, CommError, LoadRejected, Rejected, SeqMismatch,
                                      StartRejected)
from comm.opcua_client.handshake import (ACK_TIMEOUT_S, DONE_TIMEOUT_S, WRITE_RETRIES,
                                         WRITE_TIMEOUT_S, Handshake)
from comm.opcua_client.reconnect import (BACKOFF_FACTOR, HEARTBEAT_LOSS_CYCLES, OFFLINE_AFTER_S,
                                         RECONNECT_BASE_S, RECONNECT_MAX_S, WATCHDOG_TICK_S,
                                         LinkState, LinkWatchdog)
from comm.opcua_client.subscribe import (ACK_HOME_DONE, ACK_LOAD_NG, ACK_LOAD_OK, ACK_RESET_DONE,
                                         ACK_START_NG, ACK_START_OK, ACK_STOP_DONE, ALARM_ESTOP,
                                         ALARM_FOLLOW, ALARM_LIMIT, ALARM_RANGE, ALARM_SAFETY,
                                         ALARM_SERVO, ALARM_SYNC, ALARM_TEXT, ALARM_UNREACHABLE,
                                         HEARTBEAT_KEY, MS_PER_S, ST_ALARM, ST_COMM_OK, ST_DONE,
                                         ST_HOMED, ST_IDLE, ST_PAUSED, ST_READY, ST_RUNNING, Frame,
                                         ReadbackBuffer, describe_alarm)
from comm.opcua_client.write import (BLEND_EXACT, BLEND_SMOOTH, CMD_HOME, CMD_LOAD, CMD_PAUSE,
                                     CMD_RESET, CMD_RESUME, CMD_START, CMD_STOP, MOTION_ABS,
                                     MOTION_REL, SEG_CIRC, SEG_HEAD_BYTES, SEG_LIN, SEG_PTP,
                                     SEG_SLOTS, SEG_TAIL_DINTS, SEG_TAIL_REALS, SEQ_ID_MAX,
                                     SPEED_OVERRIDE_FULL, SPEED_OVERRIDE_MIN, Segment,
                                     WRITE_NODE_TYPES, axis_slots_of, pack_segments, seg_layout,
                                     unpack_segments)

__all__ = [
    # connect —— 会话装配与工厂
    "connect", "Session", "apply_security", "POLICY_NONE",
    # handshake —— 契约 §9.1 九步
    "Handshake", "WRITE_TIMEOUT_S", "WRITE_RETRIES", "ACK_TIMEOUT_S", "DONE_TIMEOUT_S",
    # errors —— 异常体系
    "CommError", "AckTimeout", "Rejected", "LoadRejected", "StartRejected", "SeqMismatch",
    # write —— 契约 §5 下行
    "Segment", "pack_segments", "unpack_segments", "seg_layout", "axis_slots_of",
    "WRITE_NODE_TYPES", "SEG_SLOTS", "SEG_HEAD_BYTES", "SEG_TAIL_REALS", "SEG_TAIL_DINTS",
    "SEQ_ID_MAX", "SPEED_OVERRIDE_MIN", "SPEED_OVERRIDE_FULL",
    "SEG_PTP", "SEG_LIN", "SEG_CIRC", "MOTION_ABS", "MOTION_REL", "BLEND_EXACT", "BLEND_SMOOTH",
    "CMD_LOAD", "CMD_START", "CMD_PAUSE", "CMD_RESUME", "CMD_STOP", "CMD_RESET", "CMD_HOME",
    # subscribe —— 契约 §6 上行
    "Frame", "ReadbackBuffer", "describe_alarm", "ALARM_TEXT", "HEARTBEAT_KEY", "MS_PER_S",
    "ST_IDLE", "ST_READY", "ST_RUNNING", "ST_PAUSED", "ST_DONE", "ST_ALARM", "ST_HOMED", "ST_COMM_OK",
    "ACK_LOAD_OK", "ACK_LOAD_NG", "ACK_START_OK", "ACK_START_NG", "ACK_STOP_DONE",
    "ACK_RESET_DONE", "ACK_HOME_DONE",
    "ALARM_LIMIT", "ALARM_SERVO", "ALARM_FOLLOW", "ALARM_SYNC", "ALARM_UNREACHABLE",
    "ALARM_RANGE", "ALARM_SAFETY", "ALARM_ESTOP",
    # reconnect —— 链路态与重连
    "LinkState", "LinkWatchdog", "HEARTBEAT_LOSS_CYCLES", "OFFLINE_AFTER_S", "WATCHDOG_TICK_S",
    "RECONNECT_BASE_S", "RECONNECT_MAX_S", "BACKOFF_FACTOR",
]

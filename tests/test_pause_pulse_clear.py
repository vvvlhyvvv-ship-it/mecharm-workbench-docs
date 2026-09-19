"""pause()/resume() 的**超时路径**脉冲清零（T15 收单指挥侧补判据 2026-09-19）。

卡面铁律「只测正常路径清了不算过」（01 蓝图 §6.2 实现铁律一）：e2e_sim U4 已实测正常路径
（ST_PAUSED 置位/清零成功后 cmd 归零）；本件用桩回读面让等待**必然超时**，证明 finally 的
``_write("cmd", 0)`` 在 AckTimeout 路径上同样落地——与 ``_pulse`` 的既有保证同形状。

Handshake 无自有 ``__init__``（属性由 Session 建立、类 docstring 声明为契约面），故按其声明面
注入桩：``_wr``／``_buffer``／``_notify``。本地模拟器无「吞暂停置位」故障档，GUI 级无法复现
该路径（comm/plc_logic.py 的 ``inject_fault`` 只有 reject／timeout／disconnect），故收在单位级。
"""
import asyncio

import pytest

from comm.opcua_client import AckTimeout
from comm.opcua_client import handshake as handshake_module
from comm.opcua_client.handshake import Handshake
from comm.opcua_client.subscribe import ST_PAUSED
from comm.opcua_client.write import CMD_PAUSE, CMD_RESUME


class _RecordingNode:
    """假下发节点：记录写序列，供断言「超时后最后一位仍是 0（脉冲收尾）」。"""

    def __init__(self) -> None:
        self.writes: list[int] = []

    async def write_value(self, value, varianttype=None) -> None:
        self.writes.append(int(value))


class _StubBuffer:
    """假回读面：``status`` 恒定返回构造值，使等待条件永不满足。"""

    def __init__(self, status: int) -> None:
        self.status = status

    def integer(self, key: str) -> int:
        return self.status


def _handshake(status: int) -> tuple[Handshake, _RecordingNode]:
    hs = object.__new__(Handshake)
    node = _RecordingNode()
    hs._wr = {"cmd": node}
    hs._buffer = _StubBuffer(status)
    hs._notify = asyncio.Event()
    return hs, node


def test_pause_timeout_still_clears_cmd(monkeypatch):
    """ST_PAUSED 永不出现 ⇒ pause() 报 AckTimeout；finally 仍把 cmd 清零。"""
    monkeypatch.setattr(handshake_module, "ACK_TIMEOUT_S", 0.05)

    async def body():
        hs, node = _handshake(0)
        with pytest.raises(AckTimeout):
            await hs.pause()
        return node.writes

    assert asyncio.run(body()) == [CMD_PAUSE, 0]


def test_resume_timeout_still_clears_cmd(monkeypatch):
    """ST_PAUSED 恒在 ⇒ resume() 报 AckTimeout；finally 仍把 cmd 清零。"""
    monkeypatch.setattr(handshake_module, "ACK_TIMEOUT_S", 0.05)

    async def body():
        hs, node = _handshake(ST_PAUSED)
        with pytest.raises(AckTimeout):
            await hs.resume()
        return node.writes

    assert asyncio.run(body()) == [CMD_RESUME, 0]

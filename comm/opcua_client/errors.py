"""comm.opcua_client.errors —— 本包异常体系。

单独成件是为依赖方向：``write``／``handshake``／``connect`` 都要抛这些异常，若把它们放进其中任一件，
另两件 import 过来就会成环（``connect`` 装配 ``handshake``，``handshake`` 又要 ``connect`` 的异常）。
本模块只向下依赖 ``subscribe``（取报警位的中文说明），依赖图因此仍是单向无环。

**两族界线**（调用方据此决定 catch 什么）：

- **取值／布局非法** → ``ValueError``：``pack_segments`` 一类纯函数的前置条件，属编程错误；
- **链路与握手失败** → ``CommError`` 家族：运行期故障，``except CommError`` 即可兜住通讯侧全部情况。

被拒时**必须带原因码**：T09 卡步骤 5「注入拒绝异常→客户端收到原因码」，原因码即契约 §6.4 的
``AlarmWord`` 位（``Rejected.alarm`` 为原值、``Rejected.reasons`` 为其中文说明）。
"""

from __future__ import annotations

from comm.opcua_client.subscribe import describe_alarm


class CommError(Exception):
    """通讯层失败基类：握手超时／被拒／序号不符／断线／配置不可用。"""


class AckTimeout(CommError):
    """契约 §9.1 步骤 4/6：等应答超时（超时表 2 s）。"""


class Rejected(CommError):
    """PLC 拒绝本次请求（§9.3-①「软件只请求，不命令」，PLC 有权拒绝或钳位）。

    ``alarm``＝§6.4 报警字原值；``reasons``＝其中文说明元组。报警字为 0 时消息里明说
    「PLC 未给出原因位」——**不猜原因**，那是现场要查的事。
    """

    def __init__(self, what: str, alarm: int, seq_id: int) -> None:
        self.what, self.alarm, self.seq_id = what, alarm, seq_id
        self.reasons = describe_alarm(alarm)
        super().__init__(f"{what}被拒（SeqID={seq_id}）："
                         f"{'、'.join(self.reasons) or '报警字为 0，PLC 未给出原因位'}")


class LoadRejected(Rejected):
    """§9.1 步骤 4：``ACK_LOAD_NG``——越界／轴数不符／限位（§3.2「PLC 接收后再校验」）。"""

    def __init__(self, alarm: int, seq_id: int) -> None:
        super().__init__("装载", alarm, seq_id)


class StartRejected(Rejected):
    """§9.1 步骤 6：``ACK_START_NG``——未就绪／未回零／报警中。"""

    def __init__(self, alarm: int, seq_id: int) -> None:
        super().__init__("启动", alarm, seq_id)


class SeqMismatch(CommError):
    """§10：PLC 回显的 ``SeqID`` 与写入值不符 → 拒绝本次结果，重新同步。"""

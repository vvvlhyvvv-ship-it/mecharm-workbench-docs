"""Qt ⇄ 视口 双向桥骨架（03 架构 §5 JSON 协议）。

本单（T02）只实现**通路 + echo 自测**，不实现任何业务消息：
  call_view(type, payload)  壳→视口：把 {type,payload} 投递给页面里的分发函数
  on_view_msg(type, data)   视口→壳：JS 经 QWebChannel 回调进来（Slot）
  received(type, data) 信号  收到任何视口消息都发出，供 shell 写日志

03 §5 约定的业务 type（本单**不实现**，仅登记口径，后续单接线）：
  壳→视口：mesh.load / pose.update / path.show / pick.enable / hl.set
  视口→壳：pick.face / cam.view
协议载荷全 ASCII（json.dumps ensure_ascii=True）。echo 用 type="ping"/"pong"。
"""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWebChannel import QWebChannel

# 视口侧（view/js/bridge.js）注册的全局分发函数名。
_DISPATCH_FN = "window.__mecharm_dispatch"


class Bridge(QObject):
    """QWebChannel 上注册名为 'bridge' 的对象，JS 侧经 channel.objects.bridge 调用。"""

    received = Signal(str, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._channel: QWebChannel | None = None
        self._ready = False

    def attach(self, page) -> None:
        """把桥挂到 QWebEnginePage 上（page 由 viewpane 提供）。"""
        self._channel = QWebChannel(page)
        self._channel.registerObject("bridge", self)
        page.setWebChannel(self._channel)

    def set_ready(self, ready: bool) -> None:
        """页面加载完成后由 shell 置 True，此前 call_view 静默丢弃（页面还没有分发函数）。"""
        self._ready = ready

    def call_view(self, type_: str, payload: dict | None = None) -> bool:
        """壳→视口：投递一条消息。返回是否真的发出（页面未就绪则 False）。"""
        page = self._channel.parent() if self._channel else None
        if not self._ready or page is None:
            return False
        msg = json.dumps({"type": type_, "payload": payload or {}}, ensure_ascii=True)
        # 用 JSON.parse(<JS 字符串字面量>) 投递，避免任何引号/转义注入。
        literal = json.dumps(msg, ensure_ascii=True)
        js = f"{_DISPATCH_FN} && {_DISPATCH_FN}(JSON.parse({literal}));"
        page.runJavaScript(js)
        return True

    @Slot(str, str)
    def on_view_msg(self, type_: str, data: str) -> None:
        """视口→壳：JS 回调入口。data 是 JSON 文本（解析失败按原始字符串处理）。"""
        try:
            parsed = json.loads(data) if data else {}
        except (ValueError, TypeError):
            parsed = data
        self.received.emit(type_, parsed)

    def ping(self, seq: int = 1) -> bool:
        """echo 自测：发 ping，视口收到后回 pong（见 view/js/bridge.js）。"""
        return self.call_view("ping", {"seq": seq})

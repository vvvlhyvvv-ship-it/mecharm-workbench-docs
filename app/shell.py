"""工作台主窗体（02 设计方案 §1 全局骨架的唯一装配处）。

骨架：顶栏(56px) │ 左装配树(280px,可折叠) ┃ 中 WebEngine 视口 ┃ 右上下文栏(360px,可折叠) │ 底状态栏(32px)。
T02 阶段内核未接入，全部用占位数据；本模块只做布局 + 外壳级接线：
  步骤条点击 → 右栏切页 + 设当前步 + 日志
  工作模式生效 → 解锁步骤②-⑤；切换 → 广播“结果作废” + 日志（G16）
  桥 echo：视口就绪后发 ping，收到 pong 写日志（证明双向通路）
  视口加载失败 → 日志（错误卡在 viewpane 内显示）
颜色/字号一律走 app.theme 全局 QSS，本模块不写内联样式。
"""

from __future__ import annotations

import pathlib
import sys

from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

from app.assemblytree import AssemblyTree
from app.bridge import Bridge
from app.mode import ModeBadge, OnlineLight, WorkModeSelector
from app.panel import Panel
from app.statusbar import StatusBar
from app.stepbar import STEP_LABELS, StepBar
from app.theme import apply_theme
from app.viewpane import ViewPane

TOP_HEIGHT = 56
LEFT_WIDTH = 280
RIGHT_WIDTH = 360
CENTER_MIN = 320


class MainWindow(QMainWindow):
    """三栏外壳主窗体。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("机械臂三维示教工作台")
        self.resize(1440, 860)
        self.setMinimumSize(LEFT_WIDTH + CENTER_MIN + RIGHT_WIDTH, 600)
        self.setAcceptDrops(True)              # 拖放模型文件到窗口即导入（02 §2 步骤①）
        self._mode_ok = False                  # 已选定工作模式
        self._brep_ok = False                  # 已导入实体模型；面片模型保持 False → ②-⑤锁定
        self._last: object = None              # 最近导入结果（含 parts.face_index，留存供 T06）

        self.bridge = Bridge(self)
        self.stepbar = StepBar()
        self.workmode = WorkModeSelector()
        self.badge = ModeBadge()
        self.light = OnlineLight()
        self.viewpane = ViewPane()
        self.viewpane.view().setAcceptDrops(False)  # 让拖放冒泡到主窗（WebEngine 默认吞 drop）
        self.panel = Panel()
        self.statusbar = StatusBar()

        central = QWidget()
        col = QVBoxLayout(central)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self._build_topbar())
        col.addWidget(self._build_splitter(), 1)
        col.addWidget(self.statusbar)
        self.setCentralWidget(central)

        self.bridge.attach(self.viewpane.page())
        self._wire()
        self.viewpane.start()

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(TOP_HEIGHT)
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(10)
        self._left_btn = self._collapse_button("◀", self._toggle_left)
        title = QLabel("机械臂工作台")
        title.setObjectName("AppTitle")
        row.addWidget(self._left_btn)
        row.addWidget(title)
        row.addWidget(self.stepbar, 1)
        row.addWidget(QLabel("工作模式"))
        row.addWidget(self.workmode)
        row.addWidget(self.badge)
        row.addWidget(self.light)
        self._right_btn = self._collapse_button("▶", self._toggle_right)
        row.addWidget(self._right_btn)
        return bar

    def _collapse_button(self, text: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setProperty("collapse", "true")
        btn.setFixedWidth(28)
        btn.clicked.connect(slot)
        return btn

    def _build_left(self) -> QWidget:
        pane = QWidget()
        pane.setObjectName("LeftPane")
        box = QVBoxLayout(pane)
        box.setContentsMargins(12, 8, 12, 8)
        box.setSpacing(8)
        title = QLabel("装配树")
        title.setObjectName("PaneTitle")
        self.tree = AssemblyTree()
        box.addWidget(title)
        box.addWidget(self.tree, 1)
        return pane

    def _build_splitter(self) -> QWidget:
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        left = self._build_left()
        left.setMinimumWidth(200)
        self.panel.setMinimumWidth(280)
        self.viewpane.setMinimumWidth(CENTER_MIN)
        self.splitter.addWidget(left)
        self.splitter.addWidget(self.viewpane)
        self.splitter.addWidget(self.panel)
        self.splitter.setCollapsible(1, False)
        self.splitter.setSizes([LEFT_WIDTH, CENTER_MIN + 240, RIGHT_WIDTH])
        self._left_pane = left
        return self.splitter

    def _wire(self) -> None:
        self.stepbar.step_clicked.connect(self._on_step_clicked)
        self.workmode.committed.connect(self._on_mode_committed)
        self.workmode.switched.connect(self._on_mode_switched)
        self.bridge.received.connect(self._on_bridge_msg)
        self.viewpane.load_failed.connect(
            lambda reason: self.statusbar.log(reason.replace("\n", " "))
        )
        self.viewpane.view().loadFinished.connect(self._on_view_load)
        self.panel.step1.imported.connect(self._on_imported)
        self.panel.step1.failed.connect(lambda msg: self.statusbar.log(f"导入未成功：{msg}"))
        self.tree.selected.connect(self._on_tree_selected)
        self.tree.focused.connect(self._on_tree_focused)
        self.panel.set_step(1)

    def _on_step_clicked(self, n: int) -> None:
        self.stepbar.set_current(n)
        self.panel.set_step(n)
        self.statusbar.log(f"切换到 {STEP_LABELS[n - 1]}")

    def _on_mode_committed(self, name: str) -> None:
        self._mode_ok = True
        self._refresh_unlock()
        tail = "，步骤②-⑤已解锁" if self._brep_ok else "（待导入实体模型后解锁步骤②-⑤）"
        self.statusbar.log(f"工作模式：{name}{tail}")

    def _on_mode_switched(self, name: str) -> None:
        self.bridge.call_view("invalidate", {"mode": name})
        self.statusbar.log("结果作废：已清空当前点位与路径，换臂后须重新示教与校核")

    def _on_bridge_msg(self, type_: str, data: object) -> None:
        self.statusbar.log(f"桥 echo：收到 {type_} {data}")

    def _on_view_load(self, ok: bool) -> None:
        if not ok:
            return
        self.bridge.set_ready(True)
        self.statusbar.log("视口就绪，发送 ping")
        self.bridge.ping(1)

    def _refresh_unlock(self) -> None:
        # 步骤②-⑤需“已选工作模式 且 已导入实体模型”同时成立（面片模型不可编程）
        ok = self._mode_ok and self._brep_ok
        for n in (2, 3, 4, 5):
            self.stepbar.set_step_enabled(n, ok)

    def _on_imported(self, res: object) -> None:
        asm = res["asm"]
        self._last = res
        self.bridge.call_view("mesh.load", {"reset": True, "parts": res["payload"]})
        self.tree.populate(asm.tree_payload())
        self.stepbar.mark_completed(1)        # 红线④：步骤①导入成功即标记完成
        self._brep_ok = bool(asm.is_brep)
        self._refresh_unlock()
        name = pathlib.Path(asm.source_path).name
        kind = "实体模型 ✓" if asm.is_brep else "面片模型 ✗（不能用于编程，步骤②保持锁定）"
        self.statusbar.log(f"已导入 {name}，{asm.stats.get('parts', 0)} 个零件，{kind}")

    def _on_tree_selected(self, ids: list) -> None:
        self.bridge.call_view("hl.set", {"ids": ids, "semantic": "ok"})

    def _on_tree_focused(self, ids: list) -> None:
        self.bridge.call_view("hl.set", {"ids": ids, "semantic": "ok", "focus": True})

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if urls:
            self.panel.step1.start_import(urls[0].toLocalFile())

    def _toggle_left(self) -> None:
        vis = not self._left_pane.isVisible()
        self._left_pane.setVisible(vis)
        self._left_btn.setText("◀" if vis else "▶")

    def _toggle_right(self) -> None:
        vis = not self.panel.isVisible()
        self.panel.setVisible(vis)
        self._right_btn.setText("▶" if vis else "◀")


def main() -> int:
    """启动外壳（须以 `python -m app.shell` 运行，确保 app 包先完成 ICU 预载）。"""
    app = QApplication(sys.argv)
    apply_theme(app)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

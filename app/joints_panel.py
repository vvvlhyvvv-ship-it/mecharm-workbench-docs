"""右栏常驻面板②：机构与关节（01 蓝图 §3.6-2；T13）。

**22 轴四组分组**（⛔ 不按 links 简单分组）：①「共用机构」＝五个模式都含的轴；②「当前工作头
〈模式名〉」＝当前模式专属轴（未选定则空组）；③「安装架」＝role=setup 轴（YA–YE，有连杆、不属
任何模式）；④「未建模机构」＝其余无连杆轴——判定**直接复用** ``core.collision.unmodeled_axes``
（G19 守卫已覆盖，⛔ 不另写一套）。

**回读覆盖只有 8/22（关键口径）**：``opcua.read_nodes.axis_pos`` 的节点数＝可回读槽位，按 axes
表序对应（现配置 X1/Z1/Y1/X2/Z2/X3/YA/YB）；其余轴**即使链路在线也无回读 ⇒ 恒「—」＋「点表
未收」标注**（⛔ 不因在线显 0.0，§1-1）；``axes[].pending: true`` 另挂「待回执」徽标（yaml 真字段）。
轴点动区整块禁用＋「待后续版本」（Δ-7：点动＝写命令，模拟器不建模回零轨迹）；软限位行只计
**有回读**的轴（无回读不计入——「—」既不当越限也不当正常）。
值更新＝只读观察 ``link.frames``／``link.link_state`` 信号（⛔ 不改 livectl/linkctl）。
"""

from __future__ import annotations

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from core.collision import unmodeled_axes
from core.config import MachineConfig

DASH = "—"
UNREAD_MARK = "点表未收"
PENDING_MARK = "待回执"
LATER_NOTE = "待后续版本"
UNITS = {"prismatic": "mm", "revolute": "°"}
G_TITLES = ("共用机构", "当前工作头", "安装架", "未建模机构")


class JointsPanel(QWidget):
    """机构与关节面板；``on_frames``/``on_link_state`` 由外壳接到链路信号（只读）。"""

    def __init__(self, cfg: MachineConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._mode: str | None = None
        self._values: dict[str, float] = {}
        slots = len(cfg.opcua.read_nodes["axis_pos"])
        self.readable: tuple[str, ...] = tuple(list(cfg.axes)[:slots])   # Pos[] 按 axes 表序对应
        self.unreadable: tuple[str, ...] = tuple(a for a in cfg.axes if a not in self.readable)
        self.pending_axes: tuple[str, ...] = tuple(a for a, spec in cfg.axes.items()
                                                   if spec.pending)
        self._value_labels: dict[str, QLabel] = {}
        self._row_texts: dict[str, QWidget] = {}
        self._titles: list[QLabel] = []
        title = QLabel("机构与关节")
        title.setObjectName("PaneTitle")
        self.header_badge = QLabel(str(len(cfg.axes)))
        self.header_badge.setProperty("tone", "accent")
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(title)
        head.addWidget(self.header_badge)
        head.addStretch(1)
        self.softline = QLabel(DASH)
        self.softline.setProperty("tone", "dim")
        self.jog_btn = QPushButton("−")
        self.jog_btn.setEnabled(False)
        self.jog_note = QLabel("轴点动（−/＋/回零/速度）" + "：" + LATER_NOTE)
        self.jog_note.setProperty("tone", "dim")
        self._body = QWidget()
        self._box = QVBoxLayout(self._body)
        self._box.setContentsMargins(8, 4, 8, 4)
        self._box.setSpacing(2)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._body)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(8)
        outer.addLayout(head)
        outer.addWidget(scroll, 1)
        outer.addWidget(self.jog_btn)
        outer.addWidget(self.jog_note)
        outer.addWidget(self.softline)
        self.rebuild()

    # --- 分组与建行 -------------------------------------------------------------- #
    def groups(self) -> list[tuple[str, list[str]]]:
        cfg = self._cfg
        first, *rest = cfg.modes
        common = set(first.axes)
        for m in rest:
            common &= set(m.axes)
        mode_axes = []
        for m in cfg.modes:
            if m.name == self._mode:
                mode_axes = [a for a in m.axes if a not in common]
        mounts = [a for a, spec in cfg.axes.items() if spec.role == "setup"]
        extra = [a for a in unmodeled_axes(cfg) if a not in mode_axes]
        groups = [(G_TITLES[0], list(common)), (G_TITLES[1], mode_axes),
                  (G_TITLES[2], mounts), (G_TITLES[3], extra)]
        if self._mode is not None:
            groups[1] = (f"{G_TITLES[1]}〈{self._mode}〉", mode_axes)
        return [(t, ids) for t, ids in groups if ids or t.startswith(G_TITLES[1])]

    def rebuild(self) -> None:
        """按当前模式重建分组行（组②空时保留组头并标「未选定」，其余空组不显示）。"""
        for lab in tuple(self._value_labels):
            self._value_labels.pop(lab)
        for row in tuple(self._row_texts):
            self._row_texts.pop(row).deleteLater()
        while self._box.count():
            item = self._box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._titles = []
        for title, ids in self.groups():
            head = QLabel(("▾ " + title) if ids else f"▾ {title}（未选定）")
            head.setProperty("tone", "dim")
            self._titles.append(head)
            self._box.addWidget(head)
            for axis_id in ids:
                self._box.addWidget(self._axis_row(axis_id))
        self._box.addStretch(1)
        self._paint_values()

    def _axis_row(self, axis_id: str) -> QWidget:
        spec = self._cfg.axes[axis_id]
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(10, 0, 0, 0)
        line.setSpacing(6)
        name = QLabel(axis_id)                       # 轴显示 id 即可，中文命名等甲方回执（卡禁项）
        value = QLabel(DASH)
        value.setProperty("mono", "true")
        line.addWidget(name)
        line.addStretch(1)
        line.addWidget(value)
        line.addWidget(QLabel(UNITS.get(spec.type, "")))
        if axis_id not in self.readable:
            unread = QLabel(UNREAD_MARK)
            unread.setProperty("tone", "dim")
            unread.setToolTip("点表未收该轴回读（opcua.read_nodes 只有 Pos[0..7]），即使在线也无值")
            line.addWidget(unread)
        if spec.pending:
            pending = QLabel(PENDING_MARK)
            pending.setProperty("tone", "warn")
            pending.setToolTip("machine.yaml 标 pending: true——行程/零点/方向待电气·机械回执（占位值）")
            line.addWidget(pending)
        self._value_labels[axis_id] = value
        self._row_texts[axis_id] = row
        return row

    # --- 链路只读侧 ---------------------------------------------------------------- #
    def set_mode(self, name: str | None) -> None:
        self._mode = name
        self.rebuild()

    def on_frames(self, batch: object) -> None:
        if not isinstance(batch, list) or not batch:
            return
        frame = batch[-1]
        pos = getattr(frame, "pos", None)
        if not isinstance(pos, tuple):
            return
        for axis_id, value in zip(self.readable, pos):
            self._values[axis_id] = float(value)
        self._paint_values()

    def on_link_state(self, state: object) -> None:
        if str(state).endswith("ONLINE"):
            return
        self._values.clear()                          # 离线/变陈 ⇒ 回「—」，不留旧值假装在线
        self._paint_values()

    def _paint_values(self) -> None:
        for axis_id, label in self._value_labels.items():
            v = self._values.get(axis_id)
            label.setText(DASH if v is None else f"{v:.1f}")
        self._paint_softline()

    def _paint_softline(self) -> None:
        """软限位行：只计**有回读且已达行程设定值**的轴（travel 与回读值都来自 machine.yaml/链路）。"""
        count = 0
        for axis_id, value in self._values.items():
            lo, hi = self._cfg.axes[axis_id].travel
            if value >= hi or value <= lo:
                count += 1
        if not self._values:
            self.softline.setText(DASH)
            self.softline.setProperty("tone", "dim")
        else:
            self.softline.setText(f"软限位：{count} 个轴已达行程设定值（计有回读的 "
                                  f"{len(self._values)} 轴）")
            self.softline.setProperty("tone", "warn" if count else "dim")
        self.softline.style().unpolish(self.softline)
        self.softline.style().polish(self.softline)

    # --- e2e/收单读数口（读操作员可见的那一份） ------------------------------------ #
    def value_text(self, axis_id: str) -> str:
        return self._value_labels[axis_id].text()

    def row_text(self, axis_id: str) -> str:
        return " ".join(l.text() for l in self._row_texts[axis_id].findChildren(QLabel))

    def group_count(self) -> int:
        return len(self._titles)

    def group_title(self, index: int) -> str:
        return self._titles[index].text()

"""app.prog_tab —— 编程页签体（T14 成形；01 蓝图 §3.4／§6.1，演示稿画面 04）。

T13 暂挂初版整体重写（换体授权，tabshell 不回改）：四步流水线指示（done/now 由**真实状态**
驱动、仅指示不导航——StepBar 完成态的新表达载体，99 台账 L-7）＋工具区（执行组期 3 禁用
Δ-7／倍率＝SpeedOverride／选点偏移）＋存取行＋重排后的步骤②点位表与步骤③段清单（**语义
零改动**，T06/T07 冻结行为逐条保留）＋底部「生成并校验轨迹」（＝step3 原生成按钮迁来，合并
语义＝生成成功后自动校核）＋「下发执行」＝**跳转**路径仿真页签（Δ-4，⛔ 不做第二套下发）＋
校验结论行（颜色＋图标＋文字三通道）。步骤①页退场为浮层（app/pop_import.py 复用其导入
管线）；本件仍 setParent 收容 step1 保 e2e T2「step1 归编程页签」判据（父子链与可见无关）。

分工：本件＝**视图与 CSV 清单纯函数**；存取编排（对话框/Project 组装/确认弹窗）与浮层、
接线总成在 ``app/pop_import.py``（增件名受派单卡预声明限制下的分工，视图/动作分离）。
CSV＝程序清单视图（序号/名称/X/Y/Z/类型；法向与来源面不在列内 ⇒ 导入按清单级恢复）。
颜色/字号走 app.theme 全局 QSS 与动态属性（tone／mono），本模块不写内联样式。
"""

from __future__ import annotations

import csv
import io

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from core.geometry.face_point import Waypoint

from app.plc_out import PlcOutArea

LATER_NOTE = "待后续版本"                  # 期 3 功能的禁用提示（Δ-7）
CRAFT_NOTE = "待工艺口径"                  # 插入动作组的禁用提示（Δ-7，等 TBD-11）
EXEC_NOTE = "执行控制在「路径仿真」页签，本页只编程（待后续版本）"
SEND_TIP = "跳转到「路径仿真」页签执行下发"  # Δ-4：本页只跳转，不做第二套下发
SEND_OFF = "校核未通过或尚未校核，无法下发：先在本页生成并校验"
FLOW_STEPS = ("① 导入模型", "② 选择面", "③ 生成轨迹", "④ PLC 输出")
OVERRIDE_STEPS = ((100.0, "100%"), (75.0, "75%"), (50.0, "50%"), (25.0, "25%"))
INSERT_TOOLS = ("等待", "IO", "工具", "夹紧", "重复", "子程序", "＋工序段")
CSV_HEAD = ("序号", "名称", "X", "Y", "Z", "类型")
_VERDICT_CN = {"pass": ("🟢", "未检出干涉", "ok"), "warn": ("🟡", "预警", "warn"),
               "interfere": ("🔴", "不通过", "deny")}   # ⛔ 通过态不含「通过」（G19-1）


class ProgTab(QWidget):
    """编程页签体。构造签名 ``ProgTab(panel)`` 固定（tabshell 取件）；外壳数据经 ``bind`` 注入。"""

    store_log = Signal(str)                  # 存取编排的人话日志（install_t14 接状态栏）

    def __init__(self, panel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._win = None                     # install_t14 里 bind(win) 注入（门禁/跳转要外壳真值）
        self._panel = panel
        self._flow: list[tuple[QLabel, QLabel]] = []
        panel.step1.setParent(self)          # ①页退场为浮层，仅保父子链（e2e T2 判据）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        stack = QWidget()
        box = QVBoxLayout(stack)
        box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(8)
        box.addLayout(self._build_flow())
        box.addWidget(self._build_tools())
        box.addLayout(self._build_store())
        box.addWidget(panel.step2)
        panel.step2.show()                   # 摘自 Panel 的栈页带着隐藏态，须显式复显
        box.addWidget(panel.step3)
        panel.step3.show()
        box.addLayout(self._build_bottom())
        self.plc_out = PlcOutArea()          # T17：PLC 输出区（演示稿画面 05，本单增件挂载）
        box.addWidget(self.plc_out)
        box.addStretch(1)
        scroll.setWidget(stack)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # --- 四步流水线指示（仅指示不可点导航；done/now 由真实状态驱动）----------------- #
    def _build_flow(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setSpacing(4)
        for i, name in enumerate(FLOW_STEPS):
            title = QLabel(name)
            title.setProperty("tone", "dim")
            sub = QLabel("—")
            sub.setProperty("mono", "true")
            sub.setProperty("tone", "dim")
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            row.addWidget(title)
            row.addWidget(sub, 1)
            holder = QWidget()
            holder.setLayout(row)
            grid.addWidget(holder, i // 2, i % 2)
            self._flow.append((title, sub))
        return grid

    def refresh_flow(self, win) -> None:
        """按真实内核状态刷四步指示：①已导入实体／②已取点／③已生成无阻断／④T17 前恒未输出。"""
        asm = (win._last or {}).get("asm")
        parts = asm.stats.get("parts") if asm is not None else None
        pts = len(win.panel.step2.waypoints())
        segs = len(win.pathctl.segments())
        steps = (self.plc_out._built or {}).get("steps") or []   # ④PLC 输出真值（指挥侧 2026-09-19 授权行）
        states = (bool(win._brep_ok), pts > 0, win.pathctl.ready(), bool(steps))
        subs = (f"{parts} 件" if states[0] and parts else "—",     # ①随 _brep_ok：清空后统计过期
                f"{pts} 点" if pts else "—",
                f"{segs} 段" if segs else "—", f"{len(steps)} 工步" if steps else "—")
        now = next((i for i, ok in enumerate(states) if not ok), len(states))
        for i, (title, sub) in enumerate(self._flow):
            title.setProperty("tone", "ok" if states[i] else ("accent" if i == now else "dim"))
            title.style().unpolish(title)
            title.style().polish(title)
            sub.setText(subs[i])

    # --- 工具区（执行组 Δ-7 禁用／倍率 SpeedOverride／选点偏移／插入动作组）--------- #
    def _build_tools(self) -> QWidget:
        card = QWidget()
        card.setObjectName("PlaceholderCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(6)
        run_row = QHBoxLayout()
        for text in ("▶ 连续", "⤼ 单步", "⏸", "⏹ 复位"):
            btn = QPushButton(text)
            btn.setEnabled(False)
            btn.setToolTip(EXEC_NOTE if text == "⏸" else LATER_NOTE)
            run_row.addWidget(btn)
        run_row.addStretch(1)
        speed_lab = QLabel("倍率")
        speed_lab.setProperty("tone", "dim")
        self._speed = QComboBox()
        for value, text in OVERRIDE_STEPS:
            self._speed.addItem(text, value)
        run_row.addWidget(speed_lab)
        run_row.addWidget(self._speed)
        box.addLayout(run_row)
        insert_lab = QLabel("插入动作")
        insert_lab.setProperty("tone", "dim")
        box.addWidget(insert_lab)
        tool_row = QHBoxLayout()
        tool_row.setSpacing(4)
        for text in INSERT_TOOLS:
            btn = QPushButton(text)
            btn.setEnabled(False)
            btn.setToolTip(CRAFT_NOTE)
            tool_row.addWidget(btn)
        tool_row.addStretch(1)
        box.addLayout(tool_row)
        off_row = QHBoxLayout()
        off_lab = QLabel("选点偏移")
        off_lab.setProperty("tone", "dim")
        self._offset = QDoubleSpinBox()      # 值域钳制＝非法输入进不来（QLineEdit 红框无全局 QSS 可用）
        self._offset.setRange(-10000.0, 10000.0)
        self._offset.setDecimals(1)
        self._offset.setSuffix(" mm")
        self._offset.setValue(0.0)
        self._offset.setToolTip("新取点位沿 Z 向的偏移量（mm）；越出行程由点位表编辑校验拒绝")
        off_row.addWidget(off_lab)
        off_row.addWidget(self._offset)
        off_row.addStretch(1)
        box.addLayout(off_row)
        return card

    # --- 存取行（动作编排在 pop_import；本类只出按钮与薄转发）----------------------- #
    def _build_store(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(4)
        for text in ("保存", "导出 JSON", "导出 CSV", "导入", "清空"):
            row.addWidget(QPushButton(text))
        self._store_btns = [row.itemAt(i).widget() for i in range(row.count())]
        self._btn_wipe = self._store_btns[-1]
        self._btn_wipe.setToolTip("清空当前程序（点位），清空前二次确认")
        row.addStretch(1)
        return row

    # --- 底部：生成并校验轨迹（step3 原按钮迁来）＋下发执行＋校验结论行 --------------- #
    def _build_bottom(self) -> QVBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self._panel.step3._btn, 1)      # 生成并校验轨迹（合并语义，门禁仍属 step3 逻辑）
        self._btn_send = QPushButton("下发执行")
        self._btn_send.setEnabled(False)
        self._btn_send.setToolTip(SEND_TIP)
        row.addWidget(self._btn_send, 1)
        self._verdict = QLabel("尚未校核：点[生成并校验轨迹]后此处给出结论")
        self._verdict.setProperty("tone", "dim")
        self._verdict.setWordWrap(True)
        box = QVBoxLayout()
        box.setSpacing(4)
        box.addLayout(row)
        box.addWidget(self._verdict)
        return box

    # --- 校核结论行（三通道：颜色 tone＋图标＋文字）＋干涉红行灌入 ------------------- #
    def refresh_check(self, result) -> None:
        """checkctl.changed 的落点：结论行三态＋涉事段/涉事点位标红（T16 前的现三态口径）。"""
        seg_ids: set[int] = set()
        if result is None:
            self._verdict.setProperty("tone", "dim")
            self._verdict.setText("尚未校核：点[生成并校验轨迹]后此处给出结论")
        else:
            icon, cn, tone = _VERDICT_CN[result.verdict]
            n = len(result.cases)
            cn = f"{cn} {n} 处" if n else cn
            permit = "禁止" if result.verdict == "interfere" else "允许"
            self._verdict.setProperty("tone", tone)
            self._verdict.setText(f"{icon} 本次轨迹校验结论：{cn} · 下发许可：{permit}"
                                  f"（详见「路径仿真」页签）")
            seg_ids = {c.seg_id for c in result.cases}
        self._verdict.style().unpolish(self._verdict)
        self._verdict.style().polish(self._verdict)
        self._panel.step3.set_clash_ids(seg_ids)
        names = {name for seg in (self._win.pathctl.segments() if self._win else ())
                 if seg.id in seg_ids for name in (seg.start_name, seg.end_name)}
        self._panel.step2.set_clash_names(names)
        if self._win is not None:
            ok = self._win.checkctl.ready()
            self._btn_send.setEnabled(ok)
            self._btn_send.setToolTip(SEND_TIP if ok else SEND_OFF)

    # --- 外壳数据注入（install_t14 调；构造时 pathctl 尚未存在，接线只能延后到这里）--- #
    def bind(self, win) -> None:
        self._win = win
        self.plc_out.bind(win)               # T17：输出区接外壳（pathctl 失效联动/声明文案/日志）
        self._speed.currentIndexChanged.connect(
            lambda _i: win.pathctl.set_speed_override(self._speed.currentData()))
        self._btn_send.clicked.connect(lambda: win.tabshell.switch_to("sim"))   # Δ-4 跳转
        self._offset.valueChanged.connect(win.panel.step2.set_pick_offset)
        self.refresh_flow(win)
        self.refresh_check(win.checkctl._result)

    # --- 存取薄转发（动作编排在 pop_import.py；e2e／测试经本类调用可直传路径）--------- #
    def save_project(self, path: str = ""):
        from app.pop_import import save_project
        return save_project(self._win, path)

    def export_json(self, path: str = ""):
        from app.pop_import import export_json
        return export_json(self._win, path)

    def export_csv(self, path: str = ""):
        from app.pop_import import export_csv
        return export_csv(self._win, path)

    def import_file(self, path: str = ""):
        from app.pop_import import import_file
        return import_file(self._win, path)

    def clear_program(self) -> bool:
        from app.pop_import import clear_program
        return clear_program(self._win)


# --- CSV 程序清单（纯函数，无 Qt 依赖；tests/test_prog_export.py 承重）------------------- #
def build_csv(waypoints: list[Waypoint], kind_text: str) -> str:
    """点位序列 → CSV 文本（表头＝CSV_HEAD；数值 ``.3f``＝点位表同口径；类型列＝段型全中文）。"""
    lines = [",".join(CSV_HEAD)]
    for w in waypoints:
        x, y, z = w.pos_mm
        lines.append(f"{w.id},{w.name},{x:.3f},{y:.3f},{z:.3f},{kind_text}")
    return "\n".join(lines) + "\n"


def parse_csv(text: str) -> list[Waypoint]:
    """CSV 文本 → 点位序列（清单级）。坏表头／坏行一律 ValueError 人话 ⛔ 不跳过不补默认。

    ``normal`` 与 ``source_face`` 不在清单列内：法向按 (0,0,0)、来源面按负序号占位——
    负值不会与任何真 B-Rep 面 id 相撞（add_face_point 的同面去重不会被误触发）。
    """
    rows = [r for r in csv.reader(io.StringIO(text)) if r]
    if not rows or tuple(rows[0]) != CSV_HEAD:
        raise ValueError(f"CSV 表头应是「{','.join(CSV_HEAD)}」，"
                         f"实得「{','.join(rows[0]) if rows else '（空）'}」")
    out: list[Waypoint] = []
    for line_no, row in enumerate(rows[1:], start=2):
        if len(row) != len(CSV_HEAD):
            raise ValueError(f"CSV 第 {line_no} 行应是 {len(CSV_HEAD)} 列，实得 {len(row)} 列")
        try:
            wid = int(row[0])
            x, y, z = float(row[2]), float(row[3]), float(row[4])
        except ValueError as exc:
            raise ValueError(f"CSV 第 {line_no} 行含非数字：{row!r}") from exc
        if not row[1].strip():
            raise ValueError(f"CSV 第 {line_no} 行名称为空")
        out.append(Waypoint(id=wid, name=row[1], pos_mm=(x, y, z), normal=(0.0, 0.0, 0.0),
                            source_face=-len(out) - 1))
    return out

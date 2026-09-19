"""app.plc_out —— 编程页签底部的 PLC 输出区（T17；01 蓝图 §6.3，演示稿画面 05）。

①输出内容开关（工步数据表 CSV／变量映射表 CSV 勾选决定导出内容；SCL 程序骨架**禁用**＋
「待电气方确认后开放」，Δ-7）②工步编排（编排方式／速度来源／工步起始**实做**；弦高容差／
掉头保护**禁用**＋「待定」——未定口径 ⛔ 禁假装生效）③「生成／预览／导出 CSV／复制」
④汇总行（已生成 N 工步 · 变量映射 M 条 · ProcessStep 预算，超限黄警示**不禁导出**）。

口径：声明文案与身份串逐字读 ``config/ui.yaml``（§1-8 代码零字面量）；数据源＝``core.process``
纯函数，路径真值只在 ``pathctl``——``bind`` 接 ``pathctl.changed``，路径一变已生成工步即作废
并提示重生成（卡片步骤 6）；未生成路径时输出区整体禁用＋「先在上方生成轨迹」；速度恒「估算值」
口径（铁律 2）；预览与导出**同源**（同一份 build_steps 结果，⛔ 禁各算一遍）；导出文件名＝
〈工程名〉_〈表名〉_〈时间戳〉.csv、UTF-8-BOM（蓝图 §6.3）。预览模态在 ``app/plc_preview.py``
（本单拆件：两件 UI 各 ~250 行，合并则必破 04 §4.5-① 的 300 行硬顶——处置先例＝T07
``pathctl.py``，收单报备追认；本件 bind 内懒导入防回环）。
"""

from __future__ import annotations

import pathlib
import time

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from core.process import (MODE_TEXT, SPEED_TEXT, budget, build_steps, steps_to_csv, variable_map,
                          vars_to_csv)

LATER_NOTE = "待定"                       # 弦高容差／掉头保护（未定口径，Δ-7）
SCL_TOGGLE = "程序骨架（SCL · 参考样例）"  # SCL 选项（Δ-7 期 3 开放；开关＋说明两件渲染）
SCL_NOTE = "待电气方确认后开放"
SCL_TEXT = f"{SCL_TOGGLE} · {SCL_NOTE}"
NO_PATH_NOTE = "先在上方生成轨迹"
READY_NOTE = "已就绪：点「生成」按当前编排产出工步数据"
STALE_NOTE = "路径已改动，已生成工步作废——请重新点「生成」"
SUMMARY_FMT = "已生成 {n} 工步 · 变量映射 {m} 条\nProcessStep 预算 {used}/{limit}（{pct:g}%）"
OVER_NOTE = "超预算（如实呈现，仍可导出）"
TS_FILE = "%Y%m%d_%H%M%S"
WRAP_CAP = 370               # 换行标签折行帽：栈宽受 T14 工具行既定 442 撑宽时，声明串折行点
                             # 仍落在 std 左栏可见区内（含卡片边距余量，逐字可见防折叠裁字）


def _repaint(widget) -> None:
    """动态属性（tone）变更后让 QSS 重新生效（theme 口径，输出区与预览模态共用）。"""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _dim(text: str) -> QLabel:
    """次要文字标签（tone=dim；字号颜色走全局 QSS，本件不写内联样式）。"""
    label = QLabel(text)
    label.setProperty("tone", "dim")
    return label


class PlcOutArea(QWidget):
    """编程页签底部的 PLC 输出区（演示稿画面 05）。构造无参；外壳数据经 ``bind`` 注入。"""

    log = Signal(str)                        # 人话日志（bind 接状态栏，先例＝prog_tab.store_log）

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._win = None
        self._built: dict | None = None      # 生成结果（预览/导出/复制与预览模态同一份）
        self._last_dir = ""                  # 导出目录的会话内记忆（口径登记见完工汇报）
        card = QFrame()
        card.setObjectName("PlaceholderCard")   # 卡片档圆角 0，样式走全局 QSS（§4-C）
        box = QVBoxLayout(card)
        box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(6)
        head = QHBoxLayout()
        title = QLabel("PLC 输出")
        title.setObjectName("PaneTitle")
        self._badge = _dim("未生成")
        head.addWidget(title)
        head.addWidget(_dim("供电气 PLC 编程使用"))
        head.addWidget(self._badge)          # 徽标随排不右推：左栏窄档（T14 工具行既定栈宽）下保可见
        box.addLayout(head)
        self._build_outputs(box)
        box.addWidget(_dim("② 工步编排"))
        box.addLayout(self._build_plan())
        note = _dim("ProcessStep 预算上限与已用数见下方汇总；弦高容差／掉头保护待工艺口径，未定前不参与编排。")
        self._summary, self._declare = QLabel(NO_PATH_NOTE), QLabel("")
        self._summary.setProperty("tone", "dim")
        for wrapped in (note, self._summary, self._declare):
            wrapped.setWordWrap(True)
            wrapped.setMaximumWidth(WRAP_CAP)   # 折行帽：防声明串折行点落进折叠区被裁字
            box.addWidget(wrapped)
        self._build_actions(box)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        self._set_enabled(False)

    def _build_outputs(self, box: QVBoxLayout) -> None:
        """①输出内容：两份 CSV 勾选（决定导出内容）＋SCL 禁用开关＋说明（Δ-7 期 3 开放）。"""
        box.addWidget(_dim("① 输出内容"))
        out_grid = QGridLayout()
        out_grid.setHorizontalSpacing(8)
        self._sw_steps, self._sw_vars = QCheckBox("工步数据表（CSV）"), QCheckBox("变量映射表（CSV，含 NodeId）")
        for row, sw in enumerate((self._sw_steps, self._sw_vars)):
            sw.setChecked(True)
            out_grid.addWidget(sw, row, 0)
        out_grid.setColumnStretch(1, 1)      # 空列吃余量，防勾选框被均摊推宽
        box.addLayout(out_grid)
        scl = QCheckBox(SCL_TOGGLE)
        scl.setEnabled(False)
        scl.setToolTip(SCL_TEXT)
        scl_note = _dim(SCL_NOTE)
        scl_note.setWordWrap(True)
        scl_row = QHBoxLayout()
        scl_row.addWidget(scl)
        scl_row.addWidget(scl_note, 1)
        box.addLayout(scl_row)

    def _build_actions(self, box: QVBoxLayout) -> None:
        """③动作行：生成（主钮）/预览/导出 CSV/复制；后三钮待生成后启用。"""
        btn_row = QHBoxLayout()
        self._btn_build = QPushButton("生成")
        self._btn_build.setProperty("role", "primary")
        self._btn_preview = QPushButton("预览")
        self._btn_export = QPushButton("导出 CSV")
        self._btn_copy = QPushButton("复制")
        for btn, slot in ((self._btn_build, self._on_generate), (self._btn_preview, self._on_preview),
                          (self._btn_export, self._on_export), (self._btn_copy, self._on_copy)):
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)
        self._btn_preview.setEnabled(False)
        self._btn_export.setEnabled(False)
        self._btn_copy.setEnabled(False)
        btn_row.addStretch(1)
        box.addLayout(btn_row)

    def _build_plan(self) -> QGridLayout:
        """②工步编排：下拉/起始实做，弦高容差/掉头保护禁用＋「待定」（⛔ 禁假装生效）。

        字段宽钉住（演示稿 58px 级窄档；不收会以 sizeHint 撑破 std 左栏可见宽）。
        """
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        self._mode = QComboBox()
        for key, text in MODE_TEXT.items():
            self._mode.addItem(text, key)
        self._mode.setFixedWidth(110)
        self._speed = QComboBox()
        for key, text in SPEED_TEXT.items():
            self._speed.addItem(text, key)
        self._speed.setFixedWidth(96)
        self._start = QSpinBox()
        self._start.setRange(1, 1000000)
        self._start.setFixedWidth(90)
        self._chord, self._turn = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self._chord, self._turn):
            spin.setEnabled(False)
            spin.setFixedWidth(90)
            spin.setSpecialValueText(LATER_NOTE)     # 值恒在最小值 ⇒ 框内显示「待定」
            spin.setToolTip(f"{LATER_NOTE}（待工艺口径）")
        for col, widget in enumerate((_dim("编排方式"), self._mode)):
            grid.addWidget(widget, 0, col)
        for col, widget in enumerate((_dim("弦高容差"), self._chord, _dim("掉头保护"), self._turn)):
            grid.addWidget(widget, 1, col)
        for col, widget in enumerate((_dim("工步起始"), self._start, _dim("速度来源"), self._speed)):
            grid.addWidget(widget, 2, col)
        grid.setColumnStretch(4, 1)          # 空列吃余量：栅格钉在左，防末列被均摊推到折叠区外
        return grid

    # --- 外壳注入与路径失效联动（卡片步骤 6；pathctl.changed 是唯一联动点）---------------- #
    def bind(self, win) -> None:
        self._win = win
        self._declare.setText(win.ui.plc_declare_table)     # 第 2 串：输出区表下注（ui.yaml）
        self.log.connect(win.statusbar.log)
        win.pathctl.changed.connect(self._on_path_changed)
        from app.plc_preview import PlcPreview               # 懒导入（拆件防回环，见模块 docstring）
        win.plc_preview = PlcPreview(win, self)              # 预览模态（先例＝install_t14 装浮层）

    def _on_path_changed(self) -> None:
        """路径真值一变：整体启停＋已生成工步作废（重生成提示）——真值只在 pathctl。"""
        has_path = bool(self._win.pathctl.segments())
        self._set_enabled(has_path)
        if self._built is not None:
            self._built = None
            [btn.setEnabled(False) for btn in (self._btn_preview, self._btn_export, self._btn_copy)]
            self._badge.setText("未生成")
            self._summary.setText(STALE_NOTE)
            self._summary.setProperty("tone", "warn")
        else:
            self._summary.setText(READY_NOTE if has_path else NO_PATH_NOTE)
            self._summary.setProperty("tone", "dim")
        _repaint(self._summary)

    def _set_enabled(self, on: bool) -> None:
        """未生成路径 ⇒ 输出区整体禁用（卡片步骤 6）。"""
        for widget in (self._sw_steps, self._sw_vars, self._mode, self._speed, self._start,
                       self._btn_build):
            widget.setEnabled(on)

    # --- 生成/预览/导出/复制（预览与导出同源：同一份 self._built）--------------------------- #
    def _on_generate(self) -> None:
        segments = self._win.pathctl.segments()
        if not segments:
            return
        cfg = self._win.pathctl.kinematics()[0]
        if cfg is None:                       # 先例＝pop_import._project 的兜底同款
            from core.config import REPO_ROOT, load_machine
            cfg = load_machine(str(REPO_ROOT / "config" / "machine.yaml"))
        steps = build_steps(segments, self._mode.currentData(), self._start.value(),
                            self._speed.currentData(), cfg.limits.speed_max_mm_s,
                            cfg.opcua.write_nodes["seg_array"])
        self._built = {"steps": steps, "vars": variable_map(cfg), "name": cfg.machine.name,
                       "mode": self._mode.currentText(), "ts": _view_ts(),
                       "file_ts": time.strftime(TS_FILE), "limit": self._win.ui.process_step_budget}
        self._refresh_summary(steps, self._built["limit"])
        [btn.setEnabled(True) for btn in (self._btn_preview, self._btn_export, self._btn_copy)]
        self.log.emit(f"已生成工步数据：{len(steps)} 工步（编排 {self._mode.currentText()}）")

    def _refresh_summary(self, steps, limit: int) -> None:
        """汇总行＋徽标：预算超限 ⇒ 黄警示＋「如实呈现，仍可导出」（硬换行短行，窄列下必可见）。"""
        used, _limit = budget(steps, limit=limit)
        pct = used * 100.0 / limit if limit else 0.0
        text = SUMMARY_FMT.format(n=len(steps), m=len(self._built["vars"]),
                                  used=used, limit=limit, pct=pct)
        if used > limit:
            text += f"\n{OVER_NOTE}"
        self._badge.setText(f"{len(steps)} 工步")
        self._summary.setText(text)
        self._summary.setProperty("tone", "warn" if used > limit else "text")
        _repaint(self._summary)

    def _on_preview(self) -> None:
        if self._built:
            self._win.plc_preview.show_preview(self._built)

    def _on_export(self) -> None:
        """按输出内容勾选导出 CSV（UTF-8-BOM）；任一取消即整体取消（半份交接物禁产生）。"""
        if not self._built:
            return
        tables = [(self._sw_steps.isChecked(), "工步数据表", steps_to_csv(self._built["steps"])),
                  (self._sw_vars.isChecked(), "变量映射", vars_to_csv(self._built["vars"]))]
        wrote: list[str] = []
        for checked, suffix, text in tables:
            if not checked:
                continue
            default = f"{self._built['name']}_{suffix}_{self._built['file_ts']}.csv"
            path, _ = QFileDialog.getSaveFileName(self, f"导出{suffix}", self._last_dir + default,
                                                  "CSV 文件 (*.csv);;所有文件 (*)")
            if not path:
                return
            target = pathlib.Path(path)
            target.write_text(text, encoding="utf-8-sig")
            self._last_dir = f"{target.parent}/"
            wrote.append(str(target))
        if wrote:
            self.log.emit("已导出：" + "；".join(wrote) + "（UTF-8 BOM）")

    def _on_copy(self) -> None:
        if self._built:
            QGuiApplication.clipboard().setText(steps_to_csv(self._built["steps"]))
            self.log.emit("工步数据表已复制到剪贴板")


def _view_ts() -> str:
    """模态「生成 〈时刻〉」的时间串（%Y-%m-%d %H:%M:%S；文件名时间戳另用 TS_FILE）。"""
    return time.strftime("%Y-%m-%d %H:%M:%S")

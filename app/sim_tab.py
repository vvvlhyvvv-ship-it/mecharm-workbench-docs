"""app.sim_tab —— 路径仿真页签体（T15 建；T16 填干涉清单挂点＋涉事设备列，蓝图 §3.4③）。
页头（结论行＋五格 KPI，预计时长恒带「估算」、无路径全「—」）→ ①时间轴·预演 → ②执行控制·下发
（＝step5_send 嵌入）→ ③干涉清单·按设备归并（T16 调 core.collision_report 只投影真值：归并行＋
首条干涉对明细＋「需调整示教点或路径」建议）→ ④轨迹清单表（涉事设备列＝真算得出的组名、算不出「—」）。
构造签名 ``SimTab(panel)`` 固定；pathctl/checkctl/bridge 由 sendctl 后绑定（attach）。投影纪律
（03 §3／G13）：真值只在 core／checkctl，本件只投影（先例＝wiring._on_check_result 读 _result）。
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from app.theme import TOKENS
from core.collision import VERDICT_INTERFERE, sample_joints
from core.collision_report import ClashReport, group_by_device
from core.kinematics.transform import to_column_major
from core.path import estimate_duration, tool_pose_in_model

_COLS = ("步", "时间(s·估算)", "涉事设备", "X(mm)", "Z(mm)", "状态")
_DASH = "—"


class _Track(QWidget):
    """时间轴横条（自绘红绿带＋刻度＋游标；带色＝语义色半透明，颜色全由 theme 派生 ⛔ 不散写色值）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(26)
        self._bands, self._ticks, self._cursor = [], [], None

    def set_track(self, bands, ticks, cursor) -> None:
        self._bands, self._ticks, self._cursor = list(bands), list(ticks), cursor
        self.update()

    def paintEvent(self, event) -> None:
        p, w, h = QPainter(self), self.width(), self.height()
        p.fillRect(self.rect(), QColor(TOKENS["bg_panel"]))
        for begin, end, bad in self._bands:          # 演示稿 band.ok/.bad 同构
            color = QColor(TOKENS["deny" if bad else "ok"])
            color.setAlpha(90 if bad else 60)
            p.fillRect(begin * w, 0, max((end - begin) * w, 1.0), h, color)
        p.setPen(QColor(TOKENS["border2"]))
        [p.drawLine(int(t * w), 0, int(t * w), h) for t in self._ticks]
        p.setPen(QColor(TOKENS["border"]))
        p.drawRect(0, 0, w - 1, h - 1)
        if self._cursor is not None:
            p.setPen(QColor(TOKENS["accent"]))
            p.drawLine(int(self._cursor * w), 0, int(self._cursor * w), h)


class SimTab(QWidget):
    """路径仿真页签体。构造签名 ``SimTab(panel)`` 固定；业务数据经 `attach` 后绑定。"""

    def __init__(self, panel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._panel, self._pathctl = panel, None
        self._checkctl = self._bridge = None
        self._bands, self._ticks, self._ids, self._case_rows = [], [], [], []
        self._cursor_seg = 0                        # 游标段号（＝step3._current，段级粒度不外推）
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_seg)
        self._poll.start(80)                        # 播放游标轮询（软件刷新率，非机台参数）
        outer, scroll = QVBoxLayout(self), QScrollArea()
        outer.setContentsMargins(0, 0, 0, 0)
        scroll.setWidgetResizable(True)
        body, box = QWidget(), QVBoxLayout()
        box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(8)
        self._summary, self._t_line = QLabel(_DASH), QLabel(_DASH)
        [w.setWordWrap(True) for w in (self._summary, self._t_line)]
        [w.setProperty("tone", "dim") for w in (self._summary, self._t_line)]
        kpi_row = QHBoxLayout()
        self._kpis: dict = {}
        for key, label in (("dur", "预计时长（估算）"), ("samples", "插补步数"), ("segs", "目标点段"), ("bad", "干涉步"), ("gate", "下发许可")):
            kpi_row.addWidget(self._kpi(key, label), 1)
        box.addLayout(kpi_row)
        self._enter, self._play, self._exit = QPushButton("◉ 进入预演"), QPushButton("▶ 播放预演"), QPushButton("⏏ 退出预演")
        btns = QHBoxLayout()
        for btn in (self._enter, self._play, self._exit):
            btn.setEnabled(False)
            btn.clicked.connect(self._on_preview)
            btns.addWidget(btn)
        btns.addStretch(1)
        btns.addWidget(self._t_line)
        self._track = _Track()
        self._mode_all, self._mode_ptp = QPushButton("全部插补步"), QPushButton("目标点级")
        for btn in (self._mode_ptp, self._mode_all):
            btn.setCheckable(True)
            btn.clicked.connect(self._switch_mode)
        self._mode_ptp.setChecked(True)
        self._only_bad = QCheckBox("只看干涉")
        self._only_bad.clicked.connect(self.refresh)
        self._table = self._make_table()
        self._clash = QLabel(_DASH)                  # ③ 干涉清单（T16）：rich text 归并＋明细
        self._clash.setWordWrap(True)
        self._section("① 时间轴 · 预演（只动画面，不下发）", box)
        box.addLayout(btns)
        box.addWidget(self._track)
        self._section("② 执行控制 · 下发", box)
        box.addWidget(panel.step5)
        panel.step5.show()   # 摘自 Panel 的栈页带着隐藏态，须显式复显（T13 同款）
        self._section("③ 干涉清单 · 按设备归并", box)
        box.addWidget(self._clash)
        self._section("④ 轨迹清单", box)
        listbar = QHBoxLayout()
        [listbar.addWidget(w) for w in (self._mode_ptp, self._mode_all, self._only_bad)]
        listbar.addStretch(1)
        listbar.addWidget(QLabel("点干涉行 → 3D 定位"))
        box.addLayout(listbar)
        box.addWidget(self._table, 1)
        body.setLayout(box)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self.refresh()

    def attach(self, pathctl, checkctl, bridge) -> None:   # 业务数据源：零毫秒定时器后绑定（构造时三者未建）
        self._pathctl, self._checkctl, self._bridge = pathctl, checkctl, bridge
        checkctl.changed.connect(self.refresh)
        self.refresh()

    def _poll_seg(self) -> None:
        seg = self._panel.step3._current            # 播放/下发段高亮＝游标真值（pathctl 每帧调）
        if seg != self._cursor_seg: self._cursor_seg, _ = max(seg, 0), self._paint_track()

    def _on_preview(self) -> None:
        if self._pathctl is None: return
        if self.sender() is self._play:
            self._pathctl.play()                    # 播放机制沿用 pathctl 原件（编程页签同源）
        elif self.sender() is self._exit:
            self._pathctl.pause()
        else:                                       # 进入预演：游标回起点
            self._cursor_seg, _ = 0, self._paint_track()

    def refresh(self) -> None:
        """全页重算（唯一入口；未生成路径 ⇒ 全「—」，⛔ 禁演示值）。"""
        segments = self._pathctl.segments() if self._pathctl else []
        cfg = self._pathctl.kinematics()[0] if self._pathctl else None
        result = self._checkctl._result if self._checkctl else None   # 先例：wiring._on_check_result
        if segments and cfg is not None:
            total = estimate_duration(segments, cfg.limits)
            samples = sample_joints(segments, cfg.limits.path_sample_step_mm)
            cases = list(result.cases) if result else []
            bad = sum(1 for case in cases if case.min_dist_mm <= 0.0)
            warn = len(cases) - bad
            asm = getattr(self._checkctl, "_asm", None) if self._checkctl else None
            report = group_by_device(result, asm.tree) if result is not None and asm else ClashReport((), ())  # ③④共用
            text = (f"校核完成 · 可行 {len(samples) - len(cases)} / 干涉 {bad} / 共 {len(samples)} 插补步"
                    f" · 结论 {'不通过' if result.verdict == VERDICT_INTERFERE else '预警' if warn else '通过'}"
                    ) if result else "已生成路径，尚未校核（在「②」区连接并开始校核）"
            tone = ("deny" if bad else "warn" if warn else "ok") if result else "dim"
            self._summary.setText(text)
            self._summary.setProperty("tone", tone)
            ready = self._checkctl.ready()
            cells = (("dur", f"≈{total:.1f} s", "accent"), ("samples", str(len(samples)), None),
                     ("segs", str(len(segments)), None), ("bad", str(bad) if result else _DASH, "deny" if bad else None),
                     ("gate", "允许" if ready else "禁止", "ok" if ready else "deny"))
            [self._set_kpi(key, val, tone) for key, val, tone in cells]
            self._build_track(segments, {case.seg_id for case in cases}, cfg.limits, total)
            self._fill_table(segments, cases, samples, cfg, report)
            self._fill_clash(result, report)
            self._t_line.setText(f"t ＝ 共 ≈{total:.1f} s（估算）")
            [btn.setEnabled(True) for btn in (self._enter, self._play, self._exit)]
        else:
            self._summary.setText("尚无路径：先在「编程」页签取点并生成轨迹")
            self._summary.setProperty("tone", "dim")
            [label.setText(_DASH) for label in [*self._kpis.values(), self._clash, self._t_line]]
            self._bands, self._ticks, self._ids, self._case_rows = [], [], [], []
            self._table.setRowCount(0)
            [btn.setEnabled(False) for btn in (self._enter, self._play, self._exit)]
        self._repaint(self._summary)
        self._paint_track()

    def _build_track(self, segments, bad_ids, limits, total) -> None:   # 带占比＝估算时长；刻度＝目标点分界
        self._bands, self._ticks, self._ids, gone = [], [], [s.id for s in segments], 0.0
        for seg in segments:
            span = self._span(seg, limits)
            self._ticks.append(gone)
            self._bands.append((gone / total, (gone + span) / total, seg.id in bad_ids))
            gone += span
        self._paint_track()

    def _paint_track(self) -> None:
        at = self._bands[self._ids.index(self._cursor_seg)][0] if self._cursor_seg in self._ids else None
        self._track.set_track(self._bands, self._ticks, None if at is None else min(at + 1e-6, 1.0))

    def _make_table(self) -> QTableWidget:
        table = QTableWidget(0, len(_COLS))
        table.setHorizontalHeaderLabels(_COLS)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.cellClicked.connect(self._locate)
        return table

    def _fill_clash(self, result, report: ClashReport) -> None:
        """③ 干涉清单（T16 挂点）：归并行＋首条干涉对明细＋人话建议；无结论「—」（⛔ 禁演示值）。"""
        rows = report.by_device if result is not None else ()
        red = TOKENS["deny"]
        self._clash.setProperty("tone", "deny" if rows else "dim")
        lines = [f"<span style='color:{red}'>⚠ {r.group} · {r.member}（{len(r.cases)} 处）</span>" for r in rows]
        if rows:
            worst = rows[0].cases[0]
            skipped = f"，另有 {len(report.skipped)} 个零件未能归并到设备组" if report.skipped else ""
            advice = "需调整示教点或路径" if worst.min_dist_mm <= 0.0 else "间距小于安全值，请确认工装与路径"
            lines.append(f"<span style='color:{red}'>干涉对：臂身 {worst.part_a} ↔ {worst.part_b} · 最小时距"
                         f" {worst.min_dist_mm:.1f} mm · 步 {worst.seg_id} · {advice}{skipped}</span>")
        self._clash.setText("<br>".join(lines) if lines else _DASH)
        self._repaint(self._clash)

    def _fill_table(self, segments, cases, samples, cfg, report=None) -> None:
        """目标点级＝段行；插补步＝样点行（first＝首样从 0 起、其后归前段）。涉事设备列（T16）＝
        该段涉事零件的设备组名（真算得出），无结论恒「—」（⛔ 禁造设备名）。"""
        chain, frame = self._pathctl.kinematics()[1], self._pathctl.kinematics()[2]
        self._table.setRowCount(0)
        self._case_rows = []
        at, by_seg, step_mm = 0.0, {}, cfg.limits.path_sample_step_mm
        by_dev = {c.seg_id: report.group_of(c.part_b) or c.part_b for c in reversed(cases)} if report else {}
        for seg_id, joints in samples:
            by_seg.setdefault(seg_id, []).append(joints)
        for pos, seg in enumerate(segments):
            span, state = self._span(seg, cfg.limits), self._state_of(seg.id)
            first, steps = (0 if pos == 0 else 1), max(1, int(-(-seg.length_mm // step_mm)))
            device = by_dev.get(seg.id, _DASH)
            if self._mode_all.isChecked() and chain is not None:
                for i, joints in enumerate(by_seg.get(seg.id, [])):
                    x, z = self._proj(joints, chain, frame)
                    self._append_row(seg.id, at + (i + first) / steps * span, device, x, z, state)
            else:
                self._append_row(seg.id, at, device, f"{seg.end_mm[0]:.1f}", f"{seg.end_mm[2]:.1f}", state)
            at += span

    def _proj(self, joints, chain, frame) -> tuple:
        if not joints:                              # 阻断段无解 → 如实「—」
            return _DASH, _DASH
        pose = to_column_major(tool_pose_in_model(joints, chain, frame))
        return f"{pose[12]:.1f}", f"{pose[14]:.1f}"  # 列主序平移在 12/13/14（03 §5 口径）

    def _state_of(self, seg_id: int) -> tuple:
        result = self._checkctl._result if self._checkctl else None
        hit = next(((i, c) for i, c in enumerate(result.cases) if c.seg_id == seg_id), None) if result else None
        if hit is None:
            return "可行", "ok", None
        case, bad = hit[1], hit[1].min_dist_mm <= 0.0
        return ("⛔ 干涉" if bad else f"⚠ 预警 {case.min_dist_mm:.1f}mm", "deny" if bad else "warn", hit[0])

    def _append_row(self, seg_id, at, device, x, z, state) -> None:
        text, tone, index = state
        if self._only_bad.isChecked() and index is None:
            return                                  # 只看干涉：无 case 的行直接不落
        row = self._table.rowCount()
        self._table.insertRow(row)
        for col, value in enumerate((str(seg_id), f"{at:.1f}", device, x, z, text)):
            item = QTableWidgetItem(value)
            if col == 5:
                item.setForeground(QColor(TOKENS[tone]))
            self._table.setItem(row, col, item)
        self._case_rows.append(index)

    def _switch_mode(self) -> None:
        self._mode_ptp.setChecked(self.sender() is self._mode_ptp)
        self._mode_all.setChecked(not self._mode_ptp.isChecked())
        self.refresh()

    def _locate(self, row: int, _col: int) -> None:
        index = self._case_rows[row] if 0 <= row < len(self._case_rows) else None
        if index is not None and self._bridge is not None:   # 复用现干涉定位桥通道（T08）
            self._bridge.call_view("collision.focus", {"index": index})

    @staticmethod
    def _span(seg, limits) -> float:
        key = "speed_rapid_mm_s" if seg.type == "JOINT" else "speed_work_mm_s"
        return seg.length_mm / min(getattr(limits, key), limits.speed_max_mm_s)

    def _kpi(self, key, label) -> QWidget:
        cap, value, host, lay = QLabel(label), QLabel(_DASH), QWidget(), QVBoxLayout()
        cap.setProperty("tone", "dim"); value.setProperty("mono", "true")
        self._kpis[key] = value
        [lay.addWidget(w) for w in (cap, value)]     # 本件列表推导风格（同 refresh 尾行）
        lay.setContentsMargins(0, 0, 0, 0)
        host.setLayout(lay)
        return host

    def _set_kpi(self, key, text, tone=None) -> None:
        label = self._kpis[key]
        label.setText(text)
        label.setProperty("tone", tone or "text")
        self._repaint(label)

    def _section(self, text, box) -> None:
        label = QLabel(text)
        label.setObjectName("PaneTitle")
        box.addWidget(label)

    @staticmethod
    def _repaint(label) -> None:
        label.style().unpolish(label)
        label.style().polish(label)

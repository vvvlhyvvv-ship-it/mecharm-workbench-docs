"""app.checkctl —— 步骤④「碰撞校核」与步骤⑤「禁发双阻断」的控制器（T08；02 §2 步骤④⑤、03 §3/§5）。

**为什么单列一个文件**：`app/shell.py` 已贴着 04 §4.5-① 的「单文件 ≤300 物理行」上限（T08 接线后
**正好 300 行＝零余量**，派单卡 T10 §4(a) 点名 ⛔ 不得再内联），校核编排／双阻断／视口报警条载荷塞进去
必越线 ⇒ 本件承载业务、shell 只做三行接线（沿用 T07 的 `app/pathctl.py` 先例）。本文件名**非** 04
预授权命名 ⇒ 已在 T08 交付汇报报备。T10 起下发侧的壳接线总成也装在**本件** `__init__` 里而不是 shell.py
（同一条零余量理由），且下发本就是本件 `send_path()` 的下一棒 ⇒ 交棒处只发一个 `send_confirmed`。

单向数据流（03 §3）：路径段真值只在 `core.path`（步骤③生成，经 `app/pathctl.py` 转交）、障碍几何只在
`core.geometry`（步骤①导入的 B-Rep 真身）⇒ 本件只把两者装进 `CollisionScene` 交 `core.collision.check`
判定，⛔ 本层不算几何、⛔ 不改判据、⛔ 不缓存第二份真值；结论（frozen dataclass）回灌右栏 `Step4Pane`、
视口报警条与步骤⑤门禁，三处读的是同一份。

**禁发双阻断**（卡片步骤 5，两条各留日志）：
  ① 步骤⑤按钮置灰（`_refresh_gate`）：结论为🔴干涉／尚未校核／路径已改动 ⇒ `panel.send_btn` disabled
     ＋旁注人话原因（02 §2 步骤⑤「校核未通过，无法下发」）；门禁**状态变化**写 info 日志；
  ② `send_path()` 入口**独立复判**：⛔ 不信任按钮状态——重新读结论、按当前路径重算指纹比对（路径改动即
     失配拒发），再**重新跑一次权威判定**（校核后若换了模型／改了点位，旧结论就不作数），任一不过即拒发
     并写 warning 日志；过了才弹确认窗（G19 第 4 条：窗内复述覆盖面标注，由操作员确认）。

载荷全 ASCII（03 §5、`app/bridge.py` 用 `ensure_ascii=True` 投递）⇒ `collision.show`／`collision.focus`
**不带**中文点名与原因：障碍只发 `mesh_id`（部件名由视口从已载入的 mesh 自取）、结论只发三态字面；人话
整句留在右栏（壳内）。二者是本单新定的视口 type，03 §5 未登记 ⇒ 汇报请回填（同 T07 的 `perf.fps`）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from app.alarm_modal import popup as alarm_popup
from app.sendctl import install_send_flow
from app.steps.step4_check import Step4Pane
from core.collision import (VERDICT_INTERFERE, VERDICT_WARN, CollisionError, CollisionResult,
                            CollisionScene, check, mode_axes, obstacles_from, path_fingerprint)
from core.collision_report import group_by_device
from core.path import summarize

log = logging.getLogger(__name__)

_SEND_NOTE = "下发 = 向 PLC 提出运动请求，PLC 会再校验并有权拒绝或限速"   # 02 §2 步骤⑤ 固定小字
_LEVEL = {VERDICT_INTERFERE: "deny", VERDICT_WARN: "warn"}   # 三态字面 → 视口颜色语义（其余＝clear）
_CLEAR = {"level": "clear", "cases": []}                     # 撤下报警条与标记的载荷


class CheckController(QObject):
    """步骤④校核＋步骤⑤禁发门禁。`changed()`＝下发可用性变了（shell 据此重算步骤⑤是否可达）。"""

    changed = Signal()
    send_confirmed = Signal(object)    # 双阻断都过且操作员已确认 → 载荷＝复判后的结论（T10 的下发交棒）

    def __init__(self, panel, bridge, stepbar, statusbar, pathctl, workmode,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._panel = panel
        self._bridge = bridge
        self._stepbar = stepbar
        self._statusbar = statusbar
        self._pathctl = pathctl
        self._workmode = workmode
        self._result: CollisionResult | None = None
        self._alarm = None                      # T16 阻断式报警模态（仅呈现；结果作废即关）
        self._alarm_path = ""
        self._asm = None                       # 步骤①的导入结果（障碍几何来源；本层不复制几何）
        self._mesh_ids: dict[str, int] = {}    # 障碍名 → mesh_id（视口高亮用，⛔ 不存第二份真值）
        self._gate_on = False
        # 确认弹窗里「请求值小字」的取数钩子：弹窗归本件（禁发第②条），下发数值归 `app/sendctl.py`
        # ⇒ 由它在 `install_send_flow` 里装上。None 即弹窗不显示小字 ⛔ 本件不自己算一份。
        self.request_note: Callable[[], str] | None = None
        self._wire()
        self._invalidate("尚未校核")
        # T10 的壳侧接线总成装在**这里**而不是 shell.py：shell.py 正好 300 行＝04 §4.5-① 上限零余量
        # （派单卡 §4(a) 点名 ⛔ 不得内联），而下发本就是本件 `send_path()` 的下一棒。理由详见 sendctl。
        self.send_flow = install_send_flow(parent, self)

    def _wire(self) -> None:
        step4 = self._panel.step4
        step4.check_requested.connect(self.run_check)
        step4.case_clicked.connect(self.locate)
        step4.log.connect(self._say)
        self._panel.step1.imported.connect(self._on_imported)
        self._panel.send_btn.clicked.connect(self.send_path)
        self._pathctl.changed.connect(self._on_path_changed)

    # --- 门禁（双阻断第①条：按钮置灰）---------------------------------------- #
    def ready(self) -> bool:
        """步骤⑤是否可达（shell 的 `_refresh_unlock` 读它）：结论非🔴干涉且路径指纹一致。"""
        return self._stale_reason() is None

    def _stale_reason(self) -> str | None:
        """当前**不能**下发的人话原因；None＝可下发。只读状态＋重算指纹 ⛔ 不跑几何（门禁要轻）。"""
        if self._result is None:
            return "尚未做碰撞校核，无法下发：先在步骤④点[开始校核]"
        if self._result.verdict == VERDICT_INTERFERE:
            return f"校核未通过，无法下发：{Step4Pane.sentence(self._result)}"
        if path_fingerprint(self._pathctl.segments()) != self._result.path_hash:
            return "路径已改动，无法下发：旧校核结果已失效，须重新校核"
        return None

    def _refresh_gate(self) -> None:
        """刷⑤按钮与旁注；门禁**状态变化**留日志（＝双阻断第①条的痕迹，卡片步骤 5）。"""
        reason = self._stale_reason()
        on = reason is None
        self._panel.send_btn.setEnabled(on)
        self._panel.send_note.setText("" if on else reason)
        self._panel.step5.set_gate(on)   # T10：同一份可用性镜像给⑤页（它一处算完四个状态，免得互相盖）
        if on != self._gate_on:
            self._gate_on = on
            log.info("步骤⑤下发按钮%s：%s", "已解锁" if on else "已置灰",
                     "校核结论非干涉且路径指纹一致" if on else reason)

    # --- 校核 --------------------------------------------------------------- #
    def run_check(self) -> None:
        """[开始校核]：跑一次权威判定，结论灌右栏＋视口＋门禁（耗时数字同时进日志与状态栏）。"""
        result = self._judge()
        if result is None:
            return
        self._publish(result)
        self._say(f"碰撞校核完成：{result.describe()}｜{result.coverage()}｜"
                  f"{summarize(self._pathctl.segments()).describe()}｜耗时 {result.elapsed_ms:.1f} ms")

    def _judge(self) -> CollisionResult | None:
        """装场景 → 交 core 判定。数据不齐即人话报错返回 None ⛔ 不塞默认值、⛔ 不报"未检出碰撞"。"""
        segments = self._pathctl.segments()
        cfg, chain, frame = self._pathctl.kinematics()
        if not segments or cfg is None or chain is None:
            self._say("还没有可校核的路径：先在步骤③点[生成路径]")
            return None
        if self._asm is None:
            self._say("还没有可校核的障碍几何：先在步骤①导入实体模型（工件／模具／周边设备）")
            return None
        if not self._asm.is_brep:
            self._say("导入的是面片模型（没有 B-Rep 真身），做不了碰撞校核：请导入实体模型")
            return None
        obstacles = obstacles_from(self._asm)
        self._mesh_ids = {item.name: item.mesh_id for item in obstacles}
        scene = CollisionScene(cfg, chain, frame, obstacles,
                               mode_axes(cfg, self._workmode.current_mode() or ""))
        try:
            return check(segments, scene, cfg.limits.clearance_warn_mm)
        except CollisionError as exc:
            self._say(str(exc))          # core 的报错本就是人话（可直上屏），本层不改写
            return None

    def _publish(self, result: CollisionResult) -> None:
        """结论落三处：右栏卡片／列表、视口报警条与标记、步骤条与⑤门禁（读同一份不可变结果）。"""
        self._result = result
        self._panel.step4.show_result(result)
        self._show_viewport(result)
        if result.verdict != VERDICT_INTERFERE:
            self._stepbar.mark_completed(4)   # 干涉态不标完成：步骤④没走完（同 T07 的 summary.ok 口径）
        elif not (self._alarm and self._alarm.isVisible()
                  and self._alarm_path == result.path_hash):
            # 阻断式报警模态（T16）：仅呈现、不裁决；同一结果已弹着就不重弹（复判路径防打扰）
            self._alarm_path = result.path_hash
            tree = self._asm.tree if self._asm is not None else ()
            self._alarm = alarm_popup(self._panel, self._bridge, result, group_by_device(result, tree))
        self._refresh_gate()
        self._refresh_ready()
        self.changed.emit()

    def _show_viewport(self, result: CollisionResult) -> None:
        """推 `collision.show`（全 ASCII：三态字面＋几何＋mesh_id ⛔ 不带中文点名与原因）。"""
        self._bridge.call_view("collision.show", {
            "level": _LEVEL.get(result.verdict, "clear"),
            "cases": [{"seg": c.seg_id, "arm": c.part_a, "obs": self._mesh_ids.get(c.part_b, 0),
                       "dist": round(c.min_dist_mm, 6), "point": [float(v) for v in c.point],
                       "box": [float(v) for v in c.box] if c.box else []}
                      for c in result.cases]})

    def locate(self, row: int) -> None:
        """列表点击行 → 视口定位干涉点＋双方红色高亮（02 §2 步骤④；障碍侧由视口转 `hl.set` 给 loader）。"""
        if self._result is None or not 0 <= row < len(self._result.cases):
            return
        case = self._result.cases[row]
        self._bridge.call_view("collision.focus", {"index": row})
        self._say(f"已在视口定位：第 {case.seg_id} 段，臂身 {case.part_a} 与 {case.part_b}"
                  f"（最小距离 {case.min_dist_mm:.1f} mm）")

    # --- 步骤⑤下发（双阻断第②条：入口独立复判）-------------------------------- #
    def send_path(self) -> bool:
        """下发入口。⛔ 不信任按钮状态：重读结论＋重算指纹＋重跑权威判定，任一不过即拒发（各留日志）。"""
        reason = self._stale_reason()
        if reason is not None:
            return self._refuse(reason)
        stale = self._result
        fresh = self._judge()             # 独立复判：校核后换了模型／改了点位，旧结论就不作数
        if fresh is None:
            log.warning("下发被拒（入口复判跑不出结论）：数据不齐或判定失败，原因已进状态栏")
            return False
        if stale is not None and (stale.verdict, stale.path_hash) != (fresh.verdict, fresh.path_hash):
            log.warning("下发前复判与上次校核不一致（%s／%s → %s／%s）：一律以复判为准",
                        stale.verdict, stale.path_hash, fresh.verdict, fresh.path_hash)
        self._publish(fresh)
        if fresh.verdict == VERDICT_INTERFERE:
            return self._refuse(f"下发前复判检出干涉：{Step4Pane.sentence(fresh)}")
        if not self._ask_operator(fresh, self._confirm_text(fresh)):
            log.info("下发已取消：操作员在确认弹窗点了[取消]")
            self._say("已取消下发")
            return False
        log.info("下发请求已确认（结论 %s、%d 段、指纹 %s）：已交下发通道（app/sendctl.py）",
                 fresh.verdict, len(self._pathctl.segments()), fresh.path_hash)
        self.send_confirmed.emit(fresh)     # T10：本件的职责到「确认可发」为止，写段与握手归下发编排
        return True

    def _refuse(self, reason: str) -> bool:
        """拒发：warning 日志留痕（双阻断第②条的证据）＋状态栏人话＋顺手刷门禁。"""
        log.warning("下发被拒（send_path 入口独立复判）：%s", reason)
        self._say(f"已拒绝下发：{reason}")
        self._refresh_gate()
        return False

    def _confirm_text(self, result: CollisionResult) -> str:
        """确认弹窗正文（02 §2 步骤⑤）：路径摘要＋校核结论＋**G19 覆盖面标注复述**（卡片处置第 4 条）
        ＋**请求值小字**（T10 卡片步骤①：把真要写进 PLC 的数摊开给操作员核，经 `request_note` 钩子取）。"""
        icon = "🟡" if result.verdict == VERDICT_WARN else "🟢"
        lines = [summarize(self._pathctl.segments()).describe(),
                 f"校核结论：{icon} {result.describe()}",
                 f"覆盖面：{result.coverage()}"]
        if result.verdict == VERDICT_WARN:
            lines.append("⚠ 预警：间距小于安全值——确认知悉后方可下发")
        if self.request_note is not None:
            lines += ["", "本次要写进 PLC 的请求值（请逐条核对）：", self.request_note()]
        return "\n".join(lines + ["", _SEND_NOTE])

    def _ask_operator(self, result: CollisionResult, text: str) -> bool:
        """确认弹窗（拆成独立方法：离屏取证可替身它，⛔ 不因此改动判定与门禁）。默认按钮＝[取消]。"""
        box = QMessageBox(self._panel)
        box.setWindowTitle("确认下发")
        box.setIcon(QMessageBox.Icon.Warning if result.verdict == VERDICT_WARN
                    else QMessageBox.Icon.Question)
        box.setText(text)
        ok = box.addButton("确认下发", QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(box.addButton("取消", QMessageBox.ButtonRole.RejectRole))
        box.exec()
        return box.clickedButton() is ok

    # --- 结果作废 ----------------------------------------------------------- #
    def _on_imported(self, res: object) -> None:
        """步骤①导入完成：障碍几何源换了 ⇒ 旧校核结果作废（模型都换了，旧结论不作数）。"""
        self._asm = res.get("asm") if isinstance(res, dict) else None
        self._invalidate("已导入新模型")

    def _on_path_changed(self) -> None:
        """步骤③路径生成／作废 ⇒ 旧校核结果一并作废（指纹已失配，留着＝给用户假数据）。"""
        self._invalidate("路径已改动")

    def _invalidate(self, why: str) -> None:
        had = self._result is not None
        self._result, self._mesh_ids = None, {}
        if self._alarm is not None and self._alarm.isVisible():
            self._alarm.close()                 # 结果作废 ⇒ 报警模态显示的旧结论一并撤下
        self._panel.step4.clear()
        self._bridge.call_view("collision.show", _CLEAR)
        if had:
            self._say(f"校核结果作废：{why}——须重新校核后才能下发")
        self._refresh_gate()
        self._refresh_ready()
        self.changed.emit()

    def _refresh_ready(self) -> None:
        """[开始校核] 可用性＝步骤③路径已生成无不可达段 **且** 步骤①已导入实体模型（与 shell 对步骤条④
        的门禁同口径）；不满足即给人话原因 ⛔ 不静默禁用、⛔ 不留一个点了只会报错的按钮。reason 为空即
        不动提示行（`show_result` 写的那行结论提示优先）。"""
        reason = ""
        if not self._pathctl.ready():
            reason = "等待步骤③：路径生成且无不可达段后才能校核"
        elif self._asm is None or not self._asm.is_brep:
            reason = "等待步骤①：导入实体模型（工件／模具／周边设备）后才能校核"
        self._panel.step4.set_ready(not reason, reason)

    def _say(self, msg: str) -> None:
        self._statusbar.log(msg)

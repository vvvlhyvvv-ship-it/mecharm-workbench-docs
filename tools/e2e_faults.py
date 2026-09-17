"""T10 卡片步骤④：异常三用例的**判据**（越界丢帧／PLC 拒绝／运行中断线）。

从 ``tools/e2e_smoke.py`` 拆出来的第三件——加了本节之后那件实测 310 行 > 04 §4.5-① 的 300 行上限，
去重复与抽函数都已做完（无函数超 50 行），只剩拆文件一条路（§4.5-②③）。拆线取**派单卡的步骤边界**：
``e2e_smoke.py`` 承载步骤⑦ 的全链路冒烟（A–G），本件承载步骤④ 的异常处置（H1–H3），
装置共用 ``tools/e2e_rig.py``，判据表与退出码仍只在 ``e2e_smoke.py`` 一处（⛔ 不另立一个入口）。

三例都在 G 节连上的**同一条链路**上顺路做，⛔ 不重连：重连就等于换了工况，前面那一步的证据也就不作数。
顺序固定为越界 → 拒绝 → 断线，因为断线会把本机模拟器停掉、之后再也发不了。

判据一律读**操作员看得见的那份原文**（⑤页红条文字与着色属性、[查看日志] 按钮、计数行、顶栏在线灯、
⑤页链路行与日志历史），⛔ 不另立只有取证才走的读数口（04 §5.5 附7-③ 那一族的假绿）。
"""

from __future__ import annotations

from tools.comm_selftest_kit import check
from tools.e2e_rig import OFFLINE_S, OVER_MARGIN, Rig

FROZEN_S = 3.0               # 断链后观察「模型停住不跳飞」的时长（够看出有没有新帧被采用）
LOG_BTN = "查看日志"          # ⑤页红条旁那只按钮的文案（app/steps/step5_send.py）
CODE_MARK = "AlarmWord=0x"   # 原因码的固定前缀（app/linkctl.py::tell 按契约 §6.4 给十六进制原值）
OFFLINE_MARK = "不外推不跳飞"  # 断线那句人话的关键字（app/sendctl.py 的 _LINK_TEXT[LinkState.OFFLINE]）


def section_h(rig: Rig, results: dict) -> None:
    """卡片步骤④的异常三用例总入口；三条判据记进同一个 ``results``。"""
    print("\n=== H 异常三用例：越界丢帧 → PLC 拒绝 → 运行中断线 ===")
    rig.goto(5)          # ⑤页翻到前台：非当前页的子控件 isVisible() 恒为 False，判「看得见」就成了空话
    _over(rig, results)
    _reject(rig, results)
    _drop_link(rig, results)


def _over(rig: Rig, results: dict) -> None:
    """第三例：越界回读 ⇒ **整帧丢弃并计数**，⛔ 不拿超行程的值去喂 fk（屏幕上会是一台飞掉的机床）。"""
    frame, axis, value = rig.over_frame()
    before = rig.flow.live.stats()[1]
    rig.emit_frames([frame])
    rig.pump(200)
    counts = rig.win.panel.step5._counts
    got, dropped = rig.flow.live.stats()
    print(f"  注入一帧越界回读：轴 {axis} 要求 {value:g} mm（行程上界 {value - OVER_MARGIN:g} ＋ 超出 "
          f"{OVER_MARGIN:g} mm），其余槽位 0")
    print(f"  丢弃帧数 {before} → {dropped}；已采用 {got} 帧；⑤页计数行原文：{counts.text()}")
    print(f"  计数行着色 tone={counts.property('tone')}（丢过帧即整行变红）；状态栏：{rig.win.statusbar._log.text()}")
    check(results, "H1", dropped == before + 1 and axis in counts.text() and counts.property("tone") == "deny",
          f"越界帧被整帧丢弃并计数（{before}→{dropped}）、计数行点名越界轴 {axis} 且变红；"
          f"模型保持在上一帧有效位姿（⛔ 不显示一个不可能存在的位姿）")


def _reject(rig: Rig, results: dict) -> None:
    """第二例：PLC 拒绝 ⇒ 红条＋原因码＋[查看日志]，且在途锁必须解开（失败一次不该永久禁发）。"""
    rig.inject("reject")
    rig.pump(300)                                    # 注入要在循环线程里落地，随后再发才会撞上 NG
    accepted = rig.win.checkctl.send_path()
    ended = rig.wait(lambda: not rig.flow.link.is_busy)
    pane = rig.win.panel.step5
    print(f"  注入 reject（下次装载给 NG＋报警位）→ send_path() 受理={accepted}、握手已收尾={ended}")
    print(f"  红条原文：{pane._err.text()}")
    print(f"  红条可见={pane._err.isVisible()}（tone={pane._err.property('tone')}）；"
          f"[查看日志] 可见={pane._err_btn.isVisible()}、文案={pane._err_btn.text()}")
    print(f"  ⑤页进度图标={''.join(rig.stage_icons())}；在途锁已解={not rig.flow.link.is_busy}")
    check(results, "H2", accepted and ended and pane._err.isVisible() and CODE_MARK in pane._err.text()
          and pane._err_btn.isVisible() and pane._err_btn.text() == LOG_BTN,
          f"PLC 拒绝 ⇒ 红条＋原因码（{CODE_MARK}… 十六进制原值）＋[{LOG_BTN}] 三件齐；"
          f"在途锁已解开（失败一次不会永久禁发）")


def _drop_link(rig: Rig, results: dict) -> None:
    """第一例：断线 ⇒ 灯灰＋人话＋模型停住不跳飞。

    ⚠️ 「停住」的判据**不是**「没有新帧」：插值时钟（≈60 Hz）断链后仍在出帧，只是恒钳在最新一帧
    （``livectl._blend`` 的 ratio 钳 [0,1] 就是「不外推」的落点）⇒ 要判的是矩阵逐数不变、且新采用的
    实测帧数为 0。先量断链前 1 s 的实收帧数作对照，否则「0 帧」可能只是链路本来就没在收（附7-① 那一族）。
    """
    flowing = rig.flow.live.stats()[0]
    rig.pump(1000)
    rate = rig.flow.live.stats()[0] - flowing
    frozen, told = rig.last_pose(), len(rig.poses())
    rig.inject("disconnect")
    pane = rig.win.panel.step5
    # ⚠ 判据钉 OFFLINE 那句而**不是**「灯灰」：顶栏在线灯在 STALE（约 3 个发布周期没收帧）时就已经变灰，
    # 等灯只等于等到「变陈」；卡片要的是**断线**（灯灰＋日志＋模型停住不跳飞）。
    off = rig.wait(lambda: OFFLINE_MARK in "".join(pane.history()), seconds=OFFLINE_S)
    base = rig.flow.live.stats()[0]    # 从「判离线成立」这一刻起算：注入到判离线之间还在正常收帧，
    line = pane._link                  # 那几帧不能算进「断链后新采用」（实测会把 0 算成 1，假红）
    print(f"  断链前 1 s 实收 {rate} 帧（对照用）；注入 disconnect → 顶栏在线灯原文={rig.win.light.text()}")
    print(f"  ⑤页链路行原文：{line.text()}（tone={line.property('tone')}）")
    print(f"  ⑤页日志里的链路人话（变陈→断线）：{[s for s in pane.history() if '链路' in s][-2:]}")
    rig.pump(FROZEN_S * 1000)
    still = rig.flow.live.stats()[0] - base
    after = rig.last_pose()
    print(f"  再等 {FROZEN_S:g} s：新采用 {still} 帧（应为 0）；pose.update 由 {told} 帧增至 "
          f"{len(rig.poses())} 帧（插值时钟仍出帧，但值必须不动）")
    print(f"  断链前矩阵＝{_fmt(frozen)}\n  等待后矩阵＝{_fmt(after)}")
    light = rig.win.light.text()
    check(results, "H3", off and light.endswith("离线") and rate > 0 and still == 0 and after == frozen
          and frozen is not None and any(abs(v) > 1e-9 for v in frozen[12:15]),
          f"断线 ⇒ 灯灰（在线灯「{light}」）＋人话（含「{OFFLINE_MARK}」）＋模型停住：断链前每秒实收 "
          f"{rate} 帧、断链后新采用 {still} 帧、矩阵逐数不变（平移 {frozen[12:15] if frozen else None} "
          f"非退化，⛔ 没塌回零位也没飞走）")


def _fmt(matrix: list | None) -> str:
    return "（没有位姿）" if matrix is None else "[" + " ".join(f"{v:.4f}" for v in matrix) + "]"

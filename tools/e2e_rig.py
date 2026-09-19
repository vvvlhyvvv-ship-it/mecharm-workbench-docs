"""``tools/e2e_smoke.py`` 的**真壳装置**（T10 全链路冒烟的底座；判据数字一律不在本件）。

**为什么拆两件**：``e2e_smoke.py`` 写完实测 330 行 > 04 §4.5-① 的 300 行上限，去重复与抽函数都已做完
（无函数超 50 行），只剩拆文件一条路（§4.5-②③）——与 T09 把 ``comm_selftest.py``（300）＋
``comm_selftest_kit.py`` 拆开的理由与手法完全一致：**装置**（起壳、驱动 UI、读数）与**判据**（阈值、
期望值、PASS 条件）分家，本件只提供前者。

装置三条纪律（evidence 红线／项目记忆 test-fixture-invariants）：
  - **样件一律现场造自造基本体**（40 mm 立方）并落 tempfile：⛔ 禁写死仓内绝对路径、⛔ 不含甲方模型／
    名称／尺寸。
  - **⛔ 不为取证改动任何交付件**：桥只**观察**（包一层记录再转调真实现）；``_ask_operator`` 按
    ``app/checkctl.py`` 自己 docstring 的授权替身（离屏没有真操作员），判定与门禁一行未动。
  - **一律走真壳真链路**：点位经 ``step2.add_face_point``、导入经 ``step1.start_import`` 的 QThread、
    工作模式经真下拉 ⇒ committed，⛔ 不直调 core 抄近道（那测不出接线错）。

读本件的私有属性（``win._last``／``statusbar._freq``／``step5._stages``／``stepbar._completed``）是**有意**
的：判据要钉的是操作员看得见的那一份原文（角标文字、进度图标），而不是另立一个只有取证才走的读数口——
后者一旦与界面脱钩就会假绿（04 §5.5 附7-③ 那一族）。⛔ 只读，不写。
"""

from __future__ import annotations

import contextlib
import io
import pathlib
import re
import tempfile
import time

from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCC.Core.gp import gp_Pnt
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from app.sendseg import slot_axes
from app.shell import MainWindow
from app.theme import apply_theme
from comm.opcua_client import axis_slots_of
from comm.opcua_client.subscribe import Frame
from core.config import load_machine
from core.geometry.face_point import FacePoint
from tests.cad_samples import write_step

CONFIG = pathlib.Path("config/machine.yaml")
MODE_INDEX = 3               # 五臂列表第 3 行（0-based）＝「氧化皮破碎」（7 轴 ≤ pack_profile 的 8 槽位；
                             # T13 前顶栏下拉带「未选定」项故为 4——列表迁右栏后无该项，判据语义不变）
THREE_POINTS = ((0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (200.0, 0.0, 0.0))
BOX = (40.0, 40.0, 40.0)     # 自造障碍基本体（⛔ 非甲方工件尺寸）
BOX_AT = (208.0, -20.0, -20.0)   # X 下角 208 ⇒ 与 200 mm 终点留 8 mm < clearance_warn 20 ⇒ 🟡 预警
READY_S = 40.0               # 连接／导入／握手的等待上限（本机模拟器首起要建地址空间）
HZ_RE = re.compile(r"数据\s+([\d.]+)Hz")    # 从角标**原文**取实测频率
FPS_RE = re.compile(r"画面\s+([\d.]+)fps")  # 同上，取视口报来的画面帧率（占位时是 "--"，故取不到即 None）
STAGES = (1, 2, 3, 4, 5)     # 握手五段（契约 §9.1 九步的壳侧投影，对应表见 app/linkctl.py::STAGES）
OVER_MARGIN = 50.0           # 越界注入的超出量（mm）：够大不会被容差吃掉，又仍是机床上可能出现的数量级
OFFLINE_S = 12.0             # 断链后判离线的等待上限（T09 完成标准第 4 条要求 5 s 内，这里给两倍余量）


class Rig:
    """离屏真壳：构造 MainWindow、记录桥载荷、驱动 UI、读出操作员可见的那一份状态。"""

    def __init__(self) -> None:
        self.qapp = QApplication.instance() or QApplication([])
        apply_theme(self.qapp)
        self.tmp = tempfile.TemporaryDirectory(prefix="t10_e2e_")
        self.win = MainWindow()
        # ⚠ 必须真显示：H 节要判「红条与[查看日志] 操作员看得见」，而 `isVisible()` 会因祖先隐藏恒为
        # False（离屏取证实测踩过）——不 show 就等于把那条判据写成一句空话。
        self.win.show()
        # T12：启动序列改经载入/登录页——离屏没有 run.py 的收集器（config 等里程碑不在 Rig 跑），
        # 故直接把 splash 置就绪态，再走与「进入系统」按钮/回车同一个槽（真页面切换，不绕过宿主）。
        self.win.splash.set_ready_state(self.win.boot.is_all_done())
        self.win.enter_system()
        self.sent: list[tuple[str, object]] = []
        real = self.win.bridge.call_view
        self.win.bridge.call_view = lambda t, p=None: (self.sent.append((t, p)), real(t, p))[1]
        self.win.workmode.select_row(MODE_INDEX)      # 真列表行 ⇒ committed ⇒ 解锁②③（T13 起列表迁右栏）
        self.flow = self.win.checkctl.send_flow
        self.stages: list[tuple[int, str]] = []           # `Signal(int, str)` ⇒ 槽必须收两个实参
        self.flow.link.stage.connect(lambda n, text: self.stages.append((n, text)))
        self.dialogs: list[str] = []
        self.win.checkctl._ask_operator = self._accept
        self.cfg = load_machine(str(CONFIG))

    def _accept(self, _result, text: str) -> bool:
        """确认弹窗替身：收下正文（判据要核里面的请求值小字）并代操作员点[确认下发]。"""
        self.dialogs.append(text)
        return True

    # --- 驱动 --------------------------------------------------------------- #
    def tab(self, key: str) -> None:
        """切左栏页签：真点页签头按钮（tree/prog/sim；T13 导航判据走真控件路径）。"""
        self.win.tabshell.switch_to(key)

    def goto(self, n: int) -> None:
        """切到第 n 步：先把承载该步的页签翻到前台（T13 范式），再发 `stepbar.step_clicked`
        走 shell 的真导航槽（薄壳 L-7：信号照旧，槽内 set_step/pick 态语义不变）。

        ⚠️ QStackedWidget 里**非当前页的子控件同样不可见** ⇒ 要判⑤页的红条／[查看日志] `isVisible()`，
        得先把⑤页所在页签真翻到前台，否则读到的 False 是「没翻到这一页」而不是「代码没把它显示出来」。
        """
        self.tab("prog" if n <= 3 else "sim")
        self.win.stepbar.step_clicked.emit(n)

    def pump(self, ms: float) -> None:
        """跑一段真事件循环（导入走 QThread、握手走 asyncio 线程，processEvents 不够）。"""
        loop = QEventLoop()
        QTimer.singleShot(int(ms), loop.quit)
        loop.exec()

    def wait(self, predicate, seconds: float = READY_S) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.pump(100)
            if predicate():
                return True
        return bool(predicate())

    def import_box(self) -> bool:
        """造自造立方障碍并走**真导入链路**（step1 信号 → shell → checkctl）。"""
        path = pathlib.Path(self.tmp.name) / "obstacle.step"
        with contextlib.redirect_stdout(io.StringIO()):      # 吞掉 OCC 写器的统计噪声
            write_step(BRepPrimAPI_MakeBox(gp_Pnt(*BOX_AT), *BOX).Shape(), path)
        self.win._last = None
        self.win.panel.step1.start_import(str(path))
        return self.wait(lambda: self.win._last is not None)

    def pick(self) -> list:
        """注 3 个点位（走真 step2 接口，⛔ 不塞私有序列），返回点位表里的 Waypoint 列表。"""
        self.win.panel.step2.clear()
        for index, pos in enumerate(THREE_POINTS, start=1):
            self.win.panel.step2.add_face_point(
                FacePoint(pos_mm=pos, normal=(0.0, 0.0, 1.0), source_face=index))
        return self.win.panel.step2.waypoints()

    # --- 异常注入（卡片步骤④三用例）------------------------------------------- #
    def over_frame(self) -> tuple[Frame, str, float]:
        """造一帧**越界回读**：其余槽位一律 0（合法零位），只把首轴顶到行程上界之外。

        返回 (帧, 越界轴号, 该轴要求的工程值)。⚠️ 注入点＝`linkctl.frames` 这条 **comm→壳的唯一边界**：
        `comm/simulator.py` 是 T09 已验收件、对本单禁改，而它的故障种类只有 reject／timeout／disconnect，
        没有「回读值越界」⇒ 无从在 PLC 侧造出这一例。边界以下走的仍是真链路
        （`livectl._accept` → T04 的 `check_limits` → ⑤页计数行），⛔ 不直调 livectl 的私有方法。
        """
        mode = self.win.workmode.current_mode() or ""
        axes = slot_axes(self.cfg, mode)
        axis = axes[0]
        value = self.cfg.axes[axis].travel[1] + OVER_MARGIN
        slots = axis_slots_of(self.cfg.opcua.pack_profile)
        pos = tuple([value] + [0.0] * (slots - 1))
        frame = Frame(t=time.monotonic(), heartbeat=0, pos=pos, vel=(0.0,) * slots,
                      status=0, ack=0, alarm_word=0, seq_id=0, cur_seg=0)
        return frame, axis, value

    def emit_frames(self, frames: list) -> None:
        """把一批回读帧从 comm→壳的边界投进去（等价于循环线程里 `_rx_frames` 的那一次 emit）。"""
        self.flow.link.frames.emit(frames)

    def inject(self, kind: str) -> None:
        """故障注入（reject／timeout／disconnect）：转调 `linkctl.inject_fault`，⛔ 不自己碰模拟器。"""
        self.flow.link.inject_fault(kind)

    def close(self) -> None:
        self.flow.shutdown()          # 先停跟随再停链路、停 asyncio 线程（否则 QThread 被销毁时还在跑）
        self.win.close()
        self.tmp.cleanup()

    # --- 读数（一律读界面上真显示的那一份）------------------------------------- #
    def assembly(self):
        return (self.win._last or {}).get("asm")

    def poses(self) -> list:
        return [payload for kind, payload in self.sent if kind == "pose.update"]

    def last_pose(self) -> list | None:
        """最后一帧上屏的 16 数矩阵。断链用例用它判「模型停住不跳飞」：断链后插值时钟**仍在出帧**
        （`livectl._tick` 恒钳在最新一帧），故判据不是「没有新帧」而是「矩阵逐数不变」。"""
        for payload in reversed(self.sent):
            kind, data = payload
            if kind == "pose.update" and data.get("poses"):
                return next(iter(data["poses"].values()))
        return None

    def hz(self) -> float | None:
        got = HZ_RE.search(self.win.statusbar._freq.text())
        return float(got.group(1)) if got else None

    def fps(self) -> float | None:
        got = FPS_RE.search(self.win.statusbar._freq.text())
        return float(got.group(1)) if got else None

    def nominal_hz(self) -> float:
        return 1000.0 / self.cfg.opcua.publish_interval_ms

    def stage_icons(self) -> list[str]:
        return [label.text()[:1] for label in self.win.panel.step5._stages]

    def said_stages(self) -> list[int]:
        """⑤页日志里**出现过人话**的阶段号：阶段 1 由下发编排自标、不经 `link.stage` 信号 ⇒ 只有读⑤页
        自己的历史才证得出它真被标过（⛔ 只看信号会漏掉第一段）。"""
        told = "".join(self.win.panel.step5.history())
        return [n for n in STAGES if f"[阶段{n}]" in told]

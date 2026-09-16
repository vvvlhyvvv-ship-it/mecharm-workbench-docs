"""evidence/T08/_rig.py — T08 取证共用装置：真壳＋桥载荷记录＋自造障碍几何。

跑法见各 `_drive_*.py`。纪律（项目记忆 test-fixture-invariants／evidence 红线）：
  ⛔ 样件一律现场造自造基本体（40 mm 立方）并落 tempfile，**禁写死仓内绝对路径**、⛔ 不含甲方
  模型／名称／尺寸；⛔ 不为取证改动任何交付件（桥只**观察**：包一层记录再转调真实现）。
"""

from __future__ import annotations

import contextlib
import io
import logging
import os
import pathlib
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import app  # noqa: F401,E402  ICU 预载须在任何 PySide6.QtWidgets 之前
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402  fmt: skip
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402
from OCC.Core.BRep import BRep_Builder  # noqa: E402
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox  # noqa: E402
from OCC.Core.TopoDS import TopoDS_Compound  # noqa: E402
from OCC.Core.gp import gp_Pnt  # noqa: E402

from app.shell import MainWindow  # noqa: E402
from app.theme import apply_theme  # noqa: E402
from core.geometry.face_point import FacePoint  # noqa: E402
from tests.cad_samples import write_step  # noqa: E402

MODE_INDEX = 1                                   # 顶栏下拉第 1 项＝「打磨臂」（真下拉 ⇒ committed）
TWO_POINTS = ((0.0, 0.0, 0.0), (100.0, 0.0, 0.0))       # 1 段：X1 行程内，采样 3 姿态
LONG_POINTS = tuple((50.0 * i, 0.0, 0.0) for i in range(21))   # 20 段／总长 1000 mm（卡片步骤 6）
OB_SIZE = (40.0, 40.0, 40.0)                     # 自造障碍基本体尺寸（⛔ 非甲方工件尺寸）
OB_YZ = (-20.0, -20.0)                           # 障碍在 Y/Z 上的下角（让它罩住臂身原点连线）
# 远处第二个自造立方（X 下角）：只为把 loader 的整体取景撑宽 ⇒ 点击定位时「相机飞到」才看得见。
# 只有一个障碍时，整体取景与定位取景是同一个盒子 ⇒ 相机一动不动，那条判据无法证伪（实测踩过）。
FAR_X0 = 4000.0                                  # 离路径 0~100 mm 极远 ⇒ ⛔ 不参与任何命中
GAP_CASES = (("相交", -20.0, "interfere"), ("间隙 5 mm", 108.0, "warn"),
             ("间隙 500 mm", 603.0, "pass"))     # (工况名, 障碍 X 下角 mm, 期望三态字面)
ICON = {"pass": "🟢", "warn": "🟡", "interfere": "🔴"}
# 上屏文案审计的禁用词：04 §5.5-③ 复查词 ＋ 02 §4「全中文」不容的内部编号／英文术语。
# ⚠️ 不放"通过"——「校核未通过，无法下发」是合法文案；G19 的措辞判据另走 `g19_wording`。
BANNED = ("B-Rep", "AP242", "wasm", "tessellation", "AABB", "BRepExtrema", "hash", "verdict",
          "clearance", "envelope", "machine.yaml", "关节角", "位姿矩阵", "插补", "插值",
          "电Q", "G19", "T08", "collision", "path_hash")
G19_LIMIT = "已建模的"          # 结论必须带的覆盖面限定（G19 第 1 条）
G19_FORBIDDEN = ("通过", "整机", "全部安全", "无碰撞风险")   # 通过态禁语（G19 第 2 条）


def g19_wording(card: str, verdict: str) -> list[str]:
    """G19 措辞判据：结论带覆盖面限定；通过态**不得**说"通过／整机"（未建模臂是判定空白）。"""
    bad = [w for w in G19_FORBIDDEN if w in card] if verdict == "pass" else []
    if G19_LIMIT not in card:
        bad.append(f"缺覆盖面限定「{G19_LIMIT}…」")
    return bad


def pump(ms: int) -> None:
    """跑一段真事件循环（导入走 QThread，processEvents 不够）。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def quiet_step(shape, path: pathlib.Path) -> pathlib.Path:
    """写 STEP 并吞掉 OCC 写器的统计噪声（日志要能读）。"""
    with contextlib.redirect_stdout(io.StringIO()):
        return write_step(shape, path)


def steps_enabled(win) -> list[bool]:
    return [b.isEnabled() for b in win.stepbar.findChildren(QPushButton)]


class Recorder(logging.Handler):
    """收 app.checkctl／core.collision 的日志记录：双阻断两条拦截与耗时行都靠它留痕。"""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.rows: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.rows.append(f"{record.levelname} {record.name}: {record.getMessage()}")

    def take(self, needle: str) -> list[str]:
        return [row for row in self.rows if needle in row]


class Rig:
    """真壳装置：构造 MainWindow（离屏）、观察桥载荷、按工况换障碍几何与路径。"""

    def __init__(self) -> None:
        self.qapp = QApplication.instance() or QApplication([])
        apply_theme(self.qapp)
        self.rec = Recorder()
        for name in ("app.checkctl", "core.collision"):
            logger = logging.getLogger(name)
            logger.setLevel(logging.INFO)
            logger.addHandler(self.rec)
        self.tmp = tempfile.TemporaryDirectory(prefix="t08_")
        self.root = pathlib.Path(self.tmp.name)
        self.win = MainWindow()
        self.sent: list[tuple[str, object]] = []
        real = self.win.bridge.call_view
        self.win.bridge.call_view = lambda t, p=None: (self.sent.append((t, p)), real(t, p))[1]
        self.win.workmode.setCurrentIndex(MODE_INDEX)     # 真下拉 ⇒ committed ⇒ 解锁②③
        self.stamp = 0

    # --- 工况装配 ----------------------------------------------------------- #
    def obstacle(self, x0: float, far: float | None = None) -> bool:
        """造一个自造立方障碍（X 下角＝x0）并走**真导入链路**（step1 信号 → shell → checkctl）。
        给 `far` 即在**同一个 STEP** 里再放一个远处立方（合成 compound ⇒ 导入后是两个零件叶子），
        只用于撑宽视口整体取景，⛔ 不参与命中（见 FAR_X0）。"""
        self.stamp += 1
        path = self.root / f"obstacle_{self.stamp}.step"
        shape = BRepPrimAPI_MakeBox(gp_Pnt(x0, *OB_YZ), *OB_SIZE).Shape()
        if far is not None:
            compound, builder = TopoDS_Compound(), BRep_Builder()
            builder.MakeCompound(compound)
            builder.Add(compound, shape)
            builder.Add(compound, BRepPrimAPI_MakeBox(gp_Pnt(far, *OB_YZ), *OB_SIZE).Shape())
            shape = compound
        quiet_step(shape, path)
        self.win._last = None
        self.win.panel.step1.start_import(str(path))
        for _ in range(40):
            pump(250)
            if self.win._last is not None:
                return True
        return False

    def path(self, points=TWO_POINTS) -> int:
        """注点位并生成路径，返回段数（点位走真 step2 接口，⛔ 不塞私有序列）。"""
        self.win.panel.step2.clear()
        for index, pos in enumerate(points, start=1):
            self.win.panel.step2.add_face_point(
                FacePoint(pos_mm=pos, normal=(0.0, 0.0, 1.0), source_face=index))
        self.win.pathctl.generate()
        return len(self.win.pathctl.segments())

    def run(self, x0: float, points=TWO_POINTS, far: float | None = None):
        """一套完整工况：换障碍 → 生成路径 → [开始校核]，返回 core 的判定结果。"""
        imported = self.obstacle(x0, far)
        count = self.path(points)
        self.win.checkctl.run_check()
        return imported, count, self.win.checkctl._result

    # --- 读数 --------------------------------------------------------------- #
    def last(self, type_: str):
        got = [p for t, p in self.sent if t == type_]
        return got[-1] if got else None

    def ui(self) -> dict:
        """右栏步骤④页与⑤门禁的可见状态（三通道里的壳侧两通道）。"""
        step4 = self.win.panel.step4
        table = step4._table
        return {
            "卡片": step4._card.text(),
            "卡片文字色": step4._card.palette().color(step4._card.foregroundRole()).name(),
            "覆盖面标注": step4._coverage.text(),
            "覆盖面色": step4._coverage.palette().color(
                step4._coverage.foregroundRole()).name(),
            "列表行": [[table.item(r, c).text() for c in range(table.columnCount())]
                       for r in range(table.rowCount())],
            "列表底色": [table.item(r, 0).background().color().name()
                         for r in range(table.rowCount())],
            "整句人话": step4._verdict_line.text(),
            "就绪提示": step4._hint.text(),
            "提示行": step4._note.text(),
            "实测数字行": step4._stat.text(),
            "校核按钮可用": step4._btn.isEnabled(),
            "⑤按钮可用": self.win.panel.send_btn.isEnabled(),
            "⑤旁注": self.win.panel.send_note.text(),
            "步骤条可用": steps_enabled(self.win),
            "状态栏": self.win.statusbar._log.text(),
        }

    def show(self, title: str) -> None:
        print(f"\n=== {title} ===")

    def dump(self, label: str, state: dict) -> None:
        print(f"  [{label}]")
        for key, value in state.items():
            print(f"    {key}: {value}")

    def close(self) -> None:
        self.win.close()
        self.tmp.cleanup()

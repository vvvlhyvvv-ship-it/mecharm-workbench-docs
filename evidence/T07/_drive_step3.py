"""evidence/T07/_drive_step3.py — 离屏行为级取证：步骤③生成／阻断门禁／播放插值／fps 角标。

跑法（worktree 根）：
  PYTHONPATH=. QT_QPA_PLATFORM=offscreen python evidence/T07/_drive_step3.py
⚠️ 离屏无中文字体，PNG 里中文呈豆腐块 ⇒ **以打印的数值为证**，截图只证布局不越界。
点位／臂名一律自造（禁甲方模型、名称、尺寸）。

结构：`Rig` 持有真控件＋替身桥，0~7 各一节方法（每节 ≤50 行＝卡片的粒度硬约束）。
本脚本不开 WebEngine 内核（离屏取证只需壳侧行为＋桥载荷），故视口侧另见 `_drive_shell_path.py`。
"""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import app  # noqa: F401,E402  ICU 预载须在任何 PySide6.QtWidgets 之前
from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from app.panel import Panel  # noqa: E402
from app.pathctl import PathController, _lerp  # noqa: E402
from app.statusbar import StatusBar  # noqa: E402
from app.stepbar import StepBar  # noqa: E402
from core.geometry.face_point import FacePoint  # noqa: E402
from core.path import summarize, tool_pose_in_model  # noqa: E402
from core.kinematics.transform import to_column_major  # noqa: E402

OUT = os.path.dirname(os.path.abspath(__file__))
FIVE = ((0.0, 0.0, 0.0), (300.0, 0.0, 0.0), (300.0, 400.0, 0.0),
        (300.0, 400.0, 250.0), (600.0, 400.0, 250.0))
BROKEN = (5000.0, 0.0, 0.0)          # 越界注入（占位行程合计只到 3000 mm）


class StubBridge(QObject):
    """替身桥：只记录壳→视口载荷（真 Bridge 需要 QWebEnginePage，离屏取证不必开内核）。"""

    received = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.sent = []

    def call_view(self, type_, payload=None):
        self.sent.append((type_, payload))
        return True

    def last(self, type_):
        got = [p for t, p in self.sent if t == type_]
        return got[-1] if got else None


def steps_enabled(stepbar):
    return [b.isEnabled() for b in stepbar.findChildren(QPushButton)]


def feed_points(panel, coords):
    panel.step2.clear()
    for i, pos in enumerate(coords, start=1):
        panel.step2.add_face_point(FacePoint(pos_mm=pos, normal=(0.0, 0.0, 1.0), source_face=i))


def table_rows(panel):
    table = panel.step3._table
    return [[table.item(r, c).text() for c in range(table.columnCount())]
            for r in range(table.rowCount())]


class Rig:
    """离屏取证装置：真控件＋替身桥＋复刻 shell 的④⑤门禁（⛔ 不为取证改交付件）。"""

    def __init__(self):
        self.qapp = QApplication([])
        self.stepbar, self.statusbar = StepBar(), StatusBar()
        self.panel, self.bridge = Panel(), StubBridge()
        self.ctl = PathController(self.panel, self.bridge, self.stepbar, self.statusbar)
        self.panel.step2.set_mode("多功能臂A")
        self.ctl.changed.connect(self.refresh)

    def refresh(self):
        """复刻 shell._refresh_unlock：②③已解锁（本脚本视作已选模式＋已导实体），④⑤另需路径 ok。"""
        for n in (2, 3):
            self.stepbar.set_step_enabled(n, True)
        for n in (4, 5):
            self.stepbar.set_step_enabled(n, self.ctl.ready())

    def s0_point_shortage(self):
        print("=== 0. 点位不足：只给 1 点，[生成路径] 须禁用且给人话提示 ===")
        feed_points(self.panel, FIVE[:1])
        self.ctl.generate()
        print("  日志:", self.statusbar._log.text())
        print("  生成按钮可用:", self.panel.step3._btn.isEnabled(), "(期望 False)")
        print("  桥载荷条数:", len(self.bridge.sent), "(期望 0：不静默造段)")

    def s1_generate(self):
        print("\n=== 1. 五点生成（点位型）：表格与视口折线同源 ===")
        feed_points(self.panel, FIVE)
        self.ctl.generate()
        segs = self.ctl._segments
        print("  段数:", len(segs), "(期望 4)")
        print("  右栏表行数:", self.panel.step3._table.rowCount())
        for row in table_rows(self.panel):
            print("   ", row)
        print("  汇总行:", self.panel.step3._summary_line.text())
        print("  红字行:", repr(self.panel.step3._block_line.text()), "(期望空)")
        print("  日志:", self.statusbar._log.text())
        print("  步骤条可用:", steps_enabled(self.stepbar), "(期望 ①②③④⑤ 全 True)")
        print("  ctl.ready():", self.ctl.ready())
        payload = self.bridge.last("path.show")
        text = json.dumps(payload, ensure_ascii=True)
        print("  path.show 段数:", len(payload["segments"]))
        print("  path.show 首段:", payload["segments"][0])
        print("  path.show 全 ASCII:", text.isascii(), "| 含中文?",
              any(ord(ch) > 127 for ch in text))
        print("  path.show 键:", sorted(payload["segments"][0]))
        print("  表格长度列 == path.show length:",
              [self.panel.step3._table.item(r, 3).text() for r in range(4)]
              == [f"{s['length']:.1f}" for s in payload["segments"]])
        print("  表格端点 == path.show start/end:",
              all([list(s.start_mm), list(s.end_mm)] == [p["start"], p["end"]]
                  for s, p in zip(segs, payload["segments"])))

    def s2_blending(self):
        print("\n=== 2. blending 默认关（完成标准③）＋段型可切 ===")
        segs = self.ctl._segments
        print("  复选框勾选:", self.panel.step3._blend.isChecked(), "(期望 False)")
        print("  段默认 blending:", [s.blending for s in segs])
        print("  当前段型:", self.panel.step3.kind(), "| 段类型:", sorted({s.type for s in segs}))
        self.panel.step3._kind.setCurrentIndex(1)          # 切轮廓型 ⇒ 已生成路径须作废
        print("  切段型后 summary:", self.panel.step3.summary(), "(期望 None：结果作废)")
        print("  切段型后 path.show:", self.bridge.last("path.show"))
        print("  日志:", self.statusbar._log.text())
        self.ctl.generate()
        print("  轮廓型段类型:", sorted({s.type for s in self.ctl._segments}),
              "| 速度:", sorted({s.speed_mm_s for s in self.ctl._segments}))
        print("  轮廓型汇总:", self.panel.step3._summary_line.text())
        self.panel.step3._kind.setCurrentIndex(0)
        self.ctl.generate()

    def s3_blocked(self):
        print("\n=== 3. 越界点注入 ⇒ 红段＋无法进入④（完成标准②）===")
        broken = list(FIVE)
        broken[2] = BROKEN
        feed_points(self.panel, broken)
        self.ctl.generate()
        summary = self.panel.step3.summary()
        print("  汇总:", self.panel.step3._summary_line.text())
        print("  红字行:", self.panel.step3._block_line.text())
        print("  阻断段号:", [s.id for s in self.ctl._segments if s.blocked])
        print("  ok:", summary.ok, "| ctl.ready():", self.ctl.ready())
        print("  步骤条可用:", steps_enabled(self.stepbar), "(期望 ④⑤ False)")
        print("  [▶播放] 可用:", self.panel.step3._play.isEnabled(), "(期望 False)")
        print("  path.show blocked 标志:",
              [s["blocked"] for s in self.bridge.last("path.show")["segments"]])
        print("  表首列（⛔ 前缀）:", [self.panel.step3._table.item(r, 0).text() for r in range(4)])
        print("  首段单元格 tooltip:", self.panel.step3._table.item(1, 0).toolTip()[:60], "...")
        self.panel.set_step(3)
        self.panel.resize(360, 640)
        self.panel.show()
        self.qapp.processEvents()
        pix = self.panel.grab()
        blocked_png = os.path.join(OUT, "step3_blocked_360x640.png")
        pix.save(blocked_png)
        print("  红段截图:", blocked_png, f"({pix.width()}x{pix.height()})")

    def s4_locate(self):
        """播放定位：按段线性插值、参数钳在 [0,1]（⛔ 不外推 W-5.7）。"""
        print("\n=== 4. 播放：按段线性插值，参数钳在 [0,1]（⛔ 不外推 W-5.7）===")
        feed_points(self.panel, FIVE)
        self.ctl.generate()
        total = summarize(self.ctl._segments).total_duration_s
        print("  总时长:", total)
        for frac in (0.0, 0.1, 0.45, 0.5, 0.9, 1.0):
            seg, ratio = self.ctl._locate(total * frac)
            print(f"   elapsed={total * frac:6.3f}s -> seg={seg.id if seg else None}"
                  f" ratio={ratio:.4f}")
        print("  超出总时长 5s:", self.ctl._locate(total + 5.0), "(期望 (None, 0.0)：走完即停)")
        for elapsed in (-1.0, total * 0.5, total + 1.0):
            seg, ratio = self.ctl._locate(max(elapsed, 0.0))
            assert 0.0 <= ratio <= 1.0, ratio
        print("  所有采样 ratio 均在 [0,1]:", True)
        self.ctl.play()
        print("  播放中：[▶] ", self.panel.step3._play.isEnabled(), "| [⏸]",
              self.panel.step3._pause.isEnabled(), "| [生成路径]",
              self.panel.step3._btn.isEnabled(), "| 段型下拉",
              self.panel.step3._kind.isEnabled(), "| 步骤②页可编辑", self.panel.step2.isEnabled())
        self._s4_pose()

    def _s4_pose(self):
        """4 节后半：pose.update 的载荷口径与列主序平移分量。"""
        seg, ratio = self.ctl._locate(0.0)
        self.ctl._emit_pose(seg, ratio)
        first = self.bridge.last("pose.update")
        link = list(first["poses"])[0]
        got = first["poses"][link]
        print("  pose.update 键:", sorted(first), "| link:", list(first["poses"]))
        print("  矩阵长度:", len(got))
        print("  矩阵全为有限数:", all(isinstance(v, float) for v in got))
        want = to_column_major(tool_pose_in_model(seg.joints_start, self.ctl._chain,
                                                  self.ctl._frame))
        print("  段首帧 == 列主序(tool_pose_in_model(joints_start)):", list(got) == list(want))
        print("  列主序平移分量 (12/13/14):", [round(got[i], 6) for i in (12, 13, 14)])
        self.ctl._emit_pose(seg, 1.0)
        end = self.bridge.last("pose.update")["poses"][link]
        print("  段末帧平移:", [round(end[i], 6) for i in (12, 13, 14)])
        print("  段号随帧下发:", self.bridge.last("pose.update")["seg"], "| ts 存在:",
              isinstance(self.bridge.last("pose.update")["ts"], float))
        print("  pose.update 全 ASCII:", json.dumps(self.bridge.last("pose.update")).isascii())
        print("  当前段高亮（set_current）:", self.panel.step3._current)
        self.ctl._on_step_clicked(2)
        print("  点步骤②后播放是否已暂停:", not self.ctl._timer.isActive(),
              "| 步骤②页恢复可编辑:", self.panel.step2.isEnabled())

    def s5_lerp(self):
        print("\n=== 5. 插值函数本身：只在一端出现的轴按常值（⛔ 不当 0）===")
        print("  ", _lerp({"A": 10.0}, {"A": 20.0, "B": 5.0}, 0.5))

    def s6_fps(self):
        print("\n=== 6. fps 角标（完成标准①：实测帧率上屏）===")
        self.ctl._on_bridge_msg("perf.fps", {"fps": 58.7})
        print("  角标:", self.statusbar._freq.text())
        self.ctl._on_bridge_msg("perf.fps", {"fps": "坏值"})
        print("  坏值后角标不变:", self.statusbar._freq.text())
        self.ctl._on_bridge_msg("cam.view", {"x": 1})
        print("  非 perf.fps 不动角标:", self.statusbar._freq.text())

    def s7_layout(self):
        print("\n=== 7. 布局取证：右栏 360px 宽不越界 ===")
        self.panel.set_step(3)          # 否则抓到的是步骤①页
        for width in (280, 360):
            self.panel.resize(width, 640)
            self.panel.show()
            for _ in range(3):
                self.qapp.processEvents()
            table = self.panel.step3._table
            header = table.horizontalHeader()
            cols = table.columnCount()
            right = header.sectionViewportPosition(cols - 1) + header.sectionSize(cols - 1)
            print(f"  width={width}: pane={self.panel.width()} table={table.width()}"
                  f" viewport={table.viewport().width()}"
                  f" 末列右缘={right} 水平滚动上限={table.horizontalScrollBar().maximum()}"
                  f" 越界={right > table.viewport().width() + 1}")
            pix = self.panel.grab()
            path = os.path.join(OUT, f"step3_panel_{width}x640.png")
            pix.save(path)
            print(f"    grabbed {pix.width()}x{pix.height()} -> {path}")


def main():
    rig = Rig()
    for section in (rig.s0_point_shortage, rig.s1_generate, rig.s2_blending, rig.s3_blocked,
                    rig.s4_locate, rig.s5_lerp, rig.s6_fps, rig.s7_layout):
        section()


if __name__ == "__main__":
    main()

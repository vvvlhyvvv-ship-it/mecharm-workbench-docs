"""app.steps.step1_import —— 步骤①「导入模型」的导入管线与结果信号（T05；T14 浮层化）。

两件东西，单一职责各管一段：
  ImportWorker  QThread 后台跑 core.geometry 的「解析→三角化→优化」三阶段，主线程不阻塞
                （02 §2「大文件导入期间界面可交互」）。取消是**协作式**的：只在阶段边界
                检查标志——OCC 单次转换不可中途抢占，故取消在下一阶段生效。
  Step1Pane     导入结果的信号源。T14 起界面形态退场为顶栏浮层（app/pop_import.py **复用
                本页管线与缓存**：拖拽／[选择文件]都转 ``start_import``，进度经新增的
                ``stage_changed`` 转发信号、结果读数取 ``imported`` 信号里的 asm.stats 真值）；
                本页仍被 ProgTab setParent 收容（保 e2e「step1 归编程页签」判据）、主窗拖放
                照旧走 ``start_import``。只发高层信号 imported/failed，**不碰桥/装配树/步骤条**。

弦高容差 deflection 走 machine.yaml limits（禁散写字面量，T05 步骤3）；读不到即导入失败、
转 failed 信号，不在代码里塞默认值。坐标单位 mm（与 core.geometry 一致）。
"""

from __future__ import annotations

import pathlib

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from core.config import REPO_ROOT, load_machine
from core.geometry import encode_mesh_parts, import_model, tessellate

# 三阶段（02 §2 步骤①原文）：进度条按此推进；「优化」当前为显示网格编码/打包，
# 真正的简化/LOD 轻量化待 trimesh 依赖核准后补（见 T05 汇报遗留问题）。
_STAGES = ("解析", "三角化", "优化")
_FILE_FILTER = "模型文件 (*.step *.stp *.iges *.igs *.stl);;所有文件 (*)"


class ImportWorker(QThread):
    """后台导入线程。信号：stage(str) 阶段名、done(object) 成功、failed(str) 人话原因。"""

    stage = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str, parent: QThread | None = None) -> None:
        super().__init__(parent)
        self._path = path
        self._cancel = False

    def cancel(self) -> None:
        """请求取消：置标志，worker 在下一个阶段边界退出（不强杀 OCC 转换）。"""
        self._cancel = True

    def run(self) -> None:
        try:
            deflection = self._read_deflection()
            self.stage.emit(_STAGES[0])
            asm = import_model(self._path)
            if self._abort():
                return
            self.stage.emit(_STAGES[1])
            parts = tessellate(asm, deflection)
            if self._abort():
                return
            self.stage.emit(_STAGES[2])
            payload = encode_mesh_parts(parts)
            self.done.emit({"asm": asm, "parts": parts, "payload": payload})
        except Exception as exc:  # noqa: BLE001 - 后台任何异常转 failed，绝不崩主线程
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    def _abort(self) -> bool:
        if self._cancel:
            self.failed.emit("已取消导入")
            return True
        return False

    @staticmethod
    def _read_deflection() -> float:
        cfg = load_machine(str(REPO_ROOT / "config" / "machine.yaml"))
        return cfg.limits.tessellate_deflection_mm


class Step1Pane(QWidget):
    """导入结果信号源（T14 浮层化后不进布局）。信号：imported/failed/stage_changed。"""

    imported = Signal(object)
    failed = Signal(str)
    stage_changed = Signal(str)      # 三阶段进度转发（浮层显示用；本页自身不再可见）

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PlaceholderCard")
        self._worker: ImportWorker | None = None
        self._build()

    def _build(self) -> None:
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 16, 16, 16)
        box.setSpacing(12)
        self._hint = QLabel("把 STEP / IGES / STL 文件拖到视口，或点下方按钮选择")
        self._hint.setObjectName("PlaceholderBody")
        self._hint.setWordWrap(True)
        self._result = QLabel("")
        self._stats = QLabel("")
        self._stats.setObjectName("PlaceholderBody")
        self._progress = QProgressBar()
        self._progress.setRange(0, len(_STAGES))
        self._progress.setVisible(False)
        self._btn = QPushButton("选择模型文件")
        self._btn.setProperty("role", "primary")
        self._btn.clicked.connect(self.pick_file)
        self._cancel = QPushButton("取消")
        self._cancel.setVisible(False)
        self._cancel.clicked.connect(self._on_cancel)
        row = QHBoxLayout()
        row.addWidget(self._cancel)
        row.addStretch(1)
        box.addWidget(self._hint)
        box.addStretch(1)
        box.addWidget(self._result)
        box.addWidget(self._stats)
        box.addWidget(self._progress)
        box.addWidget(self._btn)
        box.addLayout(row)

    def pick_file(self) -> None:
        """[选择模型文件] 兜底入口（02 §2 步骤①）：弹文件对话框，选中即开导入。"""
        path, _ = QFileDialog.getOpenFileName(self, "选择模型文件", "", _FILE_FILTER)
        if path:
            self.start_import(path)

    def start_import(self, path: str) -> None:
        """启动后台导入（拖放与按钮共用此入口）；已有任务在跑则忽略。"""
        if self._worker is not None and self._worker.isRunning():
            return
        self._set_busy(True, pathlib.Path(path).name)
        self._worker = ImportWorker(path, self)
        self._worker.stage.connect(self._on_stage)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_stage(self, name: str) -> None:
        self._progress.setValue(_STAGES.index(name) + 1 if name in _STAGES else 0)
        self._set_result(f"正在{name}…", "busy")
        self.stage_changed.emit(name)      # 浮层的三阶段进度（T14；本页自身不再可见）

    def _on_done(self, res: object) -> None:
        self._set_busy(False)
        self._progress.setValue(len(_STAGES))
        asm = res["asm"]
        if asm.is_brep:
            self._set_result("✓ 实体模型（可拾取、可算碰撞）", "brep")
        else:
            self._set_result("✗ 面片模型（不能用于编程）", "mesh")
        s = asm.stats
        self._stats.setText(
            f"零件数 {s.get('parts', 0)} · 面数 {s.get('tris', 0)} · "
            f"耗时 {s.get('load_ms', 0.0):.0f} ms")
        self.imported.emit(res)

    def _on_failed(self, msg: str) -> None:
        self._set_busy(False)
        self._progress.setValue(0)
        self._set_result("", "busy")
        self._stats.setText("")
        self.failed.emit(msg)

    def _on_cancel(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._set_result("正在取消…", "busy")

    def _set_busy(self, busy: bool, name: str = "") -> None:
        self._btn.setEnabled(not busy)
        self._cancel.setVisible(busy)
        self._progress.setVisible(busy)
        if busy:
            self._progress.setValue(0)
            self._stats.setText("")
            self._set_result(f"正在读取模型…（{name}）", "busy")

    def _set_result(self, text: str, state: str) -> None:
        self._result.setText(text)
        self._result.setProperty("result", state)
        self._result.style().unpolish(self._result)
        self._result.style().polish(self._result)

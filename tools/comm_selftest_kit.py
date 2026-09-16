"""双进程自测的通用夹具（``tools/comm_selftest.py`` 的底座；T10 的 ``e2e_smoke.py`` 可直接复用）。

**本件不含任何判据数字**：阈值、期望值、PASS 条件全在调用方那件，本件只提供「起子进程、抓它的日志、
把输出同时落盘、记账 PASS／FAIL」这四样机械动作。这样拆的理由是 04 §4.5-① 的 300 行上限——
``comm_selftest.py`` 实测 410 行，去重复与抽函数都已做完（无函数超 50 行），只剩拆文件一条路（§4.5-②③）。

三条口径：

- **子进程日志一律收着整段贴出**：完成标准第 1 条要「读写日志对得上」，只有把 PLC 侧与客户端侧的日志放进
  同一份取证物里才对得了账；子进程崩在半路时，这份日志也是唯一的线索，故 ``wait_ready`` 失败即先贴日志。
- **临时端口不写死**：向系统要空闲端口，免与常驻模拟器抢 4840；但仍限 ``127.0.0.1``（D-6 禁连真 PLC）。
- **不吞异常**：``guarded`` 把任一节抛出的异常记成该节 FAIL 并继续下一节——自测脚本自己崩了却报「通过」
  是最坏的结果。
"""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import threading
import time

SPAWN_TIMEOUT_S = 30.0        # 子进程从起到「可连」的宽裕上限（首跑要建树＋注册命名空间）
READY_MARK = "PLC 模拟器已起"  # 子进程日志里代表 Server 已起、可以连的那一行
STALL_MARK = "扫描落后"        # 子进程日志里代表「某周期超出一个整周期、重置基准且不补扫」的那一行；
                              # 出现即真的少发了几个周期（设计如此：补扫＝凭空造周期），故频率会略低于标称
RATE_MARK = "扫描自计"         # 子进程日志里代表「服务端用自己的单调钟自计的累计频率」的那一行；不经订阅
                              # 推送，故不含客户端侧的批量投递抖动，是测频结论的独立旁证


def force_utf8_stdout() -> None:
    """把 stdout 掰成 UTF-8：本机控制台默认 GBK，中文取证物会 UnicodeEncodeError。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class Tee:
    """把 print 同时送上屏与落盘（``--no-save`` 时不装这层）。"""

    def __init__(self, stream, path) -> None:
        self._stream = stream
        self._handle = open(path, "w", encoding="utf-8")

    def write(self, text: str) -> None:
        self._stream.write(text)
        self._handle.write(text)

    def flush(self) -> None:
        self._stream.flush()
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


@contextlib.contextmanager
def recording(path):
    """上下文内 stdout 同时落 ``path``；``path`` 为 None 即只上屏。"""
    original = sys.stdout
    if path is None:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tee = Tee(original, path)
    sys.stdout = tee
    try:
        yield
    finally:
        sys.stdout = original
        tee.close()


def free_endpoint() -> str:
    """向系统要一个空闲端口拼成 endpoint（仍限 127.0.0.1，D-6）。"""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return f"opc.tcp://127.0.0.1:{probe.getsockname()[1]}"


class Child:
    """子进程里的模拟器（完成标准第 1 条「双进程」的另半边）＋它的日志抓取线程。

    ``config`` 传另一份 machine.yaml 即可演示换点表；``fault`` 走 ``comm.simulator`` 的 ``--fault``。
    """

    def __init__(self, endpoint: str, config, fault: str | None = None, cwd=None) -> None:
        self.endpoint = endpoint
        self.lines: list[str] = []
        self.cwd = str(cwd or os.getcwd())
        cmd = [sys.executable, "-m", "comm.simulator", endpoint, "--config", str(config)]
        if fault is not None:
            cmd += ["--fault", fault]
        print(f"  子进程：{os.path.basename(cmd[0])} -m comm.simulator {endpoint} "
              f"--config {os.path.basename(str(config))}" + (f" --fault {fault}" if fault else ""))
        self.proc = subprocess.Popen(cmd, cwd=self.cwd, text=True, encoding="utf-8",
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        for line in self.proc.stdout:
            self.lines.append(line.rstrip())

    def wait_ready(self) -> bool:
        """等到子进程报「已起」；它先退了或超时都算失败，失败时先把已收到的日志贴出来（不闷着）。"""
        deadline = time.monotonic() + SPAWN_TIMEOUT_S
        while time.monotonic() < deadline:
            if any(READY_MARK in line for line in self.lines):
                return True
            if self.proc.poll() is not None:
                break
            time.sleep(0.1)
        self.dump()
        return False

    def kill(self) -> None:
        """硬杀（＝现场拔线／杀进程）：不走优雅停机，客户端只能靠本地计时器判离线。"""
        self.proc.kill()

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.proc.wait(timeout=10)
            if self.proc.poll() is None:
                self.proc.kill()

    def dump(self) -> None:
        """子进程日志整段贴出，与客户端日志同轮同文件（「读写日志对得上」的取证形式）。"""
        print(f"  ── 模拟器子进程日志（{len(self.lines)} 行）──")
        for line in self.lines:
            print("    |", line)


def slope(xs, ys) -> float:
    """最小二乘斜率（``ys`` 对 ``xs``）；本件只提供算法，判据数字在调用方。

    测频用它而不是「首末两点差商」：全部点都参与，两端的投递抖动被平均掉，而不是直接进结果。
    """
    size = len(xs)
    mean_x, mean_y = sum(xs) / size, sum(ys) / size
    return (sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
            / sum((x - mean_x) ** 2 for x in xs))


def check(results: dict, section: str, ok: bool, detail: str) -> None:
    """记一节结论并当场打印 PASS／FAIL＋实测依据（禁只写「已通过」）。"""
    results[section] = ok
    print(f"  → [{'PASS' if ok else 'FAIL'}] {detail}")


def guarded(results: dict, section: str, body) -> None:
    """任一节抛异常即记 FAIL 并继续下一节。"""
    try:
        body()
    except Exception as caught:
        results[section] = False
        print(f"  → [FAIL] {type(caught).__name__}: {caught}")

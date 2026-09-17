# tools/ — 自家脚本与工具

只读扫描、自检、离线预处理与收口脚本的归属目录。**不属业务码**，不得引入 03 §8 清单外的第三方依赖。

| 路径 | 唯一写者 | 说明 |
|---|---|---|
| `smoke.py` | T01 | 环境冒烟：打印 OCC（pythonocc-core）／PySide6／asyncua／numpy 版本，并核 STEP 读取器可导入。调用 `app/bootstrap.py` 的 `preload_windows_icu()` 做入口引导——conda 的 `icu` 包会让 Qt6Core.dll 命中符号不兼容的 `icuuc.dll`（WinError 127），**任何要 import PySide6 的入口都必须先走该引导**，原因与实测证据见 `app/bootstrap.py` docstring |
| `config_check.py` | T03 | 配置校验入口 |
| `lint_no_magic.py` | T03 | 常驻复查①自动化：扫轴参数魔法数字，**其他单不得修改其判定规则** |
| `comm_selftest.py` | T09 | 双进程自测取证：六节 A–F 分别对完成标准第 2／1＋3／1／步骤 5／4／5 条打印**实测数字**并当场判 PASS／FAIL，输出落 `evidence/T09/selftest.txt`。退出码 0＝所选节全 PASS。跑法 `python tools/comm_selftest.py [--only A,F] [--no-save]` |
| `comm_selftest_kit.py` | T09 | 上一件的**通用双进程夹具**（子进程宿主／日志抓取／Tee 落盘／临时端口／PASS-FAIL 记账／最小二乘）。**不含任何判据数字**，故 T10 的 `e2e_smoke.py` 可直接复用（实测复用了 `recording`／`guarded`／`check`／`force_utf8_stdout` 四件）；拆件理由见该件 docstring（04 §4.5-①②③） |
| `e2e_smoke.py` | T10 | 全链路冒烟：十三项判据 A／B／C／D／E／F／G1–G7，各对派单卡步骤⑦的一条打印**实测数字**并当场判 PASS／FAIL，输出落 `evidence/T10/e2e_smoke.txt`。退出码 0＝所选节全 PASS。跑法 `python tools/e2e_smoke.py [--only A,G] [--no-save]`（`--only G` 即选中 G1–G7，前缀匹配）。A 节＝G20-② 的 `publish_interval_ms<=50` 守卫（等价 ≥20 Hz，⛔不写死 Hz），负控证据见 `evidence/T10/e2e_smoke_negative.txt` |
| `e2e_rig.py` | T10 | 上一件的**装置半边**（起真壳／临时目录／导入自造基本体／摆三点／事件泵／等待谓词／读角标与图标）。**不含任何判据数字**，拆件理由同 T09：合起来 330 行超 04 §4.5-① 的 300 行上限。⚠ 它刻意读若干界面私有属性（`win._last`／`statusbar._freq`／`step5._stages`／`stepbar._completed`）——判据要钉的是**操作员看得见的那份原文**，绕开界面去读内部状态就会假绿（04 §5.5 附7-③）。⛔ 只读，不写任何业务件 |

新增脚本文件名**须先在该单派单卡内报备**（04 §4.5-②）。

## 环境清单再生成（T01 实测口径，改环境后照此重出）

```bash
conda env export -n mecharm --file environment.yml
python -m pip list --format=freeze > requirements.lock.txt
```

⚠️ **`requirements.lock.txt` 不用 `pip freeze`**：本环境里 numpy／packaging／pyparsing／svgwrite
是 conda 装的，`pip freeze` 会把它们写成 `xxx @ file:///D:/bld/...`（conda 构建机路径，本机不存在），
换机器 `pip install -r` 直接失败。`pip list --format=freeze` 输出干净的 `name==version`，实测 0 条 `file://`。

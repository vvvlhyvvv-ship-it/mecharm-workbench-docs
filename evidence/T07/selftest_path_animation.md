# evidence/T07 — 路径生成与动画自测（真窗体＋场景图探针，2026-09-17）

自测环境：`D:/Miniforge3/envs/mecharm/python.exe`（3.11.16，conda 不在 PATH 故用绝对路径）＋
`PYTHONPATH=.`（取证脚本不在仓根，不设 PYTHONPATH 会 `ModuleNotFoundError: No module named 'app'`）。

| 脚本 | 平台 | 产出 | 管什么 |
|---|---|---|---|
| `_drive_step3.py` | `QT_QPA_PLATFORM=offscreen` | `step3_drive_log.txt`＋3 张 PNG | 右栏段清单页、桥载荷、插值钳位、布局不越界 |
| `_drive_shell_path.py` | **真窗体**（须有显示环境） | `shell_path_log.txt`＋4 张 viewport PNG | 视口折线／箭头／红段／当前段／标记移动／fps 角标／逐位硬核对 |
| `_spy_playback_clock.py` | 真窗体（上者的挂片） | `playback_clock_log.txt` | 壳侧 16 ms 播放时钟的 tick 节拍 |
| `_probe.mjs` | 页面内注入 | 由上两者调用 | 读 three 私有场景图（⛔ 非交付件，不放 `view/`） |

⚠️ 样件由 `tests/cad_samples.box(600,400,250)` 现场生成、落 tempfile（自造基本体，⛔ 不含甲方
模型／名称／尺寸）；`view/index.html` **未**注册 path.js（注册行按卡片由指挥方合并时统一加），故
真窗体脚本在页面载入后动态注入 `_probe.mjs`＋`js/path.js`，等价于合并后的注册顺序
bridge→loader→pick→path。⛔ 全程未改 index.html、未改 `view/` 下任何既有交付件。

## 三处取证局限（如实登记，不以截图冒充）

1. **in-app 浏览器测不了动画**：`document.hidden=true`、`visibilityState=hidden`、
   `innerWidth/Height=0`，rAF 根本不转，`take_screenshot` 报 `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`
   （与 T06 记录的同一局限）⇒ 视口侧一律改用**真 Qt 窗体**取证；offscreen 只用于右栏面板。
2. **fps 读数受 Chromium 前后台节流影响，必须带定性条件读**：同一脚本三轮实测——窗体真活动时
   角标 `64／60／58 fps`（末次 `perf.fps {'fps': 56.1}`）；窗体非活动时只剩 `1~3 fps`
   （末次 `{'fps': 0.7}`）。故 D 节逐秒并列打印 `isActiveWindow`，该值为 False 的行读数作废；
   脚本自身在 `QApplication` 之前设 `QTWEBENGINE_CHROMIUM_FLAGS`（含
   `--disable-features=CalculateNativeWinOcclusion`）关掉后台节流。⛔ 不以被节流时的低值冒充
   「播放流畅」，也⛔ 不拿另一轮的高值冒充本轮实测——本文档所有 fps 均取自
   `shell_path_log.txt`／`playback_clock_log.txt` 同一轮（该轮 `isActiveWindow` 全程 True）。
3. **像素判据含干扰，硬结论一律以场景图数值为准**：工件本体色 `0x8a97a3` 与 `text_dim 0x9fb0bd`
   落在 ±26 容差内互相污染；pick.js 标号牌边框就是 accent 蓝；工具标记按 token 色匹配对光照着色
   无效（`tool_marker 0`），故另立 `green_dominant`（g>r+30 且 g>b+30）判据，实测 1087 像素。
   G 节像素统计只作辅证，`{'idle_seg':1308,'current_seg':621,'blocked_seg':0,
   'tool_marker':0,'model_body':2480,'green_dominant':1087}`。

## A. 表格与视口一致（完成标准①前半）

五点 → 4 段；右栏表格与桥载荷 `path.show` 同源逐项相等（offscreen 那组点位 300/400/250/300）：

| 段 | 表格行 | `path.show` length | 端点相等 |
|---|---|---|---|
| 1 | `['1','P1→P2','点位','300.0']` | 300.0 | True |
| 2 | `['2','P2→P3','点位','400.0']` | 400.0 | True |
| 3 | `['3','P3→P4','点位','250.0']` | 250.0 | True |
| 4 | `['4','P4→P5','点位','300.0']` | 300.0 | True |

汇总「共 4 段 · 总长 1.250 m · 预估节拍 4.2 s」；`表格长度列 == path.show length: True`、
`表格端点 == path.show start/end: True`、`path.show 全 ASCII: True｜含中文? False`、
键 `['blocked','end','id','length','start','type']`。

真窗体那轮（box 600×400×250）：表格 `600.0／400.0／250.0／600.0`、汇总「共 4 段 · 总长 1.850 m ·
预估节拍 6.2 s」，视口场景图 **折线 4｜箭头 4｜标记 1｜可被拾取(须 False) False**，四条段折线
颜色全为常态灰 `0x9fb0bd`。步骤条 `[True,True,True,True,True]`。

## B. 播放流畅＋实测 fps（完成标准①后半）

角标（`shell_path_log.txt` 同一轮，`isActiveWindow` 全程 True）：

| 时刻 | 底部角标 | 当前段 |
|---|---|---|
| 播放前 | `数据 --Hz · 画面 --fps` | — |
| 播放 1.0 s | `画面 64fps` | 1 |
| 播放 2.0 s | `画面 60fps` | 2 |
| 播放 3.0 s | `画面 58fps` | 2 |
| 播完后（看门狗退出 rAF，保留末次实测值） | `画面 56fps` | — |

壳侧播放时钟（`playback_clock_log.txt`，`_spy_playback_clock.py` 只计数、不改行为）：
**tick 总数 376｜首末跨度 6.17 s｜间隔中位 16.4 ms｜均值 16.4 ms｜最小 1.7｜最大 92.9｜
间隔 >200 ms 的次数 0/375** ⇒ 60 Hz 软件时钟没被饿死，发帧连续。

播放态互锁：`[▶] False｜[⏸] True｜[生成路径] False｜段型下拉 False｜步骤②页可编辑 False`；
播完 `计时器仍在跑: False`、`步骤②页恢复可编辑: True`、日志「播放结束：共 4 段 · 总长 1.850 m ·
预估节拍 6.2 s」。点步骤条②（离开本页）→ `播放是否已暂停: True｜步骤②页恢复可编辑: True`。

## C. 越界用例：红段＋无法进入④（完成标准②）

注入 `(5000,0,0)`（占位行程各轴合计只到 3000 mm）：

- 汇总「共 4 段 · 总长 10.025 m · 预估节拍 33.4 s · ⛔ 2 段不可达（已标红，无法进入校核）」
- 红字行整句原因：`⛔ 第 2 段不可达：X1／X2／X3 合不出 5000 mm：行程合计只到 [0, 3000] mm
  （各轴行程见 machine.yaml）（另有 1 段同样不可达）——已禁止进入步骤④`
- 阻断段号 `[2,3]`；表首列 `['1','⛔ 2','⛔ 3','4']`；单元格 tooltip 存整句
- 步骤条 `[True,True,True,False,False]`（④⑤锁定）；`[▶播放] 可用: False`
- 视口侧：`path-seg-2／path-seg-3` 转 deny 红 `0xb3261e`，另两段仍 `0x9fb0bd`；
  `path.show blocked 标志 [False,True,True,False]`
- 点位不足（只给 1 点）：`[生成路径]` 禁用＋日志「点位不足：生成路径至少需要 2 个点位
  （当前 1 个）」＋**桥载荷条数 0**（⛔ 不静默造段）

## D. blending 默认关（完成标准③）＋段型可切

`复选框勾选: False`、`段默认 blending: [False,False,False,False]`。段型下拉 point→contour：
`切段型后 summary: None`、`path.show {'segments': []}`、日志「结果作废：段型改为「轮廓型
（作业速度）」——须重新生成路径」；轮廓型段类型 `['LINE']`、速度 `[50.0]`（读自 machine.yaml 的
work 速度）、汇总节拍由 4.2 s 变 25.0 s（同几何、速度口径不同）。⛔ 电Q-8 回执未到，本期只发
0=PTP／1=LIN，无圆弧／样条插补。

## E. 播放按段线性插值，⛔ 不外推／⛔ 不预测下一帧（W-5.7）

总时长 4.166666666666666 s 的六个采样：

| elapsed | seg | ratio |
|---|---|---|
| 0.000 s | 1 | 0.0000 |
| 0.417 s | 1 | 0.4167 |
| 1.875 s | 2 | 0.6562 |
| 2.083 s | 2 | 0.8125 |
| 3.750 s | 4 | 0.5833 |
| 4.167 s | 4 | 1.0000 |

`所有采样 ratio 均在 [0,1]: True`；`超出总时长 5 s: (None, 0.0)`（走完即停，⛔ 不外推）。
插值函数本身：`_lerp({"A":10},{"A":20,"B":5},0.5) == {'A':15.0,'B':5.0}`——只在一端出现的轴按
常值处理，⛔ 不当 0（该缺陷由本轮自测暴露：初版 `first.get(key, second[key])` 会提前求值
`second[key]` 而抛 KeyError）。

**插值落点在壳侧 core 出口**（`app/pathctl.py::_locate／_lerp` → `core.path.tool_pose_in_model`），
`view/js/path.js` 只把收到的列主序矩阵投影到标记上、自身不存关节值也不推算下一帧 ⇒ 结构上
不可能外推或预测。此为与卡片措辞（把「播放按段线性插值」列在 path.js 名下）的偏差，已登记请追认。

## F. 逐位硬核对：视口 == core（不靠肉眼看截图）

暂停后按已知插值参数发帧，读探针报的标记世界坐标，与 core `tool_pose_in_model` 的平移分量对比：

| 段2 ratio | 视口标记世界坐标 | core 平移分量 | 一致 |
|---|---|---|---|
| 0.0 | `[600, 0, 0]` | `[600.0, 0.0, 0.0]` | **True** |
| 0.5 | `[600, 200, 0]` | `[600.0, 200.0, 0.0]` | **True** |
| 1.0 | `[600, 400, 0]` | `[600.0, 400.0, 0.0]` | **True** |

播放中另两次采样亦见标记随帧移动：`[600, 316.75467, 0]`（段2 进行中，该段折线转 accent 蓝
`0x2f6feb`）→ 0.6 s 后 `[600, 400, 141.21773]`（已进入段3）。`pose.update` 键
`['poses','seg','ts']`、link `['flange']`、矩阵长度 16、`矩阵全为有限数: True`、
`段首帧 == 列主序(tool_pose_in_model(joints_start)): True`、列主序平移落在 12/13/14、
`pose.update 全 ASCII: True`。

## G. 结果作废（切模式／改点／切段型／F3／新模型）

五条路径统一走 `PathController.invalidate`：清段清单＋`step3.clear()`＋（曾有路径才）下发
`path.show {"segments": []}`＋人话日志＋步骤④⑤回锁。改点位时先按真实原因作废再清点，
`had` 守卫防重复日志与重复信号（实测切段型那轮只出一条「结果作废：段型改为…」）。

## H. 布局：右栏窄宽不越界

| 面板宽 | pane | table | viewport | 末列右缘 | 水平滚动上限 | 越界 |
|---|---|---|---|---|---|---|
| 280（最小宽） | 296 | 240 | 238 | 238 | **0** | False |
| 360（默认） | 360 | 304 | 302 | 302 | **0** | False |

抓图 `step3_panel_280x640.png`／`step3_panel_360x640.png`／`step3_blocked_360x640.png`
（offscreen 无 CJK 字体，图里中文为豆腐块——与 T06 同一局限，文字内容以上表打印串为证）。

## I. fps 通道（本单新定 `perf.fps`，视口→壳）

03 §5 原无帧率回传通道，本单新定 `perf.fps {"fps": <number>}`（已登记请回填 03 §5，T09/T10 可复用）。
壳侧只认该 type：`坏值后角标不变: 数据 --Hz · 画面 59fps`、`非 perf.fps 不动角标: 同上`。
角标只在播放期间刷新，停播后保留末次实测值（path.js 的 `IDLE_STOP_MS=500` 看门狗：500 ms 没收到
`pose.update` 即 `cancelAnimationFrame` 退回按需渲染，避免空转）。

## 探针手法（为什么不用截图、也不能包 renderer.render）

three r160 下页面拿不到 loader 的私有 scene/camera：`new THREE.WebGLRenderer()` 后实例的 `render`
是构造函数里赋的**自有闭包**（`inst.render !== WebGLRenderer.prototype.render`），包原型对已建实例
完全不触发；`import * as THREE` 的命名空间导出只读，换不掉构造函数（T06 已记录此坑）。故：
`Object3D.prototype.onBeforeRender(renderer, scene, camera, …)` 是**实例级**钩子，用它捕获
renderer/camera；链式包裹 `Object3D.prototype.add` 捕获 scene；两者都只观察、原方法照旧 `apply`。
`_probe.mjs` 报对象前先过 `o.parent`，否则会把已 `dispose` 的旧段一起报（实测折线数 4→8→12 的假象）。
无 renderer 句柄需重绘时派发 `resize`，借 loader 自身 `resize()→render()` 出一帧。

## J. ik 已知位姿手算复核（`tests/test_ik.py`，25 例；纸面算式逐条对到断言值）

合成链 A（`base → gantry(SX,x) → column(SZ,z，连杆长 50) → head(WR，绕 z)`）：fk 语义＝先沿 motion
偏 `length_mm` 再叠加轴运动，故 `{SX:200, SZ:100, WR:30}` → head 位姿 = `translation(200,0,150) ∘
rotation(z,30)`。逆解该位姿：x 方程 `SX = 200 − 0 = 200`；z 方程 `SZ = 150 − 50 = 100`；姿态
`atan2 → 30` ⇒ 断言 `{"SX":200.0,"SZ":100.0,"WR":30.0}`（`abs=1e-9`，纯数学量级的浮点回代误差），
且 `fk∘ik` 往返闭合。把 WR 行程放宽到 ±一整圈后候选 `{30, −330, 390}`（390 出界）：零位 seed 取
`|30−0| < |−330−0|` ⇒ 30；`seed=−330` ⇒ 取 −330（按连续性选支，不跨圈翻转）。

合成链 B（x 向两根轴 `SX(0,500)`／`SX2(0,400)`，中间 `flange` 为被动连杆、摘除后 tip 重挂 gantry）：
一个方程两个未知量，解由 seed 与行程定。目标 150 mm、零位 seed ⇒ 均分 `SX=SX2=75`（Σ 恰等于目标，
⛔ 不是近似收敛）；`seed={SX:500,SX2:0}` ⇒ 先把 SX2 钉在**下界原值 0**、余量全给 SX ⇒ `SX=150／
SX2=0`，并额外断言 `got["SX2"] == 0.0`（钉住若留 `−1e-16` 一类残差，T08 的 `check_limits` 会把本
可达点判成越界——limits.py 的 travel 判据是严格不等式）；目标 1500 mm > 行程合计 900 mm ⇒ 不可达。

合成链 C（自指倍速轴 `DUP` 的 `ratio.master == 自身`、ratio=2 读自配置）：目标 300 mm、零位 seed ⇒
工程位置均分 `DUP=SX=150`；DUP 是**驱动级倍速**（⛔ 禁读成跨轴约束，03 §4／T04 定案口径）⇒ 返回
驱动位移 `150 ÷ 2 = 75`，断言 `{"DUP":75.0,"SX":150.0}`，且 fk 回代经 `resolve_positions` 把 75
放大回 150、总位移仍是 300 mm。

⚠️ 现场 `config/machine.yaml` 的 `links.axis／motion` 是 **G18 占位**（踏勘第 7 项回执未到），故现场链
只做**结构性**断言（末端推导唯一、被动连杆摘除、往返闭合、按配置累加），一切数值断言都落在上述
纸面手算过的合成链上；⛔ 未把 `test_kinematics.py` 的 `SAMPLE_JOINTS` 当机台事实复制。常驻守卫四条：
禁硬编码机台事实、禁复制 tests 的合成绑定、禁数值迭代（按 `SOLVER_FUNCS` 逐函数扫
`jacobian／newton／ccd／gradient／scipy／numpy／max_iter`，命中即挂）、ik 内部只用行主序。

## 全套回归

- `pytest -q` → **202 passed**（`evidence/T07/pytest_regression_log.txt`）
- `python tools/lint_no_magic.py` → `[OK] 无轴参数魔法数字；扫描 50 个文件`（path.js 入扫后仍合规）
- 粒度实测物理行：`app/pathctl.py` 243｜`app/shell.py` 297｜`app/steps/step3_path.py` 238｜
  `core/path.py` 233｜`view/js/path.js` 247（均 ≤300）

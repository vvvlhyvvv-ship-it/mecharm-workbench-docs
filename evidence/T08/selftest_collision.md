# evidence/T08 — 碰撞三态与禁发双阻断自测（离屏＋真窗体＋注入探针，2026-09-17）

自测环境：`D:/Miniforge3/envs/mecharm/python.exe`（3.11.16，conda 不在 PATH 故用绝对路径）＋
`PYTHONPATH=.`；离屏脚本 `QT_QPA_PLATFORM=offscreen`，真窗体脚本在 `import _rig` **之前**设
`QT_QPA_PLATFORM=windows` 并自带 `QTWEBENGINE_CHROMIUM_FLAGS` 四件套（含
`--disable-features=CalculateNativeWinOcclusion`，T07 实测：只关 backgrounding 三件套不够）。

| 脚本 | 平台 | 产出 | 管什么 |
|---|---|---|---|
| `_rig.py` | 被 import | 无独立产出 | 真壳装置：真导入链路／真下拉／桥只**记录**不替换；自造 40 mm 立方障碍落 tempfile |
| `_drive_step4.py` | offscreen | `step4_drive_log.txt` | ④两道门、三态三通道、点击定位、弹窗正文、上屏文案审计 |
| `_drive_send.py` | offscreen | `send_gate_log.txt` | 双阻断两条拦截、指纹失配、弹窗两出口、20 段耗时、G19 现算＋N=0、包络承重 |
| `_drive_viewport.py` | **真窗体** | `viewport_log.txt`＋5 张 PNG | 报警条／标记／代理盒线框／定位高亮／相机飞到／作废撤下（场景图数值为硬结论） |
| `_probe_collision.mjs` | 页面内注入 | 由上者调用 | 读 three 私有场景图（包 `Object3D.prototype.add`／`lookAt`，只观察）⛔ 非交付件 |
| `_probe_inject.py` | 仓外沙箱 | `injection_probe_log.txt` | 注入探针：改坏判据后 pytest 必须 rc=1 且失败项＝推理目标集 |

粒度实测（取证脚本，均 ≤300 行／单函数 ≤50 行）：`_drive_viewport.py` 209｜`_rig.py` 188｜
`_drive_send.py` 154｜`_drive_step4.py` 148｜`_probe_collision.mjs` 91｜`_probe_inject.py` 108。

## 四处取证局限（如实登记，不以截图冒充）

1. **offscreen 测不了视口**（`document.hidden=true`、rAF 不转、`grab()` 报
   `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`，T06/T07 同一局限）⇒ 视口侧一律真窗体；offscreen 无 CJK
   字体，右栏中文在 PNG 里是豆腐块 ⇒ 右栏以**打印串**为证。
2. **scene 是 loader 的模块私有变量**，页面上下文读不到 ⇒ 探针链式包裹 `Object3D.prototype.add`
   观察（pick/path 各包过一次，探针叠最外、原实现照旧 apply）。⛔ 注入发生在步骤①导入**之后**时
   钩子尚未触发（`A 节 场景已就绪: False` 即此时点真值），B 节真导入的 `group.add(mesh)` 才捕获 ⇒
   合并注册序下（collision 在 loader 之后、导入在用户操作时）不存在此时序问题。
3. **单障碍工况证伪不了「相机飞到」**：场景里只有受测障碍时，loader 的整体取景与定位取景是同一个
   盒子，相机前后完全相同（首版实测踩过）⇒ 真窗体脚本每个工况导入**两立方同一 STEP**（近处受测＋
   `FAR_X0=4000` 远处一个），整体取景被撑宽后 C/D 节才量得出位移。远处立方离路径 0~100 mm 极远 ⇒
   ⛔ 不参与命中（三态结论与离屏逐字一致：13/2/0 条）。副作用：E/F 截图是 4 m 远景、近处几何很小，
   该两节的硬结论是场景图数值（`display=none`、标记 26→0），截图只证「条子没了」。
4. **耗时数字受 OCC 首轮预热影响**：1 段工况首轮 70.9 ms、次轮 9.8/1.9 ms ⇒ 汇报只贴 20 段三轮
   （70.5/68.9/78.6 ms）与 core 日志同值，⛔ 不拿预热轮当常态、也不拿最稳轮冒充三轮。

## A. 三态全对＋三通道齐（完成标准①）

自造 40 mm 立方障碍（⛔ 非甲方工件），1 段路径（0→100 mm，3 采样姿态），只换障碍 X 下角：

| 工况 | 期望 | 实测 | 命中对 | 最近距离 | 臂侧代理盒 |
|---|---|---|---|---|---|
| X 下角 -20（相交） | interfere 🔴 | interfere 🔴 | 13 | 0.000 | `[-3,-3,-3,3,3,3]` |
| X 下角 108（间隙 5） | warn 🟡 | warn 🟡 | 2 | **5.000** | `[63.667,-3,-3,103,3,3]` |
| X 下角 603（间隙 500） | pass 🟢 | pass  | 0 | — | — |

三通道实测（干涉态）：①卡片 ` 已建模的 13 根连杆范围内 检出干涉`、文字色 `#b3261e`；②列表 13 行
全红底 `#b3261e`、首行 `['1','臂身 base ↔ 零件_1','0.0']`；③桥 `collision.show level=deny｜cases=13｜
全 ASCII=True`，首条 `{'seg':1,'arm':'base','obs':1,'dist':0.0,'point':[-3,-3,3],'box':[-3,-3,-3,3,3,3]}`
（⛔ 无中文点名：部件名由视口从 loader 的 `mesh.userData.name` 自取）。warn 态卡片色 `#d9a521`、
列表黄底、`level=warn`；pass 态卡片 `#1c7c43`、列表空、`level=clear`。整句人话与视口报警条**同一句**
口径：`⛔ 第 1 段与【零件_1】干涉，已禁止下发（…）`／`⚠ 第 1 段与【零件_1】间距 5.0 mm，小于安全值，
可进入步骤⑤（下发前会再提示）`。

视口场景图（真窗体，`viewport_log.txt`）：干涉态 `碰撞图层 显示对象 26 个`（13 点＋13 线框）、
报警条 `底色 rgb(179,38,30)｜字色 rgb(255,255,255)`、文案含从 mesh 自取的「零件_1」；
`可被拾取的碰撞对象（须 0 个）: 0`（⛔ 不设 `userData.id`，否则被 pick.js 当部件）；warn 态 4 个对象、
底色 `rgb(217,165,32)`＋深色字 `rgb(22,32,42)`；pass 态 `display=none`＋文案清空＋0 对象。
截图 `viewport_interfere/focus/warn/pass/invalidated.png`。

## B. 点击行定位：标记放大＋双方高亮＋相机飞到（完成标准①后半）

点列表首行（真信号 `case_clicked.emit(0)`）：相机 `[6387.898,3283.355,3687.453] →
[74.7,56.024,62.919]`（**确实飞过去了: True**）；首条标记 `scale 14→26.6`、其余压暗
`opacity 0.95→0.35`／线框 `1→0.45`（⛔ 不换色，保住三态语义）；障碍侧经 collision.js 转 loader 的
`hl.set` 发光 `#b3261e`（干涉）／**`#d9a520`（预警态点行，⛔ 不染红**——红会被读成"已相碰"）；
桥 `collision.focus {'index': 0}`；状态栏 `已在视口定位：第 1 段，臂身 base 与 零件_1（最小距离 0.0 mm）`。

## C. 双阻断（完成标准③④）

- **第①条（按钮置灰）**：干涉态 `⑤按钮可用 False`＋旁注 `校核未通过，无法下发：⛔ 第 1 段与【零件_1】
  干涉…`；门禁**状态变化**留日志 `INFO app.checkctl: 步骤⑤下发按钮已置灰：…`／`已解锁：…`。
- **第②条（入口独立复判）**：干涉态直调 `send_path() → False`，日志
  `WARNING app.checkctl: 下发被拒（send_path 入口独立复判）：校核未通过，无法下发：…`。
- **改点作废（完成标准④）**：真链路改一个点位 → 旧结果当场作废，`⑤按钮 False`＋旁注
  `尚未做碰撞校核…`；直调 `send_path() → False`＋同口径 WARNING。指纹 `11788b6851b8b774`。
- **指纹失配（故障注入）**：绕过作废信号就地换 `pathctl._segments`（不发 `changed`）⇒ 按钮**仍显示
  True**（读的是旧状态）而指纹 `11788b6851b8b774 → fbd99c22f6e1d1f4`、直调 `send_path() → False`、
  日志 `下发被拒（send_path 入口独立复判）：路径已改动，无法下发：旧校核结果已失效，须重新校核`
  ⇒ 第②条不信任按钮状态，独立成立。
- **弹窗两出口**：[取消] → `False`＋`INFO 下发已取消：操作员在确认弹窗点了[取消]`；[确认下发] →
  `True`＋`INFO 下发请求已确认（结论 pass、1 段、指纹 11788b6851b8b774）：PLC 下发通道由 T10 接入`。
  弹窗默认按钮＝[取消]。

## D. 🟡 预警允许进⑤＋弹窗黄条与覆盖面复述（卡片步骤 4／G19 第 4 条）

warn 态 `⑤按钮可用 True`、右栏提示行 `🟡 预警：间距小于安全值。可以进入步骤⑤，但下发前会再次提示，
由你确认`；直调 `send_path() → True`，弹窗正文逐行：

```
共 1 段 · 总长 0.100 m · 预估节拍 0.3 s
校核结论：🟡 已建模的 13 根连杆范围内 检出预警（间距小于安全值）
覆盖面：本模式含 3 根未建模臂，其干涉未校核（未建模轴：ZA1、ZA2、RA）
⚠ 预警：间距小于安全值——确认知悉后方可下发

下发 = 向 PLC 提出运动请求，PLC 会再校验并有权拒绝或限速
```

## E. 覆盖面 G19（完成标准⑥）

- 三态卡片逐字带限定：`🔴//🟢 已建模的 13 根连杆范围内 检出干涉/检出预警（间距小于安全值）/
  未检出碰撞`；G19 措辞判据三态 `CLEAN`（通过态⛔ 无"通过／整机／全部安全／无碰撞风险"）。
- UI 显式标注（N 现算）：`本模式含 3 根未建模臂，其干涉未校核（未建模轴：ZA1、ZA2、RA）`，
  覆盖面色 `#d9a521` 常显；五模式现算 `3(ZA1,ZA2,RA)／3(ZB,FB1,FB2)／3(ZC,FC,RC)／1(ZD)／1(KE)`，
  全机 `links=13｜轴 22｜N=11`（⛔ 未写死）。
- **N=0 对照工况**：合成配置（模式只挂 X1，X1 有连杆）走同一条 `check→coverage()`：
  `N=0｜()｜pass｜已建模的 2 根连杆范围内 未检出碰撞｜本模式的轴全部已建模，结论覆盖本模式所用的全部臂`。
- ⛔ 未给 `links:` 补链、⛔ 未改守卫用例 `test_kinematics.py::test_sample_arm_axes_have_no_link`
  （全套回归 226 passed 含该守卫）。

## F. 包络承重（完成标准②）

同一几何同一路径，只换包络（内存副本，⛔ 未改 machine.yaml，回读仍 3.0）：
包络 3.0 → `🟡 warn｜5.000 mm｜盒 [63.667,-3,-3,103,3,3]`；包络 12.0 → `🔴 interfere｜0.000 mm｜
盒 [54.667,-12,-12,112,12,12]` ⇒ 判定翻转，包络真参与判定。tests 侧另有用例
`test_collision_envelope_is_a_load_bearing_parameter`（3.0→干涉、1.0→预警 1.0 mm）。

## G. 校核耗时（完成标准⑤，只留实测不承诺指标）

20 段／21 采样姿态／13 已建模连杆／1 障碍（障碍在 x=603 被路径扫过 ⇒ 精判全触发的上界工况）三轮：
**70.5／68.9／78.6 ms**；core 日志 `INFO core.collision: 碰撞校核 20 段／21 采样姿态／13 根已建模
连杆／1 个障碍，耗时 78.6 ms → interfere`；右栏实测数字行同值。1 段工况 9.5／1.9 ms（首轮含 OCC
预热 70.9 ms，见局限 4）。未启用 FCL 宽相（未过 03 §8 组件准入，亦无必要）。

## H. 注入探针（附7-②：rc=1 真失败、失败项＝推理目标集）

仓外沙箱副本（copytree 去 `.git`，⛔ 工作树零改动）；基线 `24 passed` 后逐条注入：

| 注入 | rc | 失败项（＝推理目标集，无目标外失败） |
|---|---|---|
| 预警带失效（有命中也报 pass） | 1 | three_verdicts[408-warn]、precise_distance、envelope |
| 包络减半（外扩量≠配置值） | 1 | three_verdicts[398]（断言锁 ±3 盒坐标）、[408]、precise、envelope、sorted_worst、**no_magic 守卫**（注入的 `2.0` 本身是魔数） |
| G19 措辞松口（通过态说"通过"） | 1 | verdict_wording、site_config |

旁证（首跑踩出、本轮不处置）：包络配 0 会让「父级原点＝本级原点」的连杆代理盒退化成零体积、OCC
MakeBox 抛**原始错**（非人话）。生产不可达（machine.yaml 只读、现值 3.0）；本单不修——
`core/collision.py` 已顶到 300 行上限、`tools/config_check.py` 是禁改件 ⇒ 留给配置校验单（报备项已记）。

## I. 上屏文案审计

受审 160 条字符串（右栏全部可见文本＋状态栏全部句子＋弹窗正文＋就绪提示）：禁用词命中 **CLEAN**
（词表＝04 §5.5-③ 复查词＋`collision／hash／verdict／clearance／envelope／machine.yaml／关节角／
位姿矩阵／插补／插值／电Q／G19／T08` 等内部词）。

## J. 本轮自测暴露并修复的产品缺陷（证据脚本咬出，非取证装置问题）

1. `view/js/collision.js::ensureGroup` 在图层已存在时返回 false ⇒ **第二次及以后的校核一处标记都画
   不出来**（首版真窗体 D/F 节 `显示对象 0 个`）。改为图层只建一次、已建即返回 true。
2. `Step4Pane.set_ready` 只在有原因时写提示行 ⇒ 条件解除后**过期原因留在屏上**（导入模型后仍显示
   "等待步骤①"）。加底文案状态（空态句／`_DONE_HINT`，`clear()` 复位），`set_ready` 恒写"原因或底文案"。
3. 定位高亮原先恒发 `semantic:'deny'` ⇒ 预警态把工件染红、被读成"已相碰"。改为随三态（deny/warn）。
4. `[开始校核]` 原先只看步骤③ ⇒ 未导入模型时按钮可点、点了只报错，与 shell 步骤条④门禁不一致。
   `_refresh_ready` 收紧为「步骤③已生成 **且** 步骤①已导入实体模型」，不满足给人话原因。

## K. 全套回归与粒度

- `pytest -q` → **226 passed in 32.09s**（`pytest_regression_log.txt`）
- `python tools/lint_no_magic.py` → `[OK] 无轴参数魔法数字；扫描 54 个文件`（collision.js 入扫后仍合规）
- 交付件物理行：`core/collision.py` 300｜`tests/test_collision.py` 299｜`app/checkctl.py` 249｜
  `app/steps/step4_check.py` 188｜`app/shell.py` 300｜`app/pathctl.py` 255｜`app/panel.py` 92｜
  `view/js/collision.js` 244（均 ≤300）
- ⚠️ `core/collision.py` 与 `app/shell.py` **双双顶到 300 行上限**：后续任何追加都会破限 ⇒ 报备项请裁
  （collision 若需加配置校验守卫，须先拆件并由指挥方追认文件名）。

## L. 报备项（全文见收单汇报，此处摘要）

新增源文件名清单（`tests/test_collision.py`／`app/steps/step4_check.py`／`app/checkctl.py`／
`view/js/collision.js`）；`check(path, scene, clearance_warn_mm)` 签名偏离（插入几何来源 `scene`）；
`CollisionCase` 增 `box` 字段（视口画臂侧线框用）；注册顺序建议 bridge→loader→pick→path→collision；
新桥 type `collision.show`／`collision.focus` 请回填 03 §5；G13 前端预检层未做（可选增强、后置）；
包络配 0 的原始错留给配置校验单（H 节旁证）。

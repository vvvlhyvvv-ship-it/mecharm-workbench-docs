# T09 OPC UA 模拟器与通讯客户端

## 目标
`comm/simulator.py`（按 S-1 点表自建 OPC UA Server，模拟 PLC：收段→虚拟执行→20Hz 回读）+ `comm/opcua_client.py`（asyncua 客户端：订阅回读+写下发）。**真 PLC 没到位前，全部联调靠这单的模拟器。**

## 前置阅读
03 架构 §4 opcua 配置节 §5 ｜ S-1 契约第 4/5/6 章（DB 布局与数据块）、第 9 章（握手时序）、§3.2+§9.3（职责边界与钳位原则）｜ 规程 W-6.1（模拟器先行）

## 过渡期布局口径（**2026-09-15 明确，属口径说明、不是步骤**；原挂在步骤 2 导致编号重复，已移出）
> 起因：契约 **V1.2 现状仍是 8 轴口径**（§5.2 `Pos = ARRAY[0..7]`、"未使用轴位一律填 0"、§6.1 回读 `EnableMask` 为 `BYTE`），而实机 22 轴（G11）——本单**禁自行改契约**（见禁止事项）。故本单按以下口径实现：
- **段打包走 machine.yaml `opcua.pack_profile` 开关**，模拟期默认 **`v1_2_8axis`**：按 V1.2 布局（56 B/段、`Pos[0..7]`、未用轴位填 0、**无 AxisMask 字段**）实现，**先把第 9 章握手时序验通**（测试路径用 ≤8 轴的本体 6 轴即可）；
- **22 轴全表与 AxisMask 只保留在 machine.yaml 内部**（供校验与将来的 `v1_3_24axis`），**不落进 V1.2 布局**；
- 契约 **V1.3 冻结后**：改 `pack_profile` 取值即切换，**不改码**——"改配置不改码"的承诺由此成立；
- 若发现 V1.2 布局与实做**无法兼容**（非"不匹配"，而是结构上做不到）→ 停下汇报，不自行改契约。
- 扩容后的布局数字（段 56→124 B、下发块 584→1264 B、50 段方案 6224 B、回读块 92/96→228 B）见 **CR-2026-03 §三-5**，属契约 V1.3 输入，本单**只按 profile 取值实现、不硬编码这些数字**。

## 步骤
1. 点表落地：从 machine.yaml `opcua:` 节创建 Server 节点树（DB_SW_to_PLC / DB_PLC_to_SW 镜像结构，符号名访问，禁偏移直写）
   > **⚠️ G17 节点表扩表（2026-09-16 裁决，详条见 04 §7.2-G17、派单卡见 04 §6.4 T09）**：原节点表只有
   > `read_nodes: {axis_pos[8], status, heartbeat}`／`write_nodes: {cmd, seg_count, seg_array}`，**覆盖不到契约 §9.1
   > 步骤 1/2/4/6/7 所需的七个符号**；且校验器 `validate.py` 的 `_nodes()` **只按 `schema.py` 的 SPEC 遍历** →
   > **在 yaml 里自行加键不报错、被静默丢弃**，实现会话无法自救。**裁决＝扩表**（03 §4 已改）：
   > `read_nodes` 增 `axis_vel[8]`／`ack`／`alarm_word`／`seq_id`／`cur_seg`，`write_nodes` 增 `seq_id`／`speed_override`。
   > **已授权本单代 T03 改**：`core/config/{schema,validate,loader}.py`＋`config/machine.yaml`（**只 `opcua:` 节**）＋
   > `tests/fixtures/` **全部 8 个样例**。硬约束：新键**必填**；`axis_vel` 节点数**同受 `PACK_PROFILE_AXIS_COUNT` 约束**；
   > **`tests/test_config.py` 24 用例全绿且不改断言**；`lint_no_magic.py` 判定规则不得动。
   > ⛔ **不得写死符号名**（违反完成标准第 5 条）、**不得降级为 Status 位＋超时推断**（会让步骤 5"收到原因码"不可达）。
   > **本轮不加** `mode_mask`／`enable_mask`／`sync_err`／`timestamp`（理由见 G17）→ 需要时停下汇报。
   > **`seg_array`**：本期按**单节点写打包 ByteString（10×56＝560 B）**、禁逐变量写，假设进代码注释＋汇报。
   > **扩表不阻塞其余部分**：节点树骨架／段打包／20 Hz 回读／离线判定＋重连＋看门狗／非 Ack 用例可先干。
2. 模拟器行为：监听命令字→按 S-1 第 9 章握手（校验→接受→执行→完成/异常，9 步时序+超时表照契约执行）→虚拟轴运动按梯形速度规划，20Hz 更新回读区；支持注入异常（拒绝/超时/断线）供 T10 测试
3. 客户端：`connect(endpoint,cfg)`，Subscription 20Hz 回读→`on_frames` 回调；写接口 `write_segments(path)`；断线自动重连+stale 看门狗（数据超时判离线）
4. 安全策略：默认 None + 用户名占位（**电Q-2（OPC UA 接入参数/安全策略）**回执后只改配置不改码——策略可切换设计）
5. pytest/脚本：客户端读模拟器 10s，实测频率统计 ≥20Hz；注入拒绝异常→客户端收到原因码

## 完成标准
- [ ] 模拟器+客户端双进程跑通，读写日志对得上（贴实测）
- [ ] 段打包按 `pack_profile=v1_2_8axis` 完成，**段长实测 56 B**、未用轴位填 0（贴十六进制/长度实测）
- [ ] 回读频率实测 ≥20Hz（角标数据的源头就靠它）
- [ ] 断 simulator 进程→客户端 5s 内判离线并回调状态
- [ ] 节点全部符号名访问；改 machine.yaml 节点表即可换点表（代码零改动演示一次）
- [ ] commit：`feat(T09): OPC UA 桥与模拟器`

## 禁止事项
- **Q 回执冻结前禁连真 PLC**（D-6）；本单只在 127.0.0.1 自环
- **禁自行改契约**：契约 V1.2 的 8 轴布局与"未用轴位填 0"**照实现**（过渡期口径见上方专节），改动一律走 @user 的契约 V1.3 窗口；**不得把 22 轴＋AxisMask 硬塞进 V1.2 布局**
- 禁自行升级/替换 `environment.yml` 中的包（依赖增补走 04 §4 流程）

---

## 收单记录（指挥方，2026-09-16 21:17 合并；时点＝merge commit `f8de0b8` 的作者时间，可复现）

**验收结论：已过——完成标准六条逐项实测通过，已合并入 main（merge commit `f8de0b8`，`--no-ff`，零冲突）。**
交付＝`task/T09` 上单笔 `4616574 feat(T09): OPC UA 桥与模拟器`（**27 文件、+2640／−18**）；父＝merge-base `7369df9`；reflog 只有 `Created from HEAD`＋四次 `merge main: Fast-forward`＋一次 `commit:` ⇒ **无 rebase／amend／reset**；分支无 upstream，`origin/main` 全程仍 `2569104`（推送冻结令未解）。合并可行性预判：main 侧 31 文件 ∩ T09 侧 27 文件＝**空集** ⇒ 预告零冲突，实测相符。
合并后 main 回归：pytest **130 passed**（＝109＋21，与预判逐位一致）、`lint_no_magic` **rc=0（42 文件）**、`config_check` rc=0、附4 **空**、附5 **空**、附6-① 未新增 vendor／② **rc=0 空**、仓内 **0 个 `__pycache__`／`.pyc`／`.brep`／`cache/`**、`git status` 空；`tools/comm_selftest.py --no-save` 在 main 上复跑 **rc=0、6/6 PASS**（确定性量与取证物逐位同值，计时量在抖动内）。

**① 完成标准六条（数字均为指挥方实测，⛔ 不取自报——04 §5.3）**
- **双进程跑通、读写日志对得上**：A～F 六节全 PASS；取证物 `evidence/T09/selftest.txt`（**5684 字符**）已扫「通裕／通裕重工／GXTC／GXTC-A1-26170051／招标／甲方／重工／tongyu」→ **CLEAN**（R-9.4 与取证入库边界合规）。
- **段长实测 56 B**：`struct.calcsize(">4B8f4f1i")`＝56，整批 **560 B＝10×56**；未驱动轴位与第 3–10 段（448 B）全 0；逆运算解回 `(120.0, 30.0, -15.0, 0.0, 45.0, 10.0, 0.0, 0.0)`。指挥方复跑同值。
- **回读频率 ≥20 Hz**：60 s 窗口收 **1199 帧**，OLS 斜率 **20.0103 Hz**；服务端自计（只用服务端钟、不经推送）**1200 周期／60.000 s → 20.0000 Hz**、扫描落后 **0 次**。
- **断 simulator 进程 → 5 s 内判离线并回调**：实测 **4.58 s**（指挥方复跑 4.55／4.50 s），回调序列 `['stale','offline']`；降级期 `last_frame` **原样保留、不外推**（W-5.7 合规，`test_buffer_refuses_to_extrapolate_and_reset_keeps_watchdog_hungry` 承重）。
- **节点全部符号名访问＋改点表零改码**：F 节以 14 组改名点表（`DB_Auf`／`DB_Ab`＋德文键名）复跑，**代码零改动**握手到 ST_DONE；`test_code_contains_no_plc_symbol_literals` 用 AST 扫全部 `comm/**/*.py`，无 PLC 符号字面量。
- **commit 标题**：`feat(T09): OPC UA 桥与模拟器` 逐字相符。

**② G17 扩表落地核记（本单代 T03 改三处，授权与凭据见 04 §7.2-G17）**
落地：`read_nodes` ＝ `axis_pos[8]／axis_vel[8]／status／heartbeat／ack／alarm_word／seq_id／cur_seg`（**8 键**）、`write_nodes` ＝ `cmd／seq_id／seg_count／speed_override／seg_array`（**5 键**）；顶层键集未变（`machine, axes, modes, links, limits, opcua, paths`）；`publish_interval_ms` 仍 50。`machine.yaml` diff 两个 hunk 全落在 `opcua:` 节内（其余各节零改动，越界检查通过）。
四条硬约束逐条复测（均为指挥方独立探针，非读代码）：
1. **新键必填**——逐个删 7 个新键 → 全部 `ConfigError` 且带具名细节行（`axis_vel` → "应为非空 NodeId 字符串数组，实得 None"；其余六键 → "缺必填字段或应为非空字符串，实得 None"）。
2. **`axis_vel` 同受 `PACK_PROFILE_AXIS_COUNT` 约束**——`axis_vel` 给 7 个／9 个均拒；`axis_pos` 给 7 个拒并引契约 §5.2 `Pos[]`；**两键同时给 7 → 分别报两行**（`loader.py` 的 `_PROFILE_ARRAY_NODES` 双键循环）。
3. **`tests/test_config.py` 24 用例全绿且断言未改**——该文件 **T09 侧零改动**；`ILLEGAL` 表七个 `bad_*` 的「共 N 项问题」计数全部维持；8 个 fixture 均为 **+10／−0**（只加 `opcua:` 键、零删行）。
4. **`lint_no_magic.py` 判定规则未动、`config_check.py` 只读**——两文件 T09 侧零改动；`validate.py`／`core/config/__init__.py` 亦零改动。**未改 `validate.py` 的理由经核为真**：`_nodes()` 按 SPEC 遍历并对缺键通用报错，故只扩 SPEC 即令新键必填，无需另加校验分支。

**③ 三项自报偏离——裁定：接受（语义未松）**
- **回读频率判据由「10 s 计数」改为「60 s 窗口＋OLS 斜率＋量具容差 `HZ_RESOLUTION`」**：**20 Hz 阈值本身未下调**（`MIN_HZ = 20.0` 原值），只减了 0.01 Hz 的量具分辨率容差。指挥方以**负控**证明判据非恒绿：把 `CONFIG` 换成 `publish_interval_ms: 60` 的临时 yaml、窗口缩到 20 s（`MIN_HZ`／`HZ_RESOLUTION` 不动）→ 收 335 帧／20.187 s、斜率 **16.6642 Hz**（服务端自计 200 周期／12.015 s → 16.6459 Hz）、**B＝FAIL、rc=1**；估计量无偏（16.667 处 −0.0025 Hz、20.0 处 −0.0002 Hz）⇒ 排除附7 形态①（阈值被数据架空）。
- **`OFFLINE_AFTER_S` 由 5.0 收紧到 4.5**：**验收判据仍是 `< 5.0 s`**（`test_offline_is_judged_within_5s` 断言原样、`comm_selftest.py` 的 `OFFLINE_LIMIT_S = 5.0` 原样），只收紧实现常量——因判离线条件是 `age > 阈值` 且每 `WATCHDOG_TICK_S=0.1` 轮询一次，取 5.0 必然落在 5 s 之外，判据不可达。理由已写进代码常量旁。
- **文件拆分**：`comm/opcua_client.py` 实测 **536 行**超 §4.5-① 的 300 行上限，按派单卡预授权拆为包 `comm/opcua_client/`（六件）。附4 以**卡面口径 `wc -l`** 复核：最大件 `tools/comm_selftest.py` **300 行**（正好压线）、`test_opcua.py` 299、`validate.py` 297、`simulator.py` 277；AST 扫 36 个 py 文件、**260 个函数无一 >50 行**。

**④ 追认与程序性回填**
- **`comm/opcua_client/errors.py`＋`handshake.py`**：超出派单卡举例的四件（连接／订阅／写入／重连），但卡片要求的是**报备而非闭集**、且包本身已预授权；`__init__.py` docstring 已写明两件的补报理由（前者为断环、后者因握手与连接合一件时实测 340 行仍超限）⇒ **追认**。
- **`comm/virtual_motion.py`／`comm/plc_logic.py`／`comm/plc_nodes.py` 属预案外增件**：派单卡的代码粒度条款只预授权拆 `comm/opcua_client.py`，未授权拆 `comm/simulator.py`（404→322→277 行）。与 T05 的 `brep_cache.py` 同类 ⇒ **本次追认**，并划反扩边界：**追认只覆盖本轮已交付的三件，不构成"通讯侧可自由拆件"的先例**；后续任何新增源文件仍须派单前登记或收单时追认。
- **`tools/comm_selftest.py`／`comm_selftest_kit.py`** 落在卡片"自测脚本（放 `tools/` 或 `tests/`，新增文件名先报备）"授权内，且已登记进 `tools/README.md`。⚠️ 由此暴露 **`tools/README.md` 在 04 §4 矩阵中无登记归属人**（矩阵缺口），本轮已补行，口径＝**追加式归属登记表，各单只加自己那一行**。
- F 节换点表用的 `machine_swapped.yaml` 由 `tempfile.TemporaryDirectory()` 生成在**仓外**，未污染仓内（夹具纪律合规）。

**⑤ 遗留（不阻塞本单合并，均已登记 04 §7.2）**
- **G20-①｜`tools/config_check.py:57` 打印的节点表摘要已过期**：G17 扩表后仍硬编码旧键名，输出「回读节点：axis_pos 8 个、status、heartbeat；下发节点：cmd、seg_count、seg_array」，**漏 5 个读键＋2 个写键**。属显示层失真（校验本身通过、rc=0）。成因＝G17 硬约束 4 令本单不得动该文件，扩表的后果**无人被授权处置**。→ 待指挥方派活。
- **G20-②｜`publish_interval_ms` 无 CI 守卫**：绝对「≥20 Hz」判据只活在手动工具 `tools/comm_selftest.py`；pytest 侧只有 fixture 值（全 50）与 `bad_type.yaml` 的字符串 `"50"` 类型拒收 ⇒ **把它静默改成 60 时 pytest 仍全绿**。→ 建议归 T10（`e2e_smoke.py`）或加一条配置值守卫。
- **`HZ_RESOLUTION = 0.01` 的推导注释与实际散布不符**：注释称"＝两轮 60 s 实测散布（±0.002 Hz）的 5 倍"，但已公布的 60 s 斜率（19.9997／20.0003／20.0011／20.0103＋指挥方两次 19.9998）跨度 0.0106 ≈ ±0.005 ⇒ 实为**散布的约 2 倍，不是 5 倍**。**不构成架空**（负控差 3.3 Hz），但实测最小值只高出通过线 **0.0097** ⇒ 属**红闪（red-flake）风险，不是假绿风险**。因该注释在已合并业务码内，**指挥方不得自行改** ⇒ 登记遗留，建议改为 0.02 并订正推导，或维持原值并接受红闪风险。
- **契约 §4.3 与 ByteString 相抵**：契约称"字节序由 Server 自动转换"，而 `seg_array` 按单节点打包 ByteString 后对 Server 是**不透明字节串**、无法自动转换。本单选 **S7 原生大端**，已在 `comm/opcua_client/write.py` docstring 与收单汇报中声明，**未自行改契约**（合规）⇒ 登记为契约级遗留，待 `电Q-2`／契约 `Q-7` 回执后复定是否改结构化节点。
- **报告一处不实**：汇报把 `PACK_PROFILE_AXIS_COUNT = {...}` 列成本轮改动，diff 显示它是**上下文行（T03 既有）**。属 04 §5.3「不听自报」的又一例，不构成阻塞。
- `test_code_contains_no_plc_symbol_literals` 的 `banned` 只列 4 个 token（是抽样非穷举），但注入复测证明其非恒绿（见下），且 DB 名禁列已覆盖任何完整 NodeId 字面量 ⇒ 接受。

**⑥ 附7 形态②（假证据＝注入后 rc 不是 1）注入复测：三处全部 rc=1**
在 `git archive task/T09` 沙箱（基线 21 passed／rc=0）内：
1. `virtual_motion.py` 的 `if self.total <= 0.0 or elapsed >= self.total:` 删去后半 → **rc=1，3 failed**（含目标用例 `test_trapezoid_clamps_both_ends_and_never_extrapolates`，另两条为集成用例，属**覆盖更宽**非缺陷）；
2. `clamp_speeds()` 的 `min(seg.vel * ratio, limits.speed_max_mm_s)` 去掉钳位 → **rc=1，恰好 `test_clamp_takes_limits_from_config_not_literals` 失败**；
3. 向 `plc_nodes.py` 追加 `_FALLBACK_NODE = 'ns=3;s="DB_PLC_to_SW"."Pos[0]"'` → **rc=1，恰好 `test_code_contains_no_plc_symbol_literals` 失败**。
还原后 21 passed／rc=0。三处**均 rc=1（断言失败），无一次 rc=2（收集错误）** ⇒ 排除附7 形态②。
另：附7 形态③（缓存命中掏空下游契约）在本单无对应路径——`comm` 侧无缓存件；形态④（视口取向盲区）不适用（无 UI 交付）。

**⑦ 下游影响**
- **T10 可开工的前置已就绪**：模拟器支持注入异常（`--fault reject`／超时／断线），D 节已验证「装载被拒 → 客户端收到原因码 `0x0020`＝数据越界」。T10 写 `e2e_smoke.py` 时**须承接 G20-② 的 ≥20 Hz 守卫**。
- **`comm/opcua_client/` 包根 re-export 全量 API（约 70 个符号），断言在 `tests/test_opcua.py::test_package_root_reexports_whole_api`**，**未另建** `tests/test_public_api_opcua_client.py` ⇒ 与 T03／T04 的 `test_public_api_*` 命名惯例有一处不一致，属可接受偏离（同一断言强度，少一个文件）。
- **T09 交付用 `Frame`（未跟 T04 改名后的 `CoordFrame`）**：03 §3 签名行的**消歧条款已被本单遵守**（`Frame`＝时间戳＋各轴工程值，与 T04 的 `CoordFrame` 不是同一物），03 已同步核正为 `opcua_client/`。

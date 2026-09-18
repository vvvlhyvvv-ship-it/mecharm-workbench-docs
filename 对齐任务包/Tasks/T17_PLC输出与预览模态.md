# T17 PLC 输出区与预览模态（工步数据表＋变量映射）

## 目标
补上产品缺的「PLC 输出」能力：从已生成路径编排工步，预览＋导出工步数据表 CSV 与变量映射 CSV，ProcessStep 预算显示；SCL 骨架灰置。**纯离线输出，不碰通讯**——它是给电气方做 PLC 编程的数据交接物，与在线下发（T15）是两件事。

## 前置阅读
00 README §五纪律 ｜ 01 蓝图 **V1.2** §3.8 PLC 输出预览模态、**§6.3（口径最密的一节，含三串声明文案逐字原文）**、§4-B/C、**§7 Δ-4／Δ-5／Δ-6／Δ-7** ｜ 99 台账「文件归属矩阵」＋**L-8／L-9** ｜ 演示稿画面 05/09（`window.__MODAL_PLC__`＝HTML:706）｜ 现读 `core/path.py` 段结构（**只读**）、`config/machine.yaml` `opcua` 节点表（读写节点全表）、`config/ui.yaml`（`process_step_budget`，T12 已建）、`core/project.py`（**299/300，只读**）、`app/prog_tab.py`（T14 已收单版）、`core/config/schema.py`、`tools/lint_no_magic.py`

## 文件归属（唯一写者）
- 改：`app/prog_tab.py`（底部**追加** PLC 输出区挂载；T14 已收单后本单追加，⛔ 不改其已交付区）、`config/ui.yaml`＋`core/config/schema.py`（**只追加 §6.3 三串声明文案键**，波次 3b 内 ui.yaml 归本单）、`tools/e2e_tabs.py`（追加本单判据）
- 增件：`core/process.py`（工步编排纯函数层，**GUI-free：无 PySide6 import**）、`app/plc_out.py`（输出区＋预览模态 UI）、`tests/test_process.py`、`tests/test_process_export.py`
- ⛔ 禁改：`comm/**`（**本单零通讯**）、`core/path.py`（T15 域，只读其段结构）、**`core/project.py`（299/300，只剩 1 行余量 ⇒ 只可读其 API；需加函数先停下上报，L-8）**、`core/collision.py`（300/300）、`app/sim_tab.py`／`app/checkctl.py`／`app/steps/step4_check.py`／`view/js/collision.js`／`app/assemblytree.py`（**T16 并行域**）、`app/topbar.py`／`tabshell.py`（T13 已收单）、`app/theme.py`、`view/js/**`、`app/stepbar.py`

> **e2e 归属（L-2）**：本单判据追加到 `tools/e2e_tabs.py`；与 T16 并行时**后收单者 rebase**。

## 步骤
1. `core/process.py` 纯函数（**GUI-free，无 PySide6 import**；收单会核）：
   - `build_steps(segments, mode, start_no, speed_source) -> list[ProcessStep]`：`mode=by_segment`（默认，每运动段一工步）／`by_point`（逐点）；速度来源＝按轨迹算得（段速度）或字典上限（`limits`）；字段＝工步号/段号/动作名/X/Y/Z/速度/ProcessStep 序号/OPC UA 变量引用/备注
   - `variable_map(machine_cfg) -> list[VarRow]`：**只映射 `machine.yaml` 点表真实 NodeId**（读＋写节点各列一行）；⛔ **禁造 MasterLink／`J*.Command` 字样**（Δ-5，DEC-04 未决）
   - `budget(steps, limit) -> (used, limit)`：`limit` 读 `config/ui.yaml` 的 `process_step_budget`（T12 已建，默认 200，来源招标第 7 条 ≥200 工步），⛔ 禁在代码里写死
   - pytest：空路径/单段/多段/逐点/**超预算**各用例；超预算返回超限标记（UI 黄警示，**不禁导出**——如实呈现）
2. `config/ui.yaml` 追加 §6.3 三串声明文案键（**逐字照抄，⛔ 不得改写或缩写**；同步 `core/config/schema.py` 白名单，否则会被**静默丢弃**且不报错，L-9）：
   1. 顶部红条：「本输出为**供电气 PLC 编程使用的工步数据与变量映射**，不是我方交付的 PLC 程序。」
   2. 表下注：「ⓘ 各轴 **Position 为只读**；位置类指令需与 PLC 侧另行约定。本输出供 PLC 侧编程使用，**不含联锁保护逻辑**。」
   3. 页脚注（同串变体，首词多「字典中」）：「ⓘ 字典中各轴 **Position 为只读**；位置类指令需与 PLC 侧另行约定。本输出供 PLC 侧编程使用，**不含联锁保护逻辑**。」
   - ⚠️ V1.0 曾把第 2 条缩写成「各轴 Position 为只读；本输出不含联锁保护逻辑」——**漏了「位置类指令需与 PLC 侧另行约定」这半句**，而它正是「我方不承诺联锁」的免责要点，⛔ 不得再缩写；三串**不得合并为一个键复用**（第 3 条首词确与第 2 条不同，演示稿即两串）
3. `app/plc_out.py` 输出区（编程页签底部，演示稿 05 布局）：①输出内容开关（工步数据表 CSV ✓／变量映射表 CSV ✓／**SCL 程序骨架——禁用＋「待电气方确认后开放」**，Δ-7）②工步编排（编排方式下拉**实做**；**弦高容差/掉头保护两输入框禁用＋「待定」**——未定口径⛔禁假装生效）③「生成/预览/导出 CSV/复制」④汇总行（已生成 N 工步 · 变量映射 M 条 · ProcessStep 预算 N/200（百分比），超限黄）
4. 预览模态（演示稿 09，圆角 8px＝§4-C 模态档）：顶部红色用途声明条**两行**（步骤 2 的第 1、2 串，读 ui.yaml）＋KPI 行（工步数/变量条数/预算/编排方式）＋**工步表 10 列**（工步/段号/动作/X/Y/Z/速度/ProcessStep/OPC UA 变量/备注）＋页脚（导出 CSV/复制/关闭，含第 3 串页脚注）；**「备注」列凡速度推算处固定「估算值」**（口径铁律 2）
5. CSV 导出：**UTF-8-BOM**（Excel 可读）；文件名＝〈工程名〉_工步数据表_〈时间戳〉.csv／_变量映射_.csv；导出路径记忆到工程文件（**走 `core/project.py` 现成 API，⛔ 禁改该件**）；**预览与导出数据同源**（同一 `build_steps` 结果，⛔ 禁各算一遍）
6. 未生成路径时输出区**整体禁用**＋「先在上方生成轨迹」提示；工步数据随路径失效机制联动（路径改动→工步作废重生成提示）

## 完成标准
- [ ] `core/process.py` 纯函数 pytest 全绿（贴原始输出）；**GUI-free 检查**：贴 `grep -n "PySide6\|Qt" core/process.py` 输出为 0 命中（收单核）
- [ ] 预览模态截图对照演示稿画面 09（**取证档启动**；差异＝SCL 禁用、无 MasterLink 字样、弦高容差/掉头保护禁用）贴 evidence/T17/
- [ ] **三串声明文案逐字核对**：贴 ui.yaml 内三键的值＋界面截图，与 §6.3 原文逐字一致（**特别核第 2/3 串含「位置类指令需与 PLC 侧另行约定」**）；三串在界面上各自出现的位置正确
- [ ] 变量映射内容与 `machine.yaml` 点表**逐行一致**（贴对照输出：节点数、读/写各几条、抽 3 行逐字比对）；⛔ 全仓 grep 无 `MasterLink`／`J1.Command` 字样（贴输出）
- [ ] 导出的两个 CSV：贴前 5 行原文＋**确认 BOM 在场**（如 `xxd | head -1` 或等价证明）；Excel 可读样张贴 evidence/T17/
- [ ] 预算超限场景黄警示截图＋**仍可导出**（贴输出）
- [ ] 未生成路径时输出区整体禁用（截图）；路径改动后工步作废提示在场（截图或 e2e 判据）
- [ ] `wc -l` 报数：`core/process.py`／`app/plc_out.py` 各 ≤300、`app/prog_tab.py` 追加后 ≤300（贴全部数字）；**`core/project.py`／`core/path.py`／`core/collision.py` diff=0**（贴 `git diff --stat` 证明）
- [ ] ui.yaml 新键真的生效（**不是被白名单静默丢弃**）：贴 `tools/config_check.py` rc=0 ＋一条「界面读到该键」的测试或运行输出（L-9）
- [ ] pytest 全绿；`tools/lint_no_magic.py` rc=0；e2e 增「生成→预览→导出」判据 rc=0——**均贴原始输出**，不得只写「已通过」
- [ ] commit：`feat(T17): PLC 输出区与预览模态`

## 禁止事项
- 🔴 禁造 `MasterLink.ProcessStep`／`J*.Command` 等字典数据（Δ-5，DEC-04 未决）；禁实现 SCL 生成；**禁把「估算值」标成实测**
- 禁碰 `comm/`（本单零通讯）；禁改 `core/path.py`（T15 域，只读其段结构）；**弦高容差/掉头保护禁做成生效参数**
- ⛔ 禁改 `core/project.py`（299/300，L-8）；禁改 T16 并行域（`app/sim_tab.py`／`app/checkctl.py`／`view/js/collision.js`／`app/assemblytree.py`／`app/steps/step4_check.py`）
- ⛔ 禁在代码里写死预算上限、声明文案、文件名模板（全走 ui.yaml／配置）；禁改写或缩写三串声明文案；禁自造未预声明的新源文件名
- ⛔ 上屏禁出现 NodeId 明文之外的内部编号（TXX/GXX/电Q-x，§1-5）；禁造演示数字（24 工步／42.6s 等，Δ-6）

## 收单记录（指挥侧回填）

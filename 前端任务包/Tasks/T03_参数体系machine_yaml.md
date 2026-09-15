# T03 参数体系 machine.yaml

## 目标
实现 03 架构 §4 的参数加载与校验：`config/machine.yaml` 一份样例 + `core/config.py` 强校验加载器。**界面零硬编码的前提就是这单。**

**2026-09-15 口径扩充（G11 已定，随 CR-2026-03）**：样例轴表按**实机 22 个受控运动轴**建（不再用"桁架+三关节臂"占位样例——契约 §5/§7 的轴名与实机不符，见 04 §7.2-G11）；样例须体现三类结构要求：①轴分**轨迹级联动轴**与**工序级设定轴**（`role` 字段）；②**工作模式→轴子集**映射（`modes`，快接换臂）；③**X3 倍速链 1:2** 用 `coupling{type: ratio}` 显式表达。

## 前置阅读
03 架构 §4（含"实机轴系口径"块）｜ S-1 契约 §4.1+第 5/6 章（数据块布局）、附录 A（轴清单）｜ 规程 W-4.1 ｜ 04 §7.2-G11（22 轴清单与裁决口径）

## 步骤
1. 写 `config/machine.yaml` 样例：
   - **axes**：按实机 22 轴建（X1／Z1／YA~YE／Y1／X2／Z2／X3／ZA1·ZA2·RA／ZB·FB1·FB2／ZC·FC·RC／ZD·KE），每轴含 id/type/`role: trajectory|setup`/travel/zero_offset/direction/scale/coupling；行程、零点、正方向**以电气·机械回执为准**，回执前逐轴标 `pending: true` 占位
   - **modes**：五种工作模式（打磨／氧化皮吸附／脱模剂喷涂／氧化皮破碎／玻璃垫放置）→ 各自有效轴子集（本体 6 轴 X1/Z1/Y1/X2/Z2/X3 ＋ 所挂臂专用轴，上限 9）
   - **coupling**：X3 标 `{type: ratio, master: 二级筒轴, ratio: 2}`（三级筒位置 = 主动轴 × 2）；龙门双驱类同步轴用 `{type: sync, group, sync_tol_mm}`
   - **limits**：含 `collision_envelope_mm`（T08 保守包络用）与 `tessellate_deflection_mm`（T05 弦高容差用），初值按 03 §4 口径配置
   - links、opcua 节点表（节点 ID 按 S-1 契约 DB 布局自造，标注"模拟期占位，Q 回执后改此文件"）
2. `core/config.py`：`load_machine(path:str)->MachineConfig`，dataclass 定型；缺字段/类型错/行程 min≥max/direction 非 ±1 → 抛 `ConfigError` 且消息列出**全部**问题项；**`pending: true` 的轴只告警不拒绝**（回执前允许带着占位跑仿真，告警列出全部待回执轴）
3. `tools/config_check.py` 命令行校验器（现场排障用）：`python tools/config_check.py config/machine.yaml`
4. pytest：合法样例过；6 类非法样例逐项拒（tests/fixtures/ 造）；**pending 占位轴告警用例**（告警列出轴名、不抛错）；**modes 子集校验用例**（模式轴子集必须 ⊆ axes 且轨迹级轴计数 ≤9）；**ratio 耦合校验用例**（ratio>0 且 master 必须存在于 axes）

## 完成标准
- [ ] 合法样例加载成功且字段可访问（贴 REPL 输出）
- [ ] 非法用例 6/6 报错且消息含字段名
- [ ] 22 轴样例带 role/modes/ratio 耦合；pending 占位轴告警列出、不拒绝启动
- [ ] grep 全仓无轴参数魔法数字（travel/offset 只存在于 yaml；此后每单验收常驻复查，见 99 验收流程）
- [ ] commit：`feat(T03): 参数体系`

## 禁止事项
- 字段名/结构以 03 架构 §4 为准，禁自增删字段；yaml 里禁写注释之外的中文键名
- 禁把契约 §5.2 的 8 轴上界或 J1~J6 轴名当实机口径（实机 22 轴，见 G11；契约扩容随契约 V1.3 窗口，软件侧只改本文件）

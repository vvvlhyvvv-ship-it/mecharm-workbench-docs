# T03 参数体系 machine.yaml

## 目标
实现 03 架构 §4 的参数加载与校验：`config/machine.yaml` 一份样例（桁架+三关节臂，与 S-1 契约 §5/§7 轴定义对齐）+ `core/config.py` 强校验加载器。**界面零硬编码的前提就是这单。**

## 前置阅读
03 架构 §4 ｜ S-1 契约 §4.1+第 5/6 章（数据块布局）、附录 A（轴清单）｜ 规程 W-4.1

## 步骤
1. 写 `config/machine.yaml` 样例：axes（含 travel/zero_offset/direction/scale/coupling）、links、limits、opcua 节点表（节点 ID 按 S-1 契约 DB 布局自造，标注"模拟期占位，Q 回执后改此文件"）
2. `core/config.py`：`load_machine(path:str)->MachineConfig`，dataclass 定型；缺字段/类型错/行程 min≥max/direction 非 ±1 → 抛 `ConfigError` 且消息列出**全部**问题项
3. `tools/config_check.py` 命令行校验器（现场排障用）：`python tools/config_check.py config/machine.yaml`
4. pytest：合法样例过；6 类非法样例逐项拒（tests/fixtures/ 造）

## 完成标准
- [ ] 合法样例加载成功且字段可访问（贴 REPL 输出）
- [ ] 非法用例 6/6 报错且消息含字段名
- [ ] grep 全仓无轴参数魔法数字（travel/offset 只存在于 yaml；此后每单验收常驻复查，见 99 验收流程）
- [ ] commit：`feat(T03): 参数体系`

## 禁止事项
- 字段名/结构以 03 架构 §4 为准，禁自增删字段；yaml 里禁写注释之外的中文键名

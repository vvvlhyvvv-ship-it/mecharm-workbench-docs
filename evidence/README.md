# evidence/ — 验收取证物

各单验收截图与实测留痕，按单分子目录（`evidence/T02/`、`evidence/T05/` …），合并零冲突。

## ⛔ 入库边界（硬要求，不是建议）

`origin` 指向的远端仓 **实测为公开仓**（2026-09-15 未认证访问 GitHub API 得 `private=False`，见 04 §7.1-10）。因此：

**允许入库**：自造／示例模型截图、本机日志、命令输出、界面截图等**不含甲方数据**的取证物。

**一律不得入库**：甲方真实 STEP／图纸／模型截图，含甲方名称或工件尺寸的画面。
需留痕时改为**文字说明**：`文件名 ＋ SHA256 ＋ 留存位置（本机路径）`。

同类边界：`.brep` 几何真身／轻量化网格／离线资产库属**缓存**，默认落仓外 `paths.cache_dir`（默认 `%LOCALAPPDATA%\mecharm\cache`），**禁落仓内**；`.gitignore` 已加 `cache/`、`data/`、`*.brep` 作双保险。

## 自查命令（各单验收时跑）

```bash
git -c core.quotepath=false diff --name-only main...task/TXX -- evidence/
```

新增文件**逐个确认**是否含甲方数据。⚠️ 必须带 `-c core.quotepath=false`，否则中文路径被转义，检查会假通过。

---

本目录当前**仅有此占位 README，无任何取证物**（T01 完成标准之一）。

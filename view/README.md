# view/ — 前端视口层

三维视口与交互脚本的归属目录。运行期**禁止任何 CDN 引用**，第三方件一律 vendored 到 `view/vendor/`。

| 路径 | 唯一写者 | 说明 |
|---|---|---|
| `index.html` | T02 | 只放骨架与 `<script>` 注册行；样式一律进 `css/app.css`，禁在 HTML 里堆 `<style>` |
| `js/loader.js` | T05 | 模型加载与分批推送 |
| `js/pick.js` | T06 | 面拾取 |
| `js/path.js` | T07 | 路径与动画 |
| `vendor/**` | T01 建目录与 `three.module.js`；他人新增须先报备 | 第三方打包件，不受单文件 300 行限制，**不得手工编辑** |

依据：04 §4 文件归属矩阵、04 §4.5-④ 白名单、03 §8 组件准入清单。

## vendor 已落盘件与来源留痕

| 文件 | 版本 | 来源 | 字节数 | SHA256 |
|---|---|---|---|---|
| `vendor/three.module.js` | **r160（0.160.1）** | `https://cdn.jsdelivr.net/npm/three@0.160.1/build/three.module.js`（另以 `https://unpkg.com/three@0.160.1/build/three.module.js` 交叉校验，**两源字节逐字一致**） | 1,272,972 | `76dea8151bc9352aef3528b4262e249b2604f62543828328db978d060d61a495` |

许可证 MIT（文件头 `@license` 声明「Copyright 2010-2023 Three.js Authors」），03 §8 准入清单已登记 ✅ 本地分发。

### ⚠️ 表中 SHA256 的准确语义与换行转换风险（T01 实测）

**表中 SHA256 ＝ 上游原件字节 ＝ 入库 git blob 字节 ＝ 本单落盘时的工作树字节（三者实测同一值）。**
但本机 Git **系统级**配置 `C:/Program Files/Git/etc/gitconfig` 里 `core.autocrlf=true`，而本单落盘时仓内**尚无 `.gitattributes`**（现已补，见下），故存在两种形态：

| 形态 | 字节数 | SHA256 |
|---|---|---|
| 入库 blob（LF，= 上游原件） | 1,272,972 | `76dea8151bc9352aef3528b4262e249b2604f62543828328db978d060d61a495` |
| **加 `.gitattributes` 之前** checkout 出的工作树文件（被转 CRLF） | 1,326,016 | `c6eacae1ec5fd832160227ca7441311c8b30dee0419af87954fb9df6d105bf1f` |

**已处置（2026-09-16 @user 批准）**：仓根已新增 `.gitattributes`，内容 `view/vendor/** -text`，
对 vendor 目录关闭换行转换。故**现在 checkout 出的工作树文件与入库 blob 逐字节一致，表中 SHA256
可直接用于校验工作树文件**，CRLF 那一行只作为"若 .gitattributes 被误删会出现什么"的对照留档。

不依赖 `.gitattributes` 的兜底校验法（比 blob，不比工作树，任何时候都成立）：

```bash
git cat-file blob HEAD:view/vendor/three.module.js | sha256sum   # 应得上表 LF 那一行
```

### ⚠️ 升级 three.js 前必读（T01 实测约束）

任务单口径是「落一个 `three.module.js`」，而**新版 three.js 的单文件形态已不成立**：实测 `three@0.186.0` 的 `build/three.module.js`（662,772 B）内含 `import ... from './three.core.js'`，**只落这一个文件会在运行期缺模块报错**；`three@0.160.1` 的 `build/three.module.js` **自包含、无任何相对 import**（`REVISION = '160'`）。

故本仓选 **r160**（满足卡内「r160+」下限且为单文件）。若日后要升到更高版本，**必须同时 vendored `three.core.js`**——属新增 vendor 文件，按 04 §4 矩阵须**先报备后落盘**。


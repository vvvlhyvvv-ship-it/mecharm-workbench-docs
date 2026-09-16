# evidence/T06 — 视口自测（320×500 竖幅）与标号牌/列表不越界（2026-09-16）

自测环境：`python -m http.server 8765 --directory view`（系统 python，仅静态服务）＋ in-app 浏览器
（browser-use MCP）打开 `http://localhost:8765/index.html`。index.html 未注册 pick.js（合并时由指挥方
加 `<script>`），故自测以 `document.createElement('script'); s.type='module'; s.src='js/pick.js'`
动态注入，等价于合并后的注册顺序（bridge→loader→pick）。

⚠️ **两处取证局限（如实登记，不以截图冒充）**：
1. **视口截图不可用**：in-app 浏览器 `viewport=0x0, visibilityState=hidden`，`take_screenshot` 报
   `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`。故「标号牌不越界」以**逐标号牌 DOM 像素坐标**为证（下表），
   比截图更精确；未贴横屏截图。
2. **Qt 离屏抓图中文为豆腐块**：`QT_QPA_PLATFORM=offscreen` 无 CJK 字体，`step2_list_*.png` 文字呈
   □。布局/越界以**数值**为证（horizontalScrollBar.maximum=0、末列右缘==viewport 宽）；文字内容另以
   打印串（模式行/名称/序号）为证。

## A. 标号牌在 320×500 竖幅内不越界（完成标准 8 / 关键点：CENTER_MIN=320）

`#scene-host` 设 320×500 后注入 pick.js，`mesh.load`(box 20×12×8)＋`pick.enable` 推 3 标号牌：

| 标号牌 | left | top | fontSize | 在 [0,320]×[0,500] 内 |
|---|---|---|---|---|
| 1 P1 | 127.5px | 251.1px | 18px | true |
| 2 P2 | 212.2px | 248.2px | 18px | true |
| 3 P3 | 205.3px | 387.7px | 18px | true |

改 P1 世界坐标 [0,0,0]→[0,12,8] 后重推 pick.enable：left 127.5px→**50.6px**（top 251.1→161px），
**标号牌跟随坐标**（完成标准 1 的视口侧）。`invalidate` 后标号牌 DOM 计数=**0**、cursor 回 default
（完成标准 4：F3 作废含视口标号牌）。

## B. 左键取点回传 pick.face，且与 core 换算闭环（完成标准 1 的取点侧）

stub `window.bridge.on_view_msg` 捕获 3 次左键点击（160,250 / 120,200 / 200,300）：

```
{mesh_id:1, face_id:10, u:0.05935591181165263, v:0.20319572176300085}
{mesh_id:1, face_id:10, u:0.4873825637309023,  v:0.010861984623177503}
{mesh_id:1, face_id:11, u:0.04637462779408565, v:0.33322916056010704}
```

将上述载荷逐条喂 core `face_point_from_tri`（同一 box）：三点均落 z=8.0（顶面）、真法向 [0,0,1]、
brep_face=6、onSurface=True —— 证明 pick.js 的 face_id（三角形序号）与 u/v（u=bc.y、v=bc.z）口径与
core 完全一致，前端→core 闭环成立。

## C. 手势分离（关键点 3：左键取点、右键旋转不抢）

| 手势 | 相机是否旋转（以标号牌 P2 位移判定） |
|---|---|
| 右键拖拽 (button=2, Δ=50,50) | 旋转：212.2/248.2 → **66.5/465.6** |
| 左键拖拽 (button=0, Δ=50,50) | **不旋转**：仍 66.5/465.6（pick 捕获阶段 stopPropagation，loader 未收到 pointerdown） |

左键拖拽位移 ≥4px 亦不触发 pick.face（CLICK_SLOP_PX 防误触）。

## D. 右栏点位列表窄宽不越界（完成标准 8 的列表侧）

`_render_step2.py`（offscreen）渲染 Step2Pane，`set_mode("多功能臂A")`＋3 点位（含 1234.567 等宽坐标
压力值）＋1 重复面（face_2，应被去重）：waypoint 数=**3**（重复面未加）、序号 [1,2,3] 不重排、
模式行「当前：多功能臂A」。

| 面板宽 | table.viewport 宽 | 各列宽 | horizontalScrollBar.maximum | 末列右缘==viewport | 越界 |
|---|---|---|---|---|---|
| 280（面板最小宽） | 246 | [28,35,34,34,34,81] | **0** | 246==246 | False |
| 360（默认） | 326 | [28,55,54,54,54,81] | **0** | 326==326 | False |

抓图：`step2_list_280x500.png`、`step2_list_360x500.png`（中文豆腐块见上文局限 2）。

## E. 自测中发现并修复的缺陷（render-spy 失效）

初版 pick.js 用「包裹 `THREE.WebGLRenderer.prototype.render`」观察 loader 的 scene/camera。实测
（three r160 vendored）：`new THREE.WebGLRenderer()` 后 `Object.getOwnPropertyNames(inst)` **含**
`render` 且 `inst.render !== WebGLRenderer.prototype.render` —— 实例的 render 是构造函数里赋的**自有
闭包**，原型包裹对已建实例**完全不触发**；又 `import * as THREE` 命名空间导出只读，无法替换构造函数。
⇒ 标号牌永不投影、raycast 拿不到相机（自测时标号牌 left/top 恒 0px 暴露此缺陷）。

修复（仍**不改 loader.js**，仅改本单自有 pick.js）：改挂 loader 每帧/每载入必经、且确为**原型继承**
（实例不自有）的两个 `Object3D` 方法——`render()` 末尾的 `camera.lookAt` 捕获活动相机、`onMeshLoad`
的 `group.add(mesh)` 捕获 `scene`(=group.parent)；仅观察、原方法照旧 `apply`。无 renderer 句柄需重绘时
派发 `resize` 借 loader 自身 `resize()→render()` 出一帧。`updateMarkerPositions` 内自行刷新
`camera.matrixWorld/matrixWorldInverse`（lookAt 在 renderer.render 之前触发）。修复后 A/B/C 全部通过。

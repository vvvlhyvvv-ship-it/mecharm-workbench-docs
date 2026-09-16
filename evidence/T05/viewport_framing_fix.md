# T05 整改-2 取证：视口按 aspect 取景（flyTo/fitAll 不裁切）

## 缺陷（整改前）
`view/js/loader.js` `flyTo(box)` 旧式 `orbit.radius = max(box.getSize().length()*1.4, 1)`
只按外接盒对角线适配**竖直** 45° FOV，无视 `camera.aspect`。竖窄视口（aspect<1）水平视场更窄，
模型被左右切到贴边。指挥会话实测：431×625 → `bbox x1=430=w−1`（右缘列 217 前景像素齐平顶竖直裁切）；
软件自身最小中部视口 320×500（`app/shell.py` `CENTER_MIN=320`、`setMinimumSize(...,600)`）→ `bbox x1=319=w−1`。

## 整改
按外接球半径分别算竖直/水平所需距离取较大者：
`tan(半水平FOV)=aspect·tan(半竖直FOV)`，`dist=sphereR/sin(halfFOV)`，`orbit.radius=max(distV,distH)*1.06`
（横屏归竖直、竖屏归水平，两向都不裁切，6% 余量保证四边不贴边）。

## 实测（自造装配样件，非甲方模型；http.server + 浏览器内 render→drawImage→getImageData 同任务回读）
判据：`fitAll`/`flyTo` 后前景像素包围盒四边均不触边（`x0>0`、`x1<W−1`、`y0>0`、`y1<H−1`）。
前景＝与底色 `#16202a`(22,32,42) 任一通道差 >12 的像素。

| 视口(请求) | canvas W×H | aspect | x0 | x1 | y0 | y1 | 触左 | 触右 | 触上 | 触下 | 前景像素 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 320×500（软件最小中部视口） | 320×500 | 0.64 | 46 | 295 | 141 | 377 | 否 | 否 | 否 | 否 | 40031 |
| 431×625（指挥复现竖屏） | 431×625 | 0.69 | 63 | 398 | 168 | 484 | 否 | 否 | 否 | 否 | 71878 |
| 625×431（横屏对照） | 625×431 | 1.45 | 168 | 500 | 82 | 388 | 否 | 否 | 否 | 否 | 67186 |

三档全部四边不触边；竖屏宽度填充约 78%（x 跨 249/320、335/431），既未裁切也未过度缩小。
整改前同两竖屏 `x1=w−1`（触右）→ 整改后 `x1=295<319`、`x1=398<430`，缺陷消除。

> 测量技法（指挥会话指明）：WebGL canvas 无 `preserveDrawingBuffer`、headless 下 `take_screenshot` 取不到；
> 但在**同一 JS 任务**内 render 后立即 `drawImage(canvas)`+`getImageData` 可靠。本取证即此法。
> 样件由 `tests/cad_samples.assembly_step` 现场生成（自造几何，不含甲方名称/工件尺寸，符合 evidence/README 入库边界）。

// view/js/collision.js — 校核结果的视口投影（T08；T16 增红色脉冲圈＋干涉高亮条）。
//
// 职责（02 §2 步骤④）：顶部报警条＋干涉点标记＋臂侧代理盒线框＋点击列表行定位——三通道里的
//   **视口那一半**（另一半＝右栏三态卡，app/steps/step4_check.py）。
// 红线（04 §7.2-G13／G14 ①）：本文件**只做显示**——不算距离、不做判定、不存真值；三态字面与几何
//   坐标全由 core.collision 经壳推来，收到什么画什么，⛔ 禁复算或"修正"结论。
// ⚠️ G19：报警条**只在预警／干涉时出现**、通过态不挂任何"未检出碰撞"字样（覆盖面限定由右栏 `coverage()` 常显承担）。
// ⚠️ 不动 loader.js／pick.js／path.js（04 §4 归属：三者他单权限＝—）：scene/camera/renderer 都是
//   loader 模块私有。沿用 path.js 手法从外部**观察** scene（包裹 `Object3D.prototype.add`、原实现
//   照旧 apply）；本文件**不自己出帧**——重绘派发 `resize` 借 loader 的按需渲染。障碍侧高亮**不自己
//   染色**，向内层分发器合成 loader 的 `hl.set {semantic, focus:true}` ⇒ 只有一套口径，⛔ 两处不打架。
//
// 载荷口径（全 ASCII：`app/bridge.py` 用 ensure_ascii=True 投递 ⇒ 桥里**没有**中文点名与原因；
//   部件名由本文件从 loader 已建 mesh 的 `userData.name` 自取，人话句子在视口侧拼装）：
//   collision.show  {level, cases:[{seg:int, arm:str, obs:int, dist:float, point:[x,y,z], box:[6]}]}
//   collision.focus {index:int}      // 右栏列表点击行 → 放大该条标记＋障碍侧按三态语义高亮＋相机飞到
// T16（干涉体系）：**零 payload 扩展**——脉冲圈与高亮条数据全来自上述既有六键（同 T15 path.js 零
//   diff 先例）；⛔ 未新增 dispatch type。①红色脉冲圈＝**DOM 合成层动画**（CSS @keyframes，⛔ 不进
//   three 渲染循环——fps 芯片＝path.js 的 rAF 实测帧率，不因脉冲掉帧）；标记球 onBeforeRender 把干涉
//   点投影成屏幕坐标（视角不动＝按需渲染＝位置本就不变）；蓝图 §1-11 动效开关：--motion=0（外壳经
//   runJavaScript 推送）或系统 prefers-reduced-motion ⇒ 静态红环（信息不丢）。②高亮条＝视口**底缘**
//   （蓝图 §3.5）＝最危险一条（cases[0]）；「定位」按钮内部调 onFocus({index:0})。
// 报警条/高亮条样式走**元素内联**（app.css 属 T05、新选择器须指挥方合并时统一加，本单不自改）。

import * as THREE from "../vendor/three.module.js";

const COLOR_DENY = 0xb3261e;      // 干涉：deny 红（＝ loader SEM.deny ＝ app.css --deny，同一口径）
const COLOR_WARN = 0xd9a520;      // 预警：warn 黄（同上）
const DOT_OPAQUE = 0.95;          // 常态／定位中标记球的不透明度
const DOT_DIM = 0.35;             // 未定位的其余标记压暗（多处时一眼看出选的是哪条）
const WIRE_DIM = 0.45;            // 同上，代理盒线框的压暗不透明度
const MARKER_RAD_MM = 14;         // 干涉点标记球半径（自造基本体尺寸，非机台参数）
const FOCUS_SCALE = 1.9;          // 定位时标记放大倍数
const RENDER_ORDER = 20;          // 标记／线框压过实体：干涉点常在工件内部，不穿透就看不见
const MAX_BANNER_CASES = 3;       // 报警条最多逐条列出几处，其余归到"另有 N 处"（条子不能糊满视口）
const BOX_DIM = 3;                // box 前 3 元素为下界、后 3 为上界（与 core.collision 同口径）
const PULSE_CSS = "@keyframes collPulse{0%{transform:scale(.5);opacity:.95}75%,100%{transform:scale(1.8);opacity:0}}" +
  ".coll-pulse{position:absolute;pointer-events:none;border:3px solid #ff4d4d;border-radius:50%;width:56px;height:56px;margin:-28px 0 0 -28px;animation:collPulse 1.2s ease-out infinite}.coll-pulse.static{animation:none;opacity:.85}";

let scene = null;                 // 由 proto.add 钩子观察自 loader.js（见 installSceneHook）
let group = null;                 // 本文件全部显示对象的容器（挂 scene 下，不进 loader 的 group）
let banner = null;                // 顶部报警条（DOM，挂在 #scene-host 上）
let styleEl = null;               // 脉冲圈动画的 <style>（只注入一次）
let pulseLayer = null;            // 脉冲圈层（DOM 容器；子元素与 deny 级 cases 同序）
let hlBar = null;                 // 视口底缘干涉高亮条（DOM）
let marks = [];                   // [{dot, box, obs}]，与 collision.show 的 cases 同序（列表行号＝下标）
let focused = -1;
let inner = null;                 // 内层分发器（path.js 的包裹函数）：hl.set 直接投给它，不重入本文件
let view = null;                  // {renderer, camera}——首个标记 onBeforeRender 时捕获（path.js 手法）

// 链式包裹 proto.add 观察 scene（pick.js／path.js 各包过一次，本文件叠在最外、原实现照旧 apply）。
// 触发时机：步骤①导入模型时 loader 的 group.add(mesh)（group.parent＝scene）必经 ⇒ 校核前必已就位。
function installSceneHook() {
  const proto = THREE.Object3D.prototype, origAdd = proto.add;
  proto.add = function (o) {
    const found = this.isScene ? this : (this.parent && this.parent.isScene ? this.parent : null);
    if (found) scene = found;
    return origAdd.apply(this, arguments);
  };
}

// 借 loader 自己的 resize()→render() 出一帧（本文件不持 renderer，重绘只此一条路）。
function forceRender() { window.dispatchEvent(new Event("resize")); }

// 图层只建一次并常驻 scene（loader 清场不摘其它子节点）；已建过也须返回 true，否则二次校核会误走
// "场景未就绪"分支、一处标记都画不出来。
function ensureGroup() {
  if (!scene) return false;
  if (!group) {
    group = new THREE.Group(); group.name = "collision-layer";
    scene.add(group);
  }
  return true;
}

// --- collision.show：三态 → 报警条＋标记（整体重建；前端不存真值，只投影）------------------
function onShow(payload) {
  const level = (payload && payload.level) || "clear";
  const cases = (payload && payload.cases) || [];
  clearMarks();
  if (level === "clear" || !cases.length) {
    setBanner(null, ""); setHighlight(null); forceRender();
    return;
  }
  if (!ensureGroup()) {
    console.error("[collision] 视口场景未就绪（步骤①的模型没载入？），标记画不出来");
    setBanner(level, bannerText(level, cases));
    return;
  }
  for (const c of cases) addMark(c, level);
  setPulses(marks.filter((m) => m.deny).map((m) => m.point));   // deny 级补脉冲圈（含动效开关判定）
  focused = cases.length === 1 ? 0 : -1;   // 只有一处就直接放大它（省一次点击）
  paintFocus(); setBanner(level, bannerText(level, cases));
  setHighlight(level === "deny" ? cases[0] : null);   // 高亮条＝最危险一条（deny 专属，蓝图 §3.5）
  forceRender();
}

function addMark(c, level) {
  const deny = level === "deny", color = deny ? COLOR_DENY : COLOR_WARN;  // sem/圈都随 deny 走
  const p = c.point || [0, 0, 0];
  const dot = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 12),
                             new THREE.MeshBasicMaterial({ color: color, depthTest: false,
                                                           transparent: true, opacity: DOT_OPAQUE }));
  dot.position.set(p[0], p[1], p[2]);
  dot.scale.setScalar(MARKER_RAD_MM);
  dot.renderOrder = RENDER_ORDER;
  dot.name = "collision-dot";     // ⛔ 不设 userData.id：那会被 pick.js 当成可拾取部件
  group.add(dot);
  const wire = makeBox(c.box, color);      // 臂侧代理盒线框＝「双方高亮」的臂侧一方（臂身没有 mesh）
  if (wire) group.add(wire);
  // sem＝障碍侧高亮语义（随三态走：预警态把工件染红会被读成"已相碰"）；deny 级另有脉冲圈
  marks.push({ dot: dot, box: wire, obs: c.obs || 0, point: p, sem: deny ? "deny" : "warn", deny: deny });
  if (!view) dot.onBeforeRender = captureView;   // 借标记的渲染回调拿 renderer/camera（只挂一次）
}

// 代理盒（6 元下界／上界）→ 三态色线框。自绘 EdgesGeometry ⛔ 不用 Box3Helper（各 three 版本对
// 它的 update 时机口径不一，自绘的落点确定）。盒为空数组即臂侧没给出代理盒 ⇒ 只画点、不画框。
function makeBox(b, color) {
  if (!Array.isArray(b) || b.length < BOX_DIM * 2) return null;
  const size = [b[BOX_DIM] - b[0], b[BOX_DIM + 1] - b[1], b[BOX_DIM + 2] - b[2]];
  const geo = new THREE.EdgesGeometry(new THREE.BoxGeometry(size[0], size[1], size[2]));
  const line = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: color,
                                                                         depthTest: false }));
  line.position.set((b[0] + b[BOX_DIM]) / 2, (b[1] + b[BOX_DIM + 1]) / 2,
                    (b[2] + b[BOX_DIM + 2]) / 2);
  line.name = "collision-box";    // ⛔ 同上：不设 userData.id（不进拾取目标集）
  line.renderOrder = RENDER_ORDER;
  return line;
}

function clearMarks() {
  for (const m of marks) {
    for (const obj of [m.dot, m.box]) {
      if (!obj) continue;
      if (group) group.remove(obj);
      if (obj.geometry) obj.geometry.dispose();
      if (obj.material) obj.material.dispose();
    }
  }
  marks = [];
  focused = -1;
  setPulses([]); view = null;
}

// --- T16 红色脉冲圈：deny 级标记的 DOM 强化（CSS 合成层动画，不进 three 渲染循环）-----------
function captureView(renderer, _scene, camera) { view = { renderer: renderer, camera: camera }; placePulses(); }

function motionOff() {   // 蓝图 §1-11：--motion=0（外壳推送）或系统减少动态 ⇒ 只停动画、信息不丢
  const flag = getComputedStyle(document.documentElement).getPropertyValue("--motion").trim();
  return flag === "0" || window.matchMedia("(prefers-reduced-motion: reduce)").matches; }

function setPulses(points) {
  const host = document.getElementById("scene-host");
  if (!host) return;
  if (!styleEl) {
    styleEl = document.createElement("style"); styleEl.textContent = PULSE_CSS;
    document.head.appendChild(styleEl);
  }
  if (!pulseLayer || pulseLayer.parentNode !== host) {
    pulseLayer = document.createElement("div");
    pulseLayer.style.cssText = "position:absolute;inset:0;pointer-events:none;z-index:4"; host.appendChild(pulseLayer);
  }
  pulseLayer.textContent = "";
  const still = motionOff();                       // 蓝图 §1-11：动效关 ⇒ 静态红环（信息不丢）
  for (const p of points) {
    const ring = document.createElement("div");
    ring.className = still ? "coll-pulse static" : "coll-pulse";
    ring.__point = p; pulseLayer.appendChild(ring);
  }
  placePulses();
}

function placePulses() {
  // 干涉点（模型坐标）→ 屏幕坐标；视角动＝loader 按需渲染＝onBeforeRender 触发本函数（自洽）
  if (!pulseLayer || !pulseLayer.childElementCount || !view || !view.renderer) return;
  const el = view.renderer.domElement, v = new THREE.Vector3(), w = el.clientWidth, h = el.clientHeight;
  for (const ring of pulseLayer.children) {
    v.set(ring.__point[0], ring.__point[1], ring.__point[2]).project(view.camera);
    ring.style.left = ((v.x * 0.5 + 0.5) * w) + "px";
    ring.style.top = ((-v.y * 0.5 + 0.5) * h) + "px";
  }
}

// --- T16 干涉高亮条：视口底缘（蓝图 §3.5）＝最危险一条＋「定位」（deny 专属）----------------
function setHighlight(worst) {
  const host = document.getElementById("scene-host");
  if (!host) return;
  if (!worst) { if (hlBar) hlBar.style.display = "none"; return; }
  if (!hlBar || hlBar.parentNode !== host) {
    hlBar = document.createElement("div");   // 演示稿画面 06 同构（HTML:592–598）：深红底/红边/左红条；色值＝02 §4 deny 派生系内联
    hlBar.style.cssText = "position:absolute;bottom:10px;left:10px;z-index:5;display:flex;align-items:center;gap:8px;" +
      "background:rgba(42,20,22,.93);border:1px solid #7a2c2c;border-left:3px solid #ff4d4d;border-radius:4px;padding:7px 11px;" +
      "color:#ffc9c9;font:600 13px/1.5 system-ui,sans-serif;max-width:72%;overflow:hidden;white-space:nowrap";
    host.appendChild(hlBar);
  }
  hlBar.textContent = "";
  const title = document.createElement("b"), btn = document.createElement("button");
  title.textContent = "干涉高亮"; title.style.color = "#ffffff";
  btn.textContent = "定位";
  btn.style.cssText = "background:#3a1c1e;border:1px solid #7a2c2c;color:#ffb3b3;border-radius:4px;" +
    "padding:2px 10px;cursor:pointer;font:inherit";
  btn.onclick = function () { onFocus({ index: 0 }); };   // 与列表点击同一套定位口径
  const text = document.createElement("span");
  text.textContent = "臂身 " + (worst.arm || "?") + " ↔ " + nameOf(worst.obs) + " · 最小时距 " +
    (worst.dist || 0).toFixed(1) + " mm · 步 " + (worst.seg || 0);
  hlBar.append(title, text, btn);
  hlBar.style.display = "";
}

// --- collision.focus：放大该条标记＋障碍侧同语义高亮＋相机飞到（障碍侧转 loader 的 hl.set）------
function onFocus(payload) {
  const index = (payload && typeof payload.index === "number") ? payload.index : -1;
  if (index < 0 || index >= marks.length) return;
  focused = index;
  paintFocus(); highlightObstacle(marks[index].obs, marks[index].sem); forceRender();
}

function paintFocus() {
  for (let i = 0; i < marks.length; i++) {
    const on = i === focused, mark = marks[i];
    mark.dot.scale.setScalar(MARKER_RAD_MM * (on ? FOCUS_SCALE : 1));
    mark.dot.material.opacity = on || focused < 0 ? DOT_OPAQUE : DOT_DIM;
    if (mark.box) {
      mark.box.material.transparent = true;
      mark.box.material.opacity = on || focused < 0 ? 1 : WIRE_DIM;
    }
  }
}

// 障碍侧高亮：把 loader 的 hl.set **投给内层分发器**（path.js→pick.js→loader.js）统一染色并飞到
// 该部件 ⇒ 高亮口径只有一处（⛔ 本文件不自己改 mesh 材质）。
function highlightObstacle(meshId, sem) {
  if (!meshId || !inner) return;
  inner({ type: "hl.set", payload: { ids: [meshId], semantic: sem || "deny", focus: true } }); }

// 部件名从 loader 已建 mesh 的 userData.name 取（桥里没有中文）；取不到就退回"该部件"，⛔ 不猜名。
function nameOf(meshId) {
  let found = "";
  if (scene && meshId) {
    scene.traverse((o) => {
      if (!found && o.userData && o.userData.id === meshId && o.userData.name) found = o.userData.name;
    });
  }
  return found || "该部件";
}

// 报警条文案：人话、全中文（02 §4），⛔ 不带内部编号与英文术语；最多列 MAX_BANNER_CASES 处。
function bannerText(level, cases) {
  const head = level === "deny" ? "🔴 检出干涉：已禁止下发" : "🟡 检出预警：间距小于安全值";
  const rows = cases.slice(0, MAX_BANNER_CASES).map((c) => "第 " + (c.seg || 0) + " 段 臂身 " +
    (c.arm || "?") + " ↔ " + nameOf(c.obs) + "（" +
    (level === "deny" ? "已相碰" : "间距 " + (c.dist || 0).toFixed(1) + " mm") + "）");
  const more = cases.length > MAX_BANNER_CASES ? ("另有 " + (cases.length - MAX_BANNER_CASES) + " 处") : "";
  const tail = level === "deny" ? "改点位或换模式后重新校核" : "可进入步骤⑤，下发前会再提示一次";
  return [head].concat(rows).concat([more, "共 " + cases.length + " 处。" + tail]).filter((s) => s).join("　｜　");
}

function setBanner(level, text) {
  if (!text) {
    // ⛔ 不用 .hidden 类：app.css 里它是 #empty-scene 专属；文案一并清空，隐藏态不留旧警告
    if (banner) { banner.style.display = "none"; banner.textContent = ""; }
    return;
  }
  if (!banner) {
    const host = document.getElementById("scene-host");
    if (!host) return;
    banner = document.createElement("div");
    banner.style.cssText = "position:absolute;top:0;left:0;right:0;z-index:5;padding:8px 12px;"
      + "font:600 13px/1.6 system-ui,sans-serif;pointer-events:none;white-space:normal;"
      + "word-break:break-word;box-shadow:0 2px 8px rgba(0,0,0,.45)";
    host.appendChild(banner);
  }
  banner.textContent = text;
  // 配色只取 02 §4 既有调色板：干涉＝deny 红底白字；预警＝warn 黄底＋深色字（黄底白字看不清）。
  const deny = level === "deny";
  banner.style.background = deny ? "#b3261e" : "#d9a520";
  banner.style.color = deny ? "#ffffff" : "#16202a"; banner.style.display = "";
}

// 包裹统一分发（注册在 path.js 之后 ⇒ 最外层）：截走本单两类消息；invalidate 先清标记再交回内层
// （path.js 清路径、pick.js 清标号牌、loader.js 出占位提示）。
function bindDispatch() {
  const prev = window.__mecharm_dispatch;
  inner = prev || null;
  window.__mecharm_dispatch = function (msg) {
    const type = msg && msg.type;
    if (type === "collision.show") { onShow(msg.payload || {}); return; }
    if (type === "collision.focus") { onFocus(msg.payload || {}); return; }
    if (type === "invalidate") onShow({ level: "clear", cases: [] });
    if (prev) prev(msg);
  };
}

function main() {
  const host = document.getElementById("scene-host");
  if (!host) { console.error("[collision] 找不到 #scene-host"); return; }
  installSceneHook(); bindDispatch();
}

main();

// view/js/collision.js — 步骤④校核结果的视口投影（T08）。
//
// 职责（02 §2 步骤④／卡片步骤 4）：顶部报警条＋干涉点标记＋臂侧代理盒线框＋点击列表行定位。
//   三通道里的**视口那一半**（另一半＝右栏卡片／列表，见 app/steps/step4_check.py）。
//
// 红线（04 §7.2-G13／G14 ①）：本文件**只做显示**——不算距离、不做判定、不存真值；三态字面与
//   几何坐标全由 core.collision 经壳推来，本文件收到什么画什么。⛔ 禁在此处复算或"修正"结论。
// ⚠️ G19：报警条**只在预警／干涉时出现**，通过态不挂任何"未检出碰撞"字样——未建模臂属判定空白，
//   视口里给一句绿色"通过"会被读成整机结论（覆盖面限定由右栏 `coverage()` 那行常显承担）。
//
// ⚠️ 不动 loader.js／pick.js／path.js（04 §4 归属矩阵：三者他单权限＝—）：scene／camera／renderer
//   都是 loader 的模块私有变量。沿用 path.js 的手法从外部**观察** scene：包裹
//   `Object3D.prototype.add`（链式叠加、原实现照旧 apply）。本文件**不自己出帧**——重绘一律派发
//   `resize` 借 loader 的按需渲染（该帧会连本文件的 group 一起画，故 renderer／camera 不必观察）。
//   障碍侧高亮**不自己染色**，而是向内层分发器合成 loader 已实现的
//   `hl.set {semantic:<三态语义>, focus:true}` ⇒ 高亮与相机飞到只有一套口径，⛔ 两处不打架。
//
// 载荷口径（全 ASCII：`app/bridge.py` 用 ensure_ascii=True 投递 ⇒ 桥里**没有**中文点名与原因；
//   部件名由本文件从 loader 已建 mesh 的 `userData.name` 自取，人话句子在视口侧拼装）：
//   collision.show  {level:"deny"|"warn"|"clear", cases:[{seg:int, arm:str, obs:int,
//                                                       dist:float, point:[x,y,z], box:[6]}]}
//   collision.focus {index:int}      // 右栏列表点击行 → 放大该条标记＋障碍侧按三态语义高亮＋相机飞到
// 两个 type 均为本单新定（03 §5 未登记 ⇒ 汇报请回填，同 T07 的 perf.fps）；⛔ 未改 app/bridge.py、
//   ⛔ 未碰 view/index.html 注册行（注册顺序建议 bridge→loader→pick→path→collision，见汇报）。
// 报警条样式走**元素内联**（app.css 属 T05、新选择器须指挥方合并时统一加，本单不自改）。

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

let scene = null;                 // 由 proto.add 钩子观察自 loader.js（见 installSceneHook）
let group = null;                 // 本文件全部显示对象的容器（挂 scene 下，不进 loader 的 group）
let banner = null;                // 顶部报警条（DOM，挂在 #scene-host 上）
let marks = [];                   // [{dot, box, obs}]，与 collision.show 的 cases 同序（列表行号＝下标）
let focused = -1;
let inner = null;                 // 内层分发器（path.js 的包裹函数）：hl.set 直接投给它，不重入本文件

// 链式包裹 proto.add 观察 scene（pick.js／path.js 各包过一次，本文件叠在最外、原实现照旧 apply）。
// 触发时机：步骤①导入模型时 loader 的 group.add(mesh)（group.parent＝scene）必经 ⇒ 校核前必已就位。
function installSceneHook() {
  const proto = THREE.Object3D.prototype;
  const origAdd = proto.add;
  proto.add = function (o) {
    const found = this.isScene ? this : (this.parent && this.parent.isScene ? this.parent : null);
    if (found) scene = found;
    return origAdd.apply(this, arguments);
  };
}

// 借 loader 自己的 resize()→render() 出一帧（本文件不持 renderer，重绘只此一条路）。
function forceRender() {
  window.dispatchEvent(new Event("resize"));
}

// 图层只建一次并常驻 scene（loader 清场只摘自己 group 里的 mesh，不动 scene 的其它子节点）⇒
// 已建过也必须返回 true，否则第二次校核会误走"场景未就绪"分支、一处标记都画不出来。
function ensureGroup() {
  if (!scene) return false;
  if (!group) {
    group = new THREE.Group();
    group.name = "collision-layer";
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
    setBanner(null, "");
    forceRender();
    return;
  }
  if (!ensureGroup()) {
    console.error("[collision] 视口场景未就绪（步骤①的模型没载入？），标记画不出来");
    setBanner(level, bannerText(level, cases));
    return;
  }
  for (const c of cases) addMark(c, level);
  focused = cases.length === 1 ? 0 : -1;   // 只有一处就直接放大它（省一次点击）
  paintFocus();
  setBanner(level, bannerText(level, cases));
  forceRender();
}

function addMark(c, level) {
  const color = level === "deny" ? COLOR_DENY : COLOR_WARN;
  const p = c.point || [0, 0, 0];
  const dot = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 12),
                             new THREE.MeshBasicMaterial({ color: color, depthTest: false,
                                                           transparent: true,
                                                           opacity: DOT_OPAQUE }));
  dot.position.set(p[0], p[1], p[2]);
  dot.scale.setScalar(MARKER_RAD_MM);
  dot.renderOrder = RENDER_ORDER;
  dot.name = "collision-dot";     // ⛔ 不设 userData.id：那会被 pick.js 当成可拾取部件
  group.add(dot);
  const wire = makeBox(c.box, color);      // 臂侧代理盒线框＝「双方高亮」的臂侧一方（臂身没有 mesh）
  if (wire) group.add(wire);
  // sem＝障碍侧高亮要用的颜色语义（随三态走：预警态把工件染成红会被读成"已相碰"）
  marks.push({ dot: dot, box: wire, obs: c.obs || 0, sem: level === "deny" ? "deny" : "warn" });
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
}

// --- collision.focus：放大该条标记＋障碍侧同语义高亮＋相机飞到（障碍侧转 loader 的 hl.set）------
function onFocus(payload) {
  const index = (payload && typeof payload.index === "number") ? payload.index : -1;
  if (index < 0 || index >= marks.length) return;
  focused = index;
  paintFocus();
  highlightObstacle(marks[index].obs, marks[index].sem);
  forceRender();
}

function paintFocus() {
  for (let i = 0; i < marks.length; i++) {
    const on = i === focused;
    const mark = marks[i];
    mark.dot.scale.setScalar(MARKER_RAD_MM * (on ? FOCUS_SCALE : 1));
    mark.dot.material.opacity = on || focused < 0 ? DOT_OPAQUE : DOT_DIM;
    if (mark.box) {
      mark.box.material.transparent = true;
      mark.box.material.opacity = on || focused < 0 ? 1 : WIRE_DIM;
    }
  }
}

// 障碍侧高亮：把 loader 已实现的 hl.set **投给内层分发器**（path.js→pick.js→loader.js），
// 由 loader 统一染色并飞到该部件 ⇒ 高亮口径只有一处（⛔ 本文件不自己改 mesh 材质）。
function highlightObstacle(meshId, sem) {
  if (!meshId || !inner) return;
  inner({ type: "hl.set", payload: { ids: [meshId], semantic: sem || "deny", focus: true } });
}

// 部件名从 loader 已建 mesh 的 userData.name 取（桥里没有中文）；取不到就退回"该部件"，⛔ 不猜名。
function nameOf(meshId) {
  let found = "";
  if (scene && meshId) {
    scene.traverse((o) => {
      if (!found && o.userData && o.userData.id === meshId && o.userData.name) {
        found = o.userData.name;
      }
    });
  }
  return found || "该部件";
}

// 报警条文案：人话、全中文（02 §4），⛔ 不带内部编号与英文术语；最多列 MAX_BANNER_CASES 处。
function bannerText(level, cases) {
  const head = level === "deny" ? "🔴 检出干涉：已禁止下发" : "🟡 检出预警：间距小于安全值";
  const rows = cases.slice(0, MAX_BANNER_CASES).map((c) => {
    const gap = level === "deny" ? "已相碰" : ("间距 " + (c.dist || 0).toFixed(1) + " mm");
    return "第 " + (c.seg || 0) + " 段 臂身 " + (c.arm || "?") + " ↔ " + nameOf(c.obs) + "（" + gap + "）";
  });
  const more = cases.length > MAX_BANNER_CASES ? ("另有 " + (cases.length - MAX_BANNER_CASES) + " 处") : "";
  const tail = level === "deny" ? "改点位或换模式后重新校核" : "可进入步骤⑤，下发前会再提示一次";
  return [head].concat(rows).concat([more, "共 " + cases.length + " 处。" + tail])
              .filter((s) => s).join("　｜　");
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
      + "font:600 13px/1.6 system-ui,sans-serif;pointer-events:none;"
      + "white-space:normal;word-break:break-word;box-shadow:0 2px 8px rgba(0,0,0,.45)";
    host.appendChild(banner);
  }
  banner.textContent = text;
  // 配色只取 02 §4 既有调色板：干涉＝deny 红底白字；预警＝warn 黄底＋深色字（黄底白字看不清）。
  const deny = level === "deny";
  banner.style.background = deny ? "#b3261e" : "#d9a520";
  banner.style.color = deny ? "#ffffff" : "#16202a";
  banner.style.display = "";
}

// 包裹统一分发（本文件注册在 path.js 之后 ⇒ 位于最外层）：截走本单两类消息，invalidate 先清标记
// 再交回内层（path.js 清路径、pick.js 清标号牌、loader.js 出占位提示）。
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
  installSceneHook();
  bindDispatch();
}

main();

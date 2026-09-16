// view/js/path.js — 步骤③路径折线、方向箭头与播放动画（T07）。
//
// 职责（02 §2 步骤③／03 §5）：把壳推来的段序列画成折线＋方向箭头，播放时按 pose.update 摆放
//   工具标记并高亮当前段；rAF 循环**实测**帧率经 perf.fps 回传，供底部角标显示（完成标准①）。
//   红线：本文件**只做显示**——不算几何、不存点位／段真值（04 §7.2-G14 ①，同 loader.js）。
//
// ⚠️ 不动 loader.js／pick.js（04 §4 归属矩阵：二者他单权限＝—）：loader.js 把 scene／camera／
//   renderer 全留在模块私有变量。本文件沿用 pick.js 的手法从外部**观察**：包裹
//   ``Object3D.prototype.add``（链式叠加、原实现照旧 apply）拿到 scene；renderer／camera 则由
//   three 自己在渲染回调里递过来——``Object3D.onBeforeRender(renderer, scene, camera, …)`` 是
//   **实例级**钩子，不必再包原型（pick.js 已实测 WebGLRenderer 实例的 render 是自有闭包、
//   包原型对已建实例完全不触发）。首帧借 loader 的按需渲染（派发 resize）把这三个句柄拿到手，
//   之后播放期间由本文件的 rAF 循环自己出帧。
//
// ⚠️ **插值落点**（与卡片措辞的偏差，已在 T07 交付汇报登记请追认）：卡片把「播放按段线性插值」
//   列在本文件名下，但按 03 §3「数据源唯一在 core／前端不存真值」与 §5 的 pose.update 通道
//   （每帧位姿由壳给出），**关节线性插值在壳侧 core 出口做**（`app/pathctl.py::_locate/_lerp`），
//   本文件只投影：收到一帧就摆一帧。⇒ 结构上不可能外推／预测下一帧（W-5.7）：没有新帧数据时
//   标记就停在最后一帧，且壳侧插值参数恒钳在 [0,1]。
//
// 载荷口径（桥全 ASCII：`app/bridge.py` 用 ensure_ascii=True 投递 ⇒ ⛔ 不带中文原因、也不带
//   可被用户改成中文的点名；人话原因只留在右栏壳内）：
//   path.show  {segments:[{id:int, type:"JOINT"|"LINE", start:[x,y,z], end:[x,y,z],
//                          length:float, blocked:bool}]}
//   pose.update {poses:{连杆名: 16 元**列主序**扁平矩阵}, seg:int, ts:float}
//   perf.fps（视口→壳，本单新定；03 §5 未登记 ⇒ 汇报请回填，T09/T10 可复用同一通道）{fps:float}
// path.show／pose.update 的 schema 03 §5 只登记了用途（「段数组」「每部件 4x4 扁平矩阵」）、
//   未定字段；本单作为首个实现者定为此二式，⛔ 未改 app/bridge.py、未改 index.html 注册行
//   （注册行按卡片由指挥方合并时统一加：path.js 须在 pick.js 之后）。

import * as THREE from "../vendor/three.module.js";

const COLOR_IDLE = 0x9fb0bd;        // 常态段：次要文字色（02 §4 text_dim）
const COLOR_CURRENT = 0x2f6feb;     // 当前段：accent 蓝（＝当前步高亮同一口径）
const COLOR_BLOCKED = 0xb3261e;     // 不可达段：deny 红（禁发压过进度，与右栏同口径）
const COLOR_MARKER = 0x1c7c43;      // 工具标记：ok 绿（与段线区分开）
const ARROW_LEN_MM = 36;            // 方向箭头杆长（自造基本体尺寸，非机台参数）
const ARROW_HEAD_MM = 14;           // 箭头头部长度
const ARROW_MIN_MM = 60;            // 段短于此不画箭头（画了会糊满整段、看不出指向）
const MARKER_LEN_MM = 48;           // 工具标记锥体长（锥尖即工具点）
const MARKER_RAD_MM = 14;           // 锥体底面半径
const MATRIX_LEN = 16;              // 4x4 扁平矩阵元素数
const FPS_WINDOW_MS = 500;          // 帧率统计窗口（够平滑，角标也不至于长时间不刷新）
const IDLE_STOP_MS = 500;           // 这么久没收到 pose.update ⇒ 播放已停，退回按需渲染

let scene = null, renderer = null, camera = null;
let group = null;                   // 本文件全部显示对象的容器（挂 scene 下，不进 loader 的 group）
let marker = null;
const items = [];                   // [{id, line, arrow, blocked}]
let currentId = 0;
let rafId = 0, frames = 0, fpsSince = 0, lastPoseAt = 0;
const _mat = new THREE.Matrix4();
const _pos = new THREE.Vector3();
const _quat = new THREE.Quaternion();
const _scale = new THREE.Vector3();

// three 渲染每个对象前调它，顺手把 renderer／scene／camera 三个句柄交给本文件（见文件头说明）。
function capture(r, s, c) {
  renderer = r; scene = s; camera = c;
}

// 链式包裹 proto.add 观察 scene（pick.js 已包过一次，本文件叠在其上、原实现照旧 apply）。
function installSceneHook() {
  const proto = THREE.Object3D.prototype;
  const origAdd = proto.add;
  proto.add = function (o) {
    const found = this.isScene ? this : (this.parent && this.parent.isScene ? this.parent : null);
    if (found) scene = found;
    return origAdd.apply(this, arguments);
  };
}

// 无 renderer 句柄时借 loader 自己的 resize()→render() 出一帧（该帧会把句柄递给 capture）。
function forceRender() {
  window.dispatchEvent(new Event("resize"));
}

function vec(p) {
  return new THREE.Vector3(p[0], p[1], p[2]);
}

// --- path.show：段序列 → 折线＋箭头（整体重建；前端不存真值，只投影）------------------
function onPathShow(payload) {
  stopLoop();
  clearItems();
  const list = (payload && payload.segments) || [];
  if (!list.length) {
    if (marker) marker.visible = false;
    currentId = 0;
    forceRender();
    return;
  }
  ensureGroup();
  for (const seg of list) addItem(seg);
  ensureMarker();
  currentId = 0;
  forceRender();
}

function ensureGroup() {
  if (group || !scene) return;
  group = new THREE.Group();
  group.name = "path-layer";
  scene.add(group);
}

function addItem(seg) {
  const from = vec(seg.start);
  const to = vec(seg.end);
  const color = seg.blocked ? COLOR_BLOCKED : COLOR_IDLE;
  const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([from, to]),
                              new THREE.LineBasicMaterial({ color: color }));
  line.name = "path-seg-" + seg.id;
  line.userData.segId = seg.id;        // ⛔ 不设 userData.id：那会被 pick.js 当成可拾取部件
  line.onBeforeRender = capture;
  group.add(line);
  const arrow = makeArrow(from, to, color);
  if (arrow) group.add(arrow);
  items.push({ id: seg.id, line: line, arrow: arrow, blocked: !!seg.blocked });
}

function makeArrow(from, to, color) {
  const aim = to.clone().sub(from);
  const span = aim.length();
  if (!(span > ARROW_MIN_MM)) return null;
  aim.divideScalar(span);
  const origin = from.clone().addScaledVector(aim, (span - ARROW_LEN_MM) / 2);
  return new THREE.ArrowHelper(aim, origin, ARROW_LEN_MM, color,
                               ARROW_HEAD_MM, ARROW_HEAD_MM * 0.6);
}

function clearItems() {
  for (const item of items) {
    for (const obj of [item.line, item.arrow]) {
      if (!obj) continue;
      group.remove(obj);
      if (obj.geometry) obj.geometry.dispose();
      if (obj.material) obj.material.dispose();
    }
  }
  items.length = 0;
}

// --- 工具标记：自造基本体（锥尖＝工具点、锥轴＝工具 Z），随 pose.update 摆放 ----------------
function ensureMarker() {
  if (marker) { marker.visible = true; return; }
  const geo = new THREE.ConeGeometry(MARKER_RAD_MM, MARKER_LEN_MM, 12);
  geo.rotateX(-Math.PI / 2);                      // 锥轴由 +Y 转到 −Z（锥尖朝下）
  geo.translate(0, 0, MARKER_LEN_MM / 2);         // 锥尖落在原点＝工具点，锥体朝 +Z 立在工件外
  const mat = new THREE.MeshStandardMaterial({
    color: COLOR_MARKER, metalness: 0.1, roughness: 0.5,
  });
  marker = new THREE.Mesh(geo, mat);
  marker.name = "tool-marker";
  marker.userData.pathMarker = true;   // ⛔ 不设 userData.id（同上：不得进拾取目标集）
  marker.onBeforeRender = capture;
  group.add(marker);
}

// --- pose.update：一帧位姿（列主序扁平矩阵）→ 摆标记＋高亮当前段 -----------------------
function onPoseUpdate(payload) {
  const poses = (payload && payload.poses) || {};
  const names = Object.keys(poses);
  if (!names.length) return;
  const flat = poses[names[names.length - 1]];
  if (!Array.isArray(flat) || flat.length !== MATRIX_LEN) return;
  ensureGroup();
  ensureMarker();
  _mat.fromArray(flat);                           // 列主序 ⇒ three 的 fromArray 口径（03 §5）
  _mat.decompose(_pos, _quat, _scale);            // 拆回 position/quaternion/scale，交由 three 组矩阵
  marker.position.copy(_pos);
  marker.quaternion.copy(_quat);
  marker.scale.copy(_scale);
  setCurrent(payload.seg || 0);
  lastPoseAt = performance.now();
  startLoop();                                    // 有帧数据才转循环（⛔ 无数据不自造动画）
}

// 当前段高亮：不可达段**恒红**（禁发压过进度，与右栏 _paint 同口径），其余按是否当前段取蓝/灰。
function setCurrent(segId) {
  if (segId === currentId) return;
  currentId = segId;
  for (const item of items) {
    const color = item.blocked ? COLOR_BLOCKED
      : (item.id === currentId ? COLOR_CURRENT : COLOR_IDLE);
    item.line.material.color.setHex(color);
    if (item.arrow) item.arrow.setColor(color);
  }
}

// --- rAF 循环：播放期间自己出帧，并按窗口实测帧率回传（完成标准①的角标数据源）-----------
function startLoop() {
  if (rafId) return;
  frames = 0;
  fpsSince = performance.now();
  rafId = requestAnimationFrame(tick);
}

function tick(now) {
  rafId = 0;
  frames += 1;
  if (now - fpsSince >= FPS_WINDOW_MS) reportFps(now);
  if (renderer && scene && camera) renderer.render(scene, camera);
  if (now - lastPoseAt > IDLE_STOP_MS) { stopLoop(); return; }   // 播放停了 ⇒ 交回按需渲染
  rafId = requestAnimationFrame(tick);
}

function reportFps(now) {
  const span = Math.max(now - fpsSince, 1);
  const fps = (frames * 1000) / span;
  frames = 0;
  fpsSince = now;
  send("perf.fps", { fps: Math.round(fps * 10) / 10 });
}

function stopLoop() {
  if (!rafId) return;
  cancelAnimationFrame(rafId);
  rafId = 0;
}

function send(type, data) {
  if (window.bridge) window.bridge.on_view_msg(type, JSON.stringify(data));
  else console.log("[path] 桥未就绪，丢弃 " + type + ":", data);
}

// 包裹统一分发（本文件注册在 pick.js 之后 ⇒ 位于最外层）：截走本单两类消息，invalidate 先清路径
// 再交回内层（pick.js 清标号牌、bridge.js 出占位提示）。
function bindDispatch() {
  const prev = window.__mecharm_dispatch;
  window.__mecharm_dispatch = function (msg) {
    const type = msg && msg.type;
    if (type === "path.show") { onPathShow(msg.payload || {}); return; }
    if (type === "pose.update") { onPoseUpdate(msg.payload || {}); return; }
    if (type === "invalidate") onPathShow({ segments: [] });
    if (prev) prev(msg);
  };
}

function main() {
  const host = document.getElementById("scene-host");
  if (!host) { console.error("[path] 找不到 #scene-host"); return; }
  installSceneHook();
  bindDispatch();
}

main();

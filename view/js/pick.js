// view/js/pick.js — 步骤②面拾取与标号牌（T06）。
//
// 职责（02 §2 步骤②／03 §5 pick 协议）：raycaster 拾取，左键命中回传 pick.face
//   {mesh_id,face_id,u,v}（face_id＝三角形序号、u/v＝重心坐标，与 core.geometry.face_point
//   的 face_point_from_tri 同口径）；悬停部件高亮；标号牌（序号+名称、随相机距离保底字号）。
//
// ⚠️ 不动 loader.js（04 §4 矩阵：loader.js 他单权限＝—，本单禁改）：loader.js 把
//   scene／camera／renderer 全留在模块私有变量、未导出。本文件只能从外部**观察**它们。
//   ⚠️ 已实测（2026-09-16，three r160 vendored）：``WebGLRenderer`` 实例的 ``render`` 是构造函数里
//   赋的**自有闭包**（``Object.getOwnPropertyNames(inst)`` 含 ``render``、``inst.render !==
//   prototype.render``），故包裹 ``WebGLRenderer.prototype.render`` **对已建实例完全不触发**；又因
//   ``import * as THREE`` 的命名空间导出只读，无法替换构造函数本身。改挂 loader 每帧/每载入必经、
//   且确为**原型继承**（实例不自有）的两个 ``Object3D`` 方法——``render()`` 末尾的 ``camera.lookAt``
//   捕获活动相机、``onMeshLoad`` 的 ``group.add(mesh)`` 捕获 ``scene``（＝group.parent）。仅观察、
//   原方法照旧 ``apply``，不改 loader 行为。无 renderer 句柄，需重绘时派发 ``resize`` 事件借 loader
//   自己的 ``resize()→render()`` 出一帧（实测可触发悬停高亮／半透明态刷新）。
//
// 手势分离（关键点3：拾取与旋转不得抢同一按键）：loader.js 在**任意键**按下即进入旋转拖拽；本文件
//   在 #scene-host **捕获阶段**拦下**左键** pointerdown 并 stopPropagation，事件不再到达画布 ⇒
//   左键**只**取点、绝不触发 loader 旋转；右键／中键**放行**到画布 ⇒ 由 loader 旋转；滚轮缩放归
//   loader。⚠️ loader.js 未实现平移（target/orbit 为其私有、本单禁改无法补）⇒ 中键沿用旋转（汇报登记）。
//
// 数据纪律（禁在前端存点位真值，数据源唯一在 core）：标号牌**只是 core 推来的显示投影**——pick.js
//   不保存任何点位真值（法向／source_face 都不下发），每次 pick.enable 推送即整体重建；取点只回传
//   {mesh_id,face_id,u,v}，真实 3D 点与法向由 core 换算。
//
// pick.enable 载荷（03 §5 只登记用途"开关拾取模式"、未定 schema；本单作为首个实现者定为）：
//   {on:bool, markers:[{id:int, name:str, pos:[x,y,z]}]}——on 开关拾取与半透明操作态，markers 为
//   权威显示清单（整体替换）。⚠️ 未新增桥 type、未改 app/bridge.py／03 §5 表；该定义已在汇报登记请追认。
// 标号牌样式用**元素内联**（app.css 属 T05、新选择器须指挥方合并时统一加，本单不自改）。

import * as THREE from "../vendor/three.module.js";

const CLICK_SLOP_PX = 4;          // 左键按下→抬起位移 < 此＝取点点击；≥ 此视为拖拽（放行旋转）
const HOVER_EMISSIVE = 0x2f6feb;  // 悬停高亮色（＝ app.css --accent ＝ loader SEM.ok）
const PICK_OPACITY = 0.55;        // 进入步骤②的半透明操作态（02 §2「模型转半透明」）
const MARKER_MIN_FONT = 12;       // 标号牌保底字号（远处）
const MARKER_MAX_FONT = 18;       // 标号牌近处字号
const MARKER_NEAR_MM = 200;       // 该相机距离用最大字号
const MARKER_FAR_MM = 2000;       // 该相机距离用保底字号

let scene = null, camera = null;   // 由 Object3D 原型钩子观察自 loader.js（见 installSceneHooks）
let host = null, markerLayer = null;
let pickingOn = false;
let markers = [];                  // [{id, name, pos:THREE.Vector3, el}]
let hoverMesh = null, hoverEmissive = 0, hoverIntensity = 0;
let downX = 0, downY = 0;
const raycaster = new THREE.Raycaster();
const _ndc = new THREE.Vector2();
const _v = new THREE.Vector3();
const _bc = new THREE.Vector3();
const _a = new THREE.Vector3(), _b = new THREE.Vector3(), _c = new THREE.Vector3();

function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }

// 观察 loader.js 私有的 scene/camera（禁改其文件）。实例的 render 是自有闭包、原型包裹不触发，
// 故改挂 loader 必经且为原型继承的两个 Object3D 方法：每帧 render() 末尾的 camera.lookAt 取活动
// 相机；onMeshLoad 的 group.add(mesh) 取 scene（＝group.parent）。仅观察，原方法照旧 apply。
function installSceneHooks() {
  const proto = THREE.Object3D.prototype;
  const origLookAt = proto.lookAt;
  proto.lookAt = function (v) {
    if (this.isCamera) { camera = this; updateMarkerPositions(); }
    return origLookAt.apply(this, arguments);
  };
  const origAdd = proto.add;
  proto.add = function (o) {
    const sc = this.isScene ? this : (this.parent && this.parent.isScene ? this.parent : null);
    if (sc) scene = sc;
    return origAdd.apply(this, arguments);
  };
}

// 无 renderer 句柄（loader 私有）：派发 resize 让 loader 自己的 resize()→render() 出一帧，
// 刷新悬停高亮／半透明操作态等材质改动；render 末尾的 lookAt 钩子会顺带重投影标号牌。
function forceRender() {
  window.dispatchEvent(new Event("resize"));
}

// 包裹 bridge.js→loader.js 的统一分发：截走 pick.enable／invalidate，其余交回原函数。
function bindDispatch() {
  const prev = window.__mecharm_dispatch;
  window.__mecharm_dispatch = function (msg) {
    const type = msg && msg.type;
    if (type === "pick.enable") { onPickEnable(msg.payload || {}); return; }
    if (type === "invalidate") { onInvalidate(); if (prev) prev(msg); return; }
    if (prev) prev(msg);
  };
}

function onPickEnable(payload) {
  pickingOn = !!payload.on;
  setMarkers(payload.markers || []);
  applyPickState();
}

function onInvalidate() {
  pickingOn = false;
  setMarkers([]);
  applyPickState();
}

// 半透明操作态 + 十字光标；关闭时复原不透明（F3／离开步骤②）。
function applyPickState() {
  if (scene) {
    scene.traverse((o) => {
      if (!o.isMesh || !o.material || o.material.emissive === undefined) return;
      o.material.transparent = pickingOn;
      o.material.opacity = pickingOn ? PICK_OPACITY : 1;
      o.material.needsUpdate = true;
    });
  }
  if (host) host.style.cursor = pickingOn ? "crosshair" : "default";
  forceRender();
}

// --- 标号牌：core 推来的显示投影，整体重建（禁前端存真值）--------------------------
function setMarkers(list) {
  for (const m of markers) m.el.remove();
  markers = (list || []).map((d) => ({
    id: d.id, name: d.name,
    pos: new THREE.Vector3(d.pos[0], d.pos[1], d.pos[2]),
    el: makeMarkerEl(d),
  }));
  for (const m of markers) markerLayer.appendChild(m.el);
  updateMarkerPositions();
}

function makeMarkerEl(d) {
  const el = document.createElement("div");
  el.textContent = `${d.id} ${d.name}`;
  Object.assign(el.style, {
    position: "absolute", left: "0", top: "0", zIndex: "3",
    pointerEvents: "none", whiteSpace: "nowrap",
    padding: "2px 6px", borderRadius: "4px",
    background: "rgba(34,48,61,0.92)", border: "1px solid #2f6feb",
    color: "#e6edf3", fontWeight: "600", lineHeight: "1.2",
    transform: "translate(-50%,-130%)",
  });
  return el;
}

// 把每个标号牌的世界坐标投到屏幕；相机背后/远平面外则隐藏；字号随距离在保底与最大之间插值。
function updateMarkerPositions() {
  if (!camera || !markerLayer || !host) return;
  // lookAt 钩子在 renderer.render 之前触发，此时 matrixWorldInverse 还是上一帧的；自行刷新，
  // 使 project() 用到当前位姿（projectionMatrix 由 loader 在 resize 时已更新，沿用即可）。
  camera.updateMatrixWorld();
  camera.matrixWorldInverse.copy(camera.matrixWorld).invert();
  const w = host.clientWidth, h = host.clientHeight;
  for (const m of markers) {
    _v.copy(m.pos).project(camera);
    if (_v.z > 1) { m.el.style.display = "none"; continue; }
    m.el.style.display = "";
    m.el.style.left = ((_v.x * 0.5 + 0.5) * w).toFixed(1) + "px";
    m.el.style.top = ((-_v.y * 0.5 + 0.5) * h).toFixed(1) + "px";
    const dist = camera.position.distanceTo(m.pos);
    const t = clamp((MARKER_FAR_MM - dist) / (MARKER_FAR_MM - MARKER_NEAR_MM), 0, 1);
    m.el.style.fontSize =
      (MARKER_MIN_FONT + (MARKER_MAX_FONT - MARKER_MIN_FONT) * t).toFixed(1) + "px";
  }
}

// --- 手势：左键取点（捕获阶段拦下、不放行给 loader 旋转）；移动悬停高亮 --------------
function bindGestures() {
  host.addEventListener("pointerdown", onDownCapture, true);
  host.addEventListener("pointerup", onUp);
  host.addEventListener("pointermove", onMove);
}

function onDownCapture(e) {
  if (e.button !== 0) return;     // 右键/中键：放行 → loader 旋转
  e.stopPropagation();            // 左键：不再到达画布 → loader 不旋转
  downX = e.clientX;
  downY = e.clientY;
}

function onUp(e) {
  if (e.button !== 0 || !pickingOn) return;
  if (Math.hypot(e.clientX - downX, e.clientY - downY) >= CLICK_SLOP_PX) return; // 拖拽不取点
  const hit = pickAt(e.clientX, e.clientY);
  if (hit) sendPickFace(hit);
}

function onMove(e) {
  if (!pickingOn || e.buttons !== 0) { clearHover(); return; }  // 拖拽中（含右键旋转）不悬停
  hoverAt(e.clientX, e.clientY);
}

function toNdc(clientX, clientY) {
  const r = host.getBoundingClientRect();
  _ndc.x = ((clientX - r.left) / Math.max(r.width, 1)) * 2 - 1;
  _ndc.y = -((clientY - r.top) / Math.max(r.height, 1)) * 2 + 1;
  return _ndc;
}

function pickTargets() {
  const out = [];
  if (scene) scene.traverse((o) => {
    if (o.isMesh && o.userData && o.userData.id !== undefined) out.push(o);
  });
  return out;
}

function pickAt(clientX, clientY) {
  if (!scene || !camera) return null;
  raycaster.setFromCamera(toNdc(clientX, clientY), camera);
  const hits = raycaster.intersectObjects(pickTargets(), false);
  return hits.length ? toPickPayload(hits[0]) : null;
}

// hit.face.a/b/c ＝ tris[faceIndex] 的三顶点；getBarycoord 返回 (权重a,权重b,权重c)。
// face_point.py 口径 u＝V1 权重、v＝V2 权重 ⇒ u=bc.y、v=bc.z（V0=bc.x=1-u-v）。
function toPickPayload(hit) {
  const f = hit.face;
  if (!f) return null;
  const pos = hit.object.geometry.attributes.position;
  const local = hit.object.worldToLocal(hit.point.clone());
  _a.fromBufferAttribute(pos, f.a);
  _b.fromBufferAttribute(pos, f.b);
  _c.fromBufferAttribute(pos, f.c);
  if (THREE.Triangle.getBarycoord(local, _a, _b, _c, _bc) === null) return null;
  return { mesh_id: hit.object.userData.id, face_id: hit.faceIndex, u: _bc.y, v: _bc.z };
}

function sendPickFace(hit) {
  if (window.bridge) window.bridge.on_view_msg("pick.face", JSON.stringify(hit));
  else console.log("[pick] 桥未就绪，丢弃 pick.face:", hit);
}

function hoverAt(clientX, clientY) {
  if (!scene || !camera) return;
  raycaster.setFromCamera(toNdc(clientX, clientY), camera);
  const hits = raycaster.intersectObjects(pickTargets(), false);
  const mesh = hits.length ? hits[0].object : null;
  if (mesh === hoverMesh) return;
  clearHover();
  if (mesh) {
    hoverMesh = mesh;
    hoverEmissive = mesh.material.emissive.getHex();
    hoverIntensity = mesh.material.emissiveIntensity;
    mesh.material.emissive.setHex(HOVER_EMISSIVE);
    mesh.material.emissiveIntensity = 0.6;
  }
  forceRender();
}

function clearHover() {
  if (!hoverMesh) return;
  hoverMesh.material.emissive.setHex(hoverEmissive);
  hoverMesh.material.emissiveIntensity = hoverIntensity;
  hoverMesh = null;
  forceRender();
}

function main() {
  host = document.getElementById("scene-host");
  if (!host) { console.error("[pick] 找不到 #scene-host"); return; }
  markerLayer = document.createElement("div");
  markerLayer.style.cssText =
    "position:absolute;inset:0;pointer-events:none;z-index:3;overflow:hidden";
  host.appendChild(markerLayer);
  installSceneHooks();
  bindDispatch();
  bindGestures();
}

main();

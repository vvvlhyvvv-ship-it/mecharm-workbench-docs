// view/js/loader.js — 中部三维视口渲染（T05）。
//
// 职责：接收桥 mesh.load 建 three.js 场景、hl.set 高亮与相机飞到、空态显隐、轨道相机。
// 红线（04 §7.2-G14 ①）：本文件**只做显示**——不解析 CAD、不做任何几何/法向/拾取判定，
// 那些全在 core；face_map/face_index 不下发到此（见 core.geometry.tessellate）。
// three.module.js 为 vendored（禁 CDN）。接线：bridge.js 先注册 window.__mecharm_dispatch，
// 本文件包裹它、截走 mesh.load/hl.set，其余（ping/invalidate/未知）交回 bridge.js。
// 模块按 index.html 注册顺序执行（bridge 在前），故包裹时原分发函数已就位。
//
// 渲染策略：**按需同步重绘**（render-on-demand）——本单视口是静态 CAD 显示，无逐帧动画
// （轴动 60fps 插值是 T07 的 pose.update，届时再引 rAF 循环）。每次状态变化（载入/高亮/
// 旋转/缩放/尺寸）末尾直接 render()，空闲不耗 CPU，且在页面不可见时仍能完成一帧（便于自测）。

import * as THREE from "../vendor/three.module.js";

const BG = 0x16202a;            // 与 app.css --bg-deep 一致（02 §4 深色底，防白屏）
const BASE = 0x8a97a3;          // 零件常态色：深色金属灰
const SEM = { ok: 0x2f6feb, warn: 0xd9a520, deny: 0xb3261e };  // 02 §4 颜色语义

let renderer, scene, camera, host, emptyEl;
let group;                       // 全部部件 Mesh 的容器
const meshes = new Map();        // part id -> Mesh（高亮/飞到按 id 取）
const orbit = { theta: 0.7, phi: 1.05, radius: 300 };
const target = new THREE.Vector3();
let dragging = false, lastX = 0, lastY = 0;

function init() {
  host = document.getElementById("scene-host");
  emptyEl = document.getElementById("empty-scene");
  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setClearColor(BG, 1);
  host.appendChild(renderer.domElement);
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100000);
  group = new THREE.Group();
  scene.add(group);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x3a4652, 0.9));
  const key = new THREE.DirectionalLight(0xffffff, 0.85);
  key.position.set(1, 1.4, 1);
  scene.add(key);
  bindEvents();
  resize();
}

function resize() {
  const w = host.clientWidth || window.innerWidth;
  const h = host.clientHeight || window.innerHeight;
  renderer.setSize(w, h);
  camera.aspect = w / Math.max(h, 1);
  camera.updateProjectionMatrix();
  render();
}

function bindEvents() {
  window.addEventListener("resize", resize);
  const el = renderer.domElement;
  el.addEventListener("pointerdown", (e) => {
    dragging = true; lastX = e.clientX; lastY = e.clientY;
  });
  window.addEventListener("pointerup", () => { dragging = false; });
  window.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    orbit.theta -= (e.clientX - lastX) * 0.005;
    orbit.phi = clamp(orbit.phi - (e.clientY - lastY) * 0.005, 0.05, Math.PI - 0.05);
    lastX = e.clientX; lastY = e.clientY;
    render();
  });
  el.addEventListener("wheel", (e) => {
    e.preventDefault();
    orbit.radius *= e.deltaY > 0 ? 1.1 : 0.9;
    render();
  }, { passive: false });
}

function clamp(v, lo, hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

// 把球坐标轨道相机摆到 target 周围并重绘一帧（按需渲染的唯一出口）。
function render() {
  const { theta, phi, radius } = orbit;
  camera.position.set(
    target.x + radius * Math.sin(phi) * Math.cos(theta),
    target.y + radius * Math.cos(phi),
    target.z + radius * Math.sin(phi) * Math.sin(theta),
  );
  camera.lookAt(target);
  renderer.render(scene, camera);
}

// --- 桥消息：mesh.load（壳→视口，分批；payload.reset 为真先清场）-------------------
function onMeshLoad(payload) {
  if (payload.reset) clearModel();
  for (const p of payload.parts || []) {
    const mesh = decodePart(p);
    if (mesh) { group.add(mesh); meshes.set(mesh.userData.id, mesh); }
  }
  if (meshes.size > 0) {
    setEmpty(false);
    if (payload.reset) fitAll();      // 首批：相机适配整体包围盒
  }
  render();
}

function clearModel() {
  for (const m of meshes.values()) {
    group.remove(m);
    m.geometry.dispose();
    m.material.dispose();
  }
  meshes.clear();
}

// 顶点 Float32 小端、索引 Uint32 小端（core.geometry.encode_mesh_parts 的载荷口径）。
function decodePart(p) {
  const vBuf = b64ToBytes(p.vertices).buffer;
  const tBuf = b64ToBytes(p.tris).buffer;
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(vBuf), 3));
  geo.setIndex(new THREE.BufferAttribute(new Uint32Array(tBuf), 1));
  const mat = new THREE.MeshStandardMaterial({
    color: BASE, metalness: 0.25, roughness: 0.65, flatShading: true,
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.userData.id = p.id;
  mesh.userData.name = p.name;
  return mesh;
}

function b64ToBytes(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

// --- 桥消息：hl.set（壳→视口，高亮部件列表 + 颜色语义；focus 为真则相机飞到）--------
function onHighlight(payload) {
  for (const m of meshes.values()) {
    m.material.emissive.setHex(0x000000);
    m.material.emissiveIntensity = 0;
  }
  const sem = SEM[payload.semantic] !== undefined ? SEM[payload.semantic] : SEM.ok;
  const box = new THREE.Box3();
  for (const id of payload.ids || []) {
    const m = meshes.get(id);
    if (!m) continue;
    m.material.emissive.setHex(sem);
    m.material.emissiveIntensity = 0.6;
    box.expandByObject(m);
  }
  if (payload.focus && !box.isEmpty()) flyTo(box);
  render();
}

function flyTo(box) {
  target.copy(box.getCenter(new THREE.Vector3()));
  orbit.radius = Math.max(box.getSize(new THREE.Vector3()).length() * 1.4, 1);
}

function fitAll() {
  const box = new THREE.Box3().setFromObject(group);
  if (!box.isEmpty()) flyTo(box);
}

function setEmpty(visible) {
  if (emptyEl) emptyEl.classList.toggle("hidden", !visible);
}

// 包裹 bridge.js 的统一分发入口：截走本单的两类业务消息，其余交回原函数。
function bindDispatch() {
  const prev = window.__mecharm_dispatch;
  window.__mecharm_dispatch = function (msg) {
    const type = msg && msg.type;
    if (type === "mesh.load") { onMeshLoad(msg.payload || {}); return; }
    if (type === "hl.set") { onHighlight(msg.payload || {}); return; }
    if (prev) prev(msg);
  };
}

function main() {
  try {
    init();
  } catch (err) {
    console.error("[loader] 视口初始化失败:", err);
    const el = document.getElementById("bridge-state");
    if (el) el.textContent = "视口：三维内核不可用（" + err.message + "）";
    return;
  }
  bindDispatch();
  render();
}

main();

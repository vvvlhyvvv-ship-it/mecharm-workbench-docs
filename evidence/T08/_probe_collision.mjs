// evidence/T08/_probe_collision.mjs — 取证探针（⛔ 非交付件、⛔ 不放 view/，只由
// _drive_viewport.py 动态注入；等价于合并后 collision.js 之前的一条注册）。
//
// 为什么需要它：loader.js／collision.js 都把 scene 留在模块私有变量 ⇒ 页面上下文里读不到场景图，
// 无法核对「视口到底画了什么」。本探针与它们共用**同一个** three 模块实例（相对路径解析到同一个
// file: URL），故包裹 Object3D.prototype.add 即可看到 collision.js 加进场景的每个显示对象。
// 仅观察，原实现照旧 apply；⛔ 不改任何显示对象、⛔ 不参与判定。
import * as THREE from "../../view/vendor/three.module.js";

let scene = null;
const proto = THREE.Object3D.prototype;
const origAdd = proto.add;
proto.add = function (child) {
  if (this.isScene) scene = this;
  else if (this.parent && this.parent.isScene) scene = this.parent;
  return origAdd.apply(this, arguments);
};

function round(v) { return Math.round(v * 1e3) / 1e3; }

// 报警条：collision.js 用内联样式挂在 #scene-host 下、z-index 5（⛔ 没新增 CSS 选择器）。
function banner() {
  const host = document.getElementById("scene-host");
  if (!host) return null;
  for (const el of Array.from(host.children)) {
    if (el.style && el.style.zIndex === "5") {
      return { text: el.textContent, background: el.style.background || el.style.backgroundColor,
               color: el.style.color, display: el.style.display || "（默认＝显示）" };
    }
  }
  return null;
}

function layer() {
  if (!scene) return null;
  return scene.getObjectByName("collision-layer") || null;
}

function marks() {
  const group = layer();
  if (!group) return [];
  const out = [];
  for (const o of group.children) {
    out.push({
      name: o.name,
      type: o.type,
      pos: [round(o.position.x), round(o.position.y), round(o.position.z)],
      scale: round(o.scale.x),
      color: "#" + o.material.color.getHexString(),
      opacity: round(o.material.opacity),
      depthTest: o.material.depthTest,
      renderOrder: o.renderOrder,
      pickable: o.userData && o.userData.id !== undefined,   // 须恒 false（否则被 pick.js 当部件）
    });
  }
  return out;
}

// 障碍侧高亮：loader.js 的 hl.set 把命中部件的 emissive 染成 SEM 色 ⇒ 读回发光色即证高亮生效。
function glowing() {
  if (!scene) return [];
  const out = [];
  scene.traverse((o) => {
    if (!o.isMesh || !o.material || !o.material.emissive) return;
    const hex = o.material.emissive.getHex();
    if (hex !== 0 && o.material.emissiveIntensity > 0) {
      out.push({ id: o.userData.id, name: o.userData.name, emissive: "#" + o.material.emissive.getHexString(),
                 intensity: round(o.material.emissiveIntensity) });
    }
  });
  return out;
}

// 活动相机：loader 每次 render() 末尾都调 camera.lookAt(target)，且 lookAt 确为**原型继承**
// （实例不自有）⇒ 包它即可拿到相机，用来证明 collision.focus 触发了 loader 的 flyTo。
let cam = null;
const origLookAt = proto.lookAt;
proto.lookAt = function () {
  if (this.isCamera) cam = this;
  return origLookAt.apply(this, arguments);
};

window.__probe_collision = {
  dump() {
    const group = layer();
    return { sceneReady: !!scene, banner: banner(), layerFound: !!group,
             markCount: group ? group.children.length : 0, marks: marks(), glowing: glowing(),
             cameraPos: cam ? [round(cam.position.x), round(cam.position.y),
                               round(cam.position.z)] : null };
  },
};

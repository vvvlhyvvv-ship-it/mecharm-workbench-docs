// evidence/T07/_probe.mjs — 取证探针（⛔ 非交付件、⛔ 不放 view/，只由 _drive_shell_path.py 动态注入）。
//
// 为什么需要它：loader.js 把 scene／renderer 留在模块私有变量，path.js 也一样 ⇒ 页面上下文里
// 拿不到场景图，无法直接核对「视口画了什么」。本探针与 path.js 共用**同一个** three 模块实例
// （相对路径解析到同一个 file: URL），故包裹 Object3D.prototype.add 就能看到 path.js 加进场景的
// 每个显示对象：段折线的名字／颜色、箭头数量、工具标记的世界坐标。仅观察，原实现照旧 apply。
import * as THREE from "../../view/vendor/three.module.js";

const seen = [];
const proto = THREE.Object3D.prototype;
const origAdd = proto.add;
proto.add = function (child) {
  seen.push(child);
  return origAdd.apply(this, arguments);
};

function round(value) {
  return Math.round(value * 1e6) / 1e6;
}

function colorOf(obj) {
  const mat = obj.material || (obj.line && obj.line.material) || null;
  return mat && mat.color ? "0x" + mat.color.getHex().toString(16) : null;
}

function describe(obj) {
  const world = obj.getWorldPosition(new THREE.Vector3());
  return {
    name: obj.name || "",
    type: obj.type,
    segId: obj.userData && obj.userData.segId !== undefined ? obj.userData.segId : null,
    // pick.js 只把带 userData.id 的网格当拾取目标：本单的显示对象必须**不带**它
    pickable: !!(obj.userData && obj.userData.id !== undefined),
    color: colorOf(obj),
    visible: obj.visible,
    world: [round(world.x), round(world.y), round(world.z)],
  };
}

function mine() {
  // 只报**仍挂在场景图上**的对象：path.js 每次 path.show 都会 group.remove 旧段（parent 变 null），
  // 若不过滤，历次重建的旧段会一起报出来，折线数看着翻倍（实测踩过）。
  return seen.filter((o) => o.parent
                           && (/^path-seg-/.test(o.name) || o.name === "tool-marker"
                               || o.type === "ArrowHelper"));
}

window.__probe = {
  dump() {
    const items = mine();     // 活对象（仍在场景图上）
    return {
      added_total: seen.length,
      lines: items.filter((o) => /^path-seg-/.test(o.name)).length,
      arrows: items.filter((o) => o.type === "ArrowHelper").length,
      markers: items.filter((o) => o.name === "tool-marker").length,
      any_pickable: items.some((o) => o.pickable),
      items: items.map(describe),
    };
  },
};

// view/js/bridge.js — 视口侧桥引导（T02 只做通路 + echo，不实现业务消息）。
// 依赖 qwebchannel.js 已先加载（见 index.html 注册顺序）。
// 03 §5 业务 type（mesh.load/pose.update/path.show/pick.enable/hl.set/pick.face/cam.view）
// 由后续单接线，本文件只处理 ping → 回 pong，以及 invalidate 的占位提示。

const stateEl = document.getElementById("bridge-state");

function setState(text, ready) {
  if (!stateEl) return;
  stateEl.textContent = text;
  stateEl.classList.toggle("ready", !!ready);
}

// 壳→视口 的统一分发入口（app/bridge.py 的 call_view 调用此函数）。
window.__mecharm_dispatch = function (msg) {
  const type = msg && msg.type;
  if (type === "ping") {
    const payload = msg.payload || {};
    // 回 echo：经 QWebChannel 调 Python 侧 Bridge.on_view_msg(type, jsonString)
    window.bridge.on_view_msg("pong", JSON.stringify({ echo: payload }));
    setState("桥：echo 双向通路正常", true);
    return;
  }
  if (type === "invalidate") {
    // 换臂结果作废的占位提示；真正清空点位/路径由 T06/T07 接线。
    setState("桥：已收到结果作废广播", true);
    return;
  }
  console.log("[bridge] 未处理的壳消息:", type);
};

function initChannel() {
  if (!window.qt || !window.qt.webChannelTransport) {
    setState("桥：传输通道不可用", false);
    return;
  }
  new QWebChannel(window.qt.webChannelTransport, function (channel) {
    window.bridge = channel.objects.bridge;
    setState("桥：已连接", true);
  });
}

initChannel();

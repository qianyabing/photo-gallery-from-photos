// ---------- state ----------
const state = {
  folder: "__all__",
  sort: "name",
  order: "asc",
  q: "",
  all: [],
  shown: 0,
  batch: 60,
  lbIndex: -1,
  playing: false,
  scale: 1,
  tx: 0, ty: 0,
};

const $ = (s) => document.querySelector(s);
const grid = $("#grid");
const sentinel = $("#sentinel");

// ---------- helpers ----------
function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
function fmtSize(b) {
  if (b > 1048576) return (b / 1048576).toFixed(1) + " MB";
  if (b > 1024) return Math.round(b / 1024) + " KB";
  return b + " B";
}
function fmtDim(w, h) { return w && h ? `${w}×${h}` : ""; }

// ---------- lazy thumb loading ----------
const io = new IntersectionObserver((entries) => {
  entries.forEach((e) => {
    if (e.isIntersecting) {
      const img = e.target;
      if (img.dataset.src) { img.src = img.dataset.src; img.removeAttribute("data-src"); }
      io.unobserve(img);
    }
  });
}, { rootMargin: "250px" });

// ---------- folders ----------
async function loadFolders() {
  const d = await (await fetch("/api/folders", { cache: "no-store" })).json();
  const list = $("#folders");
  list.innerHTML = "";
  const mk = (label, val) => {
    const el = document.createElement("div");
    el.className = "folder" + (val === state.folder ? " active" : "");
    el.textContent = label;
    el.onclick = () => { state.folder = val; markFolders(); refresh(); };
    return el;
  };
  list.appendChild(mk("全部图片", "__all__"));
  d.folders.forEach((f) => list.appendChild(mk(f === "" ? "根目录" : f, f)));
}
function markFolders() {
  document.querySelectorAll("#folders .folder").forEach((el) => {
    const label = el.textContent;
    const val = label === "全部图片" ? "__all__" : (label === "根目录" ? "" : label);
    el.classList.toggle("active", val === state.folder);
  });
}

// ---------- images ----------
async function refresh() {
  const p = new URLSearchParams({
    folder: state.folder, sort: state.sort, order: state.order, q: state.q,
  });
  const d = await (await fetch("/api/images?" + p, { cache: "no-store" })).json();
  state.all = d.images;
  state.shown = 0;
  grid.innerHTML = "";
  $("#empty").classList.toggle("hidden", d.total > 0);
  loadMore();
  $("#count").textContent = d.total + " 张";
}

function makeCard(it) {
  const card = document.createElement("div");
  card.className = "card";
  const img = document.createElement("img");
  img.dataset.src = it.thumb;
  img.alt = it.name;
  img.onload = () => img.classList.add("loaded");
  const info = document.createElement("div");
  info.className = "info";
  info.innerHTML =
    `<span class="nm">${esc(it.name)}</span>` +
    `<span class="meta">${fmtDim(it.w, it.h)} · ${fmtSize(it.size)}</span>`;
  card.appendChild(img);
  card.appendChild(info);
  card.onclick = () => openLightbox(it.id);
  io.observe(img);
  return card;
}

function loadMore() {
  const next = state.all.slice(state.shown, state.shown + state.batch);
  const frag = document.createDocumentFragment();
  next.forEach((it) => frag.appendChild(makeCard(it)));
  grid.appendChild(frag);
  state.shown += next.length;
}

const ioSent = new IntersectionObserver((es) => {
  es.forEach((e) => {
    if (e.isIntersecting && state.shown < state.all.length) loadMore();
  });
}, { rootMargin: "500px" });
ioSent.observe(sentinel);

// ---------- lightbox ----------
function openLightbox(id) {
  state.lbIndex = state.all.findIndex((i) => i.id === id);
  if (state.lbIndex < 0) return;
  $("#lb").classList.add("open");
  document.body.style.overflow = "hidden";
  showLb();
}
function showLb() {
  const it = state.all[state.lbIndex];
  if (!it) return;
  resetZoom();
  const im = $("#lbImg");
  im.src = it.full;
  $("#lbCap").innerHTML =
    `<b>${esc(it.name)}</b> · ${fmtDim(it.w, it.h)} · ${fmtSize(it.size)} · ` +
    `<span class="dim">${esc(it.folder || "根目录")}</span>`;
}
function closeLb() {
  $("#lb").classList.remove("open");
  stopSlide();
  document.body.style.overflow = "";
}
function nav(d) {
  state.lbIndex = (state.lbIndex + d + state.all.length) % state.all.length;
  showLb();
}

// zoom + pan
function resetZoom() { state.scale = 1; state.tx = 0; state.ty = 0; applyZoom(); }
function applyZoom() {
  $("#lbImg").style.transform =
    `scale(${state.scale}) translate(${state.tx}px, ${state.ty}px)`;
}
function zoom(d) {
  state.scale = Math.min(5, Math.max(0.5, state.scale + d));
  if (state.scale === 1) { state.tx = 0; state.ty = 0; }
  applyZoom();
}
let panning = false, sx = 0, sy = 0;
$("#lbImg").addEventListener("mousedown", (e) => {
  if (state.scale > 1) { panning = true; sx = e.clientX - state.tx; sy = e.clientY - state.ty; }
});
window.addEventListener("mousemove", (e) => {
  if (panning) { state.tx = e.clientX - sx; state.ty = e.clientY - sy; applyZoom(); }
});
window.addEventListener("mouseup", () => (panning = false));
$("#lbImg").addEventListener("wheel", (e) => {
  e.preventDefault(); zoom(e.deltaY < 0 ? 0.25 : -0.25);
}, { passive: false });

// slideshow
let slideTimer = null;
function startSlide() {
  state.playing = true; $("#playBtn").textContent = "⏸";
  slideTimer = setInterval(() => nav(1), 3000);
}
function stopSlide() {
  state.playing = false; $("#playBtn").textContent = "▶";
  if (slideTimer) clearInterval(slideTimer);
}
function toggleSlide() { state.playing ? stopSlide() : startSlide(); }
function toggleFs() {
  if (!document.fullscreenElement) $("#lb").requestFullscreen?.();
  else document.exitFullscreen?.();
}

// wiring
$("#rescan").onclick = async () => {
  const btn = $("#rescan");
  const old = btn.textContent;
  btn.textContent = "扫描中…";
  btn.disabled = true;
  try {
    await fetch("/api/refresh", { cache: "no-store" });
    await loadFolders();
    await refresh();
  } finally {
    btn.textContent = old;
    btn.disabled = false;
  }
};
$("#prevBtn").onclick = () => nav(-1);
$("#nextBtn").onclick = () => nav(1);
$("#closeBtn").onclick = closeLb;
$("#playBtn").onclick = toggleSlide;
$("#zoomIn").onclick = () => zoom(0.3);
$("#zoomOut").onclick = () => zoom(-0.3);
$("#fsBtn").onclick = toggleFs;
$("#lb").addEventListener("click", (e) => { if (e.target.id === "lb") closeLb(); });

document.addEventListener("keydown", (e) => {
  if (!$("#lb").classList.contains("open")) return;
  if (e.key === "ArrowRight") nav(1);
  else if (e.key === "ArrowLeft") nav(-1);
  else if (e.key === "Escape") closeLb();
  else if (e.key === " ") { e.preventDefault(); toggleSlide(); }
  else if (e.key === "+" || e.key === "=") zoom(0.3);
  else if (e.key === "-" || e.key === "_") zoom(-0.3);
  else if (e.key === "f" || e.key === "F") toggleFs();
});

// search + sort
let st;
$("#search").addEventListener("input", (e) => {
  clearTimeout(st);
  st = setTimeout(() => { state.q = e.target.value.trim(); refresh(); }, 300);
});
$("#sort").addEventListener("change", (e) => { state.sort = e.target.value; refresh(); });
$("#order").addEventListener("click", (e) => {
  state.order = state.order === "asc" ? "desc" : "asc";
  e.target.textContent = state.order === "asc" ? "↑" : "↓";
  refresh();
});

// ---------- init ----------
loadFolders();
refresh();

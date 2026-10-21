"use strict";

const $ = (s) => document.querySelector(s);
const QUICK = ["mp4", "mp3", "m4a", "wav", "flac", "opus", "webm", "mkv"];
const STORE = "streammate.jobs";
const state = { config: null, jobs: loadJobs(), downloadFormat: "mp4", polling: null };

function loadJobs() {
  try { return JSON.parse(localStorage.getItem(STORE)) || []; } catch { return []; }
}
function saveJobs() {
  try { localStorage.setItem(STORE, JSON.stringify(state.jobs.map(({ id, kind, title, format }) => ({ id, kind, title, format })))); } catch {}
}

/* tema */
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $("#theme").textContent = theme === "dark" ? "tema claro" : "tema escuro";
  try { localStorage.setItem("streammate.theme", theme); } catch {}
}
let savedTheme = null;
try { savedTheme = localStorage.getItem("streammate.theme"); } catch {}
setTheme(savedTheme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));
$("#theme").onclick = () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");

/* abas */
function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === name));
  document.querySelectorAll(".page").forEach((p) => (p.hidden = p.id !== name));
  history.replaceState(null, "", `#${name}`);
}
document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
showTab(location.hash === "#convert" ? "convert" : "download");
addEventListener("hashchange", () => showTab(location.hash === "#convert" ? "convert" : "download"));

/* configuração */
async function api(path, options = {}) {
  const res = await fetch(path, options);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || body.detail || `Erro ${res.status}`);
  return body;
}

async function init() {
  const cfg = (state.config = await api("api/config"));
  $("#version").textContent = cfg.version;
  $("#footer").textContent = `Os arquivos ficam neste servidor por ${cfg.ttl_minutes} min e depois são apagados · limite de ${cfg.max_upload_mb} MB por arquivo`;
  $("#limits").textContent = "mp4 mkv mov avi webm wmv mp3 wav flac ogg m4a vlc m3u … até " + cfg.max_upload_mb + " MB";

  const all = [...Object.keys(cfg.video_formats), ...Object.keys(cfg.audio_formats)];
  const chips = $("#download-formats");
  QUICK.forEach((fmt) => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = fmt; b.dataset.fmt = fmt;
    b.onclick = () => pickDownloadFormat(fmt);
    chips.append(b);
  });
  const others = document.createElement("select");
  others.id = "download-others";
  others.setAttribute("aria-label", "Outros formatos");
  others.innerHTML = `<option value="">outros…</option>` + all.filter((f) => !QUICK.includes(f)).map((f) => `<option>${f}</option>`).join("");
  others.onchange = () => others.value && pickDownloadFormat(others.value);
  chips.append(others);
  pickDownloadFormat("mp4");

  const select = $("#convert-format");
  const group = (label, formats) =>
    `<optgroup label="${label}">` + Object.entries(formats).map(([k, v]) => `<option value="${k}">${k} — ${v}</option>`).join("") + "</optgroup>";
  select.innerHTML = group("Vídeo", cfg.video_formats) + group("Áudio", cfg.audio_formats);
  select.value = "mp4";

  if (!cfg.youtube) {
    $("#youtube-off").hidden = false;
    $("#download-form").querySelectorAll("input, button").forEach((el) => (el.disabled = true));
  }
  render();
  poll();
}

function pickDownloadFormat(fmt) {
  state.downloadFormat = fmt;
  document.querySelectorAll("#download-formats button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.fmt === fmt));
  const others = $("#download-others");
  const inMenu = !QUICK.includes(fmt);
  others.value = inMenu ? fmt : "";
  others.classList.toggle("picked", inMenu);
}

/* baixar */
$("#download-form").onsubmit = async (e) => {
  e.preventDefault();
  const button = e.target.querySelector("button");
  button.disabled = true;
  try {
    const job = await api("api/download", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: $("#url").value.trim(), format: state.downloadFormat }),
    });
    addJobs([job]);
    $("#url").value = "";
  } catch (err) {
    alert(err.message);
  } finally {
    button.disabled = false;
  }
};

/* converter */
const drop = $("#drop");
$("#files").onchange = (e) => { upload([...e.target.files]); e.target.value = ""; };
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => upload([...e.dataTransfer.files]));

function upload(files) {
  if (!files.length) return;
  const form = new FormData();
  files.forEach((f) => form.append("files", f, f.name));
  form.append("format", $("#convert-format").value);

  const box = $("#upload"), bar = $("#upload-bar");
  box.hidden = false; $("#skipped").hidden = true;
  $("#upload-text").textContent = files.length === 1 ? `enviando ${files[0].name}` : `enviando ${files.length} arquivos`;

  const xhr = new XMLHttpRequest();
  xhr.open("POST", "api/convert");
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const pct = e.loaded / e.total;
    bar.style.width = `${pct * 100}%`;
    $("#upload-pct").textContent = `${Math.round(pct * 100)}%`;
  };
  xhr.onload = () => {
    box.hidden = true; bar.style.width = "0";
    let body = {};
    try { body = JSON.parse(xhr.responseText); } catch {}
    if (xhr.status >= 400) return alert(body.error || body.detail || "Falha no envio.");
    addJobs(body.jobs || []);
    const skipped = body.skipped || [];
    const list = $("#skipped");
    list.hidden = !skipped.length;
    list.innerHTML = "";
    skipped.forEach((s) => { const li = document.createElement("li"); li.textContent = `${s.title}: ${s.reason}`; list.append(li); });
  };
  xhr.onerror = () => { box.hidden = true; alert("Não foi possível enviar os arquivos."); };
  xhr.send(form);
}

/* jobs */
function addJobs(list) {
  state.jobs = [...list, ...state.jobs];
  saveJobs(); render(); poll();
}

async function refresh() {
  if (!state.jobs.length) return;
  try {
    const { jobs } = await api(`api/jobs?ids=${state.jobs.map((j) => j.id).join(",")}`);
    const live = new Map(jobs.map((j) => [j.id, j]));
    state.jobs = state.jobs.filter((j) => live.has(j.id)).map((j) => live.get(j.id));
    saveJobs(); render();
  } catch {}
}

function poll() {
  clearTimeout(state.polling);
  refresh().then(() => {
    const active = state.jobs.some((j) => j.state === "queued" || j.state === "running");
    state.polling = setTimeout(poll, active ? 1000 : 8000);
  });
}

const STATUS = { queued: "na fila", running: "processando", done: "pronto", error: "erro", cancelled: "cancelado" };

function size(bytes) {
  if (bytes == null) return "";
  const units = ["B", "KB", "MB", "GB"]; let i = 0, n = bytes;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
}

function render() {
  const tpl = $("#job-row");
  ["download", "convert"].forEach((kind) => {
    const host = $(`#${kind}-jobs`);
    host.replaceChildren(...state.jobs.filter((j) => j.kind === kind).map((job) => {
      const el = tpl.content.firstElementChild.cloneNode(true);
      el.dataset.state = job.state || "queued";
      el.querySelector(".title").textContent = job.filename || job.title;
      el.querySelector(".title").title = job.title;
      el.querySelector(".meta").textContent = job.filename ? size(job.size) : (job.kind === "download" ? "youtube" : "");
      el.querySelector(".fmt").textContent = job.format;
      let status = job.message || STATUS[job.state] || "";
      if (job.state === "running" && job.progress != null) status = `${status} ${Math.round(job.progress * 100)}%`;
      el.querySelector(".status").textContent = status;
      const bar = el.querySelector(".state .bar");
      bar.classList.toggle("spin", job.state === "running" && job.progress == null);
      bar.querySelector("i").style.width = job.state === "running" && job.progress != null ? `${job.progress * 100}%` : "";
      const save = el.querySelector(".save");
      if (job.state === "done") { save.hidden = false; save.href = `api/jobs/${job.id}/file`; save.download = job.filename || ""; }
      el.querySelector(".remove").onclick = async () => {
        state.jobs = state.jobs.filter((j) => j.id !== job.id); saveJobs(); render();
        fetch(`api/jobs/${job.id}`, { method: "DELETE" }).catch(() => {});
      };
      el.querySelector(".remove").textContent = job.state === "running" || job.state === "queued" ? "cancelar" : "remover";
      return el;
    }));
  });
}

init().catch((err) => {
  document.querySelector("main").insertAdjacentHTML("afterbegin", `<p class="notice">Não consegui falar com o servidor: ${err.message}</p>`);
});

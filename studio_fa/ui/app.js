"use strict";

const SAMPLE_TEXT =
  "اپل توی سال هزار و نهصد و هفتاد و شش، توی یه گاراژ کوچیک شروع شد؛ " +
  "استیو جابز و استیو وازنیاک فقط هزار و سیصد دلار پول داشتن. باورت می‌شه؟";
const SAMPLE_SUBS = "اپل در سال ۱۹۷۶ توی یه گاراژ شروع شد.\nSteve Jobs و Wozniak فقط ۱۳۰۰ دلار داشتن!";

const ENV_LABELS = {
  GOOGLE_API_KEY: "کلید Gemini (گوگل)",
  AVALAI_API_KEY: "کلید AvalAI",
  OPENAI_API_KEY: "کلید OpenAI یا gateway",
  ELEVENLABS_API_KEY: "کلید ElevenLabs",
  OPENAI_BASE_URL: "آدرس gateway سازگار با OpenAI",
  SUBTITLE_FONTS_DIR: "پوشه‌ی فونت زیرنویس",
};
const PROVIDER_NOTES = {
  gemini_tts: "Gemini 3.8 مستقیم از گوگل",
  avalai_gemini_tts: "همون صداهای Gemini از راه AvalAI",
  elevenlabs_tts: "ElevenLabs v3",
  openai_tts: "OpenAI یا gateway (بدون صدای بومی فارسی)",
  azure_tts: "Azure، صداهای fa-IR",
  piper_tts: "آفلاین، صدای fa_IR لازم داره",
};

const $ = (sel) => document.querySelector(sel);
const fa = (n, digits = 1) =>
  n == null ? "؟" : Number(n).toLocaleString("fa-IR", { maximumFractionDigits: digits });
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

let voices = [];
let toastTimer;

function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("err", isError);
  el.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), isError ? 7000 : 3500);
}

async function api(path, body) {
  const opts = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json", "X-Studio-FA": "1" }, body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join("، ") : data.detail;
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return data;
}

// ---- tabs ----------------------------------------------------------------

function showTab(name) {
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${name}`));
  history.replaceState(null, "", `#${name}`);
  if (name === "projects") loadProjects();
}

document.querySelectorAll("#nav button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
document.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.goto)));

// ---- status --------------------------------------------------------------

function renderStatus(s) {
  $("#providers").innerHTML = s.providers.map((p, i) => `
    <li>
      <span class="rank">${fa(i + 1)}</span>
      <span class="dot ${p.available ? "ok" : ""}"></span>
      <span class="name">${esc(p.name)}</span>
      <span class="note">${p.available ? esc(PROVIDER_NOTES[p.name] || "") : "تنظیم نشده"}</span>
    </li>`).join("");

  const ready = s.providers.filter((p) => p.available).length;
  $("#tools").innerHTML = `
    <li><span class="dot ${s.ffmpeg ? "ok" : "bad"}"></span>ffmpeg ${s.ffmpeg ? "پیدا شد" : "پیدا نشد"}</li>
    <li><span class="dot ${s.font_dir ? "ok" : "bad"}"></span>فونت Vazirmatn ${s.font_dir ? "نصبه" : "پیدا نشد"}</li>
    <li><span class="dot ${ready ? "ok" : "bad"}"></span>${fa(ready)} ارائه‌دهنده‌ی صدای فارسی آماده</li>`;

  $("#keys-summary").innerHTML = Object.entries(s.env)
    .filter(([name]) => name.endsWith("_KEY"))
    .map(([name, v]) => `<li><span class="dot ${v.set ? "ok" : ""}"></span>${esc(ENV_LABELS[name] || name)}
      <span class="hint">${v.set ? "تنظیم شده" : "خالی"}</span></li>`).join("");

  $("#side-foot").textContent = ready
    ? `صدای فارسی: ${s.providers.find((p) => p.available).name}`
    : "هیچ ارائه‌دهنده‌ی صدایی آماده نیست";
  renderEnvForm(s.env);
}

async function loadStatus() {
  try {
    renderStatus(await api("/api/status"));
  } catch (e) {
    $("#side-foot").textContent = "سرور جواب نمی‌ده";
    toast(`خطا در گرفتن وضعیت: ${e.message}`, true);
  }
}

// ---- keys ----------------------------------------------------------------

function renderEnvForm(env) {
  $("#env-form").innerHTML = Object.entries(env).map(([name, v]) => {
    const secret = name.endsWith("_KEY");
    const placeholder = secret ? (v.set ? "•••••••• (برای عوض کردن، کلید جدید رو بنویس)" : "کلید رو اینجا بذار") : "";
    return `
      <div class="env-row" data-name="${esc(name)}">
        <div class="env-name">${esc(name)}<small>${esc(ENV_LABELS[name] || "")} · ${v.set ? "تنظیم شده" : "خالی"}</small></div>
        <input type="${secret ? "password" : "text"}" autocomplete="off" spellcheck="false"
          placeholder="${esc(placeholder)}" value="${secret ? "" : esc(v.value || "")}">
        <button class="btn small">ذخیره</button>
      </div>`;
  }).join("");

  $("#env-form").querySelectorAll(".env-row").forEach((row) => {
    row.querySelector("button").addEventListener("click", async () => {
      const name = row.dataset.name;
      const value = row.querySelector("input").value.trim();
      if (name.endsWith("_KEY") && !value) {
        toast("کلید خالیه؛ چیزی ذخیره نشد.", true);
        return;
      }
      try {
        renderStatus(await api("/api/env", { name, value }));
        toast(`${ENV_LABELS[name] || name} ذخیره شد.`);
      } catch (e) {
        toast(`ذخیره نشد: ${e.message}`, true);
      }
    });
  });
}

// ---- voice studio --------------------------------------------------------

function clipHTML(c) {
  const fallback = (c.fallback_from || []).map((f) => f.tool).join("، ");
  return `
    <div class="clip">
      <div class="clip-text">${esc(c.text)}</div>
      <audio controls preload="none" src="${esc(c.url)}"></audio>
      <div class="meta">
        <span class="tag accent">${esc(c.voice_id)}</span>
        <span class="tag">${c.model_id.includes("lite") ? "پیش‌نویس" : "نهایی"}</span>
        <span class="tag">${esc(c.selected_tool)}</span>
        <span class="tag">${fa(c.duration)} ثانیه</span>
        <span class="tag">${fa(c.cps)} کاراکتر در ثانیه</span>
        <span class="tag">هزینه: ${c.cost_usd == null ? "نامعلوم" : "$" + Number(c.cost_usd).toFixed(4)}</span>
        ${c.style ? `<span class="tag">لحن: ${esc(c.style)}</span>` : ""}
        ${fallback ? `<span class="tag warn">جایگزین شد؛ خطا داد: ${esc(fallback)}</span>` : ""}
      </div>
    </div>`;
}

async function loadHistory() {
  try {
    const rows = await api("/api/tts/history");
    $("#tts-history").innerHTML = rows.map(clipHTML).join("");
  } catch (e) {
    toast(`تاریخچه نیومد: ${e.message}`, true);
  }
}

function describeVoice() {
  const v = voices.find((x) => x.id === $("#tts-voice").value);
  $("#voice-desc").textContent = v && v.description
    ? `${v.gender || ""} · ${v.persona || ""} — ${v.description}`
    : "";
}

async function loadVoices() {
  try {
    const data = await api("/api/voices");
    voices = data.voices;
    $("#tts-voice").innerHTML = voices.map((v) =>
      `<option value="${esc(v.id)}">${esc(v.id)}${v.gender ? ` — ${v.gender === "female" ? "زن" : v.gender === "male" ? "مرد" : esc(v.gender)}` : ""}</option>`).join("");
    $("#tts-voice").value = voices.some((v) => v.id === "Kore") ? "Kore" : voices[0]?.id;
    describeVoice();
  } catch (e) {
    toast(`لیست صداها نیومد: ${e.message}`, true);
  }
}

function updateCount() {
  const n = $("#tts-text").value.length;
  $("#tts-count").textContent = `${fa(n)} از ${fa(3000)} کاراکتر`;
}

$("#tts-voice").addEventListener("change", describeVoice);
$("#tts-text").addEventListener("input", updateCount);
document.querySelectorAll("#style-chips button").forEach((b) =>
  b.addEventListener("click", () => { $("#tts-style").value = b.dataset.style; }));

$("#tts-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const go = $("#tts-go");
  const status = $("#tts-status");
  go.disabled = true;
  status.classList.remove("err");
  status.textContent = "در حال ساخت صدا…";
  try {
    const clip = await api("/api/tts", {
      text: $("#tts-text").value,
      voice_id: $("#tts-voice").value,
      style: $("#tts-style").value,
      model_id: $("#tts-model").value,
      provider: $("#tts-provider").value,
    });
    const result = $("#tts-result");
    result.innerHTML = `<h2>نتیجه</h2>${clipHTML(clip)}`;
    result.classList.remove("hidden");
    result.querySelector("audio").play().catch(() => {});
    status.textContent = `ساخته شد در ${fa(clip.elapsed)} ثانیه`;
    loadHistory();
  } catch (e) {
    status.classList.add("err");
    status.textContent = e.message;
  } finally {
    go.disabled = false;
  }
});

// ---- subtitles -----------------------------------------------------------

$("#subs-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const go = $("#subs-go");
  const status = $("#subs-status");
  go.disabled = true;
  status.classList.remove("err");
  status.textContent = "در حال رندر…";
  try {
    const lines = $("#subs-lines").value.split("\n").filter((l) => l.trim()).slice(0, 4);
    const data = await api("/api/subtitles/preview", { lines, font_size: Number($("#subs-size").value) || 36 });
    const result = $("#subs-result");
    result.innerHTML = `
      <div class="card-head"><h2>فریم‌ها</h2>
        <span class="hint">جهت: ${data.direction === "rtl" ? "راست به چپ" : "چپ به راست"} ·
        ${data.font_dir ? "فونت Vazirmatn" : "Vazirmatn پیدا نشد؛ فونت جایگزین"}</span></div>
      <div class="frames">${data.frames.map((f) => `<img src="${esc(f)}" alt="">`).join("")}</div>`;
    result.classList.remove("hidden");
    status.textContent = "";
  } catch (e) {
    status.classList.add("err");
    status.textContent = e.message;
  } finally {
    go.disabled = false;
  }
});

// ---- projects / Backlot --------------------------------------------------

async function openBacklot(projectId) {
  toast("Backlot داره باز می‌شه…");
  try {
    const { url } = await api("/api/backlot/open", { project_id: projectId || null });
    window.open(url, "_blank", "noopener");
  } catch (e) {
    toast(`Backlot باز نشد: ${e.message}`, true);
  }
}

async function loadProjects() {
  const list = $("#projects-list");
  list.innerHTML = `<div class="empty">در حال خوندن…</div>`;
  try {
    const rows = await api("/api/projects");
    if (!rows.length) {
      list.innerHTML = `<div class="empty">هنوز تولیدی نیست. اولین ویدیو که شروع بشه، اینجا میاد.</div>`;
      return;
    }
    list.innerHTML = rows.map((p) => `
      <div class="project">
        <span class="dot ${p.live ? "ok" : p.awaiting_human ? "warn" : ""}"></span>
        <div>
          <div class="title">${esc(p.title || p.project_id)}</div>
          <div class="sub">${esc(p.pipeline_type)} ·
            ${p.awaiting_human ? "منتظر تأیید تو" : p.live ? "در حال اجرا" : "متوقف"}
            ${p.active_stage ? ` · مرحله: ${esc(p.active_stage.name || p.active_stage)}` : ""}
            · ${fa(p.scene_count)} صحنه · ${fa(p.render_count)} رندر</div>
        </div>
        <button class="btn ghost small" data-project="${esc(p.project_id)}">باز کردن در Backlot</button>
      </div>`).join("");
    list.querySelectorAll("[data-project]").forEach((b) =>
      b.addEventListener("click", () => openBacklot(b.dataset.project)));
  } catch (e) {
    list.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

$("#projects-refresh").addEventListener("click", loadProjects);
$("#open-library").addEventListener("click", () => openBacklot());
$("#open-library-2").addEventListener("click", () => openBacklot());

// ---- tests ---------------------------------------------------------------

$("#tests-go").addEventListener("click", async () => {
  const go = $("#tests-go");
  const status = $("#tests-status");
  const out = $("#tests-output");
  go.disabled = true;
  status.classList.remove("err");
  status.textContent = "در حال اجرا…";
  try {
    const r = await api("/api/tests/run", {});
    status.textContent = r.ok ? `سبز: ${r.summary}` : `قرمز: ${r.summary}`;
    status.classList.toggle("err", !r.ok);
    out.textContent = r.output;
    out.classList.remove("hidden");
  } catch (e) {
    status.classList.add("err");
    status.textContent = e.message;
  } finally {
    go.disabled = false;
  }
});

// ---- boot ----------------------------------------------------------------

$("#tts-text").value = SAMPLE_TEXT;
$("#subs-lines").value = SAMPLE_SUBS;
updateCount();
const startTab = location.hash.slice(1);
showTab(["home", "voice", "subs", "projects", "keys", "tests"].includes(startTab) ? startTab : "home");
loadStatus();
loadVoices();
loadHistory();

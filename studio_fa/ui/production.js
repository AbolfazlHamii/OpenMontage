"use strict";
// Production pages: wizard, timeline, costs, provider health, style gallery, LLM routing.
// Uses $, api, fa, esc, toast, showTab and voices from app.js.

const STAGE_FA = {
  research: "پژوهش", proposal: "پیشنهاد", script: "متن", scene_plan: "صحنه‌بندی",
  assets: "ساخت رسانه", edit: "تدوین", compose: "رندر", publish: "انتشار",
};
const STATUS_FA = {
  completed: "تمام شده", awaiting_human: "منتظر تأیید شما", in_progress: "در حال انجام",
  failed: "خطا", pending: "شروع نشده",
};
const usd = (n) => (n == null ? "؟" : "$" + Number(n).toFixed(4));

let styleCards = [];
let wizStep = 0;
let wizStyle = null;

// ---- style cards ---------------------------------------------------------

function styleCardHTML(c, selectable) {
  if (c.error) return `<div class="style-card"><h3>${esc(c.name)}</h3><p class="err">${esc(c.error)}</p></div>`;
  const pace = ["hook", "body", "outro"].map((k) => `${fa(c.asl_seconds[k])}ث`).join(" / ");
  return `
    <div class="style-card ${selectable && wizStyle === c.name ? "selected" : ""}" data-style="${esc(c.name)}">
      <div class="swatches">${c.palette.map((p) => `<span style="background:${esc(p)}"></span>`).join("")}</div>
      <h3>${esc(c.title)}</h3>
      <p class="desc">${esc(c.description)}</p>
      <div class="meta">
        <span class="tag">${c.kind === "learned" ? "یادگرفته" : "آماده"}</span>
        <span class="tag">طول نما (هوک/بدنه/پایان): ${pace}</span>
        <span class="tag">${fa(c.words_per_minute, 0)} کلمه در دقیقه</span>
        <span class="tag">زیرنویس: ${esc(c.subtitles)}</span>
      </div>
      <div class="hint">هوک: ${esc(c.hook_beats.join(" ← "))}</div>
      <div class="hint">حرکت: ${esc(c.top_camera_moves.join("، "))} · گذار: ${esc(c.top_transitions.join("، "))}</div>
    </div>`;
}

async function loadStyles() {
  try {
    styleCards = await api("/api/fa/styles");
    $("#styles-gallery").innerHTML = styleCards.map((c) => styleCardHTML(c, false)).join("");
    renderWizStyles();
  } catch (e) {
    toast(`کارت‌های سبک نیامد: ${e.message}`, true);
  }
}

// ---- wizard --------------------------------------------------------------

function renderWizStyles() {
  const box = $("#wiz-styles");
  box.innerHTML = styleCards.filter((c) => !c.error).map((c) => styleCardHTML(c, true)).join("");
  box.querySelectorAll("[data-style]").forEach((el) => el.addEventListener("click", () => {
    wizStyle = el.dataset.style;
    renderWizStyles();
  }));
}

function wizBody() {
  return {
    project_id: $("#wiz-id").value.trim(),
    topic: $("#wiz-topic").value.trim(),
    format: $("#wiz-format").value,
    duration_seconds: Number($("#wiz-duration").value) || 90,
    edit_style: wizStyle || "",
    voice: $("#wiz-voice").value || "Kore",
    voice_style: $("#wiz-voice-style").value,
    budget_usd: Number($("#wiz-budget").value) || 0,
    draft_rounds: Number($("#wiz-rounds").value) || 0,
  };
}

async function showEstimate() {
  const box = $("#wiz-estimate");
  box.textContent = "در حال تخمین…";
  try {
    const e = await api("/api/fa/estimate", wizBody());
    box.innerHTML = `
      <div class="est-row"><strong>پیش‌نویس:</strong> ${usd(e.draft.total_usd)}
        <span class="hint">(${fa(e.draft.images)} تصویر ارزان، ${fa(e.draft.narration_seconds, 0)} ثانیه صدا)</span></div>
      <div class="est-row"><strong>نهایی:</strong> ${usd(e.final.total_usd)}
        <span class="hint">(تصویر ۲K + ${fa(Number($("#wiz-rounds").value))} دور پیش‌نویس؛ زمان تولید با اجرای موازی حدود ${fa(e.final.generation_seconds_parallel, 0)} ثانیه)</span></div>
      <div class="est-row ${e.within_budget ? "ok" : "err"}">${e.within_budget ? "در بودجه است." : "از بودجه بیشتر است؛ بودجه یا طول را تغییر دهید."}</div>
      <div class="hint">قیمت‌ها: ${esc(e.prices_updated)} ${e.warnings.length ? "· " + esc(e.warnings.join("، ")) : ""}</div>`;
    $("#wiz-create").disabled = !e.within_budget;
  } catch (err) {
    box.innerHTML = `<span class="err">${esc(err.message)}</span>`;
  }
}

function setWizStep(n) {
  wizStep = Math.max(0, Math.min(4, n));
  document.querySelectorAll(".wiz-step").forEach((el) => el.classList.toggle("hidden", Number(el.dataset.step) !== wizStep));
  document.querySelectorAll("#wiz-steps li").forEach((li, i) => {
    li.classList.toggle("active", i === wizStep);
    li.classList.toggle("done", i < wizStep);
  });
  $("#wiz-back").disabled = wizStep === 0;
  $("#wiz-next").classList.toggle("hidden", wizStep === 4);
  $("#wiz-create").classList.toggle("hidden", wizStep !== 4);
  if (wizStep === 2 && !styleCards.length) loadStyles();
  if (wizStep === 3 && !$("#wiz-voice").options.length) {
    $("#wiz-voice").innerHTML = (voices || []).map((v) => `<option value="${esc(v.id)}">${esc(v.id)}</option>`).join("");
    $("#wiz-voice").value = "Kore";
  }
  if (wizStep === 4) showEstimate();
}

function wizValid() {
  const b = wizBody();
  if (wizStep === 0 && (b.topic.length < 3 || !/^[a-z0-9][a-z0-9-]{2,60}$/.test(b.project_id))) {
    return "موضوع و شناسه‌ی انگلیسی (حروف کوچک، عدد و خط تیره) لازم است.";
  }
  if (wizStep === 2 && !b.edit_style) return "یک کارت سبک انتخاب کنید.";
  return null;
}

$("#wiz-next").addEventListener("click", () => {
  const problem = wizValid();
  if (problem) return toast(problem, true);
  setWizStep(wizStep + 1);
});
$("#wiz-back").addEventListener("click", () => setWizStep(wizStep - 1));
$("#wiz-budget").addEventListener("change", showEstimate);
$("#wiz-rounds").addEventListener("change", showEstimate);
$("#wiz-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const status = $("#wiz-status");
  status.classList.remove("err");
  status.textContent = "در حال ساخت پروژه…";
  try {
    const r = await api("/api/fa/projects", wizBody());
    status.textContent = `ساخته شد: ${r.project_id}. ${r.next}`;
    toast("پروژه ساخته شد.");
  } catch (e) {
    status.classList.add("err");
    status.textContent = e.message;
  }
});

// ---- timeline ------------------------------------------------------------

async function openTimeline(projectId) {
  showTab("timeline");
  const list = $("#tl-list");
  list.innerHTML = `<li class="empty">در حال خواندن…</li>`;
  try {
    renderTimeline(await api(`/api/fa/projects/${encodeURIComponent(projectId)}/timeline`));
  } catch (e) {
    list.innerHTML = `<li class="empty">${esc(e.message)}</li>`;
  }
}
window.openTimeline = openTimeline;

function renderTimeline(t) {
  $("#tl-title").textContent = `مراحل: ${t.title || t.project_id}`;
  $("#tl-list").innerHTML = t.stages.map((s) => `
    <li class="stage ${esc(s.status)}">
      <span class="dot ${s.status === "completed" ? "ok" : s.status === "awaiting_human" ? "warn" : s.status === "failed" ? "bad" : ""}"></span>
      <div class="stage-body">
        <strong>${esc(STAGE_FA[s.name] || s.name)}</strong>
        <span class="hint">${esc(STATUS_FA[s.status] || s.status)}${s.gated ? " · نیاز به تأیید" : ""}${s.review ? ` · نظر شما: ${s.review === "approve" ? "تأیید" : "رد"}` : ""}</span>
      </div>
      ${s.gated && !t.protected ? `
        <input class="note" placeholder="یادداشت (اختیاری)" data-note="${esc(s.name)}">
        <button class="btn small" data-review="approve" data-stage="${esc(s.name)}">تأیید</button>
        <button class="btn ghost small" data-review="reject" data-stage="${esc(s.name)}">رد</button>` : ""}
    </li>`).join("") + (t.protected ? `<li class="hint">این پروژه قفل است؛ تأیید را در گفت‌وگو با ایجنت بنویسید.</li>` : "");
  document.querySelectorAll("[data-review]").forEach((b) => b.addEventListener("click", async () => {
    const note = document.querySelector(`[data-note="${b.dataset.stage}"]`)?.value || "";
    try {
      const r = await api(`/api/fa/projects/${encodeURIComponent(t.project_id)}/review`,
        { stage: b.dataset.stage, action: b.dataset.review, note });
      toast(`ثبت شد (${r.logged}).`);
      renderTimeline(r.timeline);
    } catch (e) {
      toast(e.message, true);
    }
  }));
}

// ---- costs ---------------------------------------------------------------

function bars(obj) {
  const entries = Object.entries(obj);
  if (!entries.length) return `<div class="empty">هنوز هزینه‌ای ثبت نشده.</div>`;
  const max = Math.max(...entries.map(([, v]) => v), 1e-9);
  return entries.map(([k, v]) => `
    <div class="bar-row"><span class="bar-label">${esc(k)}</span>
      <span class="bar"><span style="width:${(100 * v) / max}%"></span></span>
      <span class="bar-value">${usd(v)}</span></div>`).join("");
}

async function loadCosts() {
  try {
    const c = await api("/api/fa/costs");
    $("#costs-note").textContent = c.note;
    $("#costs-projects").innerHTML = bars(Object.fromEntries(c.projects.map((p) => [p.project_id, p.total_usd])));
    $("#costs-months").innerHTML = bars(c.months);
    $("#costs-tools").innerHTML = bars(c.by_tool);
  } catch (e) {
    toast(`هزینه‌ها نیامد: ${e.message}`, true);
  }
}

// ---- health --------------------------------------------------------------

function healthList(title, rows) {
  return `<div class="card"><h2>${title}</h2><ul class="checks">${rows.map((r) => `
    <li><span class="dot ${r.available ? (r.reachable === false ? "bad" : "ok") : ""}"></span>${esc(r.name)}
      <span class="hint">${r.available ? (r.latency_ms != null ? `${fa(r.latency_ms, 0)} میلی‌ثانیه` : r.reachable === false ? esc(r.error || "در دسترس نیست") : "آماده") : esc(r.reason ? "تنظیم نشده: " + r.reason : "تنظیم نشده")}</span></li>`).join("")}</ul></div>`;
}

async function loadHealth(ping = false) {
  const status = $("#health-status");
  status.textContent = ping ? "در حال آزمایش اتصال…" : "";
  try {
    const h = ping ? await api("/api/fa/health/ping", {}) : await api("/api/fa/health");
    $("#health-grid").innerHTML = healthList("صدا", h.tts) + healthList("تصویر", h.images) + healthList("متن (LLM)", h.llm_profiles);
    status.textContent = `بررسی: ${h.checked_at}`;
  } catch (e) {
    status.textContent = e.message;
  }
}
$("#health-ping").addEventListener("click", () => loadHealth(true));

// ---- learn style ---------------------------------------------------------

function learnBody() {
  return { url: $("#learn-url").value.trim(), name: $("#learn-name").value.trim(),
           duration_seconds: Number($("#learn-duration").value) || 180 };
}

$("#learn-est").addEventListener("click", async () => {
  try {
    const e = await api("/api/fa/styles/learn/estimate", learnBody());
    $("#learn-estimate").innerHTML = `هزینه‌ی تخمینی: <strong>${usd(e.total_usd)}</strong> · ${fa(e.frames)} فریم · ${esc(e.note)}`;
  } catch (err) {
    $("#learn-estimate").innerHTML = `<span class="err">${esc(err.message)}</span>`;
  }
});

$("#learn-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const status = $("#learn-status");
  status.classList.remove("err");
  try {
    const job = await api("/api/fa/styles/learn", learnBody());
    status.textContent = "در حال یادگیری… (دانلود و تحلیل چند دقیقه طول می‌کشد)";
    const timer = setInterval(async () => {
      const j = await api(`/api/fa/jobs/${job.id}`);
      if (j.status === "running") return;
      clearInterval(timer);
      status.textContent = j.status === "done"
        ? `کارت ساخته شد: ASL ${fa(j.result.asl_seconds, 2)} ثانیه، هزینه ${usd(j.result.cost_usd)}`
        : j.error;
      status.classList.toggle("err", j.status !== "done");
      loadStyles();
    }, 4000);
  } catch (e) {
    status.classList.add("err");
    status.textContent = e.message;
  }
});

// ---- LLM routing ---------------------------------------------------------

const TIER_FA = { bulk: "انبوه (bulk)", worker: "کارگر (worker)", vision_bulk: "تصویر انبوه", premium: "ممتاز (فقط headless)" };

async function loadRouting() {
  try {
    const r = await api("/api/fa/llm-routing");
    const profiles = Object.keys(r.profiles);
    const models = Object.keys(r.prices.avalai || {});
    $("#routing-grid").innerHTML = Object.keys(TIER_FA).map((tier) => `
      <form class="card routing" data-tier="${tier}">
        <h2>${TIER_FA[tier]}</h2>
        ${(r.tiers[tier] || []).map((e, i) => `
          <div class="fields">
            <label>پروفایل <select name="p${i}">${profiles.map((p) => `<option ${p === e.profile ? "selected" : ""}>${esc(p)}</option>`).join("")}</select></label>
            <label>مدل <input name="m${i}" list="model-list" dir="ltr" value="${esc(e.model)}"></label>
            <span class="hint">${r.profiles[e.profile]?.available ? "کلید دارد" : "کلید ندارد"}</span>
          </div>`).join("")}
        <div class="actions"><button class="btn small">ذخیره</button></div>
      </form>`).join("") + `
      <div class="card"><h2>حالت اجرا</h2><p>${r.mode === "interactive" ? "تعاملی: سطح ممتاز خود ایجنت است و API صدا زده نمی‌شود." : "headless"}</p>
        <p class="hint">مقایسه‌ی مدل‌ها: <code>${esc(r.bakeoff)}</code></p></div>
      <datalist id="model-list">${models.map((m) => `<option value="${esc(m)}">`).join("")}</datalist>`;
    document.querySelectorAll("form.routing").forEach((f) => f.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const entries = [];
      for (let i = 0; f.elements[`p${i}`]; i++) {
        entries.push({ profile: f.elements[`p${i}`].value, model: f.elements[`m${i}`].value.trim() });
      }
      try {
        await api("/api/fa/llm-routing", { tier: f.dataset.tier, entries });
        toast("ذخیره شد در config/llm_routing.yaml");
      } catch (e) {
        toast(e.message, true);
      }
    }));
  } catch (e) {
    toast(`مسیریابی نیامد: ${e.message}`, true);
  }
}

// ---- tab hooks -----------------------------------------------------------

document.addEventListener("tab", (ev) => {
  const name = ev.detail;
  if (name === "new") setWizStep(wizStep);
  if (name === "costs") loadCosts();
  if (name === "health") loadHealth(false);
  if (name === "styles") loadStyles();
  if (name === "routing") loadRouting();
});
// app.js has already replaced the hash during boot; startTab is its copy of the original.
const startHash = startTab;
if (["new", "costs", "health", "styles", "routing"].includes(startHash)) {
  document.dispatchEvent(new CustomEvent("tab", { detail: startHash }));
}
if (startHash.startsWith("timeline=")) openTimeline(decodeURIComponent(startHash.slice(9)));

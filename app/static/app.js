const form = document.getElementById("form");
const submitBtn = document.getElementById("submit");
const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");
const screenplayEl = document.getElementById("screenplay");
const structuredEl = document.getElementById("view-structured");
const modeBadge = document.getElementById("mode-badge");

function show(el) { el.classList.remove("hidden"); }
function hide(el) { el.classList.add("hidden"); }

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

const structuredView = document.getElementById("view-structured");
const timelineView = document.getElementById("view-timeline");
const screenplayView = document.getElementById("view-screenplay");

// Tab switching
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    const view = tab.dataset.view;
    screenplayView.classList.toggle("hidden", view !== "screenplay");
    structuredView.classList.toggle("hidden", view !== "structured");
    timelineView.classList.toggle("hidden", view !== "timeline");
  });
});

function voiceStr(v) {
  const parts = [v.gender, v.age_range, `${v.pitch} pitch`, `${v.pace} pace`];
  if (v.accent && v.accent !== "neutral") parts.push(v.accent);
  if (v.timbre) parts.push(v.timbre);
  return parts.filter(Boolean).join(", ");
}

function renderStructured(script) {
  let html = `<h2>${esc(script.title)}</h2>`;
  html += `<p class="meta"><em>"${esc(script.logline)}"</em></p>`;
  html += `<p class="meta">${esc(script.genre)} · ${esc(script.language)} · ~${script.estimated_duration_minutes} min · audio drama</p>`;
  html += `<p>${esc(script.synopsis)}</p>`;

  html += `<h3>Cast &amp; Voices</h3>`;
  const n = script.narrator;
  html += `<div class="char">
    <h3>Narrator <span class="meta">— ${esc(n.style)}</span></h3>
    <p class="meta"><b>Voice:</b> ${esc(voiceStr(n.voice))}</p>
  </div>`;
  for (const c of script.characters) {
    html += `<div class="char">
      <h3>${esc(c.name)} <span class="meta">[${esc(c.id)}] — ${esc(c.role)}</span></h3>
      <p>${esc(c.description)}</p>
      <p class="meta"><b>Wants:</b> ${esc(c.motivation)}</p>
      <p class="meta"><b>Arc:</b> ${esc(c.emotional_arc)}</p>
      <p class="meta"><b>Voice:</b> ${esc(voiceStr(c.voice))}</p>
    </div>`;
  }

  html += `<h3>Scenes</h3>`;
  for (const s of script.scenes) {
    html += `<div class="scene">
      <h3>Scene ${s.number}. ${esc(s.heading)}</h3>
      <p class="meta">[${esc(s.mood)}] ${esc(s.summary)}</p>
      ${s.ambience ? `<p class="meta">🔊 Ambience: ${esc(s.ambience)}</p>` : ""}`;
    for (const el of s.elements) {
      if (el.kind === "narration" && el.narration) {
        html += `<p class="action-el"><b>Narrator:</b> ${esc(el.narration)}</p>`;
      } else if (el.kind === "sound" && el.sound) {
        html += `<p class="sfx">&gt;&gt; ${esc(el.sound.cue_type)}: ${esc(el.sound.description)}</p>`;
      } else if (el.kind === "dialogue" && el.dialogue) {
        const d = el.dialogue;
        html += `<div class="line">
          <span class="who">${esc(d.character)}</span>
          <span class="emo">(${esc(d.emotion)} ${Number(d.intensity).toFixed(1)}${d.direction ? ", " + esc(d.direction) : ""})</span><br>
          ${esc(d.line)}
        </div>`;
      }
    }
    html += `</div>`;
  }
  structuredEl.innerHTML = html;
}

function renderTimeline(script) {
  let html = `<p class="meta">${script.timeline.length} ordered audio events. This is what the text-to-speech / mixing stage consumes.</p>`;
  html += `<table class="tl"><thead><tr><th>#</th><th>Sc</th><th>Type</th><th>Speaker</th><th>Emotion</th><th>Text / Sound</th></tr></thead><tbody>`;
  for (const u of script.timeline) {
    const emo = u.kind === "dialogue" ? `${esc(u.emotion)} ${Number(u.intensity).toFixed(1)}` : (u.kind === "narration" ? esc(u.emotion) : "—");
    const content = u.kind === "sound" && u.sound_cue
      ? `<em>${esc(u.sound_cue.cue_type)}: ${esc(u.sound_cue.description)}</em>`
      : esc(u.text);
    html += `<tr class="tl-${esc(u.kind)}">
      <td>${u.index}</td><td>${u.scene_number}</td><td>${esc(u.kind)}</td>
      <td>${esc(u.speaker_name)}</td><td>${emo}</td><td>${content}</td>
    </tr>`;
  }
  html += `</tbody></table>`;
  timelineView.innerHTML = html;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  hide(resultEl);
  statusEl.classList.remove("error");
  show(statusEl);
  statusEl.textContent = "Generating your script… this can take a moment.";
  submitBtn.disabled = true;

  const durationVal = document.getElementById("duration").value;
  const payload = {
    prompt: document.getElementById("prompt").value.trim(),
    duration_minutes: durationVal ? parseFloat(durationVal) : null,
    genre: document.getElementById("genre").value.trim() || null,
    language: document.getElementById("language").value.trim() || "English",
  };

  try {
    const res = await fetch("/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();

    hide(statusEl);
    screenplayEl.textContent = data.screenplay_text;
    renderStructured(data.script);
    renderTimeline(data.script);

    modeBadge.textContent = data.mode === "mock"
      ? "MOCK MODE — set LLM_API_KEY in .env for real AI generation"
      : `Generated with ${"LLM"}`;
    show(modeBadge);

    show(resultEl);
  } catch (err) {
    statusEl.classList.add("error");
    statusEl.textContent = "Error: " + err.message;
  } finally {
    submitBtn.disabled = false;
  }
});

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

// Tab switching
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    const view = tab.dataset.view;
    document.getElementById("view-screenplay").classList.toggle("hidden", view !== "screenplay");
    document.getElementById("view-structured").classList.toggle("hidden", view !== "structured");
  });
});

function renderStructured(script) {
  let html = `<h2>${esc(script.title)}</h2>`;
  html += `<p class="meta"><em>"${esc(script.logline)}"</em></p>`;
  html += `<p class="meta">${esc(script.genre)} · ${esc(script.language)} · ~${script.estimated_duration_minutes} min</p>`;
  html += `<p>${esc(script.synopsis)}</p>`;

  html += `<h3>Characters</h3>`;
  for (const c of script.characters) {
    html += `<div class="char">
      <h3>${esc(c.name)} <span class="meta">— ${esc(c.role)}</span></h3>
      <p>${esc(c.description)}</p>
      <p class="meta"><b>Wants:</b> ${esc(c.motivation)}</p>
      <p class="meta"><b>Arc:</b> ${esc(c.emotional_arc)}</p>
      ${c.voice_profile ? `<p class="meta"><b>Voice:</b> ${esc(c.voice_profile)}</p>` : ""}
    </div>`;
  }

  html += `<h3>Scenes</h3>`;
  for (const s of script.scenes) {
    html += `<div class="scene">
      <h3>${s.number}. ${esc(s.heading)}</h3>
      <p class="meta">[${esc(s.mood)}] ${esc(s.summary)}</p>`;
    for (const el of s.elements) {
      if (el.kind === "action" && el.action) {
        html += `<p class="action-el">${esc(el.action)}</p>`;
      } else if (el.kind === "dialogue" && el.dialogue) {
        const d = el.dialogue;
        html += `<div class="line">
          <span class="who">${esc(d.character)}</span>
          <span class="emo">(${esc(d.parenthetical || d.emotion)})</span><br>
          ${esc(d.line)}
        </div>`;
      }
    }
    html += `</div>`;
  }
  structuredEl.innerHTML = html;
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

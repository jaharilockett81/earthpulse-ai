/* EarthPulse AI frontend: no build step, no framework. */
(() => {
  "use strict";

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (typeof u === "string" && /^https?:\/\//i.test(u) ? u : null);
  const cssUrl = (u) => u.replace(/['"()\\\s]/g, (c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0"));
  const fmt = (n, d = 1) => (n == null ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: 0 }));

  const CLAIM_TEXT = { listed: "Listed", computed: "Computed", qloo_signal: "Qloo signal", ai_written: "AI-written", not_verified: "Not verified" };
  const CAT_ICON = { nature: "🌳", culture: "🏛️", coffee: "☕", books_music: "📚", live_music: "🎷", makers: "🏺", dining: "🍽️", stay: "🛏️" };
  const SLOT_TEXT = { morning: "Morning", midday: "Midday", afternoon: "Afternoon", evening: "Evening" };
  const claim = (k) => `<span class="claim ${esc(k)}">${esc(CLAIM_TEXT[k] || k)}</span>`;

  const state = { seeds: [], inputMode: "picks", health: null, result: null, compare: null, activeDay: 1, map: null };

  /* ------------------------------------------------------------ storage (best effort) */
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
  };

  /* ------------------------------------------------------------ routing */
  const VIEWS = { "": "landing", plan: "plan", results: "results", lab: "lab", how: "how" };
  function route() {
    const key = (location.hash.replace(/^#\/?/, "").split("?")[0]) || "";
    const view = VIEWS[key] || "landing";
    $$(".view").forEach((v) => { v.hidden = v.id !== `view-${view}`; });
    $$(".topbar nav a").forEach((a) => a.toggleAttribute("aria-current", a.getAttribute("href") === `#/${key}`));
    if (view === "results" && !state.result && !state.running) renderEmptyResults();
    if (view === "results" && state.map) setTimeout(() => state.map.invalidateSize(), 50);
    if (view === "lab") renderTally();
    window.scrollTo({ top: 0 });
  }
  window.addEventListener("hashchange", route);

  /* ------------------------------------------------------------ health / banner */
  async function loadHealth() {
    try {
      const r = await fetch("/api/health");
      state.health = await r.json();
    } catch {
      state.health = { categories: [], qloo_configured: false };
    }
    const b = $("#banner");
    if (state.health.fixtures) {
      b.textContent = "Development mode: showing SYNTHETIC places (names start with “[Synthetic]”), not Qloo data. Set QLOO_API_KEY for live results.";
      b.hidden = false;
    } else if (!state.health.qloo_configured) {
      b.textContent = "Live taste data isn't configured on this server yet (QLOO_API_KEY is missing), so plans can't run.";
      b.classList.add("err");
      b.hidden = false;
    }
    const cats = $("#categories");
    cats.innerHTML = (state.health.categories || []).map((c) => `
      <label class="toggle"><input type="checkbox" value="${esc(c.key)}" ${c.default ? "checked" : ""}>
      <span>${CAT_ICON[c.key] || ""} ${esc(c.label)}</span></label>`).join("");
  }

  /* ------------------------------------------------------------ planner: taste input */
  function renderSeeds() {
    $("#seed-chips").innerHTML = state.seeds.map((s, i) => `
      <span class="chip">${esc(s.name)}${s.kind ? ` <small class="muted">${esc(s.kind)}</small>` : ""}
        <button type="button" class="x" data-i="${i}" aria-label="Remove ${esc(s.name)}">×</button></span>`).join("");
    $("#seed-input").placeholder = state.seeds.length >= 5 ? "Five is plenty" : (state.seeds.length ? "Add another…" : "Search a film, artist, book, brand, place…");
    $("#seed-input").disabled = state.seeds.length >= 5;
  }
  $("#seed-chips").addEventListener("click", (e) => {
    const b = e.target.closest("button.x");
    if (!b) return;
    state.seeds.splice(Number(b.dataset.i), 1);
    renderSeeds();
    $("#seed-input").focus();
  });

  function addSeed(s) {
    if (state.seeds.length >= 5) return;
    if (state.seeds.some((x) => x.name.toLowerCase() === s.name.toLowerCase())) return;
    state.seeds.push(s);
    renderSeeds();
  }

  let suggestTimer = null, suggestAbort = null, suggestItems = [], activeIdx = -1;
  const list = $("#seed-list"), input = $("#seed-input");
  function closeSuggest() { list.hidden = true; input.setAttribute("aria-expanded", "false"); activeIdx = -1; }
  function paintSuggest() {
    list.innerHTML = suggestItems.map((h, i) => {
      const img = safeUrl(h.image_url);
      return `<li role="option" id="opt-${i}" data-i="${i}" aria-selected="${i === activeIdx}">
        ${img ? `<img src="${esc(img)}" alt="" referrerpolicy="no-referrer" loading="lazy">` : `<span class="ph"></span>`}
        <span><span>${esc(h.name)}</span><br><span class="kind">${esc(h.kind)}${h.disambiguation ? " · " + esc(h.disambiguation) : ""}</span></span></li>`;
    }).join("");
    list.hidden = !suggestItems.length;
    input.setAttribute("aria-expanded", String(!list.hidden));
    input.setAttribute("aria-activedescendant", activeIdx >= 0 ? `opt-${activeIdx}` : "");
  }
  input.addEventListener("input", () => {
    clearTimeout(suggestTimer);
    const q = input.value.trim();
    if (q.length < 2) { suggestItems = []; closeSuggest(); return; }
    suggestTimer = setTimeout(async () => {
      suggestAbort?.abort();
      suggestAbort = new AbortController();
      try {
        const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`, { signal: suggestAbort.signal });
        if (!r.ok) { suggestItems = []; closeSuggest(); return; }
        suggestItems = (await r.json()).results || [];
        activeIdx = -1;
        paintSuggest();
      } catch { /* aborted or offline */ }
    }, 260);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" && suggestItems.length) { e.preventDefault(); activeIdx = (activeIdx + 1) % suggestItems.length; paintSuggest(); }
    else if (e.key === "ArrowUp" && suggestItems.length) { e.preventDefault(); activeIdx = (activeIdx - 1 + suggestItems.length) % suggestItems.length; paintSuggest(); }
    else if (e.key === "Escape") closeSuggest();
    else if (e.key === "Enter") {
      e.preventDefault();
      const h = activeIdx >= 0 ? suggestItems[activeIdx] : null;
      if (h) addSeed({ name: h.name, entity_id: h.entity_id, kind: h.kind });
      else if (input.value.trim().length >= 2) addSeed({ name: input.value.trim() });
      input.value = ""; suggestItems = []; closeSuggest();
    } else if (e.key === "Backspace" && !input.value && state.seeds.length) { state.seeds.pop(); renderSeeds(); }
  });
  list.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li");
    if (!li) return;
    e.preventDefault();
    const h = suggestItems[Number(li.dataset.i)];
    addSeed({ name: h.name, entity_id: h.entity_id, kind: h.kind });
    input.value = ""; suggestItems = []; closeSuggest(); input.focus();
  });
  input.addEventListener("blur", () => setTimeout(closeSuggest, 120));

  function setInputMode(mode) {
    state.inputMode = mode;
    $$(".seg-btn[data-input]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.input === mode)));
    $("#input-picks").hidden = mode !== "picks";
    $("#input-prompt").hidden = mode !== "prompt";
  }
  $$(".seg-btn[data-input]").forEach((b) => b.addEventListener("click", () => setInputMode(b.dataset.input)));
  for (const id of ["days", "budget"]) {
    $(`#${id}`).addEventListener("click", (e) => {
      const b = e.target.closest(".seg-btn");
      if (!b) return;
      $$(`#${id} .seg-btn`).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    });
  }

  $$(".example").forEach((b) => b.addEventListener("click", () => {
    setInputMode("prompt");
    $("#prompt").value = b.dataset.prompt;
    $("#location").value = b.dataset.location;
    location.hash = "#/plan";
  }));

  function collect() {
    const body = {
      location: $("#location").value.trim(),
      origin: $("#origin").value.trim() || null,
      categories: $$("#categories input:checked").map((i) => i.value),
      priorities: $$("#priorities input[value]:checked").map((i) => i.value),
      car_free: $("#car_free").checked,
      step_free: $("#step_free").checked,
      travelers: Math.max(1, Math.min(8, Number($("#travelers").value) || 1)),
      days: Number($("#days .seg-btn[aria-pressed=true]").dataset.v),
      budget: Number($("#budget .seg-btn[aria-pressed=true]").dataset.v) || null,
    };
    if (state.inputMode === "picks") body.seeds = state.seeds;
    else body.prompt = $("#prompt").value.trim();
    return body;
  }
  function validate(b) {
    if (state.inputMode === "picks" && !b.seeds.length) return "Add at least one favourite, or switch to “Describe it”.";
    if (state.inputMode === "prompt" && (b.prompt || "").length < 3) return "Describe what you love in a few words.";
    if (b.location.length < 2) return "Where are you going? Add a destination city.";
    if (!b.categories.length) return "Choose at least one kind of place.";
    if (b.categories.length > 6) return "Choose at most six kinds of place.";
    return null;
  }

  let submitMode = "plan";
  $$("#plan-form button[type=submit]").forEach((b) => b.addEventListener("click", () => { submitMode = b.dataset.mode; }));
  $("#plan-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const body = collect();
    const problem = validate(body);
    const errEl = $("#form-error");
    errEl.hidden = !problem;
    errEl.textContent = problem || "";
    if (problem) return;
    if (submitMode === "compare") startCompare(body);
    else startRun(body);
  });

  /* ------------------------------------------------------------ streaming */
  async function streamNDJSON(url, body, onEvent) {
    const r = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) {
      let msg = `Request failed (${r.status}).`;
      try { msg = (await r.json()).error.message || msg; } catch { /* not json */ }
      onEvent({ type: "error", code: `http_${r.status}`, message: msg });
      return;
    }
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (line) { try { onEvent(JSON.parse(line)); } catch { /* skip partial */ } }
      }
    }
    if (buf.trim()) { try { onEvent(JSON.parse(buf)); } catch { /* ignore */ } }
  }

  function timeline(el) {
    el.innerHTML = "";
    const rows = {};
    return (st) => {
      let li = rows[st.id];
      if (!li) { li = document.createElement("li"); rows[st.id] = li; el.appendChild(li); }
      li.className = st.status;
      li.innerHTML = `<span class="dot" aria-hidden="true"></span>
        <span class="t-name">${esc(st.name)}${st.status !== "running" ? `<span class="t-ms">${(st.ms / 1000).toFixed(1)}s</span>` : ""}</span>
        <span class="t-agent">${esc(st.agent)} agent · ${esc(st.status)}</span>
        ${st.detail ? `<span class="t-detail">${esc(st.detail)}</span>` : ""}`;
    };
  }

  /* ------------------------------------------------------------ run */
  function setBusy(b) { $$("#plan-form button[type=submit]").forEach((x) => { x.disabled = b; }); }

  async function startRun(body) {
    state.result = null; state.running = true;
    location.hash = "#/results";
    const main = $("#results-main");
    main.innerHTML = `<div class="skeleton"><div class="sk h"></div><div class="sk"></div><div class="sk"></div></div>`;
    const tl = timeline($("#timeline"));
    $("#run-stats").textContent = "";
    setBusy(true);
    try {
      await streamNDJSON("/api/run", body, (ev) => {
        if (ev.type === "stage") tl(ev.stage);
        else if (ev.type === "result") { state.result = ev; renderResult(ev); }
        else if (ev.type === "error") renderError(main, ev);
      });
    } catch {
      renderError(main, { message: "Lost connection to the server. Please try again." });
    } finally {
      state.running = false; setBusy(false);
    }
  }

  function renderEmptyResults() {
    $("#timeline").innerHTML = "";
    $("#results-main").innerHTML = `<div class="panel"><h2>No plan yet</h2><p class="muted">Tell us what you love and where you're going.</p><a class="btn primary" href="#/plan">Start planning</a></div>`;
  }

  function renderError(el, ev) {
    el.innerHTML = `<div class="error-card" role="alert"><h2>We couldn't finish this plan</h2><p>${esc(ev.message)}</p>
      <a class="btn ghost small" href="#/plan">Adjust and try again</a></div>`;
  }

  function seedChips(seeds) {
    return seeds.map((s) => {
      const ok = s.resolved_as === "entity" || s.resolved_as === "tag";
      const img = safeUrl(s.image_url);
      return ok ? `<span class="seed" title="Matched in Qloo as ${esc(s.resolved_as)}">${img ? `<img src="${esc(img)}" alt="" referrerpolicy="no-referrer">` : `<span class="ph"></span>`}
          ${esc(s.name)} <span class="k">${esc(s.kind)}${s.approximate ? " · closest match" : ""}</span></span>`
        : `<span class="seed miss" title="Not matched in Qloo">${esc(s.input)}</span>`;
    }).join("");
  }

  function renderResult(res) {
    const main = $("#results-main");
    const s = res.summary;
    const cats = res.request.categories.map((c) => c.label.toLowerCase()).join(", ");
    $("#run-stats").textContent = `Qloo calls: ${res.stats.network_calls} live, ${res.stats.cache_hits} cached.`;
    const portrait = [...(res.portrait.taste || []).slice(0, 8).map((t) => `<span class="chip tag theme">${esc(t.name)}</span>`),
      ...(res.portrait.ambience || []).slice(0, 4).map((t) => `<span class="chip tag">${esc(t.name)}</span>`)].join("");
    const notes = [...res.notes, ...res.replaced.map((r) => `Verification replaced ${r.removed} (${r.failed.join(", ")})${r.replacement ? ` with ${r.replacement}` : ""}.`)];
    main.innerHTML = `
      <div class="res-head">
        <p class="eyebrow">${esc(res.request.days)}-day plan · ${esc(cats)}</p>
        <h1>${esc(res.request.location)}, matched to your taste</h1>
        <div class="seeds">${seedChips(res.seeds)}</div>
      </div>
      ${notes.length ? `<div class="notes"><ul>${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>` : ""}
      <div class="stats">
        <div class="stat"><div class="v">${s.stops}</div><div class="l">stops, each verified</div></div>
        <div class="stat"><div class="v">${fmt(s.km)} km</div><div class="l">straight-line, all legs ${claim("computed")}</div></div>
        <div class="stat"><div class="v">${fmt(s.suggested_kg_co2e, 2)} kg</div><div class="l">CO2e walking + transit ${claim("computed")}</div></div>
        <div class="stat hl"><div class="v">${s.saved_kg_co2e != null ? fmt(s.saved_kg_co2e, 2) + " kg" : "car-free"}</div>
          <div class="l">${s.saved_kg_co2e != null ? `less than driving every leg (${fmt(s.car_kg_co2e, 2)} kg)` : "no driving in this plan"}</div></div>
      </div>
      ${portrait ? `<div class="portrait"><span class="h-small">Your taste portrait ${claim("qloo_signal")}</span>${portrait}</div>` : ""}
      <div id="map" role="img" aria-label="Map of planned stops"></div>
      <div class="day-tabs" role="tablist">
        ${res.days.map((d) => `<button class="seg-btn" role="tab" data-day="${d.day}" aria-selected="${d.day === 1}">Day ${d.day}</button>`).join("")}
        <span class="day-totals" id="day-totals"></span>
      </div>
      <ol class="stops" id="stops"></ol>
      <section><h2 class="h-small">More options</h2><div class="alts" id="alts"></div></section>
      <p class="muted tiny">Origin: ${res.origin ? esc(res.origin.label) : "unknown"}. ${res.explanation_source === "ai" ? "Explanations reworded by AI from grounded facts." : "Explanations written from grounded facts."} Travel figures are straight-line lower bounds from EPA factors.</p>`;
    $$(".day-tabs .seg-btn", main).forEach((b) => b.addEventListener("click", () => {
      $$(".day-tabs .seg-btn", main).forEach((x) => x.setAttribute("aria-selected", String(x === b)));
      renderDay(res, Number(b.dataset.day));
    }));
    renderDay(res, 1);
    const alts = Object.values(res.alternates).flat().map((id) => res.cards[id]).filter(Boolean);
    $("#alts").innerHTML = alts.length ? alts.map((c) => `<button class="alt" data-id="${esc(c.id)}">
        <span class="n">${CAT_ICON[c.category] || ""} ${esc(c.name)}</span>
        <span class="m">${esc(c.category_label)}${c.distance_km != null ? ` · ${fmt(c.distance_km)} km` : ""}${c.affinity != null ? ` · affinity ${c.affinity.toFixed(2)}` : ""}</span></button>`).join("")
      : `<p class="muted">No other options passed the filters.</p>`;
    $("#alts").addEventListener("click", (e) => { const b = e.target.closest(".alt"); if (b) openEvidence(res.cards[b.dataset.id], res); });
    drawMap(res);
  }

  function renderDay(res, n) {
    const day = res.days.find((d) => d.day === n);
    if (!day) return;
    const t = day.totals;
    $("#day-totals").innerHTML = `${fmt(t.km)} km · ${fmt(t.suggested_kg_co2e, 2)} kg CO2e${t.car_kg_co2e != null ? ` vs ${fmt(t.car_kg_co2e, 2)} kg by car` : ""} ${claim("computed")}`;
    const out = [];
    day.stops.forEach((st, i) => {
      const leg = day.legs[i];
      if (leg) out.push(legRow(leg, i === 0 && res.origin ? `from ${res.origin.label}` : ""));
      out.push(placeCard(res.cards[st.id], st.slot, res));
    });
    const back = day.legs[day.stops.length];
    if (back) out.push(legRow(back, "back to start"));
    $("#stops").innerHTML = out.join("");
    $$("#stops [data-open]").forEach((b) => b.addEventListener("click", () => openEvidence(res.cards[b.dataset.open], res)));
    highlightDay(n);
  }

  function legRow(leg, label) {
    const icon = leg.mode === "walk" ? "🚶" : "🚌";
    return `<li class="leg">${icon} ${esc(leg.label)} ${fmt(leg.km)} km ${esc(label)} · ${fmt(leg.kg_co2e, 2)} kg CO2e${leg.car_kg_co2e != null ? ` (car ${fmt(leg.car_kg_co2e, 2)})` : ""}</li>`;
  }

  function placeCard(c, slot, res) {
    if (!c) return "";
    const img = safeUrl(c.image_url);
    const swap = res.swaps[c.id];
    const alt = swap && res.cards[swap.to_id];
    const aff = c.affinity;
    return `<li><article class="place">
      <div class="img" ${img ? `style="background-image:url('${esc(cssUrl(img))}')"` : ""}>${img ? "" : `<span class="ph" aria-hidden="true">${CAT_ICON[c.category] || "📍"}</span>`}
        ${slot ? `<span class="slot">${esc(SLOT_TEXT[slot] || slot)}</span>` : ""}</div>
      <div class="body">
        <div class="top">
          <div><h3>${esc(c.name)}</h3><span class="cat">${esc(c.category_label)}${c.address ? " · " + esc(c.address) : ""}</span></div>
          ${aff != null ? `<div class="aff" title="Qloo taste affinity (0–1)"><div class="n">${aff.toFixed(2)}</div><div class="bar"><i style="width:${Math.round(aff * 100)}%"></i></div><div class="k">taste match</div></div>` : ""}
        </div>
        <p class="why">${esc(c.why.text)} ${claim(c.why.label)}</p>
        <div class="tags">${c.shared_themes.map((t) => `<span class="chip tag theme">${esc(t)}</span>`).join("")}${c.signals.map((t) => `<span class="chip tag">🌿 ${esc(t)}</span>`).join("")}</div>
        <div class="meta">
          ${c.distance_km != null ? `<span>📍 ${fmt(c.distance_km)} km</span>` : `<span>${claim("not_verified")} distance</span>`}
          <span>${esc(c.price_text)}</span>
          ${c.step_free ? `<span>♿ step-free entrance</span>` : ""}
          <button class="linkish" data-open="${esc(c.id)}">Evidence &amp; sources</button>
        </div>
        ${alt ? `<div class="swap">🌿 <span><b>Lighter swap:</b> ${esc(alt.name)} is ${fmt(swap.km_closer)} km closer and nearly as strong a match
          (−${fmt(swap.base_gap, 3)}). Saves ${fmt(swap.kg_co2e_saved, 2)} kg CO2e round trip by ${esc(swap.compared_mode)}.</span> ${claim("computed")}
          <button class="linkish" data-open="${esc(alt.id)}">See it</button></div>` : ""}
      </div></article></li>`;
  }

  /* ------------------------------------------------------------ map */
  let dayLayers = {};
  function drawMap(res) {
    const el = $("#map");
    if (!window.L || !el) { if (el) el.hidden = true; return; }
    if (state.map) { state.map.remove(); state.map = null; }
    const pts = [];
    const map = L.map(el, { scrollWheelZoom: false });
    state.map = map;
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap contributors" }).addTo(map);
    dayLayers = {};
    if (res.origin) {
      const o = [res.origin.lat, res.origin.lon];
      pts.push(o);
      L.marker(o, { icon: L.divIcon({ className: "", html: `<div class="map-pin origin" style="width:26px;height:26px">★</div>`, iconSize: [26, 26] }) })
        .addTo(map).bindTooltip(esc(res.origin.label));
    }
    res.days.forEach((d) => {
      const layer = L.layerGroup().addTo(map);
      const line = res.origin ? [[res.origin.lat, res.origin.lon]] : [];
      d.stops.forEach((st, i) => {
        const c = res.cards[st.id];
        if (c?.lat == null) return;
        const p = [c.lat, c.lon];
        pts.push(p); line.push(p);
        L.marker(p, { icon: L.divIcon({ className: "", html: `<div class="map-pin d${d.day}" style="width:24px;height:24px">${i + 1}</div>`, iconSize: [24, 24] }) })
          .addTo(layer).bindTooltip(`Day ${d.day} · ${esc(c.name)}`);
      });
      if (res.origin && line.length > 1) line.push([res.origin.lat, res.origin.lon]);
      L.polyline(line, { color: d.day === 1 ? "#183F35" : "#5c7f4d", weight: 3, opacity: .7, dashArray: "6 6" }).addTo(layer);
      dayLayers[d.day] = layer;
    });
    if (pts.length) map.fitBounds(pts, { padding: [30, 30], maxZoom: 14 });
    else el.hidden = true;
  }
  function highlightDay(n) {
    Object.entries(dayLayers).forEach(([d, layer]) => layer.eachLayer((l) => {
      const on = Number(d) === n;
      if (l.setStyle) l.setStyle({ opacity: on ? .85 : .2 });
      if (l.setOpacity) l.setOpacity(on ? 1 : .45);
    }));
  }

  /* ------------------------------------------------------------ evidence drawer */
  let lastFocus = null;
  function openEvidence(c, res) {
    if (!c) return;
    lastFocus = document.activeElement;
    const trip = c.trip;
    const parts = Object.entries(c.score_parts || {}).map(([k, v]) => `<tr><td>${esc(k.replace(/_/g, " "))}</td><td>${v > 0 && k !== "base" ? "+" : ""}${fmt(v, 3)}</td></tr>`).join("");
    const links = (c.taste_links || []).map((l) => `<tr><td>${esc(l.name)}</td><td>${fmt(l.score, 3)}</td></tr>`).join("");
    const site = safeUrl(c.website);
    $("#drawer-body").innerHTML = `
      <p class="eyebrow">${esc(c.category_label)}</p>
      <h2 id="drawer-title">${esc(c.name)}</h2>
      ${site ? `<p><a href="${esc(site)}" target="_blank" rel="noopener nofollow">Website ↗</a></p>` : ""}
      <section><h3>Why it's here</h3><p>${esc(c.why.text)} ${claim(c.why.label)}</p>
        <details class="method"><summary>Grounded facts used</summary><ul>${c.why.facts.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></details></section>
      <section><h3>Claims on this card</h3><ul class="claims">${c.claims.map((x) => `<li>${claim(x.label)} <span>${esc(x.text)}</span></li>`).join("")}</ul></section>
      ${links ? `<section><h3>Which of your interests drove it ${claim("qloo_signal")}</h3><table><tr><th>Your interest</th><th>Qloo explainability score</th></tr>${links}</table></section>` : ""}
      ${c.keyword_hits?.length ? `<section><h3>Keyword matches (baseline)</h3><p>${c.keyword_hits.map(esc).join(", ")}</p></section>` : ""}
      <section><h3>Ranking score ${claim("computed")}</h3><table><tr><th>Component</th><th>Value</th></tr>${parts}<tr><th>Total</th><th>${fmt(c.score, 3)}</th></tr></table>
        <p class="muted tiny">Base is Qloo's affinity for your taste. Weights are listed on <a href="#/how">How it works</a>.</p></section>
      ${trip ? `<section><h3>Getting there and back ${claim("computed")}</h3>
        <table><tr><th>Mode</th><th>kg CO2e</th><th>Factor</th></tr>
        ${trip.modes.map((m) => `<tr><td>${esc(m.label)}</td><td>${fmt(m.kg_co2e, 2)}</td><td>${esc(m.factor)}${m.caveat ? `<br><span class="muted tiny">${esc(m.caveat)}</span>` : ""}</td></tr>`).join("")}</table>
        <p class="muted tiny">${fmt(trip.one_way_km, 2)} km each way from ${esc(res.origin?.label || "start")}, ${esc(trip.units)}.</p>
        <details class="method"><summary>Method, assumptions, uncertainty</summary><p>${esc(trip.method)}</p>
          <ul>${trip.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul><p>${esc(trip.uncertainty)}</p>
          <p>Source: <a href="${esc(trip.source.url)}" target="_blank" rel="noopener">${esc(trip.source.name)}</a>, ${esc(trip.source.version)}.</p></details></section>`
        : `<section><h3>Getting there</h3><p>${claim("not_verified")} No coordinates were listed, so distance and emissions aren't shown.</p></section>`}
      ${c.checks?.length ? `<section><h3>Verification</h3><ul class="checks">${c.checks.map((k) => `<li><span class="${k.passed ? "ok" : (k.hard ? "bad" : "soft")}">${k.passed ? "✓" : (k.hard ? "✗" : "!")}</span><span>${esc(k.detail)}</span></li>`).join("")}</ul></section>` : ""}
      ${c.tags?.length ? `<section><h3>Qloo tags ${claim("listed")}</h3><div class="tags">${c.tags.map((t) => `<span class="chip tag">${esc(t)}</span>`).join(" ")}</div></section>` : ""}
      <p class="muted tiny">Opening hours, prices and availability can change. Check before you go.</p>`;
    $("#drawer").hidden = false;
    $(".drawer-close").focus();
  }
  function closeDrawer() { $("#drawer").hidden = true; lastFocus?.focus?.(); }
  $("#drawer").addEventListener("click", (e) => { if (e.target.closest("[data-close]")) closeDrawer(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#drawer").hidden) closeDrawer(); });

  /* ------------------------------------------------------------ comparison lab */
  async function startCompare(body) {
    state.compare = null; state.running = true;
    location.hash = "#/lab";
    const main = $("#lab-main");
    main.innerHTML = `<div class="skeleton"><div class="sk h"></div><div class="sk"></div></div>`;
    const tl = timeline($("#lab-timeline"));
    setBusy(true);
    try {
      await streamNDJSON("/api/compare", body, (ev) => {
        if (ev.type === "stage") tl(ev.stage);
        else if (ev.type === "compare") { state.compare = ev; renderCompare(ev); }
        else if (ev.type === "error") renderError(main, ev);
      });
    } catch {
      renderError(main, { message: "Lost connection to the server. Please try again." });
    } finally {
      state.running = false; setBusy(false);
    }
  }

  function renderCompare(cmp) {
    const ratings = { A: 0, B: 0 };
    const main = $("#lab-main");
    const panel = (k) => `<div class="panel" data-list="${k}">
        <h2>List ${k} <span class="who" hidden></span></h2>
        <ol>${cmp.lists[k].map((x) => `<li><span class="n">${esc(x.name)}</span><br>
          <span class="m">${esc(x.category_label)}${x.distance_km != null ? ` · ${fmt(x.distance_km)} km` : ""} · ${esc(x.tags.join(", "))}</span></li>`).join("")}</ol>
        <div class="stars" role="group" aria-label="Rate list ${k} for fit with your taste">
          <span class="muted tiny">Fits my taste:</span>
          ${[1, 2, 3, 4, 5].map((n) => `<button type="button" data-k="${k}" data-n="${n}" aria-pressed="false">${n}</button>`).join("")}
        </div></div>`;
    main.innerHTML = `
      <div class="res-head"><h1>${esc(cmp.request.location)}: which list is more you?</h1>
        <div class="seeds">${seedChips(cmp.seeds)}</div></div>
      <div class="ab">${panel("A")}${panel("B")}</div>
      <div class="reveal-row"><button class="btn primary" id="reveal" disabled>Rate both lists to reveal</button>
        <span class="muted">${cmp.overlap} place${cmp.overlap === 1 ? "" : "s"} appear in both lists.</span></div>
      <div id="reveal-out"></div>`;
    main.onclick = (e) => {
      const b = e.target.closest(".stars button");
      if (!b || cmp.revealed) return;
      ratings[b.dataset.k] = Number(b.dataset.n);
      $$(`.stars button[data-k="${b.dataset.k}"]`, main).forEach((x) => x.setAttribute("aria-pressed", String(Number(x.dataset.n) <= ratings[b.dataset.k])));
      const ready = ratings.A && ratings.B;
      $("#reveal").disabled = !ready;
      $("#reveal").textContent = ready ? "Reveal which is Qloo" : "Rate both lists to reveal";
    };
    $("#reveal").addEventListener("click", () => {
      cmp.revealed = true;
      $("#reveal").disabled = true;
      for (const k of ["A", "B"]) {
        const who = $(`[data-list="${k}"] .who`, main);
        who.hidden = false;
        who.textContent = cmp.reveal[k] === "qloo" ? "Qloo taste graph" : "Keyword baseline";
        who.classList.toggle("qloo", cmp.reveal[k] === "qloo");
      }
      const q = cmp.reveal.A === "qloo" ? ratings.A : ratings.B;
      const b = cmp.reveal.A === "qloo" ? ratings.B : ratings.A;
      const log = store.get("ep_lab", []);
      if (!log.some((x) => x.run_id === cmp.run_id)) log.push({ run_id: cmp.run_id, qloo: q, baseline: b, at: Date.now() });
      store.set("ep_lab", log.slice(-100));
      const m = cmp.metrics;
      $("#reveal-out").innerHTML = `<div class="panel"><h3>${q > b ? "You preferred the Qloo-ranked list." : q < b ? "You preferred the keyword baseline this time." : "A tie."}</h3>
        <p class="muted">Average distance from the start point: Qloo ${fmt(m.qloo.avg_km)} km, baseline ${fmt(m.baseline.avg_km)} km ${claim("computed")}. Both lists used the same filters and carbon rules; only the taste signal differs.</p>
        <a class="btn ghost small" href="#/plan">Run another comparison</a></div>`;
      renderTally();
    });
  }

  function renderTally() {
    const log = store.get("ep_lab", []);
    const el = $("#lab-tally");
    if (!log.length) { el.innerHTML = ""; return; }
    const avg = (k) => (log.reduce((a, x) => a + x[k], 0) / log.length).toFixed(1);
    const wins = log.filter((x) => x.qloo > x.baseline).length;
    el.innerHTML = `
      <div class="stat"><div class="v">${log.length}</div><div class="l">comparisons rated in this browser</div></div>
      <div class="stat hl"><div class="v">${Math.round((wins / log.length) * 100)}%</div><div class="l">preferred the Qloo list</div></div>
      <div class="stat"><div class="v">${avg("qloo")} / ${avg("baseline")}</div><div class="l">avg rating, Qloo / baseline</div></div>`;
  }

  /* ------------------------------------------------------------ boot */
  renderSeeds();
  loadHealth();
  route();
})();

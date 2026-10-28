// One id per browser, sent with every /api call: on the public demo, what you change (lessons, shipping your own
// orders, counters you open) stays with your browser and never changes the shop for other people.
(() => {
  let vid = "";
  try { vid = localStorage.getItem("oc_visitor") || ""; if (!vid) { vid = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2)).replace(/-/g, "").slice(0, 24); localStorage.setItem("oc_visitor", vid); } } catch (e) {}
  const f = window.fetch.bind(window);
  window.fetch = (u, o = {}) => (typeof u === "string" && u.startsWith("/api") && vid ? f(u, { ...o, headers: { ...(o.headers || {}), "x-visitor": vid } }) : f(u, o));
})();

// Hero: the cursor is Lena's bench lamp, the shopper's AI works on the left, the sale lands on her phone on the right.
(() => {
  const root = document.documentElement;
  const hero = document.getElementById("hero");
  let tx = 0.62, ty = 0.42, x = tx, y = ty, auto = true, t0 = performance.now();

  hero.addEventListener("pointermove", (e) => {
    const r = hero.getBoundingClientRect();
    tx = (e.clientX - r.left) / r.width; ty = (e.clientY - r.top) / r.height; auto = false;
  });
  hero.addEventListener("pointerleave", () => { auto = true; t0 = performance.now(); });

  // The lamp only moves while the hero is on screen and the tab is visible, and only the hero repaints: a
  // page-wide mask animated every frame for minutes made iPhone Safari reload the page mid-chat (Roma 14530).
  let onScreen = true, running = false;
  function loop(now) {
    if (!onScreen || document.hidden) { running = false; return; }
    if (auto) {  // a slow figure-eight over the car while nobody holds the lamp (also what the video shows)
      const s = (now - t0) / 1000;
      tx = 0.6 + 0.16 * Math.sin(s * 0.45); ty = 0.5 + 0.12 * Math.sin(s * 0.9);
    }
    x += (tx - x) * 0.12; y += (ty - y) * 0.12;
    hero.style.setProperty("--mx", (x * 100).toFixed(2) + "%");
    hero.style.setProperty("--my", (y * 100).toFixed(2) + "%");
    requestAnimationFrame(loop);
  }
  const wake = () => { if (!running && onScreen && !document.hidden) { running = true; requestAnimationFrame(loop); } };
  new IntersectionObserver((es) => { onScreen = es[0].isIntersecting; wake(); }).observe(hero);
  document.addEventListener("visibilitychange", wake);
  wake();

  // --- the shopper's AI at work (demo script; the live demo runs the same tools for real) ---
  const steps = [
    ["searching makers' counters", "found <b>Small Garage</b> · Columbus, OH"],
    ["reading the listing", "<b>Green Fastback, 1968</b> · 1:43 · $59 · in stock"],
    ["checking delivery to CO", "ships Thu · arrives <b>Tue–Thu</b> · on time"],
    ["preparing PayPal checkout", "waiting for your approval"],
  ];
  const agent = document.getElementById("agent"), list = document.getElementById("steps");
  const approve = document.getElementById("approve");
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  async function run() {
    list.innerHTML = ""; approve.hidden = true; agent.classList.add("working");
    for (const [doing, done] of steps) {
      const li = document.createElement("li");
      li.innerHTML = `<i></i><span>${doing}…</span>`; li.className = "active"; list.appendChild(li);
      gsap.to(li, { opacity: 1, y: 0, duration: 0.35, ease: "power2.out" });
      await wait(1100);
      li.className = "done"; li.innerHTML = `<i></i><span>${done}</span>`;
    }
    approve.hidden = false;
    gsap.fromTo(approve, { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.5, ease: "power3.out" });
    agent.classList.remove("working");  // the agent stops here: only a person can press the button
  }

  function sold() {
    const card = document.getElementById("sold"), amt = document.getElementById("amt");
    document.getElementById("scene").classList.add("flash");
    setTimeout(() => document.getElementById("scene").classList.remove("flash"), 200);
    const idle = document.getElementById("idle"); if (idle) gsap.to(idle, { opacity: 0, duration: 0.2 });
    gsap.fromTo(card, { opacity: 0, y: -40 }, { opacity: 1, y: 0, duration: 0.55, ease: "back.out(1.4)" });
    const n = { v: 0 };
    gsap.to(n, { v: 59, duration: 0.8, ease: "expo.out", onUpdate: () => (amt.textContent = "$" + Math.round(n.v)) });
    card.classList.add("trace"); setTimeout(() => card.classList.remove("trace"), 900);
    chime();
  }

  function chime() {  // two-note bench bell, Web Audio, no files
    try {
      const ac = new (window.AudioContext || window.webkitAudioContext)();
      [[880, 0], [1318.5, 0.14]].forEach(([f, d]) => {
        const o = ac.createOscillator(), g = ac.createGain();
        o.type = "sine"; o.frequency.value = f; o.connect(g); g.connect(ac.destination);
        g.gain.setValueAtTime(0.0001, ac.currentTime + d);
        g.gain.exponentialRampToValueAtTime(0.25, ac.currentTime + d + 0.01);
        g.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + d + 0.9);
        o.start(ac.currentTime + d); o.stop(ac.currentTime + d + 1);
      });
    } catch (e) {}
  }

  document.getElementById("ppbtn").addEventListener("click", sold);
  window.addEventListener("load", () => setTimeout(async () => { await run(); if (new URLSearchParams(location.search).has("sold")) setTimeout(sold, 300); }, 700));
  window.openCounter = { run, sold };
})();

// ---------- live shopper chat, catalog, agent endpoints ----------
(() => {
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\[([^\]]*)\]\(\s*https:\/\/www\.sandbox\.paypal\.com[^)]*\)?/g, "$1 ↓").replace(/(https:\/\/www\.sandbox\.paypal\.com\S+)/g, "↓");
  const log = document.getElementById("log"), form = document.getElementById("askform"), input = document.getElementById("askin");
  // The chat survives a reload or coming back later (Roma 14526): kept in this browser for 7 days.
  const KEY = "oc_chat_v1";
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) {}
  if (saved && Date.now() - (saved.at || 0) > 7 * 864e5) saved = null;
  const history = saved?.history || [];
  const items = saved?.items || [];
  let convId = saved?.conv_id || "";
  const persist = () => { try { localStorage.setItem(KEY, JSON.stringify({ conv_id: convId, history, items: items.slice(-120), at: Date.now() })); } catch (e) {} };
  const add = (cls, html, keep = true) => { const d = document.createElement("div"); d.className = cls; d.innerHTML = html; log.appendChild(d); log.scrollTop = log.scrollHeight; if (keep) items.push({ cls, html }); return d; };
  // "New chat" sits in the chat's header, visible once a chat has started (Roma 14647); the example questions
  // are only for an empty chat, after that they're in the way
  const bar = document.querySelector(".chat-bar"), fresh = document.createElement("button");
  fresh.type = "button"; fresh.className = "newchat"; fresh.textContent = "↺ New chat"; fresh.hidden = true;
  fresh.addEventListener("click", () => { try { localStorage.removeItem(KEY); } catch (e) {} location.reload(); });
  bar?.appendChild(fresh);
  const started = () => { fresh.hidden = false; document.getElementById("chips")?.remove(); };
  if (items.length) {
    items.forEach((it) => { const d = document.createElement("div"); d.className = it.cls; d.innerHTML = it.html; log.appendChild(d); });
    started();
    requestAnimationFrame(() => (log.scrollTop = log.scrollHeight));
  }

  // PayPal's own buttons inside the receipt: the buyer approves in PayPal's popup and never leaves the chat.
  // The plain link stays as the fallback (no JS SDK, popup blocked, a chat restored after reload).
  let sdk = null;
  const loadSdk = () => sdk || (sdk = fetch("/api/paypal/config").then((r) => r.json()).then((cfg) => new Promise((ok, no) => {
    if (!cfg.client_id) return no(new Error("no client id"));
    const s = document.createElement("script");
    s.src = `https://www.paypal.com/sdk/js?client-id=${encodeURIComponent(cfg.client_id)}&currency=USD&intent=capture&components=buttons&disable-funding=paylater,venmo,card`;
    s.onload = () => ok(window.paypal); s.onerror = no; document.head.appendChild(s);
  })));
  function payInChat(card, c) {
    const token = (String(c.approve_url).match(/token=([A-Z0-9]+)/) || [])[1]; if (!token) return;
    const link = card.querySelector("a.pp"), box = document.createElement("div"); box.className = "ppsdk";
    loadSdk().then((pp) => {
      if (!card.isConnected || !link?.isConnected) return;
      link.before(box);
      return pp.Buttons({
        fundingSource: pp.FUNDING.PAYPAL,   // one PayPal button, no extra funding rows
        style: { layout: "horizontal", color: "gold", shape: "pill", label: "pay", height: 40, tagline: false },
        createOrder: () => token,
        onApprove: () => fetch("/api/paypal/approved", { method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ order_id: c.order_id, paypal_order_id: token }) }).then((r) => r.json()).then((j) => {
            if (j.error) { box.innerHTML = `<p class="fine">${esc(j.error)}</p>`; return; }
            box.innerHTML = `<p class="paidok">✓ Paid in PayPal · ${esc(c.order_id)}</p><a class="thx" href="${esc(j.thanks || "/thanks/" + c.order_id)}" target="_blank" rel="noopener">Your receipt and delivery dates →</a><a class="thx next" href="/maker#orders" target="_blank" rel="noopener">Step 2 · see it land on Lena's side →</a>`;
            const k = items.findIndex((it) => it.html.includes(c.approve_url));
            link.remove();
            if (k >= 0) items[k].html = card.innerHTML;   // a reload shows it paid, not a stale button
            persist();
          }),
        onError: () => { box.remove(); link.hidden = false; },
      }).render(box).then(() => { link.hidden = true; });
    }).catch(() => { box.remove(); if (link) link.hidden = false; });
  }

  async function ask(text) {
    if (!text.trim()) return;
    history.push({ role: "user", content: text });
    add("msg u", esc(text));
    started();
    persist();
    const t = add("think", "Reading your message", false);
    const stages = ["Reading your message", "Checking the shelf", "Working out delivery", "Almost there"];
    let k = 0; const tick = setInterval(() => { k = Math.min(k + 1, stages.length - 1); t.textContent = stages[k]; }, 2200);
    try {
      // never an endless "thinking": the server answers within ~35 s; past 50 s the person gets a retry line
      const ac = new AbortController(), cut = setTimeout(() => ac.abort(), 50000);
      const r = await fetch("/api/shopper", { method: "POST", signal: ac.signal, headers: { "content-type": "application/json" }, body: JSON.stringify({ messages: history, conv_id: convId }) });
      clearTimeout(cut);
      const j = await r.json();
      if (j.conv_id) convId = j.conv_id;
      clearInterval(tick); t.remove();
      if (j.error) { add("msg a", esc(j.error), false); return; }
      for (const s of j.steps) add("tl", `<i></i>${esc(s.label)} · ${esc(s.result)}`);
      add("msg a", md(j.reply));
      history.push({ role: "assistant", content: j.reply, memo: j.memo || "" });
      if (j.checkout) {
        window.dispatchEvent(new CustomEvent("oc-checkout", { detail: j.checkout }));
        const c = j.checkout;
        // a newer order in this chat replaces the earlier one (stock orders): its button no longer pays
        if (c.order_id && !c.deposit_usd) log.querySelectorAll(".cocard:not([data-k=mto]) a.pp").forEach((a) => { a.parentElement.querySelector(".ppsdk")?.remove(); const p = document.createElement("p"); p.className = "fine"; p.textContent = "Replaced by the newer order below."; a.replaceWith(p); });
        const r = c.receipt, $ = (v) => (v < 0 ? "−$" : "$") + Math.abs(v).toFixed(2);
        const rec = r ? `<div class="rcpt"><small>Your order</small><ol>${r.rows.map((x) => `<li><span>${esc(x.name)}</span><b>${x.qty} × ${$(x.unit)} = ${$(x.sum)}</b></li>`).join("")}</ol>
          ${r.extra.map((x) => `<p class="rx"><span>${esc(x.name)}</span><b>${$(x.sum)}</b></p>`).join("")}<p class="rt"><span>Total</span><b>${$(r.total)}</b></p>${r.deposit ? `<p class="rd"><span>Pay now (deposit)</span><b>${$(r.deposit)}</b></p><p class="rn">The rest before your cars ship. PayPal also emailed you the invoice.</p>` : ""}</div>`
          : `<div class="ap-pair"><div><small>You're approving</small>${esc(c.you_are_approving)}</div></div>`;
        const card = add("cocard", `${rec}<details class="asked"><summary>What you asked for</summary>${esc(c.you_asked_for)}</details>
          <a class="pp" href="${esc(c.approve_url)}" target="_blank" rel="noopener"><span class="pp-a">Pay</span><span class="pp-b">Pal</span></a>
          ${c.ship_to ? `<p class="shipto"><small>Ships to</small>${esc(c.ship_to)}</p>` : ""}
          <p class="fine">${esc(c.delivery)}. Nothing is charged until you approve in PayPal.</p>`);
        if (c.deposit_usd) card.dataset.k = "mto"; else payInChat(card, c);
        log.scrollTop = log.scrollHeight;
      }
      persist();
    } catch (e) {
      clearInterval(tick); t.remove();
      history.pop();   // the question wasn't answered: take it back so a retry sends it once
      const again = add("msg a", "That took too long on my side, sorry. ", false);
      const b = document.createElement("button"); b.type = "button"; b.className = "retry"; b.textContent = "Send it again";
      b.addEventListener("click", () => {
        again.remove();
        const mine = [...log.querySelectorAll(".msg.u")].pop(); if (mine) mine.remove();   // ask() shows it again
        const k = items.map((it) => it.cls).lastIndexOf("msg u"); if (k >= 0) items.splice(k, 1);
        ask(text);
      }, { once: true });
      again.appendChild(b); persist();
    }
  }
  // first visit: one line that says what to do, gone after the first message
  const chips = document.getElementById("chips");
  if (!items.length && chips) {
    const hint = document.createElement("p"); hint.className = "firsthint";
    hint.textContent = "New here? Tap a question below, or type your own. A test buyer for PayPal is under the chat.";
    chips.before(hint);
    const off = () => hint.remove();
    form.addEventListener("submit", off, { once: true }); chips.addEventListener("click", off, { once: true });
  }
  form.addEventListener("submit", (e) => { e.preventDefault(); const v = input.value; input.value = ""; ask(v); });
  document.querySelectorAll("#chips button").forEach((b) => b.addEventListener("click", () => ask(b.textContent)));

  // catalog from the same JSON agents read
  const slug = "small-garage";
  fetch(`/c/${slug}.json`).then((r) => r.json()).then((d) => {
    document.getElementById("mcpurl").textContent = d.mcp;
    document.getElementById("jsonurl").textContent = location.origin + `/c/${slug}.json`;
    const paint = { "68-G": "#1F6B47", "67-B": "#1E3F8A", "70-O": "#FF5A1F", "73-Y": "#F5C400", "65-R": "#E3242B" };
    document.getElementById("cards").innerHTML = d.listings.map((x) => {
      const code = (x.paint.match(/code (\w+-\w)/) || [])[1] || "";
      const yr = (x.title.match(/(\d{4})/) || [])[1] || "";
      return `<article class="card" id="${esc(x.id)}">
        <img class="d" src="${esc(x.photo_url)}" alt="" loading="lazy"><img class="l" src="${esc(x.photo_url)}" alt="${esc(x.title)}" loading="lazy">
        <div class="yr">${esc(yr.slice(2))}</div>
        <div class="meta"><h3>${esc(x.title.replace(/, \d{4}$/, ""))}</h3>
          <div class="spec"><span class="chip" style="background:${paint[code] || "#888"}"></span>${esc(code)} · ${esc(x.scale)} · ${x.length_mm} mm · ${x.build_hours} h</div>
          <div class="row"><span class="price">$${x.price_usd.toFixed(0)}</span><span class="stock ${x.stock > 0 ? "" : "out"}" data-stock="${esc(x.id)}">${x.stock > 0 ? x.stock + " AVAILABLE" : "SOLD OUT · MADE TO ORDER"}</span></div>
          <div class="acts2"><button class="buy" data-buy="${esc(x.id)}" data-title="${esc(x.title)}" data-price="${x.price_usd}" data-max="${x.stock}" ${x.stock > 0 ? "" : "disabled"}>${x.stock > 0 ? "Buy · $" + x.price_usd.toFixed(0) : "Sold out"}</button>${x.model_url ? `<button class="m3d" data-model="${esc(x.model_url)}" data-title="${esc(x.title)}"><span class="cube" aria-hidden="true"></span>View in 3D</button>` : ""}</div></div></article>`;
    }).join("");
    document.querySelectorAll(".card").forEach((c) => c.addEventListener("pointermove", (e) => {
      const r = c.getBoundingClientRect();
      c.style.setProperty("--cx", ((e.clientX - r.left) / r.width * 100) + "%");
      c.style.setProperty("--cy", ((e.clientY - r.top) / r.height * 100) + "%");
    }));
  });
  // stock shown to buyers is live: refreshed from the same JSON agents read
  setInterval(() => fetch(`/c/${slug}.json`).then((r) => r.json()).then((d) => d.listings.forEach((x) => {
    const s = document.querySelector(`[data-stock="${x.id}"]`), b = document.querySelector(`[data-buy="${x.id}"]`);
    if (s) { s.textContent = x.stock > 0 ? x.stock + " AVAILABLE" : "SOLD OUT · MADE TO ORDER"; s.classList.toggle("out", x.stock <= 0); }
    if (b) { b.dataset.max = x.stock; b.disabled = x.stock <= 0; b.textContent = x.stock > 0 ? "Buy · $" + x.price_usd.toFixed(0) : "Sold out"; }
  })).catch(() => {}), 20000);
  // a person can buy directly too: same rules, same PayPal approval
  const STATES = "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA PR RI SC SD TN TX UT VT VA WA WV WI WY".split(" ");
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-buy]"); if (!b || b.disabled) return;
    const bg = document.createElement("div"); bg.className = "sheet-bg";
    const max = Math.max(1, +b.dataset.max || 1), price = +b.dataset.price || 59;
    bg.innerHTML = `<div class="sheet"><h3>${esc(b.dataset.title)}</h3><p>$${price.toFixed(0)} each + $6.50 shipping · ${max} available · Lena ships Mon–Fri from Columbus, OH. You approve in PayPal; nothing is charged before that.</p>
      <label class="qty">How many <input id="qn" type="number" min="1" max="${max}" value="1"> <span id="qt">$${(price + 6.5).toFixed(2)}</span></label>
      <select id="st"><option value="">Ship to which state?</option>${STATES.map((s) => `<option>${s}</option>`).join("")}</select>
      <div class="row2"><button type="button" class="cx">Cancel</button><button type="button" class="go"><span style="color:#003087">Pay</span><span style="color:#009CDE">Pal</span></button></div><div class="msg2" id="m2"></div></div>`;
    document.body.appendChild(bg);
    const qn = bg.querySelector("#qn");
    qn.addEventListener("input", () => { const n = Math.min(max, Math.max(1, +qn.value || 1)); bg.querySelector("#qt").textContent = "$" + (n * price + 6.5).toFixed(2); });
    bg.addEventListener("click", async (ev) => {
      if (ev.target === bg || ev.target.classList.contains("cx")) return bg.remove();
      if (!ev.target.closest(".go")) return;
      const st = bg.querySelector("#st").value; if (!st) { bg.querySelector("#m2").textContent = "Pick a state first."; return; }
      const r = await fetch("/api/checkout", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ item_id: b.dataset.buy, quantity: Math.min(max, Math.max(1, +qn.value || 1)), us_state: st, asked_for: "Bought directly on the counter page", channel: "web" }) });
      const j = await r.json();
      if (j.ok) location.href = j.approve_url; else bg.querySelector("#m2").textContent = j.reason || "Couldn't start checkout.";
    });
  });
  // 3D: the replica as a glTF model, turned with a finger or the mouse, lit like the bench
  let mvLoaded = false;
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-model]"); if (!b) return;
    if (!mvLoaded) { const s = document.createElement("script"); s.type = "module"; s.src = "https://unpkg.com/@google/model-viewer@3.5.0/dist/model-viewer.min.js"; document.head.appendChild(s); mvLoaded = true; }
    const bg = document.createElement("div"); bg.className = "v3d-bg";
    bg.innerHTML = `<div class="v3d-box"><button class="v3d-x" aria-label="Close">&times;</button>
      <model-viewer src="${esc(b.dataset.model)}" alt="${esc(b.dataset.title)}, 3D model" camera-controls touch-action="pan-y" auto-rotate auto-rotate-delay="0" rotation-per-second="18deg"
        interaction-prompt="auto" shadow-intensity="1.1" shadow-softness="0.8" exposure="1.05" tone-mapping="neutral" camera-orbit="35deg 72deg 105%" min-camera-orbit="auto 20deg auto" max-camera-orbit="auto 95deg auto"></model-viewer>
      <div class="v3d-cap"><b>${esc(b.dataset.title)}</b><span>Drag to turn · pinch or scroll to zoom</span></div></div>`;
    document.body.appendChild(bg);
    bg.addEventListener("click", (ev) => { if (ev.target === bg || ev.target.closest(".v3d-x")) bg.remove(); });
  });
  document.getElementById("copy").addEventListener("click", () => navigator.clipboard?.writeText(document.getElementById("mcpurl").textContent));
})();

// "How one is made": each clip plays only while it's on screen
(() => {
  const vids = document.querySelectorAll(".steps4 video"); if (!vids.length || !("IntersectionObserver" in window)) return;
  const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) e.target.play().catch(() => {}); else e.target.pause(); }), { threshold: 0.35 });
  vids.forEach((v) => io.observe(v));
})();

// Lena's side, live, right under the chat: what the maker sees as your order moves (same feed as her screen).
(() => {
  const box = document.getElementById("lenaside"); if (!box) return;
  const t = document.getElementById("ls-t"), sub = document.getElementById("ls-s");
  const mine = new Set();
  const says = { awaiting_approval: ["New order on Lena's phone", "Waiting for your OK in PayPal; nothing is charged yet."],
    paid: ["SOLD TO AN AI AGENT", "Paid in PayPal. Lena packs it and adds the tracking number."],
    deposit_paid: ["Deposit in: Lena starts building", "The rest is due before it ships."],
    shipped: ["Shipped", "The tracking number went to PayPal; the buyer is told."],
    replaced: ["Replaced by your newer order", "Only the newest order can be paid."],
    refunded_out_of_stock: ["Refunded", "The last one sold a moment earlier; PayPal refunded you in full."] };
  const show = (o) => { const w = says[o.status] || [o.status, ""]; box.hidden = false; box.classList.toggle("paid", ["paid", "deposit_paid", "shipped"].includes(o.status));
    t.textContent = `${w[0]} · ${o.id}`; sub.textContent = `${o.title} · $${(o.total_usd || 0).toFixed(2)}. ${w[1]}`; };
  window.addEventListener("oc-checkout", (e) => { mine.add(e.detail.order_id); fetch(`/api/orders/${e.detail.order_id}`).then((r) => r.json()).then((o) => o.id && show(o)).catch(() => {}); });
  try {
    const es = new EventSource("/api/maker/feed");
    es.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.order && mine.has(m.order.id)) show(m.order); };
  } catch (e) {}
})();

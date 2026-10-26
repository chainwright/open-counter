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

  (function loop(now) {
    if (auto) {  // a slow figure-eight over the car while nobody holds the lamp (also what the video shows)
      const s = (now - t0) / 1000;
      tx = 0.6 + 0.16 * Math.sin(s * 0.45); ty = 0.5 + 0.12 * Math.sin(s * 0.9);
    }
    x += (tx - x) * 0.12; y += (ty - y) * 0.12;
    root.style.setProperty("--mx", (x * 100).toFixed(2) + "%");
    root.style.setProperty("--my", (y * 100).toFixed(2) + "%");
    requestAnimationFrame(loop);
  })(performance.now());

  // --- the shopper's AI at work (demo script; the live demo runs the same tools for real) ---
  const steps = [
    ["searching makers' counters", "found <b>Small Garage</b> · Columbus, OH"],
    ["reading the listing", "<b>Green Fastback, 1968</b> · 1:43 · $59 · 1 in stock"],
    ["checking delivery to CO", "ships Mon · arrives <b>Thu–Fri</b>"],
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
  const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(https:\/\/www\.sandbox\.paypal\.com\S+)/g, "");
  const log = document.getElementById("log"), form = document.getElementById("askform"), input = document.getElementById("askin");
  const history = [];
  const add = (cls, html) => { const d = document.createElement("div"); d.className = cls; d.innerHTML = html; log.appendChild(d); log.scrollTop = log.scrollHeight; return d; };

  async function ask(text) {
    if (!text.trim()) return;
    history.push({ role: "user", content: text });
    add("msg u", esc(text));
    const t = add("think", "Shopper's AI is working…");
    try {
      const r = await fetch("/api/shopper", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ messages: history }) });
      const j = await r.json();
      t.remove();
      if (j.error) { add("msg a", esc(j.error)); return; }
      for (const s of j.steps) add("tl", `<i></i>${esc(s.label)} · ${esc(s.result)}`);
      add("msg a", md(j.reply));
      history.push({ role: "assistant", content: j.reply });
      if (j.checkout) {
        const c = j.checkout;
        add("cocard", `<div class="ap-pair"><div><small>You asked for</small>${esc(c.you_asked_for)}</div><div><small>You're approving</small>${esc(c.you_are_approving)}</div></div>
          <a class="pp" href="${esc(c.approve_url)}" target="_blank" rel="noopener"><span class="pp-a">Pay</span><span class="pp-b">Pal</span></a>
          <p class="fine">${esc(c.delivery)}. Nothing is charged until you approve in PayPal.</p>`);
      }
    } catch (e) { t.textContent = "Couldn't reach the counter. Try again."; }
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
          <div class="row"><span class="price">$${x.price_usd.toFixed(0)}</span><span class="stock ${x.stock > 0 ? "" : "out"}">${x.stock > 0 ? x.stock + " IN STOCK" : "SOLD OUT · COMMISSION"}</span></div>
          <button class="buy" data-buy="${esc(x.id)}" data-title="${esc(x.title)}" ${x.stock > 0 ? "" : "disabled"}>${x.stock > 0 ? "Buy · $" + x.price_usd.toFixed(0) : "Sold out"}</button></div></article>`;
    }).join("");
    document.querySelectorAll(".card").forEach((c) => c.addEventListener("pointermove", (e) => {
      const r = c.getBoundingClientRect();
      c.style.setProperty("--cx", ((e.clientX - r.left) / r.width * 100) + "%");
      c.style.setProperty("--cy", ((e.clientY - r.top) / r.height * 100) + "%");
    }));
  });
  // a person can buy directly too: same rules, same PayPal approval
  const STATES = "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA PR RI SC SD TN TX UT VT VA WA WV WI WY".split(" ");
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-buy]"); if (!b || b.disabled) return;
    const bg = document.createElement("div"); bg.className = "sheet-bg";
    bg.innerHTML = `<div class="sheet"><h3>${esc(b.dataset.title)}</h3><p>$59 + $6.50 shipping · Lena ships Mon–Fri from Columbus, OH. You approve in PayPal; nothing is charged before that.</p>
      <select id="st"><option value="">Ship to which state?</option>${STATES.map((s) => `<option>${s}</option>`).join("")}</select>
      <div class="row2"><button type="button" class="cx">Cancel</button><button type="button" class="go"><span style="color:#003087">Pay</span><span style="color:#009CDE">Pal</span></button></div><div class="msg2" id="m2"></div></div>`;
    document.body.appendChild(bg);
    bg.addEventListener("click", async (ev) => {
      if (ev.target === bg || ev.target.classList.contains("cx")) return bg.remove();
      if (!ev.target.closest(".go")) return;
      const st = bg.querySelector("#st").value; if (!st) { bg.querySelector("#m2").textContent = "Pick a state first."; return; }
      const r = await fetch("/api/checkout", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ item_id: b.dataset.buy, quantity: 1, us_state: st, asked_for: "Bought directly on the counter page", channel: "web" }) });
      const j = await r.json();
      if (j.ok) location.href = j.approve_url; else bg.querySelector("#m2").textContent = j.reason || "Couldn't start checkout.";
    });
  });
  document.getElementById("copy").addEventListener("click", () => navigator.clipboard?.writeText(document.getElementById("mcpurl").textContent));
})();

// One period for every tab (Roma 14547): today, week, 2 weeks, month, quarter, year.
window.OC = (() => {
  let days = 14;
  const start = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime() / 1000 - (days - 1) * 86400; };
  const label = () => ({ 1: "today", 7: "in the last 7 days", 14: "in the last 2 weeks", 30: "in the last month", 90: "in the last quarter", 365: "in the last year" })[days];
  document.addEventListener("click", (e) => {
    const b = e.target.closest("#ovp [data-d]"); if (!b) return;
    days = +b.dataset.d; document.querySelectorAll("#ovp button").forEach((x) => x.classList.toggle("on", x === b));
    document.dispatchEvent(new Event("oc-period"));
  });
  return { get days() { return days; }, start, label };
})();

// Lena's phone: live order feed (SSE), "sold to an AI agent" moment, packing note, tracking, stock.
(() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const photos = {};
  let orders = [];

  async function load() {
    const [o, c] = await Promise.all([fetch("/api/maker/orders").then((r) => r.json()), fetch("/c/small-garage.json").then((r) => r.json())]);
    c.listings.forEach((l) => (photos[l.id] = l.photo_url));
    orders = o;
    renderStock(c);
    render();
  }

  function render() {
    const feed = document.getElementById("feed");
    const shown = orders.filter((o) => o.status !== "error" && o.created >= OC.start());
    document.getElementById("s-sold").textContent = shown.filter((o) => ["paid", "shipped"].includes(o.status) && o.channel !== "walk-in").length;
    document.getElementById("s-wait").textContent = shown.filter((o) => o.status === "awaiting_approval").length;
    const today = new Date().toDateString();
    const rev = shown.filter((o) => o.paid_at && new Date(o.paid_at * 1000).toDateString() === today).reduce((a, o) => a + o.total_usd, 0);
    const sr = document.getElementById("s-rev"); if (sr) sr.textContent = "$" + rev.toFixed(0);
    if (!shown.length) return;
    feed.innerHTML = shown.map((o) => {
      const st = { awaiting_approval: "WAITING FOR BUYER", paid: "PAID · SHIP IT", shipped: "SHIPPED", cancelled: "CANCELLED", refunded_out_of_stock: "REFUNDED" }[o.status] || o.status.toUpperCase();
      const where = (o.customer?.name ? o.customer.name + " · " : "") + (o.ship_to?.city ? `${o.ship_to.city}, ${o.ship_to.state}` : (o.customer?.where || o.ship_state));
      const acts = o.status === "paid"
        ? `<div class="acts"><button class="p" data-note="${esc(o.id)}">Packing note</button><input placeholder="Tracking number" data-trk="${esc(o.id)}"><button data-ship="${esc(o.id)}">Shipped</button></div><div class="note" id="n-${esc(o.id)}" hidden></div>`
        : o.status === "shipped" ? `<div class="m">USPS ${esc(o.tracking?.number)}</div>` : "";
      const mto = o.kind === "commission" ? `<div class="m">MADE TO ORDER · build ${o.quote?.build_weeks} wk · ready ${esc((o.quote?.ready_to_ship_by || "").split(" ").pop())}${o.contact ? ` · ${esc(o.contact.name)} <a href="tel:${esc(o.contact.phone)}">${esc(o.contact.phone)}</a>` : ""}</div>` : "";
      return `<div class="o"><img src="${esc(photos[o.listing_id] || "")}" alt=""><div>${mto}
        <span class="badge ${esc(o.status)}">${st}</span>${o.sample ? ` <span class="badge smpb">SAMPLE</span>` : ""}
        <h3>${esc(o.title)}</h3>
        <div class="m">$${o.total_usd.toFixed(2)} · ${esc(where)} · via ${o.channel === "web" ? "shop page (human)" : o.channel === "mcp" ? "AI agent (MCP)" : o.channel === "demo-shopper" || o.channel === "web-agent" ? "AI agent" : esc(o.channel)}</div>
        <div class="asked">"${esc((o.asked_for || "").slice(0, 140))}"</div>${acts}</div></div>`;
    }).join("");
  }

  function renderStock(c) {
    document.getElementById("stock").innerHTML = c.listings.map((l) => `<a class="s" href="/#${esc(l.id)}"><img src="${esc(l.photo_url)}" alt=""><div><b>${esc(l.title.replace(/, \d{4}$/, ""))}</b><span>${l.stock > 0 ? l.stock + " left" : "sold out"} · $${l.price_usd.toFixed(0)}</span></div></a>`).join("");
    document.getElementById("rules").textContent = `Rules agents must follow: ships to ${c.ships_to} only · any quantity up to the stock shown · $${c.shipping_usd.toFixed(2)} shipping · made to order: ${c.made_to_order} · every order approved by the buyer in PayPal.`;
  }

  function toast(o) {
    document.querySelector(".t-k").innerHTML = o.channel === "web" ? "SOLD ON<br>YOUR COUNTER" : "SOLD TO AN<br>AI AGENT";
    document.getElementById("t-a").textContent = "$" + o.total_usd.toFixed(2);
    document.getElementById("t-l").textContent = `${o.title} · ${o.ship_to?.city || o.ship_state} · ship by ${o.estimate?.ships_on || ""}`;
    const t = document.getElementById("toast");
    t.classList.add("on"); setTimeout(() => t.classList.remove("on"), 5200);
    try {
      const ac = new AudioContext();
      [[880, 0], [1318.5, 0.14]].forEach(([f, d]) => {
        const os = ac.createOscillator(), g = ac.createGain(); os.frequency.value = f; os.connect(g); g.connect(ac.destination);
        g.gain.setValueAtTime(0.0001, ac.currentTime + d); g.gain.exponentialRampToValueAtTime(0.25, ac.currentTime + d + 0.01);
        g.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + d + 0.9); os.start(ac.currentTime + d); os.stop(ac.currentTime + d + 1);
      });
    } catch (e) {}
  }

  document.addEventListener("click", async (e) => {
    const n = e.target.dataset.note, s = e.target.dataset.ship;
    if (n) {
      const o = orders.find((x) => x.id === n), box = document.getElementById("n-" + n);
      box.hidden = false;
      box.textContent = `${o.id}\n${o.qty} × ${o.title}\nTo: ${o.ship_to?.name || ""}, ${o.ship_to?.city || ""} ${o.ship_to?.state || o.ship_state}\nPlinth + dust cover · wrap in two layers · FRAGILE\nNote: "Hand-built for you in Columbus. — Lena"`;
    }
    if (s) {
      const num = document.querySelector(`[data-trk="${s}"]`).value.trim();
      if (!num) return;
      const r = await fetch(`/api/maker/orders/${s}/tracking`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ tracking_number: num, carrier: "USPS" }) });
      if (r.ok) load();
    }
  });

  const es = new EventSource("/api/maker/feed");
  es.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    const i = orders.findIndex((o) => o.id === m.order.id);
    if (i >= 0) orders[i] = m.order; else orders.unshift(m.order);
    render();
    if (m.kind === "paid") { toast(m.order); load(); }
  };
  es.onerror = () => (document.getElementById("live").textContent = "○ reconnecting");
  es.onopen = () => (document.getElementById("live").textContent = "● live");
  document.addEventListener("oc-period", render);
  load();
})();

// People who asked Lena to call them (the agent took their number).
(() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const box = document.getElementById("reqs"); if (!box) return;
  async function load() {
    const rs = (await fetch("/api/maker/requests").then((r) => r.json()).catch(() => [])).filter((r) => r.kind === "callback");
    box.hidden = !rs.length; if (!rs.length) return;
    box.innerHTML = `<h2 class="rq-h">Call back <span>${rs.filter((r) => r.status === "to_call").length} waiting</span></h2>` + rs.map((r) => `
      <div class="rq ${esc(r.status)}"><span class="badge rqb">${r.status === "to_call" ? "CALL THEM" : "CALLED"}</span>
        <h3><a href="tel:${esc(r.contact.phone)}">${esc(r.contact.phone)}</a>${r.contact.name ? " · " + esc(r.contact.name) : ""}</h3>
        ${r.message ? `<div class="asked">"${esc(r.message)}"</div>` : ""}
        <div class="m">via ${r.channel === "mcp" ? "AI agent (MCP)" : "AI agent"} · ${new Date(r.created * 1000).toLocaleString()}</div>
        ${r.status === "to_call" ? `<div class="acts"><a class="p btn" href="tel:${esc(r.contact.phone)}">Call</a><button data-rq="${esc(r.id)}" data-st="called">Done</button></div>` : ""}
      </div>`).join("");
  }
  box.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-rq]"); if (!b) return;
    await fetch(`/api/maker/requests/${b.dataset.rq}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ status: b.dataset.st }) });
    load();
  });
  load(); setInterval(load, 10000);
})();

// Tabs, today's numbers, chats by day (each opens on its own), customers with the news list (Roma 14530).
(() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const day = (t) => { const d = new Date(t * 1000); d.setHours(0, 0, 0, 0); return d.getTime(); };
  const today = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime(); };
  const dayName = (ms) => { const n = Math.round((today() - ms) / 864e5); return n === 0 ? "Today" : n === 1 ? "Yesterday" : new Date(ms).toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" }); };
  const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  let chats = [], custs = [], orders = [], calls = [], filter = "all";

  function show() {
    const [tab, id] = (location.hash.slice(1) || "today").split("/");
    document.querySelectorAll(".tab").forEach((t) => (t.hidden = t.id !== "tab-" + tab));
    document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#" + tab));
    document.getElementById("ovp").hidden = tab === "stock";
    if (tab === "chats") openChat(id);
  }
  window.addEventListener("hashchange", show);

  const who = (c) => c.name ? esc(c.name) : `<span class="guest">Guest, no name</span>`;
  const row = (c) => `<a class="row chat" href="#chats/${esc(c.id)}"><b>${esc(clock(c.updated))}</b>
    <span><em class="no">#${c.no || "–"}</em> ${who(c)}${c.sample ? ` <em class="smp">sample</em>` : ""}<small>${esc((c.turns[0]?.user || "").slice(0, 90))}</small></span>
    <i>${c.turns.length} msg${c.orders.length ? ` · <em>${c.orders.length} order${c.orders.length > 1 ? "s" : ""}</em>` : ""}${!c.name && !c.asked_name ? `<br><u>AI didn't ask the name</u>` : ""}</i></a>`;

  function renderChats() {
    const groups = {};
    chats.filter((c) => c.updated >= OC.start()).forEach((c) => (groups[day(c.updated)] ||= []).push(c));
    const keys = Object.keys(groups).map(Number).sort((a, b) => b - a);
    document.getElementById("chatlist").innerHTML = keys.length ? keys.map((k) => `<div class="k sec">${esc(dayName(k).toUpperCase())} · ${groups[k].length} chat${groups[k].length > 1 ? "s" : ""}</div>
      <div class="rows">${groups[k].map(row).join("")}</div>`).join("") : `<p class="empty">No chats yet.</p>`;
    const t = groups[today()] || [];
    document.getElementById("latest").innerHTML = t.length ? t.slice(0, 4).map(row).join("") : `<p class="empty">No chats yet today.</p>`;
    document.getElementById("n-chats").textContent = t.length ? t.length : "";
  }

  function openChat(id) {
    const list = document.getElementById("chatlist"), view = document.getElementById("chatview");
    const c = chats.find((x) => x.id === id);
    list.hidden = !!c; view.hidden = !c;
    if (!c) return;
    view.innerHTML = `<a class="back" href="#chats">← all chats</a>
      <div class="chead"><b>#${c.no || "–"} · ${c.name ? esc(c.name) : "Guest, no name"}</b><span>${esc(dayName(day(c.started)))}, ${esc(clock(c.started))} · ${!c.name ? (c.asked_name ? "the AI asked for a name, none given · " : "the AI never asked for a name · ") : ""}${c.turns.length} message${c.turns.length > 1 ? "s" : ""}${c.orders.length ? " · orders " + c.orders.map(esc).join(", ") : " · no order"}</span></div>
      <div class="thread">${c.turns.map((t) => `<p class="q">${esc(t.user)}</p>${t.steps.length ? `<p class="s">${t.steps.map(esc).join("<br>")}</p>` : ""}<p class="a">${esc(t.reply)}</p>`).join("")}</div>`;
  }

  function renderCustomers() {
    const pick = custs.filter((c) => (c.last_seen || 0) >= OC.start()).filter((c) => filter === "all" || (filter === "yes" && c.marketing === true) || (filter === "no" && c.marketing === false) || (filter === "none" && c.marketing == null));
    document.getElementById("custs").innerHTML = pick.length ? pick.map((c) => `<div class="cu"><div><b>${esc(c.name)}</b><span>${esc(c.where)}</span></div>
      <span>${esc(c.email)} · ${esc(c.phone)}</span>
      <span class="n ${c.marketing === true ? "y" : c.marketing === false ? "x" : ""}">${c.marketing === true ? "Wants news" : c.marketing === false ? "No emails" : "Not asked yet"} · ${c.orders.length} order${c.orders.length > 1 ? "s" : ""}</span></div>`).join("")
      : `<p class="empty">Nobody here yet.</p>`;
  }
  document.getElementById("cfilter").addEventListener("click", (e) => {
    const b = e.target.closest("[data-f]"); if (!b) return;
    filter = b.dataset.f; document.querySelectorAll("#cfilter button").forEach((x) => x.classList.toggle("on", x === b)); renderCustomers();
  });
  document.getElementById("export").addEventListener("click", () => {
    const key = prompt("Lena's key"); if (key) location.href = "/api/maker/news-list.csv?key=" + encodeURIComponent(key);
  });


  const PL = { 1: "today", 7: "in the last 7 days", 14: "in the last 2 weeks", 30: "in the last month", 90: "in the last quarter", 365: "in the last year" };
  function renderToday() {
    const ovDays = OC.days;
    const t0 = OC.start();
    const live = (o) => !["error", "cancelled", "refunded_out_of_stock"].includes(o.status);
    document.querySelectorAll("#tab-today .pl").forEach((e) => (e.textContent = PL[ovDays]));
    document.getElementById("t-chats").textContent = chats.filter((c) => c.started >= t0).length;
    document.getElementById("t-orders").textContent = orders.filter((o) => o.created >= t0 && live(o)).length;
    document.getElementById("t-rev").textContent = "$" + orders.filter((o) => (o.paid_at || 0) >= t0 && ["paid", "shipped"].includes(o.status)).reduce((a, o) => a + o.total_usd, 0).toFixed(0);
    document.getElementById("t-calls").textContent = calls.filter((r) => r.status === "to_call").length;
    document.getElementById("t-subs").textContent = custs.filter((c) => c.marketing === true && (c.consent_at || 0) >= t0).length;
    document.getElementById("n-orders").textContent = orders.filter((o) => o.status === "paid").length || "";
    // chart: days (up to 2 weeks), weeks (month, quarter) or months (year)
    const span = ovDays === 1 ? 7 : ovDays;
    const unit = span <= 14 ? 1 : span <= 90 ? 7 : 30;
    const n = Math.ceil(span / unit);
    const end = today() + 864e5;
    const buckets = [...Array(n)].map((_, i) => { const a = end - (n - i) * unit * 864e5; return { a, b: a + unit * 864e5 }; });
    const cnt = buckets.map((x) => ({ ...x, c: chats.filter((c) => c.started * 1000 >= x.a && c.started * 1000 < x.b).length,
      o: orders.filter((o) => o.created * 1000 >= x.a && o.created * 1000 < x.b && live(o)).length }));
    const max = Math.max(1, ...cnt.map((x) => Math.max(x.c, x.o)));
    const lab = (x) => unit === 1 ? new Date(x.a).toLocaleDateString([], n > 7 ? { day: "numeric" } : { weekday: "short" })
      : unit === 7 ? new Date(x.a).toLocaleDateString([], { month: "short", day: "numeric" }) : new Date(x.a + 15 * 864e5).toLocaleDateString([], { month: "short" });
    const w = document.getElementById("week");
    w.style.gridTemplateColumns = `repeat(${n}, minmax(0,1fr))`;
    w.innerHTML = cnt.map((x) => `<div class="wd"><div class="bars"><i class="bc" style="height:${(x.c / max) * 100}%"></i><i class="bo" style="height:${(x.o / max) * 100}%"></i></div>
      ${n <= 14 ? `<b>${x.c}/${x.o}</b>` : ""}<span>${esc(lab(x))}</span></div>`).join("") + `<p class="legend"><i class="bc"></i>chats <i class="bo"></i>orders${unit > 1 ? ` · per ${unit === 7 ? "week" : "month"}` : ""}</p>`;
    document.getElementById("ovchart").textContent = ovDays === 1 ? "LAST 7 DAYS" : "CHATS AND ORDERS " + PL[ovDays].toUpperCase();
    const recent = chats.filter((c) => c.updated >= t0);
    document.getElementById("ovlatest").textContent = ovDays === 1 ? "TODAY'S CHATS" : "LATEST CHATS " + PL[ovDays].toUpperCase();
    document.getElementById("latest").innerHTML = recent.length ? recent.slice(0, 5).map(row).join("") : `<p class="empty">No chats ${PL[ovDays]}.</p>`;
  }

  async function load() {
    [chats, custs, orders, calls] = await Promise.all(["/api/maker/conversations", "/api/maker/customers", "/api/maker/orders", "/api/maker/requests"]
      .map((u) => fetch(u).then((r) => r.json()).catch(() => [])));
    renderChats(); renderCustomers(); renderToday(); show();
  }
  document.addEventListener("oc-period", () => { renderChats(); renderCustomers(); renderToday(); show(); });
  load(); setInterval(load, 15000);
})();

// Insights: what sells (in the cars' colours), when shoppers come, where the AI got stuck (Roma 14532).
(() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  async function load() {
    const days = OC.days;
    const d = await fetch(`/api/maker/insights?days=${days}`).then((r) => r.json());
    // bucket a long period into weeks so the lines stay readable
    const step = days > 60 ? 7 : 1;
    const n = Math.ceil(d.labels.length / step);
    const lab = [...Array(n)].map((_, i) => d.labels[Math.min(i * step, d.labels.length - 1)]);
    const ser = d.series.map((s) => ({ ...s, pts: [...Array(n)].map((_, i) => s.units.slice(i * step, i * step + step).reduce((a, b) => a + b, 0)) }));
    const max = Math.max(1, ...ser.flatMap((s) => s.pts));
    const X = (i) => 30 + (n === 1 ? 320 : (i * 650) / (n - 1)), Y = (v) => 200 - (v / max) * 180;
    let svg = [0, 0.5, 1].map((f) => `<line x1="30" x2="690" y1="${Y(max * f)}" y2="${Y(max * f)}" class="grid"/><text x="2" y="${Y(max * f) + 4}" class="ax">${Math.round(max * f)}</text>`).join("");
    svg += ser.filter((s) => s.pts.some((v) => v)).map((s) => `<polyline fill="none" stroke="${s.colour}" stroke-width="3" stroke-linejoin="round" points="${s.pts.map((v, i) => X(i) + "," + Y(v)).join(" ")}"/>`
      + s.pts.map((v, i) => (v ? `<circle cx="${X(i)}" cy="${Y(v)}" r="4" fill="${s.colour}"/>` : "")).join("")).join("");
    [0, Math.floor((n - 1) / 2), n - 1].forEach((i) => (svg += `<text x="${X(i)}" y="217" class="ax" text-anchor="middle">${esc(new Date(lab[i] + "T12:00").toLocaleDateString([], { month: "short", day: "numeric" }))}</text>`));
    document.getElementById("lines").innerHTML = svg;
    document.getElementById("keys").innerHTML = ser.map((s) => `<span><i style="background:${s.colour}"></i>${esc(s.title)}</span>`).join("");
    const tot = ser.map((s) => ({ ...s, u: s.units.reduce((a, b) => a + b, 0) })).sort((a, b) => b.u - a.u);
    const top = Math.max(1, tot[0].u);
    document.getElementById("rank").innerHTML = tot.map((s, i) => `<div class="rk"><span>${i + 1}. ${esc(s.title)}</span><div class="rb"><i style="width:${(s.u / top) * 100}%;background:${s.colour}"></i></div><b>${s.u} car${s.u === 1 ? "" : "s"}${s.usd ? ` · $${s.usd.toFixed(0)} paid` : ""}</b></div>`).join("");
    const hm = Math.max(1, ...d.heat.flat());
    const wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    document.getElementById("heat").innerHTML = `<span></span>${[0, 6, 12, 18].map((h) => `<b style="grid-column:span 6">${h}:00</b>`).join("")}`
      + d.heat.map((r, w) => `<span>${wd[w]}</span>` + r.map((v, h) => `<i title="${wd[w]} ${h}:00 · ${v} msg" style="opacity:${v ? 0.25 + 0.75 * (v / hm) : 0.06}"></i>`).join("")).join("");
    document.getElementById("quality").innerHTML = `<div><b>${d.chats}</b><span>chats</span></div><div><b>${d.conversion}%</b><span>of chats became an order</span></div>
      <div><b>${d.answered_pct}%</b><span>of messages answered without trouble</span></div>`;
    document.getElementById("stuck").innerHTML = d.stuck.length ? d.stuck.map((x) => `<a class="row" href="#chats/${esc(x.chat)}"><b>${esc(new Date(x.at * 1000).toLocaleDateString([], { month: "short", day: "numeric" }))}</b><span>${esc(x.asked)}</span><i>${esc(x.why)}</i></a>`).join("")
      : `<p class="empty">Nothing to fix in this period: every message got a proper answer.</p>`;
  }
  document.addEventListener("oc-period", load);
  load(); setInterval(load, 30000);
})();

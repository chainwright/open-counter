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
    const shown = orders.filter((o) => o.status !== "error");
    document.getElementById("s-sold").textContent = shown.filter((o) => ["paid", "shipped"].includes(o.status) && o.channel !== "walk-in").length;
    document.getElementById("s-wait").textContent = shown.filter((o) => o.status === "awaiting_approval").length;
    const today = new Date().toDateString();
    const rev = shown.filter((o) => o.paid_at && new Date(o.paid_at * 1000).toDateString() === today).reduce((a, o) => a + o.total_usd, 0);
    document.getElementById("s-rev").textContent = "$" + rev.toFixed(0);
    if (!shown.length) return;
    feed.innerHTML = shown.map((o) => {
      const st = { awaiting_approval: "WAITING FOR BUYER", paid: "PAID · SHIP IT", shipped: "SHIPPED", cancelled: "CANCELLED", refunded_out_of_stock: "REFUNDED" }[o.status] || o.status.toUpperCase();
      const where = o.ship_to?.city ? `${o.ship_to.city}, ${o.ship_to.state}` : o.ship_state;
      const acts = o.status === "paid"
        ? `<div class="acts"><button class="p" data-note="${esc(o.id)}">Packing note</button><input placeholder="Tracking number" data-trk="${esc(o.id)}"><button data-ship="${esc(o.id)}">Shipped</button></div><div class="note" id="n-${esc(o.id)}" hidden></div>`
        : o.status === "shipped" ? `<div class="m">USPS ${esc(o.tracking?.number)}</div>` : "";
      const mto = o.kind === "commission" ? `<div class="m">MADE TO ORDER · build ${o.quote?.build_weeks} wk · ready ${esc((o.quote?.ready_to_ship_by || "").split(" ").pop())}${o.contact ? ` · ${esc(o.contact.name)} <a href="tel:${esc(o.contact.phone)}">${esc(o.contact.phone)}</a>` : ""}</div>` : "";
      return `<div class="o"><img src="${esc(photos[o.listing_id] || "")}" alt=""><div>${mto}
        <span class="badge ${esc(o.status)}">${st}</span>
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

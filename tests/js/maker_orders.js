// Runs web/static/maker.js in node with a stub page, and prints what Lena's order feed shows (used by test_maker_ui.py).
// argv[2]: maker.js path; argv[3]: JSON {orders, listings, balance_status, balance_detail}
const fs = require("fs");
const fx = JSON.parse(process.argv[3]);
process.on("unhandledRejection", () => {});
const els = {};
const el = (id) => els[id] || (els[id] = { id, innerHTML: "", textContent: "", hidden: false, value: "", dataset: {},
  classList: { add() {}, remove() {}, toggle() {} }, addEventListener() {}, querySelectorAll: () => [], querySelector: () => el("_") });
const handlers = [];
global.window = global;
global.addEventListener = () => {};
global.location = { hash: "", href: "" };
global.localStorage = { getItem: () => "testvisitor", setItem() {} };
global.crypto = {};
global.document = { getElementById: el, querySelector: () => el("_q"), querySelectorAll: () => [],
  addEventListener: (t, h) => handlers.push([t, h]), dispatchEvent() {}, createElement: () => el("_c") };
global.Event = class { constructor(t) { this.type = t; } };
global.EventSource = class { constructor() {} };
global.setInterval = () => 0;
global.AudioContext = class {};
const json = (body, status = 200) => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });
global.fetch = (u, o = {}) => {
  if (u.startsWith("/api/maker/orders/") && u.endsWith("/balance")) return json({ detail: fx.balance_detail }, fx.balance_status);
  if (u === "/api/maker/orders") return json(fx.orders);
  if (u === "/c/small-garage.json") return json({ listings: fx.listings, ships_to: "US", shipping_usd: 6.5, made_to_order: "" });
  return json([]);
};
try { eval(fs.readFileSync(process.argv[2], "utf8")); } catch (e) { console.error("later part of maker.js:", e.message); }
setTimeout(async () => {
  const feed = els.feed ? els.feed.innerHTML : "";
  const btn = { dataset: { balance: fx.orders[0].id }, disabled: false, textContent: "" };
  for (const [t, h] of handlers) if (t === "click") { try { await h({ target: btn }); } catch (e) {} }
  console.log(JSON.stringify({ feed, clicked: btn.textContent }));
}, 50);

// One id per browser, sent with every /api call: on the public demo, what you change (lessons, shipping your own
// orders, counters you open) stays with your browser and never changes the shop for other people.
(() => {
  let vid = "";
  try { vid = localStorage.getItem("oc_visitor") || ""; if (!vid) { vid = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2)).replace(/-/g, "").slice(0, 24); localStorage.setItem("oc_visitor", vid); } } catch (e) {}
  const f = window.fetch.bind(window);
  window.fetch = (u, o = {}) => (typeof u === "string" && u.startsWith("/api") && vid ? f(u, { ...o, headers: { ...(o.headers || {}), "x-visitor": vid } }) : f(u, o));
})();

// Open your counter: photo + one sentence → the AI writes the listing words; the maker sets price and stock (Roma 14565 #4).
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  let image = "", listing = null;
  const ready = () => ($("draft").disabled = !image);
  async function toDataUrl(blob) {
    const bmp = await createImageBitmap(blob); const k = Math.min(1, 1280 / Math.max(bmp.width, bmp.height));
    const cv = document.createElement("canvas"); cv.width = bmp.width * k; cv.height = bmp.height * k;
    cv.getContext("2d").drawImage(bmp, 0, 0, cv.width, cv.height); return cv.toDataURL("image/jpeg", 0.86);
  }
  async function use(blob) { image = await toDataUrl(blob); $("preview").src = image; $("preview").hidden = false; ready(); }
  $("samples").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-src]"); if (!b) return;
    document.querySelectorAll("#samples .on").forEach((x) => x.classList.remove("on")); b.classList.add("on");
    await use(await fetch(b.dataset.src).then((r) => r.blob()));
    const s = { mug: ["Rosa Diaz", "Clay & Kiln", 32, 6, "TX", "Wheel-thrown stoneware, glazed by hand, holds 12 oz"],
      candle: ["Ben Okoro", "Slow Flame", 24, 20, "OR", "Hand-poured soy wax, 50-hour burn"],
      wallet: ["Ana Petrov", "Saddle & Thread", 68, 4, "OH", "Hand-stitched full-grain leather bifold"] }[b.dataset.src.split("/").pop().split(".")[0]];
    if (s) ["maker", "shopname", "price", "stock", "from", "note"].forEach((id, i) => ($(id).value = s[i]));
  });
  $("file").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) { document.querySelectorAll("#samples .on").forEach((x) => x.classList.remove("on")); use(f); } });
  $("draft").addEventListener("click", async () => {
    $("draft").disabled = true; $("dhint").textContent = "NVIDIA Nemotron VL is looking at your photo…";
    const r = await fetch("/api/open/draft", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ image, note: $("note").value }) })
      .then((r) => r.json()).catch(() => ({ error: "Couldn't reach the server." }));
    $("draft").disabled = false;
    if (r.error || !r.listing) { $("dhint").textContent = r.error || r.detail || "Try another photo."; return; }
    listing = r.listing; $("dhint").textContent = `Written in ${r.seconds} s`;
    $("model").textContent = `Written by ${r.model} from your photo and sentence. Change anything that isn't right.`;
    $("t_title").value = listing.title || ""; $("t_desc").value = listing.short_description || "";
    $("t_mat").value = [].concat(listing.materials || []).join(", "); $("t_size").value = listing.size || "";
    $("t_col").value = listing.colour || ""; $("t_kw").value = [].concat(listing.keywords || []).join(", ");
    $("s3").hidden = false; $("s3").scrollIntoView({ behavior: "smooth", block: "start" });
  });
  $("publish").addEventListener("click", async () => {
    const l = { ...listing, title: $("t_title").value, short_description: $("t_desc").value, size: $("t_size").value, colour: $("t_col").value,
      materials: $("t_mat").value.split(",").map((s) => s.trim()).filter(Boolean), keywords: $("t_kw").value.split(",").map((s) => s.trim()).filter(Boolean) };
    $("publish").disabled = true; $("phint").textContent = "Opening your counter and registering it with PayPal…";
    const r = await fetch("/api/open/publish", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ listing: l, price_usd: $("price").value, stock: $("stock").value, ships_from: $("from").value, maker: $("maker").value, shop_name: $("shopname").value, paypal_email: $("ppemail").value.trim(), image }) })
      .then(async (r) => ({ ok: r.ok, ...(await r.json()) })).catch(() => ({ ok: false, detail: "Couldn't reach the server." }));
    $("publish").disabled = false;
    if (!r.ok) { $("phint").textContent = r.detail || "Something's missing."; return; }
    $("phint").textContent = "";
    $("dname").textContent = $("shopname").value || "Your counter";
    $("dpage").href = $("dpage").textContent = r.page; $("djson").href = $("djson").textContent = r.json;
    $("dprod").textContent = r.paypal_catalog_product || "(PayPal not reachable right now)";
    $("dpaid").textContent = `Buyers' payments go to ${r.payment_goes_to || "your PayPal account"}.` + (/demo merchant/.test(r.payment_goes_to || "") ? " Add your PayPal email to be paid directly." : "");
    $("dcard").textContent = JSON.stringify(await fetch(r.json).then((x) => x.json()), null, 2);
    $("s4").hidden = false; $("s4").scrollIntoView({ behavior: "smooth", block: "start" }); recent();
  });
  async function recent() {
    const rs = await fetch("/api/open/latest").then((r) => r.json()).catch(() => []);
    $("recent").innerHTML = rs.length ? rs.map((c) => `<a href="/c/${esc(c.slug)}"><b>${esc(c.name)}</b> ${esc(c.title)}<span>$${c.price_usd.toFixed(2)}${c.paypal_catalog_product ? " · PayPal catalog " + esc(c.paypal_catalog_product) : ""}</span></a>`).join("")
      : `<p class="fine">None yet. Be the first.</p>`;
  }
  recent(); ready();
})();

// Your whole range at once (Shelf gap, 9 Nov): every source (a pasted list, and the readers added after it) ends in
// the same table the maker checks line by line; only then does the counter open. Values are set with .value and
// textContent, never as HTML. open.js (one product) is untouched; this file only adds the second mode.
(() => {
  const $ = (id) => document.getElementById(id);
  const SAMPLE = "Brass bell 6cm $24 (5 in stock)\nOak coaster set of 4 $32\nLinen napkin pair $18.50\nBeeswax candle, tall $14";
  // what each source is, said plainly next to the button that reads it
  const NOTES = {
    text: "NVIDIA Nemotron (on Nebius) reads your list; if it's busy, simple rules read it instead. A price is kept only if you wrote that number. You check every line before anything opens.",
  };
  const READERS = { text: () => ({ url: "/api/open/parse", body: { text: $("r_text").value } }) };
  window.ocRange = { NOTES, READERS };   // later sources register here
  let src = "text", photo = "", source = "price list";

  function setMode(m) {
    document.body.classList.toggle("mode-range", m === "range");
    document.querySelectorAll("#modes button").forEach((b) => { const on = b.dataset.mode === m; b.classList.toggle("on", on); b.setAttribute("aria-selected", on); });
  }
  $("modes").addEventListener("click", (e) => { const b = e.target.closest("button[data-mode]"); if (b) setMode(b.dataset.mode); });
  if (location.hash === "#range") setMode("range");

  function setSrc(s) {
    src = s;
    document.querySelectorAll("#srcs button").forEach((b) => b.classList.toggle("on", b.dataset.src === s));
    document.querySelectorAll("[data-pane]").forEach((p) => (p.hidden = p.dataset.pane !== s));
    $("r_srcnote").textContent = NOTES[s] || "";
  }
  $("srcs").addEventListener("click", (e) => { const b = e.target.closest("button[data-src]"); if (b) setSrc(b.dataset.src); });
  window.ocRange.setSrc = setSrc;
  setSrc("text");
  $("r_sample").addEventListener("click", () => { $("r_text").value = SAMPLE; });

  function row(it = {}) {
    const tr = document.createElement("tr");
    const cell = (cls, input) => { const td = document.createElement("td"); if (cls) td.className = cls; td.appendChild(input); tr.appendChild(td); return input; };
    const inp = (type, v, extra = {}) => Object.assign(document.createElement("input"), { type, value: v ?? "", ...extra });
    cell("", inp("text", it.title, { maxLength: 60, placeholder: "Item name", ariaLabel: "Item name" }));
    cell("n", inp("number", it.price_usd, { min: "0.01", max: "10000", step: "0.01", ariaLabel: "Price in USD" }));
    cell("n", inp("number", it.stock || 1, { min: "1", max: "1000", step: "1", ariaLabel: "How many you have" }));
    const x = document.createElement("button"); x.type = "button"; x.textContent = "×"; x.title = "Remove this line";
    x.addEventListener("click", () => { tr.remove(); count(); });
    cell("x", x);
    $("r_rows").appendChild(tr);
  }
  function rows() {
    return [...$("r_rows").querySelectorAll("tr")].map((tr) => { const [t, p, s] = tr.querySelectorAll("input"); return { title: t.value.trim(), price_usd: p.value, stock: s.value }; })
      .filter((r) => r.title || r.price_usd);
  }
  function count() { const n = $("r_rows").querySelectorAll("tr").length; $("r_open").textContent = n ? `Open my counter with ${n} item${n > 1 ? "s" : ""}` : "Open my counter"; $("r_add").disabled = n >= 12; }
  $("r_add").addEventListener("click", () => { if ($("r_rows").querySelectorAll("tr").length < 12) { row(); count(); } });

  // a reader's answer → the table (shared by every source)
  function show(r, label) {
    $("r_rows").textContent = "";
    (r.items || []).forEach(row); count();
    source = label;
    const by = r.read_by === "rules" ? "simple rules (no AI)" : r.read_by;
    $("r_by").textContent = `${(r.items || []).length} item${(r.items || []).length === 1 ? "" : "s"} read from your ${label} by ${by}` +
      (r.dropped ? `; ${r.dropped} line${r.dropped > 1 ? "s" : ""} left out (no usable name or price, or over 12 items)` : "") +
      `. Fix anything that isn't right${(r.items || []).length ? "" : ", or add lines by hand"}.` + (r.note ? " " + r.note : "");
    $("r2").hidden = false; $("r2").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  window.ocRange.show = show;

  const LABELS = { text: "price list" };
  window.ocRange.LABELS = LABELS;
  $("r_read").addEventListener("click", async () => {
    const make = READERS[src]; if (!make) return;
    let req; try { req = await make(); } catch (e) { $("r_hint").textContent = e.message || String(e); return; }
    if (!req) return;
    $("r_read").disabled = true; $("r_hint").textContent = "Reading…";
    const r = await fetch(req.url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(req.body) })
      .then(async (x) => ({ ok: x.ok, ...(await x.json().catch(() => ({}))) })).catch(() => ({ ok: false, error: "Couldn't reach the server." }));
    $("r_read").disabled = false;
    if (!r.ok) { $("r_hint").textContent = r.error || r.detail || "Couldn't read that."; return; }
    $("r_hint").textContent = r.seconds != null ? `Read in ${r.seconds} s` : "";
    show(r, LABELS[src] || "price list");
  });

  async function toDataUrl(blob) {
    const bmp = await createImageBitmap(blob); const k = Math.min(1, 1280 / Math.max(bmp.width, bmp.height));
    const cv = document.createElement("canvas"); cv.width = Math.round(bmp.width * k); cv.height = Math.round(bmp.height * k);
    cv.getContext("2d").drawImage(bmp, 0, 0, cv.width, cv.height); return cv.toDataURL("image/jpeg", 0.86);
  }
  window.ocRange.toDataUrl = toDataUrl;
  $("r_photo").addEventListener("change", async (e) => { const f = e.target.files[0]; photo = f ? await toDataUrl(f).catch(() => "") : ""; });

  $("r_open").addEventListener("click", async () => {
    const items = rows();
    if (!items.length) { $("r_phint").textContent = "Add at least one item with a price."; return; }
    $("r_open").disabled = true; $("r_phint").textContent = `Opening your counter and registering ${items.length} products with PayPal…`;
    const r = await fetch("/api/open/publish_many", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ items, maker: $("r_maker").value, shop_name: $("r_shop").value, ships_from: $("r_from").value, paypal_email: $("r_pp").value.trim(), image: photo, source }) })
      .then(async (x) => ({ ok: x.ok, ...(await x.json().catch(() => ({}))) })).catch(() => ({ ok: false, detail: "Couldn't reach the server." }));
    $("r_open").disabled = false;
    if (!r.ok) { $("r_phint").textContent = r.detail || "Something's missing."; return; }
    $("r_phint").textContent = "";
    $("r_dname").textContent = $("r_shop").value || "Your counter";
    $("r_dpage").href = $("r_dpage").textContent = r.page; $("r_djson").href = $("r_djson").textContent = r.json; $("r_dmcp").textContent = r.mcp;
    $("r_ditems").textContent = "";
    r.items.forEach((it) => {
      const li = document.createElement("li"), b = document.createElement("b"), s = document.createElement("span");
      b.textContent = it.title; s.textContent = `$${it.price_usd.toFixed(2)} · ${it.stock} in stock · PayPal ${it.paypal_catalog_product || "(not reachable now)"}`;
      li.append(b, s); $("r_ditems").appendChild(li);
    });
    $("r_dpaid").textContent = `Buyers' payments go to ${r.payment_goes_to}.`;
    $("r3").hidden = false; $("r3").scrollIntoView({ behavior: "smooth", block: "start" });
  });
})();

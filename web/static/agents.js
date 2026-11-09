// /agents: copy buttons, a live read-only MCP console (plain fetch JSON-RPC to /mcp/) and a replay of one recorded
// outside-agent purchase (agents_run.json). No model is called from this page and no order can be made from it.
(function () {
  "use strict";
  var LIVE = "https://open-counter.onrender.com";
  var $ = function (s) { return document.querySelector(s); };

  // a copy of the app deployed elsewhere shows its own address
  if (location.origin !== LIVE && /^https?:/.test(location.origin)) {
    ["#mcpurl", "#cfg-claude", "#cfg-insp", "#cfg-curl"].forEach(function (s) {
      var el = $(s); if (el) el.textContent = el.textContent.split(LIVE).join(location.origin);
    });
  }

  // ---- copy ----
  document.querySelectorAll("[data-copy]").forEach(function (b) {
    b.addEventListener("click", function () {
      var text = $(b.getAttribute("data-copy")).textContent;
      var done = function () { b.textContent = "Copied"; setTimeout(function () { b.textContent = "Copy"; }, 1400); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { fallback(text); done(); });
      } else { fallback(text); done(); }
    });
  });
  function fallback(text) {
    var t = document.createElement("textarea"); t.value = text; t.setAttribute("readonly", "");
    t.style.position = "fixed"; t.style.opacity = "0"; document.body.appendChild(t); t.select();
    try { document.execCommand("copy"); } catch (e) { /* nothing else to try */ }
    document.body.removeChild(t);
  }

  // JSON-RPC answers carry tool results as a JSON string in content[].text; show it parsed so it reads
  function readable(obj) {
    var o = JSON.parse(JSON.stringify(obj));
    var r = o && o.result;
    if (r && Array.isArray(r.content)) {
      r.content.forEach(function (c) {
        if (c && typeof c.text === "string") { try { c.text = JSON.parse(c.text); } catch (e) { /* plain text */ } }
      });
    }
    return JSON.stringify(o, null, 2);
  }

  // ---- live console: read-only calls only ----
  var READ_ONLY = { "initialize": 1, "tools/list": 1, "search_counter": 1 };
  var seq = 0;
  function body(kind) {
    seq += 1;
    if (kind === "initialize") {
      return { jsonrpc: "2.0", id: seq, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {},
        clientInfo: { name: "open-counter-agents-page", version: "1" } } };
    }
    if (kind === "tools/list") return { jsonrpc: "2.0", id: seq, method: "tools/list", params: {} };
    var q = ($("#q").value || "").trim().slice(0, 40);
    return { jsonrpc: "2.0", id: seq, method: "tools/call", params: { name: "search_counter", arguments: { query: q } } };
  }
  var buttons = document.querySelectorAll("[data-call]");
  buttons.forEach(function (b) {
    b.addEventListener("click", function () {
      var kind = b.getAttribute("data-call");
      if (!READ_ONLY[kind]) return;
      var req = body(kind);
      buttons.forEach(function (x) { x.disabled = true; x.classList.toggle("on", x === b); });
      $("#io").hidden = false;
      $("#req").textContent = JSON.stringify(req, null, 2);
      $("#res").textContent = "…";
      $("#stat").textContent = "calling…";
      var t0 = performance.now();
      fetch("/mcp/", { method: "POST", headers: { "content-type": "application/json",
        "accept": "application/json, text/event-stream" }, body: JSON.stringify(req) })
        .then(function (r) {
          return r.text().then(function (txt) { return { status: r.status, txt: txt }; });
        })
        .then(function (x) {
          var ms = Math.round(performance.now() - t0);
          var shown = x.txt;
          try { shown = readable(JSON.parse(x.txt)); } catch (e) {
            // an event-stream answer: take the JSON from its data: line
            var line = x.txt.split("\n").filter(function (l) { return l.indexOf("data:") === 0; }).pop();
            if (line) { try { shown = readable(JSON.parse(line.slice(5))); } catch (e2) { /* show as is */ } }
          }
          $("#res").textContent = shown;
          $("#stat").textContent = "HTTP " + x.status + " · " + ms + " ms";
        })
        .catch(function () { $("#res").textContent = "No answer from the server. Try again in a moment."; $("#stat").textContent = ""; })
        .then(function () { buttons.forEach(function (x) { x.disabled = false; }); });
    });
  });

  // ---- replay of the recorded run ----
  var run = null, at = 0;
  var KIND = { mcp: "OUTSIDE AGENT → MCP", person: "THE PERSON, IN PAYPAL", app: "OPEN COUNTER", paypal: "PAYPAL'S RECORD" };
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function hm(iso) { return iso ? iso.replace("T", " ").replace("Z", " UTC") : ""; }
  function show(i) {
    at = Math.max(0, Math.min(i, run.steps.length - 1));
    var s = run.steps[at];
    var resp = s.response;
    var txt = s.kind === "mcp" ? readable({ result: resp }) : JSON.stringify(resp, null, 2);
    if (s.step === "tools/list") {   // nine full schemas are long; names first, schemas below
      txt = "tools: " + resp.tools.map(function (t) { return t.name; }).join(", ") + "\n\n" + JSON.stringify(resp, null, 2);
    }
    var times = s.started_utc ? hm(s.started_utc) + (s.answered_utc && s.answered_utc !== s.started_utc ? " → " + hm(s.answered_utc).slice(11) : "") : (s.note || "");
    $("#rstep").innerHTML = '<div class="rstep"><div class="who">' + (at + 1) + " / " + run.steps.length + " · " + esc(KIND[s.kind] || s.kind) +
      "</div><h3>" + esc(s.step) + '</h3><div class="t">' + esc(times) + "</div>" +
      (s.command ? "<b class=\"who\">COMMAND</b><pre>" + esc(s.command) + "</pre>" : "") +
      (s.url ? '<b class="who">PAGE</b><pre>' + esc(s.url) + "</pre>" : "") +
      '<b class="who">' + (s.kind === "mcp" ? "ANSWER (content[].text shown parsed)" : "WHAT HAPPENED") + "</b><pre>" + esc(txt) + "</pre></div>";
    document.querySelectorAll("#rdots button").forEach(function (d, k) {
      d.classList.toggle("on", k === at); d.classList.toggle("past", k < at);
    });
    $("#rprev").disabled = at === 0;
    $("#rnext").disabled = at === run.steps.length - 1;
    if (at === run.steps.length - 1) result();
  }
  function result() {
    var r = run.result;
    var cells = [["ORDER", r.order_id], ["PAYPAL ORDER", r.paypal_order_id], ["CAPTURE", r.capture_id],
      ["AMOUNT", "$" + r.amount_usd + " · " + r.status], ["CHECKOUT STARTED", hm(r.checkout_started_utc)], ["CAPTURED", hm(r.captured_utc)]];
    $("#rresult").innerHTML = '<div class="ids">' + cells.map(function (c) {
      return "<div><span>" + esc(c[0]) + "</span><code>" + esc(c[1]) + "</code></div>";
    }).join("") + '</div><p class="fine">The same ids are logged in the project README (Logged run: outside MCP client → paid).</p>';
    $("#rresult").hidden = false;
  }
  fetch("/static/agents_run.json", { cache: "no-cache" }).then(function (r) { return r.json(); }).then(function (d) {
    run = d;
    $("#rlabel").textContent = d.label.toUpperCase();
    $("#rintro").textContent = "A real run on the live app, replayed step by step: " + d.client + " against " + d.endpoint +
      ", the sandbox buyer approving in PayPal, and the capture. Nothing on this page calls the server again.";
    $("#rdots").innerHTML = d.steps.map(function (s, k) {
      return '<button aria-label="Step ' + (k + 1) + ": " + esc(s.step) + '">' + (k + 1) + "</button>";
    }).join("");
    document.querySelectorAll("#rdots button").forEach(function (b, k) { b.addEventListener("click", function () { show(k); }); });
    show(0);
  }).catch(function () { $("#rintro").textContent = "The recorded run couldn't be loaded."; });
  $("#rprev").addEventListener("click", function () { if (run) show(at - 1); });
  $("#rnext").addEventListener("click", function () { if (run) show(at + 1); });
  $("#rall").addEventListener("click", function () { if (run) show(run.steps.length - 1); });
})();

/* Propelo on job pages (only after you switch it on in the extension, and only on the hiring systems it lists).
   Shows how well the role matches your real resume, fills the application form when you ask, and walks
   your apply queue: each approved role opens, gets filled, and waits for you to check it and press Submit.
   It never submits, never reads LinkedIn, Naukri, Indeed or Wellfound, and treats the page's text as data. */
(function () {
  "use strict";
  if (window.top !== window || window.__propeloOnPage) return;
  window.__propeloOnPage = true;
  var BLOCKED = /(^|\.)(linkedin\.com|naukri\.com|indeed\.[a-z.]+|wellfound\.com|angel\.co)$/i;
  if (BLOCKED.test(location.hostname)) return;
  // Words a confirmation page uses once an application is sent. Checked only in text that appears after a fill.
  var SENT = /thank(s| you) for (applying|your application|submitting)|application (has been |was )?(submitted|received|sent)|we('ve| have) received your application|successfully (applied|submitted)|your application is (in|complete)/i;

  function send(msg) {
    return new Promise(function (res) {
      try { chrome.runtime.sendMessage(msg, function (r) { res(chrome.runtime.lastError ? { ok: false, error: chrome.runtime.lastError.message } : (r || { ok: false })); }); }
      catch (e) { res({ ok: false, error: String(e) }); }
    });
  }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function page() {
    var p = {};
    try { p = window.__careerosRead ? window.__careerosRead() : {}; } catch (e) { p = {}; }
    p.url = location.href;
    if (!p.jd) {
      var main = document.querySelector("main, [role=main], #content, .job, .posting, .job-description, [class*='description']") || document.body;
      p.jd = String(main.innerText || "").replace(/\n{3,}/g, "\n\n").slice(0, 20000);
    }
    return p;
  }
  function formFields() {
    return Array.prototype.slice.call(document.querySelectorAll("input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select"))
      .filter(function (el) { var r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }).length;
  }

  // ------------------------------------------------------------ the panel (in a shadow root, so the page's styles don't reach it)
  var host = document.createElement("div");
  host.setAttribute("data-propelo", "");
  host.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483646;";
  var root = host.attachShadow({ mode: "closed" });
  root.innerHTML = '<style>' +
    ':host{all:initial}*{box-sizing:border-box}' +
    '.w{max-height:calc(100vh - 32px);overflow:auto;font:14px/1.45 Figtree,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#151515;background:#FAF3E6;border:1px solid rgba(21,21,21,.14);border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.18);width:320px;max-width:calc(100vw - 32px);overflow:hidden}' +
    '@media (prefers-color-scheme:dark){.w{color:#F4EEE3;background:#1c1a17;border-color:rgba(244,238,227,.16)}.b{border-color:#F4EEE3!important;color:#F4EEE3!important}.b.s{background:#F4EEE3!important;color:#151413!important}.chip{background:rgba(244,238,227,.1)!important}.muted{color:#a39d92!important}.risk{background:#3a2f1c!important}.ok{background:#1f3324!important}}' +
    '.top{display:flex;align-items:center;gap:10px;padding:10px 12px;cursor:pointer;background:none;border:0;width:100%;font:inherit;color:inherit;text-align:left}' +
    '.logo{font-weight:700;letter-spacing:-.04em}.logo i{display:inline-block;width:6px;height:6px;border-radius:50%;background:#FF85BA;margin-left:1px}' +
    '.sc{margin-left:auto;font-weight:600;font-variant-numeric:tabular-nums;display:flex;align-items:center;gap:6px}.dot{width:10px;height:10px;border-radius:50%}' +
    '.body{padding:0 12px 12px;display:grid;gap:8px}.muted{color:#6E675D;font-size:12.5px}.chips{display:flex;flex-wrap:wrap;gap:4px}' +
    '.chip{font-size:12px;padding:2px 8px;border-radius:99px;background:rgba(21,21,21,.07)}.chip.miss{background:transparent;border:1px dashed currentColor;opacity:.8}' +
    '.row{display:flex;gap:6px;flex-wrap:wrap}.b{font:inherit;font-weight:500;border:1px solid #151515;background:transparent;color:#151515;border-radius:99px;padding:7px 12px;cursor:pointer;min-height:36px}' +
    '.b.s{background:#151515;color:#FAF3E6}.b:disabled{opacity:.5;cursor:default}.x{margin-left:4px;background:none;border:0;color:inherit;opacity:.6;cursor:pointer;font-size:16px;line-height:1}' +
    '.risk{background:#FBEFD5;border-radius:10px;padding:8px 10px;font-size:12.5px}.ok{background:#D6EDD9;border-radius:10px;padding:8px 10px;font-size:12.5px}' +
    'b{font-weight:600}ul{margin:4px 0 0;padding-left:16px}li{font-size:12.5px}' +
    (window.PropeloGauge ? window.PropeloGauge.css : '') + '.w .pg{margin-top:2px}' +
    '</style><div class="w" role="complementary" aria-label="Propelo"><div id="c"></div></div>';
  var box = root.getElementById("c");
  var S = { open: false, match: null, matchErr: "", q: null, report: null, busy: "", msg: "", sent: false, page: null };

  function color(n) { return window.PropeloGauge ? window.PropeloGauge.tone(n) : "#3859F9"; }
  function render() {
    var m = S.match, q = S.q, parts = [];
    var head = '<button class="top" data-a="toggle" aria-expanded="' + S.open + '"><span class="logo">propelo<i></i></span>' +
      (q ? '<span class="muted">Role ' + q.position + ' of ' + q.total + '</span>' : '') +
      '<span class="sc">' + (m && m.score != null ? '<span class="dot" style="background:' + color(m.score) + '"></span>' + m.score + ' · ' + esc(m.label) : m ? '' : S.matchErr ? '' : '<span class="muted">Checking fit…</span>') + '</span>' +
      '<span class="x" data-a="hide" title="Hide on this site" aria-label="Hide Propelo on this site">×</span></button>';
    parts.push(head);
    if (S.open || q) {
      parts.push('<div class="body">');
      if (q && q.item) parts.push('<div><b>' + esc(q.item.company) + '</b> · ' + esc(q.item.title) + '</div>');
      if (m) {
        if (m.needsResume) parts.push('<p class="risk">Add your resume in Propelo to see how you match.</p>');
        else if (window.PropeloGauge) parts.push('<div id="pgwrap">' + window.PropeloGauge.html(m, { size: 112, chips: 10 }) + '</div>');
        if (m.risk && m.risk.level !== "ok") parts.push('<div class="risk"><b>' + (m.risk.level === "high" ? "This posting looks unsafe. Don't pay or share documents." : "Check this posting before you apply.") + '</b><ul>' +
          (m.risk.reasons || []).slice(0, 3).map(function (r) { return '<li>' + esc(r.why) + '</li>'; }).join("") + '</ul></div>');
      }
      if (S.matchErr) parts.push('<p class="muted">' + esc(S.matchErr) + '</p>');
      if (S.report) parts.push('<div class="ok"><b>Filled ' + S.report.filled.length + (S.report.filled.length === 1 ? " field" : " fields") + '.</b> ' +
        (S.report.needs.length ? S.report.needs.length + ' need you (outlined in orange). ' : '') + 'Check each answer, then press Submit on the page.</div>');
      if (S.sent) parts.push('<div class="ok"><b>Recorded as applied.</b>' + (q ? ' Opening the next role…' : '') + '</div>');
      if (S.msg) parts.push('<p class="muted">' + esc(S.msg) + '</p>');
      var fields = formFields();
      parts.push('<div class="row">' + (fields >= 2 ? '<button class="b s" data-a="fill"' + (S.busy ? " disabled" : "") + '>' + (S.busy === "fill" ? "Filling…" : S.report ? "Fill again" : "Fill this form") + '</button>' : '') +
        (q ? '<button class="b" data-a="done">I submitted it, next</button><button class="b" data-a="skip">Skip</button><button class="b" data-a="stop">Stop</button>'
           : '<button class="b" data-a="save"' + (S.busy ? " disabled" : "") + '>Save to Propelo</button>') + '</div>');
      parts.push('</div>');
    }
    box.innerHTML = parts.join("");
    var g = root.getElementById("pgwrap");
    if (g && m && !m.__shown && window.PropeloGauge) { m.__shown = true; window.PropeloGauge.animate(g); }
  }

  function fill() {
    S.busy = "fill"; S.msg = ""; render();
    var p = S.page || page();
    send({ type: "fill", company: (S.q && S.q.item && S.q.item.company) || p.company || "" }).then(function (r) {
      S.busy = "";
      if (!r.ok) { S.msg = r.error || "Couldn't fill this form."; return render(); }
      S.report = r.data;
      if (!r.data.filled.length && !r.data.needs.length) S.msg = "No form here yet. Open the application form (often behind an Apply button), then fill.";
      watchForSent();
      render();
    });
  }
  function recordSent(auto) {
    if (S.sent) return;
    S.sent = true; render();
    var p = S.page || page(), item = S.q && S.q.item;
    if (item) { p.company = p.company || item.company; p.title = item.title || p.title; }
    send({ type: "track", page: p, applied: true, jobId: item && item.id }).then(function () {
      if (S.q) setTimeout(function () { send({ type: "queue:next", how: "done" }).then(function (r) { if (r.ok && r.data && r.data.finished) { S.q = null; S.msg = "Queue finished: " + r.data.done + " sent, " + r.data.skipped + " skipped."; render(); } }); }, auto ? 2500 : 300);
      else S.msg = "Saved to Propelo as applied.";
      render();
    });
  }
  // After a fill, watch only new text on the page for a confirmation, so a job description that says
  // "thank you for your interest" doesn't count.
  var watching = false;
  function watchForSent() {
    if (watching) return; watching = true;
    var obs = new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        for (var j = 0; j < muts[i].addedNodes.length; j++) {
          var n = muts[i].addedNodes[j];
          if (n.nodeType === 1 && n !== host && SENT.test(String(n.innerText || n.textContent || "").slice(0, 2000))) { obs.disconnect(); return recordSent(true); }
        }
      }
    });
    obs.observe(document.body, { childList: true, subtree: true });
    send({ type: "filled:set", url: location.href.split("#")[0] });
  }

  box.addEventListener("click", function (e) {
    var a = e.target.closest("[data-a]"); if (!a) return;
    var act = a.getAttribute("data-a");
    if (act === "hide") { e.stopPropagation(); send({ type: "hide", host: location.hostname }); host.remove(); return; }
    if (act === "toggle") { S.open = !S.open; return render(); }
    if (act === "fill") return fill();
    if (act === "done") return recordSent(false);
    if (act === "skip") { S.msg = "Skipped."; render(); return send({ type: "queue:next", how: "skip" }); }
    if (act === "stop") { return send({ type: "queue:stop" }).then(function () { S.q = null; S.msg = "Apply queue stopped."; render(); }); }
    if (act === "save") {
      S.busy = "save"; render();
      send({ type: "track", page: S.page || page(), applied: false }).then(function (r) { S.busy = ""; S.msg = r.ok ? "Saved to Propelo." : (r.error || "Couldn't save it."); render(); });
    }
  });

  function start() {
    send({ type: "connected", host: location.hostname }).then(function (c) {
      if (!c.ok || !c.data.connected || c.data.hidden) return;
      document.documentElement.appendChild(host);
      S.page = page();
      render();
      send({ type: "queue:state" }).then(function (r) {
        if (r.ok && r.data && r.data.active) {
          S.q = r.data; S.open = true; render();
          // A confirmation page after the form was filled: record it and move on.
          send({ type: "filled:get" }).then(function (f) {
            var filled = f.ok && f.data;
            if (filled && filled !== location.href.split("#")[0] && SENT.test(String(document.body.innerText || "").slice(0, 4000))) return recordSent(true);
            var tries = 0, t = setInterval(function () {  // wait for the form, then fill once
              tries += 1;
              if (formFields() >= 3) { clearInterval(t); fill(); }
              else if (tries > 20) { clearInterval(t); S.msg = "No form found. Press Apply on the page if there is one, then Fill this form."; render(); }
            }, 750);
          });
        }
      });
      if (String(S.page.jd || "").length >= 200) {
        send({ type: "match", page: { url: S.page.url, title: S.page.title, jd: S.page.jd } }).then(function (r) {
          if (r.ok) S.match = r.data; else S.matchErr = r.status === 400 ? "" : (r.error || "");
          render();
        });
      } else { S.matchErr = "Open the job description to see your match."; render(); }
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();

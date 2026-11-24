/* Propelo Autofill popup: connect once with your server address and a computer key, then
   "Fill this form" on any application page. Filling runs only when you press the button, only
   in the tab you're looking at, and never submits. The key stays in this browser's extension storage. */
(function () {
  "use strict";
  var BLOCKED = /(^|\.)(linkedin\.com|naukri\.com|indeed\.[a-z.]+|wellfound\.com|angel\.co)$/i;
  var app = document.getElementById("app");
  (function () { var st = document.createElement("style"); st.textContent = window.PropeloGauge.css; document.head.appendChild(st); })();
  var S = { server: "", key: "", tab: null, page: null, report: null, busy: "", msg: "", err: false, tracked: null,
            match: null, queue: null, qstatus: null, onpage: null };
  function bg(msg) {
    return new Promise(function (res, rej) {
      chrome.runtime.sendMessage(msg, function (r) {
        if (chrome.runtime.lastError) return rej(new Error(chrome.runtime.lastError.message));
        if (!r || !r.ok) { var e = new Error((r && r.error) || "Something went wrong."); e.status = r && r.status; return rej(e); }
        res(r.data);
      });
    });
  }
  function color(n) { return n >= 80 ? "#1f9d55" : n >= 65 ? "#3859F9" : n >= 50 ? "#e0a100" : "#c0392b"; }
  function matchCard() {
    var m = S.match;
    if (!m) return "";
    if (m.needsResume) return '<div class="note">Add your resume in Propelo to see how you match this role.</div>';
    return '<div class="card match" id="match">' + window.PropeloGauge.html(m, { size: 124, chips: 12 }) + '</div>';
  }
  function queueCard() {
    var st = S.qstatus, q = S.queue;
    if (st && st.active) return '<div class="card"><div class="row end"><b>Apply queue</b><span class="count">' + st.position + ' of ' + st.total + '</span></div>' +
      '<p class="muted">Each role opens and fills in its own tab. Check it, press Submit, then press "I submitted it, next" on the page.</p>' +
      '<div class="row"><button class="btn" data-act="q-show">Go to the tab</button><button class="btn ghost" data-act="q-stop">Stop</button></div></div>';
    if (!q) return "";
    var roles = q.roles || [];
    if (!roles.length) return '<div class="card"><b>Apply queue</b><p class="muted">' + (q.left === 0 ? "You've reached today's limit (" + q.dailyCap + "). More tomorrow." : "Nothing waiting. Approve roles in Propelo, or let auto-apply pick roles above your apply line.") + '</p></div>';
    return '<div class="card"><div class="row end"><b>Apply queue</b><span class="count">' + roles.length + '</span></div>' +
      '<ul>' + roles.slice(0, 4).map(function (r) { return '<li><b>' + esc(r.company) + '</b><span>' + esc(r.title) + (r.score ? ' · fit ' + esc(Number(r.score).toFixed(1)) : '') + '</span></li>'; }).join("") + '</ul>' +
      (roles.length > 4 ? '<p class="muted">And ' + (roles.length - 4) + ' more.</p>' : '') +
      '<button class="btn solid block" data-act="q-start">Start applying</button><p class="muted">Propelo opens each role and fills it. You check every answer and press Submit yourself. ' + q.left + ' left today on your plan.</p></div>';
  }
  function onPageCard() {
    if (S.onpage === null) return "";
    return '<label class="switch"><input type="checkbox" id="onpage"' + (S.onpage ? " checked" : "") + '> Show Propelo on job pages <span class="muted">(Greenhouse, Lever, Ashby, Workday and 20 more)</span></label>';
  }

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function originOf(u) { try { var x = new URL(u); return x.protocol + "//" + x.host; } catch (e) { return ""; } }
  function okServer(u) { return /^https:\/\/[^/]+/i.test(u) || /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?/i.test(u); }
  function hostOf(u) { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return ""; } }

  function api(path, opts) {
    opts = opts || {};
    var h = { "Authorization": "Bearer " + S.key };
    if (opts.body) h["Content-Type"] = "application/json";
    return fetch(S.server + path, { method: opts.method || "GET", headers: h, body: opts.body ? JSON.stringify(opts.body) : undefined, credentials: "omit", cache: "no-store" })
      .then(function (r) {
        if (opts.raw && r.ok) return r;
        return r.json().catch(function () { return {}; }).then(function (d) {
          if (!r.ok) { var e = new Error(d.error || ("The server answered " + r.status + ".")); e.status = r.status; throw e; }
          return d;
        });
      }, function () { throw new Error("Couldn't reach " + hostOf(S.server) + ". Check the address and your connection."); });
  }
  function bufToB64(buf) {
    var bytes = new Uint8Array(buf), out = "", step = 0x8000;
    for (var i = 0; i < bytes.length; i += step) out += String.fromCharCode.apply(null, bytes.subarray(i, i + step));
    return btoa(out);
  }

  function render() {
    if (!S.server || !S.key) return renderConnect();
    var t = S.tab, url = t && t.url || "", host = hostOf(url);
    var parts = [];
    if (!/^https?:/.test(url)) {
      parts.push('<h1>Open an application form</h1><p class="muted">Go to a job\'s application page, then click Propelo and press Fill this form.</p>');
    } else if (BLOCKED.test(host)) {
      parts.push('<h1>Apply here yourself</h1><div class="note">Propelo never fills forms on LinkedIn, Naukri, Indeed or Wellfound. Those sites don\'t allow it, and it can get your account restricted. Your answers are ready in Propelo to copy.</div>');
      parts.push(trackCard());
    } else {
      parts.push('<h1>' + esc(S.page && S.page.title || host) + '</h1><p class="muted">' + esc(S.page && S.page.company ? S.page.company + " · " + host : host) + '</p>');
      parts.push('<button class="btn solid block" data-act="fill"' + (S.busy ? " disabled" : "") + '>' + (S.busy === "fill" ? '<span class="spin" aria-hidden="true"></span>Filling…' : S.report ? "Fill again" : "Fill this form") + '</button>');
      if (S.report) parts.push(reportView(S.report));
      parts.push(matchCard());
      if (S.page && S.page.frames && S.page.frames.length && !S.framesOk) parts.push('<div class="note">This form sits inside a frame from <b>' + esc(S.page.frames.map(hostOf).join(", ")) + '</b>. <button class="btn ghost" data-act="frames">Allow Propelo there</button></div>');
      parts.push(trackCard());
    }
    if (S.msg) parts.push('<p class="' + (S.err ? "note" : "good") + '" role="status">' + esc(S.msg) + '</p>');
    parts.push(queueCard());
    parts.push(onPageCard());
    parts.push('<div class="foot"><a href="' + esc(S.server) + '/app" target="_blank" rel="noopener">Open Propelo</a><button class="btn ghost" data-act="disconnect">Disconnect</button></div>');
    app.innerHTML = parts.join("");
    // The gauge counts up once per result; later re-renders show it settled.
    var g = document.getElementById("match");
    if (g && S.match && !S.match.__shown) { S.match.__shown = true; window.PropeloGauge.animate(g); }
  }
  function trackCard() {
    if (S.tracked) return '<div class="good">Saved to Propelo as <b>' + esc(S.tracked.stage === "applied" ? "Applied" : "To apply") + '</b>.</div>' + riskView(S.tracked.risk);
    var p = S.page || {};
    return '<details class="card"' + (S.report ? " open" : "") + '><summary>Save to Propelo</summary>' + (p.jd ? '<p class="muted">The posting\'s full text comes along, so Propelo can score it.</p>' : '') + '' +
      '<label>Role<input type="text" id="tr-title" value="' + esc(p.title || "") + '" maxlength="160"></label>' +
      '<label>Company<input type="text" id="tr-company" value="' + esc(p.company || "") + '" maxlength="120"></label>' +
      '<div class="row"><button class="btn solid" data-act="track" data-applied="1"' + (S.busy ? " disabled" : "") + '>I submitted it</button><button class="btn" data-act="track" data-applied="0"' + (S.busy ? " disabled" : "") + '>Save to apply later</button></div></details>';
  }
  function riskView(r) {
    if (!r || r.level === "ok" || !r.reasons) return "";
    return '<div class="note"><b>' + (r.level === "high" ? "This posting looks unsafe." : "Check this posting.") + '</b><ul>' +
      r.reasons.slice(0, 4).map(function (x) { return '<li><span>' + esc(x.why) + ' “' + esc(x.quote) + '”</span></li>'; }).join("") + '</ul></div>';
  }
  function reportView(r) {
    var out = [];
    out.push('<div class="good"><b>Filled ' + r.filled.length + (r.filled.length === 1 ? " field" : " fields") + '.</b> Check each answer on the page (outlined in pink), then press Submit yourself.</div>');
    if (r.fromAnswers) out.push('<div class="note"><b>' + r.fromAnswers + ' from your saved answers.</b> Read each one: it should still be true for this role.</div>');
    if (r.needs.length) out.push('<div class="card"><div class="row end"><b>Needs you</b><span class="count">' + r.needs.length + '</span></div><ul>' +
      r.needs.slice(0, 12).map(function (n) { return '<li><b>' + esc(n.label.slice(0, 120)) + '</b><span>' + esc(n.why) + '</span></li>'; }).join("") + '</ul>' +
      (r.needs.length > 12 ? '<p class="muted">And ' + (r.needs.length - 12) + ' more, outlined in orange on the page.</p>' : "") + '</div>');
    if (r.filled.length) out.push('<details class="card"><summary>What was filled</summary><ul>' + r.filled.slice(0, 30).map(function (f) { return '<li><b>' + esc(f.label.slice(0, 90)) + '</b><span>' + esc(String(f.value).slice(0, 90)) + '</span></li>'; }).join("") + '</ul></details>');
    if (r.skippedSensitive) out.push('<p class="muted">Left ' + r.skippedSensitive + ' private ' + (r.skippedSensitive === 1 ? "field" : "fields") + ' alone. Propelo never fills passwords, codes, ID numbers, bank details or dates of birth.</p>');
    return out.join("");
  }
  function renderConnect() {
    app.innerHTML = '<h1>Connect to Propelo</h1><p class="muted">Fills application forms from your Propelo profile. You review every answer and press Submit yourself.</p>' +
      '<form id="connect" class="card" novalidate><label>Your Propelo address<input type="url" id="server" placeholder="https://app.propelo.org" value="' + esc(S.server || "") + '" required></label>' +
      '<label>Computer key<input type="password" id="key" placeholder="cos_k_…" autocomplete="off" required></label>' +
      '<p class="muted">Make one in Propelo: Settings, Your computer, Create computer key. The key stays in this browser.</p>' +
      '<button class="btn solid block" type="submit"' + (S.busy ? " disabled" : "") + '>' + (S.busy === "connect" ? '<span class="spin" aria-hidden="true"></span>Checking…' : "Connect") + '</button></form>' +
      (S.msg ? '<p class="' + (S.err ? "note" : "good") + '" role="status">' + esc(S.msg) + '</p>' : "");
  }
  function say(m, err) { S.msg = m; S.err = !!err; render(); }

  function connect(e) {
    e.preventDefault();
    var server = document.getElementById("server").value.trim().replace(/\/+$/, "").replace(/\/app$/, "");
    var key = document.getElementById("key").value.trim();
    if (!okServer(server)) return say("Use your Propelo address starting with https://", true);
    if (!/^cos_k_[A-Za-z0-9_-]{10,}$/.test(key)) return say("That doesn't look like a computer key. It starts with cos_k_.", true);
    // Permission must be asked inside the click, before anything async.
    chrome.permissions.request({ origins: [originOf(server) + "/*"] }, function (granted) {
      if (!granted) return say("Propelo needs permission to talk to " + hostOf(server) + ".", true);
      S.server = server; S.key = key; S.busy = "connect"; S.msg = ""; renderConnect();
      api("/api/agent/applicant").then(function (d) {
        S.busy = "";
        chrome.storage.local.set({ server: server, key: key });
        say(d.applicant ? "Connected. Your application details are ready." : "Connected. Add your application details in Propelo (Profile) so there's something to fill.", !d.applicant);
        loadPage();
      }, function (err) {
        S.busy = ""; S.key = "";
        say(err.status === 401 || err.status === 403 ? "That key didn't work. Make a new one in Propelo and paste it here." : err.message, true);
      });
    });
  }

  function exec(tabId, allFrames, fn, args) {
    return chrome.scripting.executeScript({ target: { tabId: tabId, allFrames: allFrames }, files: ["fill.js"] })
      .then(function () { return chrome.scripting.executeScript({ target: { tabId: tabId, allFrames: allFrames }, func: fn, args: args || [] }); });
  }
  function loadPage() {
    chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
      S.tab = tabs && tabs[0]; S.page = null;
      if (!S.tab || !/^https?:/.test(S.tab.url || "")) return render();
      // On the big boards Propelo reads nothing from the page: only the link and the tab's title.
      if (BLOCKED.test(hostOf(S.tab.url))) { S.page = { title: String(S.tab.title || "").split(/ [|\-–] /)[0].slice(0, 160), company: "" }; S.framesOk = true; return render(); }
      exec(S.tab.id, false, function () {
        var r = window.__propeloRead();
        r.frames = Array.prototype.slice.call(document.querySelectorAll("iframe[src]")).map(function (f) { return f.src; })
          .filter(function (s) { return /greenhouse\.io|lever\.co|ashbyhq\.com|myworkdayjobs\.com|smartrecruiters\.com|workable\.com|recruitee\.com|teamtailor\.com|icims\.com|jobvite\.com|breezy\.hr|zohorecruit/i.test(s); });
        return r;
      }).then(function (res) {
        S.page = res && res[0] && res[0].result;
        if (S.page && String(S.page.jd || "").length >= 200) bg({ type: "match", page: { url: S.page.url, title: S.page.title, jd: S.page.jd } }).then(function (m) { S.match = m; render(); }, function () {});
        var origins = (S.page && S.page.frames || []).map(function (f) { return originOf(f) + "/*"; });
        if (!origins.length) { S.framesOk = true; return render(); }
        chrome.permissions.contains({ origins: origins }, function (ok) { S.framesOk = ok; render(); });
      }, function () { render(); });
    });
  }
  function fill() {
    if (!S.tab) return;
    S.busy = "fill"; S.msg = ""; render();
    api("/api/agent/applicant").then(function (d) {
      var a = d.applicant || {};
      if (!d.applicant) throw new Error("Add your application details in Propelo first (Profile, Application details).");
      var res = a.resume || {};
      var getResume = res.id ? api("/_blob/" + encodeURIComponent(res.id), { raw: true }).then(function (r) { return r.arrayBuffer(); })
        .then(function (b) { return b.byteLength > 8 * 1024 * 1024 ? null : { b64: bufToB64(b), name: res.name || "resume.pdf", type: "application/pdf" }; }, function () { return null; }) : Promise.resolve(null);
      return getResume.then(function (resume) {
        var applicant = {};
        ["fullName", "email", "phone", "city", "linkedin", "github", "portfolio", "currentTitle", "currentCompany", "experienceYears", "noticePeriod",
          "currentCtcLpa", "expectedCtcLpa", "degree", "college", "graduationYear", "cgpa", "branch", "backlogs", "state", "pinCode",
          "workAuthIndia", "workAuth", "expectedPay", "currentPay", "sponsorshipAbroad", "relocate", "howHeard", "servingNotice", "lastWorkingDay", "noticeBuyout",
        "fixedCtcLpa", "variableCtcLpa", "bondOk", "currentlyEmployed", "gapReason", "shiftsOk", "officeOk", "preferredCities"].forEach(function (k) { if (a[k] !== undefined && a[k] !== null && a[k] !== "") applicant[k] = a[k]; });
        var answers = (a.answers || []).filter(function (x) { return x && x.q && x.a; }).map(function (x) { return { q: x.q, a: x.a, company: x.company || "" }; });
        return exec(S.tab.id, true, function (data) { return window.__propeloFill(data); }, [{ applicant: applicant, resume: resume, answers: answers, company: (S.page && S.page.company) || "" }]);
      });
    }).then(function (results) {
      var merged = { filled: [], needs: [], skippedSensitive: 0, resume: "", blocked: false };
      (results || []).forEach(function (r) {
        var x = r && r.result; if (!x) return;
        merged.filled = merged.filled.concat(x.filled); merged.needs = merged.needs.concat(x.needs);
        merged.skippedSensitive += x.skippedSensitive; merged.blocked = merged.blocked || x.blocked; if (x.resume) merged.resume = x.resume;
        merged.fromAnswers = (merged.fromAnswers || 0) + (x.fromAnswers || 0);
      });
      S.busy = ""; S.report = merged;
      if (merged.blocked) return say("Propelo doesn't fill forms on this site.", true);
      if (!merged.filled.length && !merged.needs.length) return say("No form fields found on this page. Open the application form itself (often behind an Apply button).", true);
      S.msg = ""; render();
    }).catch(function (err) { S.busy = ""; say(err.message || "Something went wrong.", true); });
  }
  function track(applied) {
    var title = (document.getElementById("tr-title") || {}).value || "", company = (document.getElementById("tr-company") || {}).value || "";
    if (!title.trim() || !company.trim()) return say("Add the role and the company first.", true);
    S.busy = "track"; render();
    var p = S.page || {}, body = { url: S.tab.url, title: title.trim(), company: company.trim(), applied: applied };
    ["jd", "location", "salary", "employmentType", "postedAt", "validThrough"].forEach(function (k) { if (p[k]) body[k] = p[k]; });
    api("/api/agent/track", { method: "POST", body: body })
      .then(function (d) { S.busy = ""; S.tracked = d; say(d.created ? "Added to your applications." : "Updated the role you already had."); },
            function (err) { S.busy = ""; say(err.message, true); });
  }

  app.addEventListener("submit", function (e) { if (e.target.id === "connect") connect(e); });
  app.addEventListener("change", function (e) {
    if (e.target.id !== "onpage") return;
    if (e.target.checked) {
      chrome.permissions.request({ origins: S.hosts || [] }, function (ok) {
        if (!ok) { S.onpage = false; return say("Without access to those sites Propelo can't show up on them.", true); }
        bg({ type: "onpage:enable" }).then(function () { S.onpage = true; say("Propelo now shows your match and a Fill button on job pages on those sites."); }, function (err) { say(err.message, true); });
      });
    } else bg({ type: "onpage:disable" }).then(function () { S.onpage = false; render(); });
  });
  app.addEventListener("click", function (e) {
    var b = e.target.closest("[data-act]"); if (!b) return;
    var act = b.dataset.act;
    if (act === "fill") fill();
    else if (act === "track") track(b.dataset.applied === "1");
    else if (act === "frames") {
      var origins = S.page.frames.map(function (f) { return originOf(f) + "/*"; });
      chrome.permissions.request({ origins: origins }, function (ok) { S.framesOk = ok; if (ok) fill(); else say("Without that, Propelo can't reach the form inside the frame.", true); });
    }
    else if (act === "q-start") {
      var roles = (S.queue && S.queue.roles) || [];
      var origins = roles.map(function (r) { return originOf(r.url) + "/*"; }).filter(function (o, i, a) { return o.length > 3 && a.indexOf(o) === i && !BLOCKED.test(hostOf(o.replace(/\/\*$/, ""))); });
      // Asked inside the click: the queue's sites, so each role can be filled when it opens.
      chrome.permissions.request({ origins: origins.concat(S.hosts || []) }, function (ok) {
        if (!ok) return say("Propelo needs to reach those sites to fill each form.", true);
        bg({ type: "onpage:enable" }).then(function () { return bg({ type: "queue:start", roles: roles }); })
          .then(function () { window.close(); }, function (e) { say(e.message, true); });
      });
    }
    else if (act === "q-stop") bg({ type: "queue:stop" }).then(function () { S.qstatus = null; loadExtras(); });
    else if (act === "q-show") { if (S.qstatus && S.qstatus.tabId) chrome.tabs.update(S.qstatus.tabId, { active: true }); window.close(); }
    else if (act === "disconnect") { chrome.storage.local.remove(["server", "key"]); S.key = ""; S.report = null; S.msg = ""; render(); }
  });

  function loadExtras() {
    bg({ type: "queue:status" }).then(function (st) { S.qstatus = st; if (!st.active) return bg({ type: "queue:list" }).then(function (q) { S.queue = q; }); }).then(render, function () {});
    bg({ type: "onpage:get" }).then(function (o) { S.onpage = o.on; S.hosts = o.hosts; render(); }, function () {});
  }
  chrome.storage.local.get(["server", "key"], function (v) {
    S.server = v.server || ""; S.key = v.key || "";
    if (S.server && S.key) { loadPage(); loadExtras(); } else render();
  });
})();

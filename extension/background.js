/* Propelo Autofill: background worker.
   Holds the connection (server address and computer key stay here and in extension storage; pages never
   see them), talks to Propelo for the popup and the on-page button, fills forms in every frame of a tab,
   and runs the apply queue: it opens your approved roles one at a time and fills each. You review every
   answer and press Submit yourself; nothing here submits a form. */
"use strict";

// Hiring systems where the on-page button can appear, once you switch it on (each is asked for then).
var JOB_HOSTS = [
  "https://boards.greenhouse.io/*", "https://job-boards.greenhouse.io/*", "https://*.greenhouse.io/*",
  "https://jobs.lever.co/*", "https://jobs.eu.lever.co/*", "https://jobs.ashbyhq.com/*",
  "https://*.myworkdayjobs.com/*", "https://jobs.smartrecruiters.com/*", "https://apply.workable.com/*",
  "https://*.recruitee.com/*", "https://*.teamtailor.com/*", "https://*.icims.com/*", "https://jobs.jobvite.com/*",
  "https://*.breezy.hr/*", "https://*.bamboohr.com/*", "https://*.jobs.personio.de/*", "https://*.jobs.personio.com/*",
  "https://*.zohorecruit.com/*", "https://*.zohorecruit.in/*", "https://*.darwinbox.in/*", "https://*.keka.com/*",
  "https://*.freshteam.com/*", "https://*.successfactors.com/*", "https://*.successfactors.eu/*", "https://*.taleo.net/*"
];
var BLOCKED = /(^|\.)(linkedin\.com|naukri\.com|indeed\.[a-z.]+|wellfound\.com|angel\.co)$/i;
var SCRIPT_ID = "propelo-onpage";

function hostOf(u) { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return ""; } }
function conn() { return chrome.storage.local.get(["server", "key"]); }

function api(path, opts) {
  opts = opts || {};
  return conn().then(function (c) {
    if (!c.server || !c.key) { var e0 = new Error("Connect Propelo first: click the Propelo icon."); e0.status = 401; throw e0; }
    var h = { "Authorization": "Bearer " + c.key };
    if (opts.body) h["Content-Type"] = "application/json";
    return fetch(c.server + path, { method: opts.method || "GET", headers: h, body: opts.body ? JSON.stringify(opts.body) : undefined, credentials: "omit", cache: "no-store" })
      .then(function (r) {
        if (opts.raw && r.ok) return r;
        return r.json().catch(function () { return {}; }).then(function (d) {
          if (!r.ok) { var e = new Error(d.error || ("Propelo answered " + r.status + ".")); e.status = r.status; throw e; }
          return d;
        });
      }, function () { throw new Error("Couldn't reach " + hostOf(c.server) + ". Check your connection."); });
  });
}
function bufToB64(buf) {
  var bytes = new Uint8Array(buf), out = "", step = 0x8000;
  for (var i = 0; i < bytes.length; i += step) out += String.fromCharCode.apply(null, bytes.subarray(i, i + step));
  return btoa(out);
}

// What the fill script needs: your application details, resume file and saved answers. Kept in memory for a few minutes.
var cache = { at: 0, data: null };
function fillData() {
  if (cache.data && Date.now() - cache.at < 5 * 60 * 1000) return Promise.resolve(cache.data);
  return api("/api/agent/applicant").then(function (d) {
    var a = d.applicant;
    if (!a) throw new Error("Add your application details in Propelo first (Profile, Application details).");
    var res = a.resume || {};
    var getResume = res.id ? api("/_blob/" + encodeURIComponent(res.id), { raw: true }).then(function (r) { return r.arrayBuffer(); })
      .then(function (b) { return b.byteLength > 8 * 1024 * 1024 ? null : { b64: bufToB64(b), name: res.name || "resume.pdf", type: "application/pdf" }; }, function () { return null; }) : Promise.resolve(null);
    return getResume.then(function (resume) {
      var applicant = {};
      ["fullName", "email", "phone", "city", "linkedin", "github", "portfolio", "currentTitle", "currentCompany", "experienceYears", "noticePeriod",
        "currentCtcLpa", "expectedCtcLpa", "degree", "college", "graduationYear", "cgpa", "branch", "backlogs", "state", "pinCode",
        "workAuthIndia", "sponsorshipAbroad", "relocate", "howHeard"].forEach(function (k) { if (a[k] !== undefined && a[k] !== null && a[k] !== "") applicant[k] = a[k]; });
      var answers = (a.answers || []).filter(function (x) { return x && x.q && x.a; }).map(function (x) { return { q: x.q, a: x.a, company: x.company || "" }; });
      cache = { at: Date.now(), data: { applicant: applicant, resume: resume, answers: answers } };
      return cache.data;
    });
  });
}

function fillTab(tabId, company) {
  return chrome.tabs.get(tabId).then(function (tab) {
    if (BLOCKED.test(hostOf(tab.url || ""))) throw new Error("Propelo never fills forms on this site.");
    return fillData();
  }).then(function (data) {
    var payload = { applicant: data.applicant, resume: data.resume, answers: data.answers, company: company || "" };
    return chrome.scripting.executeScript({ target: { tabId: tabId, allFrames: true }, files: ["fill.js"] })
      .then(function () { return chrome.scripting.executeScript({ target: { tabId: tabId, allFrames: true }, func: function (d) { return window.__careerosFill(d); }, args: [payload] }); });
  }).then(function (results) {
    var merged = { filled: [], needs: [], skippedSensitive: 0, resume: "", blocked: false, fromAnswers: 0 };
    (results || []).forEach(function (r) {
      var x = r && r.result; if (!x) return;
      merged.filled = merged.filled.concat(x.filled); merged.needs = merged.needs.concat(x.needs);
      merged.skippedSensitive += x.skippedSensitive; merged.blocked = merged.blocked || x.blocked; if (x.resume) merged.resume = x.resume;
      merged.fromAnswers += x.fromAnswers || 0;
    });
    return merged;
  });
}

// Match scores, kept per page for the session so revisiting a role doesn't ask again.
function match(page) {
  var key = "m:" + (page.url || "").split("#")[0];
  return chrome.storage.session.get(key).then(function (got) {
    if (got[key]) return got[key];
    return api("/api/agent/match", { method: "POST", body: { title: page.title || "", jd: page.jd || "", url: page.url || "" } }).then(function (m) {
      var o = {}; o[key] = m; chrome.storage.session.set(o); return m;
    });
  });
}

// ---------------------------------------------------------------- the apply queue
function queue() { return chrome.storage.session.get("queue").then(function (v) { return v.queue || null; }); }
function setQueue(q) { return q ? chrome.storage.session.set({ queue: q }) : chrome.storage.session.remove("queue"); }
// Open the application form itself where the hiring system has a separate page for it.
function applyUrl(u) {
  try {
    var x = new URL(u);
    if (/(^|\.)jobs(\.eu)?\.lever\.co$/.test(x.hostname) && !/\/apply\/?$/.test(x.pathname)) x.pathname = x.pathname.replace(/\/$/, "") + "/apply";
    else if (x.hostname === "jobs.ashbyhq.com" && !/\/application\/?$/.test(x.pathname)) x.pathname = x.pathname.replace(/\/$/, "") + "/application";
    return x.toString();
  } catch (e) { return u; }
}
function startQueue(roles) {
  var items = (roles || []).filter(function (r) { return r && /^https:\/\//.test(r.url || "") && !BLOCKED.test(hostOf(r.url)); })
    .map(function (r) { return { id: r.id, url: applyUrl(r.url), company: r.company || "", title: r.title || "", score: r.score || null }; });
  if (!items.length) return Promise.reject(new Error("Nothing in your apply queue right now."));
  // The panel also runs on the queue's own sites (company career pages), which the popup asked for.
  var origins = items.map(function (r) { try { return new URL(r.url).origin + "/*"; } catch (e) { return ""; } })
    .filter(function (o, i, a) { return o && a.indexOf(o) === i; });
  var register = chrome.scripting.getRegisteredContentScripts({ ids: ["propelo-queue"] }).then(function (got) {
    return got.length ? chrome.scripting.unregisterContentScripts({ ids: ["propelo-queue"] }) : null;
  }).then(function () {
    return chrome.permissions.contains({ origins: origins }).then(function (ok) {
      if (!ok) return null;
      return chrome.scripting.registerContentScripts([{ id: "propelo-queue", matches: origins, js: ["fill.js", "gauge.js", "content.js"], runAt: "document_idle", allFrames: false, persistAcrossSessions: false }]);
    });
  }).catch(function () { return null; });
  return register.then(function () { return chrome.tabs.create({ url: items[0].url, active: true }); }).then(function (tab) {
    var q = { items: items, index: 0, tabId: tab.id, done: [], skipped: [], startedAt: Date.now() };
    return setQueue(q).then(function () { return q; });
  });
}
function step(q, how) {
  var cur = q.items[q.index];
  if (cur) (how === "done" ? q.done : q.skipped).push(cur.id);
  q.index += 1;
  chrome.storage.session.remove(["filledUrl", "filledTab"]);
  if (q.index >= q.items.length) {
    return setQueue(null).then(function () { return { finished: true, done: q.done.length, skipped: q.skipped.length }; });
  }
  return setQueue(q).then(function () { return chrome.tabs.update(q.tabId, { url: q.items[q.index].url }); }).then(function () { return { next: q.items[q.index], position: q.index + 1, total: q.items.length }; });
}
function track(page, applied, jobId) {
  var body = { url: page.url, title: page.title || "", company: page.company || "", applied: !!applied };
  ["jd", "location", "salary", "employmentType", "postedAt", "validThrough"].forEach(function (k) { if (page[k]) body[k] = page[k]; });
  if (jobId) body.jobId = jobId;
  return api("/api/agent/track", { method: "POST", body: body });
}

// ---------------------------------------------------------------- the on-page button
function onPageEnabled() { return chrome.scripting.getRegisteredContentScripts({ ids: [SCRIPT_ID] }).then(function (s) { return s.length > 0; }); }
function enableOnPage() {
  return onPageEnabled().then(function (on) {
    if (on) return true;
    return chrome.scripting.registerContentScripts([{ id: SCRIPT_ID, matches: JOB_HOSTS, js: ["fill.js", "gauge.js", "content.js"], runAt: "document_idle", allFrames: false, persistAcrossSessions: true }])
      .then(function () { return true; });
  });
}
function disableOnPage() { return onPageEnabled().then(function (on) { return on ? chrome.scripting.unregisterContentScripts({ ids: [SCRIPT_ID] }) : null; }); }

chrome.runtime.onMessage.addListener(function (msg, sender, reply) {
  var tabId = msg.tabId || (sender.tab && sender.tab.id);
  var p;
  switch (msg && msg.type) {
    case "fill": p = fillTab(tabId, msg.company); break;
    case "match": p = match(msg.page || {}); break;
    case "track": p = track(msg.page || {}, msg.applied, msg.jobId).then(function (d) { cache.at = 0; return d; }); break;
    case "queue:list": p = api("/api/agent/next?limit=" + Math.min(25, Math.max(1, msg.limit || 25))); break;
    case "queue:start": p = startQueue(msg.roles); break;
    case "queue:state": p = queue().then(function (q) {
      if (!q || q.tabId !== tabId) return { active: false };
      return { active: true, item: q.items[q.index], position: q.index + 1, total: q.items.length, done: q.done.length };
    }); break;
    case "queue:status": p = queue().then(function (q) { return q ? { active: true, position: q.index + 1, total: q.items.length, done: q.done.length, tabId: q.tabId } : { active: false }; }); break;
    case "queue:next": p = queue().then(function (q) { return q && q.tabId === tabId ? step(q, msg.how === "done" ? "done" : "skip") : { finished: true }; }); break;
    case "queue:stop": p = setQueue(null).then(function () { return { stopped: true }; }); break;
    case "onpage:get": p = onPageEnabled().then(function (on) { return { on: on, hosts: JOB_HOSTS }; }); break;
    case "onpage:enable": p = enableOnPage().then(function () { return { on: true }; }); break;
    case "onpage:disable": p = disableOnPage().then(function () { return { on: false }; }); break;
    case "connected": p = Promise.all([conn(), chrome.storage.local.get("hiddenHosts")]).then(function (v) {
      return { connected: !!(v[0].server && v[0].key), hidden: (v[1].hiddenHosts || []).indexOf(msg.host || "") >= 0 }; }); break;
    case "hide": p = chrome.storage.local.get("hiddenHosts").then(function (v) {
      var h = (v.hiddenHosts || []).filter(function (x) { return x !== msg.host; }).concat([String(msg.host || "").slice(0, 200)]).slice(-200);
      return chrome.storage.local.set({ hiddenHosts: h }).then(function () { return { hidden: true }; }); }); break;
    case "filled:set": p = chrome.storage.session.set({ filledUrl: String(msg.url || "").slice(0, 1000), filledTab: tabId }).then(function () { return true; }); break;
    case "filled:get": p = chrome.storage.session.get(["filledUrl", "filledTab"]).then(function (v) { return v.filledTab === tabId ? v.filledUrl || "" : ""; }); break;
    default: return false;
  }
  p.then(function (v) { reply({ ok: true, data: v }); }, function (e) { reply({ ok: false, error: e.message || String(e), status: e.status || 0 }); });
  return true; // answer asynchronously
});

// The queue ends if its tab is closed.
chrome.tabs.onRemoved.addListener(function (tabId) { queue().then(function (q) { if (q && q.tabId === tabId) setQueue(null); }); });

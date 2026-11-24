/* Propelo Autofill: the part that runs inside an application page.
   It fills empty fields from the Propelo profile it is given, attaches the resume, outlines what
   it filled, and lists what it left for you. It never presses Submit, never ticks consent boxes,
   never overwrites what is already typed, and never touches passwords, one-time codes, identity
   numbers, bank details or dates of birth. The page's own text is only matched, never followed. */
(function () {
  "use strict";
  if (window.__propeloFill) return;

  var BLOCKED = /(^|\.)(linkedin\.com|naukri\.com|indeed\.[a-z.]+|wellfound\.com|angel\.co)$/i;
  var SENSITIVE = /pass(word|code)|one[- ]?time|\botp\b|verification code|aadhaa?r|\bpan\b|pan (card|number)|permanent account|bank|ifsc|account (number|no)|routing|passport|date of birth|\bdob\b|birth ?date|\bssn\b|social security|national id|credit card|card number|\bcvv\b|security question|mother'?s maiden/i;

  // [key, label pattern]. First match wins, so specific labels come before general ones.
  var RULES = [
    ["firstName", /\b(first|given|fore) ?name\b|\bfname\b/i],
    ["lastName", /\b(last|family|sur) ?name\b|\bsurname\b|\blname\b/i],
    ["email", /e-?mail/i],
    ["phone", /phone|mobile|contact (number|no)|whats ?app/i],
    ["linkedin", /linked ?in/i],
    ["github", /git ?hub/i],
    ["portfolio", /portfolio|personal (site|website)|^website\b|\bwebsite\b|\burl\b|blog/i],
    ["currentCompany", /current (company|employer|organi[sz]ation)|present (company|employer)|^company( name)?$/i],
    ["currentTitle", /current (title|role|designation|position|job title)|^(job )?title$|designation/i],
    ["experienceYears", /(years|yrs)( of)? (total |relevant |work |professional )?experience|total experience|experience \((in )?years\)|^experience$/i],
    // Indian HR screening questions, specific ones first.
    ["noticeBuyout", /buy ?-?out|early (release|relieving)|notice (period )?(is )?negotiable|negotiable notice/i],
    ["servingNotice", /serving (your |the )?notice|(currently )?(in|on) (your |the )?notice period|resigned already|have you resigned/i],
    ["lastWorkingDay", /last working (day|date)|\blwd\b|relieving date|date of relieving/i],
    ["noticePeriod", /notice period|how soon can you (join|start)|earliest (start|joining)|availability to (join|start)|joining (time|availability)|when can you join/i],
    ["expectedCtcLpa", /expected (ctc|salary|compensation|pay|package)|salary expectation|desired (salary|compensation)|compensation expectation|\bectc\b/i],
    ["fixedCtcLpa", /fixed (ctc|pay|component|salary|compensation)|base (salary|pay)/i],
    ["variableCtcLpa", /variable (pay|ctc|component|compensation)|incentives?|bonus component|annual bonus/i],
    ["currentCtcLpa", /current (ctc|salary|compensation|pay|package)|present (ctc|salary)|\bcctc\b|last drawn/i],
    ["bondOk", /\bbond\b|service agreement|commitment (period|agreement)/i],
    ["currentlyEmployed", /currently (employed|working)|are you (currently )?(employed|working)|employment status/i],
    ["gapReason", /\bgap\b|career break|break in (your )?(career|employment|education)/i],
    ["shiftsOk", /night shifts?|rotational shifts?|shift timings?|work in shifts/i],
    ["officeOk", /work(ing)? from (the )?office|in[- ]office|on[- ]?site|onsite|days a week (in|from) (the )?office/i],
    ["preferredCities", /preferred (job |work )?(location|city|cities)|location preference|which (city|cities|location)/i],
    ["graduationYear", /graduation (year|date)|year of (graduation|passing)|passing year|batch/i],
    ["cgpa", /\bc?gpa\b|cgpa|^percentage$|percentage (scored|obtained)|aggregate (marks|score|percentage)|academic score|marks obtained/i],
    ["branch", /\bbranch\b|speciali[sz]ation|^major$|^stream$|^discipline$|field of study/i],
    ["backlogs", /backlogs?|arrears|\bkt\b/i],
    ["pinCode", /pin ?code|postal code|post ?code|zip ?code|\bzip\b/i],
    ["state", /^(state|province|state ?\/ ?ut|state or province|state of residence)$|\b(current|home|residential) state\b/i],
    ["degree", /degree|qualification|education level/i],
    ["college", /college|university|school|institut/i],
    ["workAuthIndia", /(authori[sz]ed|eligible|legally (allowed|permitted)).{0,40}work.{0,40}india|work (authori[sz]ation|permit).{0,30}india/i],
    ["workAuth", /(authori[sz]ed|eligible|legally (allowed|permitted|entitled)|(legal )?right) to work|work (authori[sz]ation|eligibility)/i],
    ["sponsorshipAbroad", /sponsor/i],
    ["relocate", /relocat/i],
    ["city", /\bcity\b|current location|where are you (based|located)|^location\b|\blocation$|town/i],
    ["howHeard", /how did you (hear|find|learn)|where did you (hear|find)|referral source|^source$/i],
    ["fullName", /full ?name|^name\b|your name|candidate name|legal name|^name$/i]
  ];
  // Questions about someone else (a referrer, a reference, an emergency contact) are never filled with your details.
  var OTHER_PERSON = /referr(er|ed by|ing employee)|\breference\b|emergency|guardian|father|mother|spouse|parent|recruiter'?s|manager'?s|employee'?s/i;
  var CHOICE_KEYS = { workAuth: 1, workAuthIndia: 1, sponsorshipAbroad: 1, relocate: 1, noticePeriod: 1, degree: 1, backlogs: 1, servingNotice: 1, noticeBuyout: 1,
    bondOk: 1, currentlyEmployed: 1, shiftsOk: 1, officeOk: 1, preferredCities: 1 };
  var CTC = { expectedCtcLpa: 1, currentCtcLpa: 1, fixedCtcLpa: 1, variableCtcLpa: 1 };
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function words(s) { return String(s || "").toLowerCase().replace(/[^a-z0-9 ]+/g, " ").split(/\s+/).filter(function (w) { return w.length > 2 && !/^(the|and|you|your|for|with|this|that|are|our|why|what|how|please|tell|describe)$/.test(w); }); }
  // A saved answer fits a question when they share most of their words, and a company-only answer
  // is used only on that company's form.
  function savedAnswer(label, answers, company) {
    var cw = words(company).concat(["here", "company", "join", "team", "organisation", "organization"]);
    var strip = function (ws) { return ws.filter(function (w) { return cw.indexOf(w) < 0; }); };
    var lw = strip(words(label)); if (lw.length < 2) return null;
    var co = String(company || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
    var best = null, bestScore = 0;
    (answers || []).forEach(function (a) {
      if (!a || !a.q || !a.a) return;
      var ac = String(a.company || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
      if (ac && (!co || (co.indexOf(ac) < 0 && ac.indexOf(co) < 0))) return;
      var qw = strip(words(a.q).filter(function (w) { return words(a.company).indexOf(w) < 0; })), inter = qw.filter(function (w) { return lw.indexOf(w) >= 0; }).length;
      var score = inter / Math.max(1, Math.min(qw.length, lw.length));
      if (score > bestScore) { best = a; bestScore = score; }
    });
    return bestScore >= 0.75 ? best : null;
  }

  function clean(s) { return String(s || "").replace(/[\s ]+/g, " ").replace(/[*:]+\s*$/, "").trim(); }
  // Forms built from web components keep their fields inside shadow roots, where document.querySelectorAll
  // can't see them. Every open shadow root on the page is searched too (closed ones stay closed).
  function roots() {
    var out = [document], i = 0;
    while (i < out.length && out.length < 400) {
      var all = out[i++].querySelectorAll("*");
      for (var k = 0; k < all.length; k++) if (all[k].shadowRoot) out.push(all[k].shadowRoot);
    }
    return out;
  }
  function deepAll(sel) {
    var res = [];
    roots().forEach(function (r) { res = res.concat(Array.prototype.slice.call(r.querySelectorAll(sel))); });
    return res;
  }
  function rootOf(el) { var r = el.getRootNode ? el.getRootNode() : document; return r && r.querySelector ? r : document; }
  function byId(el, id) { var r = rootOf(el); return (r.getElementById ? r.getElementById(id) : null) || document.getElementById(id); }
  function visible(el) {
    if (el.disabled || el.readOnly) return false;
    if (el.type === "hidden") return false;
    var r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.display === "none") return false;
    return (r.width > 0 && r.height > 0) || el.type === "file" || el.type === "radio";
  }
  function labelOf(el) {
    var parts = [];
    if (el.getAttribute("aria-labelledby")) el.getAttribute("aria-labelledby").split(/\s+/).forEach(function (id) { var n = byId(el, id); if (n) parts.push(n.textContent); });
    if (el.getAttribute("aria-label")) parts.push(el.getAttribute("aria-label"));
    if (el.id) { try { var l = rootOf(el).querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) parts.push(l.textContent); } catch (e) { /* odd id */ } }
    var wrap = el.closest("label"); if (wrap) parts.push(wrap.textContent);
    if (!parts.length) {
      // Common form layouts: a label or legend in the same field wrapper.
      var box = el.closest(".field, .form-group, .application-question, .application-field, [class*='question'], [class*='field'], li, fieldset, div");
      for (var i = 0; box && i < 3 && !parts.length; i++, box = box.parentElement && box.parentElement.closest("div, fieldset, li")) {
        var lab = box.querySelector("label, legend, .label, [class*='label']"); if (lab && !lab.contains(el)) parts.push(lab.textContent);
      }
    }
    if (el.placeholder) parts.push(el.placeholder);
    return clean(parts.join(" ")).slice(0, 300);
  }
  function hints(el) { return [el.name, el.id, el.getAttribute("autocomplete"), el.getAttribute("data-qa"), el.getAttribute("data-automation-id")].filter(Boolean).join(" ").replace(/[_\-\[\]]+/g, " "); }
  function required(el, label) { return el.required || el.getAttribute("aria-required") === "true" || /\*\s*$|\(required\)|\brequired\b/i.test(label || ""); }

  // React, Vue and Angular track values through the prototype setter, so set it there and announce it.
  function setValue(el, v) {
    var proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    var desc = Object.getOwnPropertyDescriptor(proto, "value");
    el.focus({ preventScroll: true });
    if (desc && desc.set) desc.set.call(el, v); else el.value = v;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
  }
  function norm(s) { return String(s || "").toLowerCase().replace(/[^a-z0-9+]+/g, " ").trim(); }
  function pickOption(options, want) {
    var w = norm(want); if (!w) return null;
    var yes = /^(yes|y|true)$/.test(w), no = /^(no|n|false)$/.test(w);
    var best = null, bestScore = 0;
    options.forEach(function (o) {
      var t = norm(o.text), s = 0;
      if (!t || /^(select|choose|please select|none selected)/.test(t)) return;
      if (t === w) s = 100;
      else if (yes && /^yes\b/.test(t)) s = 90;
      else if (no && /^no\b/.test(t)) s = 90;
      else if (!yes && !no && (t.indexOf(w) === 0 || w.indexOf(t) === 0)) s = 70;
      else if (!yes && !no && t.indexOf(w) >= 0) s = 50;
      else { var n = parseFloat(w); var m = t.match(/(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)/); if (!isNaN(n) && m && n >= +m[1] && n <= +m[2]) s = 60; }
      if (s > bestScore) { best = o; bestScore = s; }
    });
    return best;
  }

  function valueFor(key, a, label, el) {
    var v = a[key];
    if (/^prefer not/i.test(String(v || ""))) v = "";
    if (key === "lastWorkingDay" && v) {
      var d = new Date(String(v) + "T00:00:00");
      if (isNaN(d) || d < new Date(new Date().toDateString()) || !/^yes/i.test(a.servingNotice || "")) v = "";  // only a real, upcoming date
      else if (!el || el.type !== "date") v = d.getDate() + " " + MON[d.getMonth()] + " " + d.getFullYear();
    }
    if (CTC[key] && v !== undefined && v !== null && v !== "") {
      // Stored in lakhs a year. A form that asks in rupees gets rupees; a monthly figure is left to you.
      var l = String(label || "") + " " + String(el && el.placeholder || "");
      if (/per month|monthly|\/\s*month|\bpm\b/i.test(l) || (key !== "expectedCtcLpa" && /expect|desir/i.test(label || ""))) v = "";
      else if (!/lpa|lakh|\blacs?\b|\blac\b|in l\b/i.test(l) && (/\binr\b|rupees|₹|\brs\.?\b|in numbers|absolute/i.test(l) || /\d{5,}/.test(String(el && el.placeholder || "")) || +(el && el.min) >= 10000)) v = Math.round(parseFloat(v) * 100000);
    }
    if (key === "preferredCities" && v && el && (el.tagName === "SELECT" || el.type === "radio" || el.__combo)) v = String(v).split(/[,;/]/)[0].trim();
    // "Venkata Vishnu Vardhan Raju Chakravarthula": the surname is the last word, the given names the rest.
    var parts = String(a.fullName || "").trim().split(/\s+/).filter(Boolean);
    if (key === "firstName" && !v) v = parts.length > 1 ? parts.slice(0, -1).join(" ") : (parts[0] || "");
    if (key === "lastName" && !v) v = parts.length > 1 ? parts[parts.length - 1] : "";
    if (key === "sponsorshipAbroad" && /not applicable/i.test(v || "")) v = "No";
    // Someone applying outside India keeps pay as text with its currency: it goes into free-text boxes only, never a number box.
    if ((key === "expectedCtcLpa" || key === "currentCtcLpa") && (v === undefined || v === null || v === "") && (!el || (el.tagName !== "SELECT" && el.type !== "number")))
      v = (key === "expectedCtcLpa" ? a.expectedPay : a.currentPay) || "";
    // "Are you authorised to work in the UK?": yes for a citizen, resident or visa holder. Someone who needs sponsorship answers it themselves.
    if (key === "workAuth" && v) v = /sponsor/i.test(v) ? "" : "Yes";
    if ((key === "expectedCtcLpa" || key === "currentCtcLpa") && v !== undefined && v !== null && v !== "") v = String(v);
    if (key === "experienceYears" && v !== undefined && v !== null && v !== "") v = String(v);
    if (key === "graduationYear" && v) v = String(v);
    return v === undefined || v === null ? "" : String(v);
  }
  function matchKey(label, hint) {
    if (SENSITIVE.test(label) || SENSITIVE.test(hint)) return "__sensitive";
    var other = OTHER_PERSON.test(label);
    for (var i = 0; i < RULES.length; i++) if (RULES[i][1].test(label)) return other && RULES[i][0] !== "howHeard" ? "" : RULES[i][0];
    if (other) return "";
    for (var j = 0; j < RULES.length; j++) if (RULES[j][1].test(hint)) return RULES[j][0];
    if (/\bname\b/i.test(hint) && !/user ?name|company|file/i.test(hint)) return "fullName";
    return "";
  }
  var MARKS = "[data-propelo=filled]{outline:2px solid #F5B8DB!important;outline-offset:1px}[data-propelo=needs]{outline:2px dashed #E49A3C!important;outline-offset:1px}";
  function mark(el, kind) {
    el.setAttribute("data-propelo", kind);
    var r = rootOf(el), host = r === document ? (document.head || document.documentElement) : r;
    if (!(r.getElementById ? r.getElementById("propelo-marks") : r.querySelector("#propelo-marks"))) {
      var st = document.createElement("style"); st.id = "propelo-marks"; st.textContent = MARKS;
      host.appendChild(st);
    }
  }
  function questionOf(el, group) {
    var fs = el.closest("fieldset");
    if (fs && fs.querySelector("legend")) return clean(fs.querySelector("legend").textContent);
    var box = el.parentElement;
    for (var i = 0; box && i < 5; i++, box = box.parentElement) {
      if (!group.every(function (r) { return box.contains(r); })) continue;
      var cands = box.querySelectorAll("label, legend, p, span, div, h3, h4, [class*='label']");
      for (var j = 0; j < cands.length; j++) {
        var c = cands[j];
        if (c.querySelector("input") || group.some(function (r) { return c.contains(r) || (r.id && c.getAttribute("for") === r.id); })) continue;
        var t = clean(c.textContent); if (t.length > 3) return t.slice(0, 300);
      }
    }
    return clean(el.getAttribute("aria-label") || el.name || "");
  }
  function b64ToFile(r) {
    var bin = atob(r.b64), u = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
    return new File([u], r.name || "resume.pdf", { type: r.type || "application/pdf" });
  }

  window.__propeloRead = function () {
    var h1 = document.querySelector("h1, .posting-headline h2, [data-automation-id='jobPostingHeader'], .app-title");
    var og = document.querySelector('meta[property="og:site_name"]'), ogt = document.querySelector('meta[property="og:title"]');
    var co = document.querySelector(".company-name, .main-header-logo img[alt], [class*='companyName'], [data-automation-id='company']");
    var company = co ? clean(co.getAttribute("alt") || co.textContent).replace(/^at /i, "") : og ? clean(og.content) : "";
    var title = h1 ? clean(h1.textContent) : ogt ? clean(ogt.content) : clean(document.title.split(/[|\-–]/)[0]);
    var m = location.pathname.match(/^\/([^/]+)\//);
    if (!company && /greenhouse\.io|lever\.co|ashbyhq\.com/.test(location.hostname) && m) company = m[1].replace(/[-_]+/g, " ").replace(/\b\w/g, function (c) { return c.toUpperCase(); });
    if (!company) company = location.hostname.replace(/^(www|careers|jobs|apply)\./, "").split(".")[0].replace(/\b\w/g, function (c) { return c.toUpperCase(); });
    var out = { url: location.href, title: title.slice(0, 160), company: company.slice(0, 120), host: location.hostname };
    var jp = jobPosting();
    if (jp) {
      if (jp.title) out.title = clean(jp.title).slice(0, 160);
      var org = jp.hiringOrganization && (jp.hiringOrganization.name || jp.hiringOrganization);
      if (typeof org === "string" && clean(org)) out.company = clean(org).slice(0, 120);
      out.jd = htmlText(jp.description || "").slice(0, 60000);
      out.location = placeOf(jp).slice(0, 160);
      out.salary = payOf(jp.baseSalary).slice(0, 120);
      out.employmentType = [].concat(jp.employmentType || []).join(", ").slice(0, 60);
      out.postedAt = String(jp.datePosted || "").slice(0, 40);
      out.validThrough = String(jp.validThrough || "").slice(0, 40);
    }
    return out;
  };

  // schema.org JobPosting, which most career sites publish for search engines. Read as data only.
  function jobPosting() {
    var nodes = document.querySelectorAll('script[type="application/ld+json"]');
    for (var i = 0; i < nodes.length; i++) {
      var data;
      try { data = JSON.parse(nodes[i].textContent || "null"); } catch (e) { continue; }
      var queue = [].concat(data || []);
      while (queue.length) {
        var x = queue.shift();
        if (!x || typeof x !== "object") continue;
        var t = [].concat(x["@type"] || []);
        if (t.indexOf("JobPosting") >= 0) return x;
        if (x["@graph"]) queue = queue.concat(x["@graph"]);
      }
    }
    return null;
  }
  function htmlText(h) {
    var d = new DOMParser().parseFromString("<div>" + String(h) + "</div>", "text/html");
    d.querySelectorAll("br,p,li,h1,h2,h3,h4,div").forEach(function (n) { n.insertAdjacentText("afterend", "\n"); });
    return (d.body.textContent || "").replace(/[ \t]+/g, " ").replace(/\n\s*\n+/g, "\n\n").trim();
  }
  function placeOf(jp) {
    if (/telecommute/i.test(String(jp.jobLocationType || ""))) return "Remote";
    var l = [].concat(jp.jobLocation || [])[0], a = l && l.address;
    if (!a) return "";
    if (typeof a === "string") return clean(a);
    return [a.addressLocality, a.addressRegion, a.addressCountry && (a.addressCountry.name || a.addressCountry)].filter(Boolean).map(clean).join(", ");
  }
  function payOf(s) {
    if (!s || typeof s !== "object") return "";
    var v = s.value || {}, cur = s.currency || v.currency || "", unit = (v.unitText || "").toLowerCase();
    var lo = v.minValue || v.value, hi = v.maxValue;
    if (!lo) return "";
    return cur + " " + lo + (hi && hi !== lo ? "–" + hi : "") + (unit ? " per " + unit : "");
  }

  // Custom dropdowns (Workday, Angular Material, react-select): open, pick the option that matches, or close and leave it.
  var COMBO = '[role=combobox], [aria-haspopup=listbox], button[aria-haspopup=true][aria-expanded]';
  function isCombo(el) { return el.matches && el.matches(COMBO) && !(el.tagName === "SELECT"); }
  var PLACEHOLDER = /^(select|choose|please select|search|type to search|--|none selected|select one|select\.\.\.)/i;
  function comboHasValue(el) {
    if (el.tagName === "INPUT") {
      if (String(el.value || "").trim()) return true;
      var box = el.closest("[class*=container], [class*=control], [class*=select]") || el.parentElement;
      return !!(box && box.querySelector("[class*=singleValue], [class*=single-value], [class*=multiValue], [class*=multi-value], [data-automation-id=selectedItem]"));
    }
    var t = clean(el.textContent || "");
    return !!t && !PLACEHOLDER.test(t) && !/^\s*$/.test(t);
  }
  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  // Pickers that load their options from the server (Workday's, among others) take anything from a moment to a
  // couple of seconds. Look every 80 ms for an option that matches, for up to 3 seconds; a search box that hasn't
  // shown anything after 700 ms gets an Enter, which is how Workday's search fields start looking.
  function waitForPick(el, want, ms) {
    var start = Date.now(), entered = false;
    return new Promise(function (res) {
      (function tick() {
        var hit = pickOption(optionsFor(el), want);
        if (hit || Date.now() - start > ms) return res(hit);
        if (!entered && el.tagName === "INPUT" && Date.now() - start > 700 && !optionsFor(el).length) {
          entered = true;
          ["keydown", "keyup"].forEach(function (t) { el.dispatchEvent(new KeyboardEvent(t, { key: "Enter", code: "Enter", keyCode: 13, bubbles: true })); });
        }
        setTimeout(tick, 80);
      })();
    });
  }
  function press(el) { ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach(function (t) { el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window })); }); }
  function optionsFor(el) {
    var ids = (el.getAttribute("aria-controls") || el.getAttribute("aria-owns") || "").split(/\s+/).filter(Boolean), scope = null;
    for (var i = 0; i < ids.length && !scope; i++) scope = byId(el, ids[i]);
    var list = scope ? Array.prototype.slice.call(scope.querySelectorAll("[role=option]")) : deepAll("[role=option]");
    return list.filter(function (o) { var r = o.getBoundingClientRect(); return r.width > 0 && r.height > 0 && o.getAttribute("aria-disabled") !== "true"; })
      .map(function (o) { return { el: o, text: clean(o.textContent) }; });
  }
  function fillCombo(el, data, out) {
    var a = data.applicant || {}, label = labelOf(el), hint = hints(el), key = matchKey(label, hint);
    el.setAttribute("data-propelo-seen", "1");
    if (key === "__sensitive") { out.skippedSensitive++; return Promise.resolve(); }
    if (comboHasValue(el)) return Promise.resolve();
    el.__combo = true;
    var want = key ? valueFor(key, a, label, el) : "";
    if (/gender|ethnic|race|veteran|disabilit|caste|religio/i.test(label)) want = "";
    if (!want) { if (required(el, label)) { out.needs.push({ label: label || "A choice", why: "Pick the answer that's true for you." }); mark(el, "needs"); } return Promise.resolve(); }
    var typed = false;
    try { el.scrollIntoView({ block: "center" }); } catch (e) { /* ignore */ }
    press(el);
    if (el.tagName === "INPUT") { setValue(el, String(want).split(/[,(]/)[0].trim()); el.focus(); typed = true; }
    return waitForPick(el, want, 3000).then(function (hit) {
      if (hit) { press(hit.el); mark(el, "filled"); out.filled.push({ label: label || key, value: hit.text }); return wait(150); }
      el.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      if (typed) setValue(el, "");
      if (required(el, label)) { out.needs.push({ label: label || "A choice", why: "None of the choices matched your details. Pick one yourself." }); mark(el, "needs"); }
      return wait(100);
    });
  }

  function pass(data, out, onlyNew) {
    var a = (data && data.applicant) || {};
    var seenRadio = {}, combos = [];
    var fields = deepAll("input, textarea, select");
    deepAll(COMBO).forEach(function (c) { if (c.tagName !== "INPUT" && c.tagName !== "SELECT" && fields.indexOf(c) < 0) fields.push(c); });
    fields.forEach(function (el) {
      if (onlyNew && el.getAttribute("data-propelo-seen")) return;
      var type = (el.type || "").toLowerCase();
      if (el.tagName !== "INPUT" && el.tagName !== "TEXTAREA" && el.tagName !== "SELECT") { if (visible(el)) combos.push(el); return; }
      if (/^(submit|button|reset|image|hidden|password|checkbox|range|color|search)$/.test(type)) {
        if (type === "checkbox" && !el.getAttribute("data-propelo-seen") && required(el, labelOf(el)) && !el.checked && visible(el)) { out.needs.push({ label: labelOf(el) || "A required checkbox", why: "Tick it yourself if it's true." }); mark(el, "needs"); }
        if (type === "checkbox" && visible(el)) el.setAttribute("data-propelo-seen", "1");
        return;
      }
      if (!visible(el)) return;
      el.setAttribute("data-propelo-seen", "1");
      if (el.tagName === "INPUT" && isCombo(el) && type !== "radio") { combos.push(el); return; }
      var label = labelOf(el), hint = hints(el), key = matchKey(label, hint);
      // "Reasons for leaving your current role" asks for an answer, not your current role.
      if (key && key !== "__sensitive" && key !== "gapReason" && /\b(why|reasons?|explain|describe|tell us)\b/i.test(label)) key = "";
      if (key === "__sensitive") { out.skippedSensitive++; if (required(el, label)) { out.needs.push({ label: label || "A private field", why: "Propelo never fills this. Type it yourself if you choose to share it." }); mark(el, "needs"); } return; }

      if (type === "file") {
        var isResume = /resume|\bcv\b|curriculum/i.test(label + " " + hint) && !/cover/i.test(label + " " + hint);
        if (!isResume) { if (required(el, label)) { out.needs.push({ label: label || "A file upload", why: "Attach this yourself." }); mark(el, "needs"); } return; }
        if (el.files && el.files.length) { out.resume = "already attached"; return; }
        if (!data.resume || !data.resume.b64) { out.resume = "no resume in Propelo"; out.needs.push({ label: label || "Resume", why: "Upload your resume PDF in Propelo first, or attach it here." }); mark(el, "needs"); return; }
        try { var dt = new DataTransfer(); dt.items.add(b64ToFile(data.resume)); el.files = dt.files; el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); out.resume = "attached"; mark(el, "filled"); out.filled.push({ label: label || "Resume", value: data.resume.name || "resume.pdf" }); }
        catch (e) { out.resume = "couldn't attach"; out.needs.push({ label: label || "Resume", why: "This page wouldn't take the file. Attach it yourself." }); mark(el, "needs"); }
        return;
      }

      if (type === "radio") {
        if (seenRadio[el.name]) return; seenRadio[el.name] = 1;
        var group = Array.prototype.slice.call(rootOf(el).querySelectorAll('input[type=radio][name="' + (window.CSS ? CSS.escape(el.name) : el.name) + '"]'));
        group.forEach(function (r) { r.setAttribute("data-propelo-seen", "1"); });
        if (group.some(function (r) { return r.checked; })) return;
        var q = questionOf(el, group);
        var gkey = matchKey(q, el.name || "");
        var want = gkey && gkey !== "__sensitive" && CHOICE_KEYS[gkey] ? valueFor(gkey, a, q, el) : "";
        var opts = group.map(function (r) { return { el: r, text: labelOf(r) || r.value }; });
        var hit = want ? pickOption(opts, want) : null;
        if (hit) { hit.el.click(); mark(hit.el, "filled"); out.filled.push({ label: q, value: hit.text }); }
        else if (required(el, q) || group.some(function (r) { return r.required; })) { out.needs.push({ label: q || "A choice", why: "Pick the answer that's true for you." }); group.forEach(function (r) { mark(r, "needs"); }); }
        return;
      }

      var current = el.tagName === "SELECT" ? (el.selectedIndex > 0 ? el.value : "") : el.value;
      if (String(current || "").trim()) return; // never overwrite what's there
      var v = key ? valueFor(key, a, label, el) : "";
      if (key === "gender" || /gender|ethnic|race|veteran|disabilit|caste|religio/i.test(label)) v = ""; // voluntary questions stay with you
      if (el.tagName === "SELECT") {
        var o = v ? pickOption(Array.prototype.slice.call(el.options).map(function (x) { return { el: x, text: x.text || x.value }; }), v) : null;
        if (o) { setValue(el, o.el.value); mark(el, "filled"); out.filled.push({ label: label, value: o.text }); return; }
      } else if (v !== "" && v !== null && v !== undefined) {
        v = String(v);
        if (type === "number" && isNaN(parseFloat(v))) v = "";
        if (type === "email" && v.indexOf("@") < 0) v = "";
        if (type === "date" && !/^\d{4}-\d{2}-\d{2}$/.test(v)) v = "";
        if (v) { setValue(el, v); mark(el, "filled"); out.filled.push({ label: label || key, value: v }); return; }
      }
      var saved = (el.tagName === "TEXTAREA" || type === "text" || !type) && !key ? savedAnswer(label, data.answers, data.company) : null;
      if (saved) { setValue(el, saved.a); mark(el, "filled"); out.filled.push({ label: label, value: "From your saved answers" }); out.fromAnswers++; return; }
      if (required(el, label) || el.tagName === "TEXTAREA") {
        out.needs.push({ label: label || "A question", why: el.tagName === "TEXTAREA" ? "Write this in your own words, or draft it in Propelo under Writing & interviews > Form answer." : "Propelo doesn't have this. Fill it in yourself." });
        mark(el, "needs");
      }
    });
    // Dropdowns one at a time, since each opens a list of its own.
    return combos.slice(0, 30).reduce(function (p, el) { return p.then(function () { return fillCombo(el, data, out); }); }, Promise.resolve());
  }

  function blank() { return { host: location.hostname, filled: [], needs: [], skippedSensitive: 0, resume: "", blocked: false, fromAnswers: 0 }; }

  // Questions that appear after the first fill (a follow-up that shows once you answer, the next page of a
  // Workday form) are filled too, for up to 15 minutes. Still never overwrites, never submits.
  var watch = { obs: null, data: null, timer: 0, until: 0, rounds: 0, busy: false };
  function startWatch(data) {
    watch.data = data; watch.until = Date.now() + 15 * 60 * 1000; watch.rounds = 0;
    if (watch.obs || !window.MutationObserver || !document.body) return;
    watch.obs = new MutationObserver(function () {
      if (Date.now() > watch.until || watch.rounds >= 40) { watch.obs.disconnect(); watch.obs = null; return; }
      clearTimeout(watch.timer);
      watch.timer = setTimeout(refill, 700);
    });
    roots().forEach(function (r) { watch.obs.observe(r === document ? document.body : r, { childList: true, subtree: true }); });
  }
  function refill() {
    if (watch.busy || !watch.data) return;
    var fresh = deepAll("input:not([data-propelo-seen]), textarea:not([data-propelo-seen]), select:not([data-propelo-seen])")
      .some(function (el) { return el.type !== "hidden" && visible(el); });
    var freshCombo = deepAll(COMBO).some(function (el) { return !el.getAttribute("data-propelo-seen") && visible(el); });
    if (!fresh && !freshCombo) return;
    watch.busy = true; watch.rounds++;
    var out = blank();
    pass(watch.data, out, true).then(function () {
      watch.busy = false;
      if ((out.filled.length || out.needs.length) && typeof window.__propeloOnMore === "function") { try { window.__propeloOnMore(out); } catch (e) { /* the panel is gone */ } }
    }, function () { watch.busy = false; });
  }

  window.__propeloFill = function (data) {
    var out = blank();
    if (BLOCKED.test(location.hostname)) { out.blocked = true; return Promise.resolve(out); }
    data = data || {};
    var a = data.applicant || {};
    if (/prefer not/i.test(a.backlogs || "")) delete a.backlogs;
    // A fresh fill looks at every field again (a field you cleared can be filled again); never overwrites.
    deepAll("[data-propelo-seen]").forEach(function (el) { el.removeAttribute("data-propelo-seen"); });
    return pass(data, out, false).then(function () { if (data.watch !== false) startWatch(data); return out; });
  };
})();

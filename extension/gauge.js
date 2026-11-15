/* The match gauge: a big score that counts up while its ring fills, then the arithmetic behind it.
   Shared by the popup and the on-page panel (the app has its own copy in dashboard/app.html).
   Respects prefers-reduced-motion. Everything shown comes from the server's match result. */
(function (root) {
  "use strict";
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function tone(n) { return n == null ? "#8a8378" : n >= 75 ? "#1f9d55" : n >= 60 ? "#3859F9" : n >= 45 ? "#d68a00" : "#d0443a"; }
  var STATUS = { proven: "Proven with a number", mentioned: "In your experience", listed: "Only in your skills list", found: "In your resume", missing: "Not in your resume" };

  function html(m, opts) {
    opts = opts || {};
    var size = opts.size || 132, r = size / 2 - 9, c = 2 * Math.PI * r, s = m.score;
    var col = tone(s), off = s == null ? c : c * (1 - s / 100);
    var ring = '<svg class="pg-ring" width="' + size + '" height="' + size + '" viewBox="0 0 ' + size + ' ' + size + '" aria-hidden="true">' +
      '<circle cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r + '" fill="none" stroke="currentColor" stroke-opacity=".12" stroke-width="10"/>' +
      '<circle class="pg-arc" cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r + '" fill="none" stroke="' + col + '" stroke-width="10" stroke-linecap="round" ' +
      'stroke-dasharray="' + c.toFixed(1) + '" stroke-dashoffset="' + off.toFixed(1) + '" data-c="' + c.toFixed(1) + '" data-to="' + off.toFixed(1) + '" transform="rotate(-90 ' + size / 2 + ' ' + size / 2 + ')"/></svg>';
    var num = '<div class="pg-num"><b class="pg-val" data-to="' + (s == null ? "" : s) + '">' + (s == null ? "–" : s) + '</b><span>out of 100</span></div>';
    var head = '<div class="pg-head"><div class="pg-dial" style="width:' + size + 'px;height:' + size + 'px">' + ring + num + '</div>' +
      '<div class="pg-sum"><b style="color:' + col + '">' + esc(m.label || "Not enough to score") + '</b>' +
      (s == null ? '' : '<span>Could be ' + Math.max(0, s - m.margin) + ' to ' + Math.min(100, s + m.margin) + ' (± ' + m.margin + ')</span>') +
      (m.source ? '<span>Against ' + esc(m.source) + '</span>' : '') + '</div></div>';
    var rows = (m.parts || []).map(function (p, i) {
      var measured = p.points != null, w = measured ? Math.round(100 * p.points / p.max) : 0;
      return '<div class="pg-part' + (measured ? '' : ' off') + '"><div class="pg-pt"><span>' + esc(p.label) + '</span><b>' + (measured ? (Math.round(p.points * 10) / 10) + ' / ' + p.max : 'not measured') + '</b></div>' +
        '<div class="pg-bar"><i style="width:' + w + '%;background:' + col + ';transition-delay:' + (300 + i * 140) + 'ms" data-w="' + w + '"></i></div><small>' + esc(p.detail) + '</small></div>';
    }).join("");
    var math = '<div class="pg-math"><div class="pg-mt">How it\'s worked out</div>' + rows +
      (m.scaled ? '<small class="pg-note">Parts that couldn\'t be measured are left out, and the rest are scaled to 100.</small>' : '') + '</div>';
    var chips = (m.terms || []).slice(0, opts.chips || 14).map(function (t) {
      return '<span class="pg-chip ' + t.status + '" title="' + esc(STATUS[t.status] + (t.required ? "" : " · nice to have")) + '">' + esc(t.term) + (t.required ? '' : '<em>plus</em>') + '</span>';
    }).join("");
    var legend = '<div class="pg-legend"><span class="pg-chip proven">proven</span><span class="pg-chip mentioned">in experience</span><span class="pg-chip listed">skills list</span><span class="pg-chip missing">missing</span></div>';
    return '<div class="pg">' + head + math + (chips ? '<div class="pg-mt">Skills in this posting</div><div class="pg-chips">' + chips + '</div>' + legend : '') +
      '<small class="pg-note">' + esc(m.note || "") + '</small></div>';
  }

  // Count up and fill. Call once per new result; pass instant=true to skip the motion.
  function animate(el, instant) {
    if (!el) return;
    var reduce = instant || (root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches);
    var arc = el.querySelector(".pg-arc"), val = el.querySelector(".pg-val"), bars = el.querySelectorAll(".pg-bar i");
    var to = parseInt(val && val.getAttribute("data-to"), 10);
    if (reduce || isNaN(to)) return;
    var c = parseFloat(arc.getAttribute("data-c")), end = parseFloat(arc.getAttribute("data-to"));
    arc.style.transition = "none"; arc.setAttribute("stroke-dashoffset", String(c));
    Array.prototype.forEach.call(bars, function (b) { b.style.transition = "none"; b.style.width = "0%"; });
    val.textContent = "0";
    var t0 = null, dur = 1100;
    function frame(t) {
      if (t0 === null) t0 = t;
      var k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      val.textContent = String(Math.round(to * e));
      arc.setAttribute("stroke-dashoffset", (c - (c - end) * e).toFixed(1));
      if (k < 1) root.requestAnimationFrame(frame);
    }
    root.requestAnimationFrame(function () {
      root.requestAnimationFrame(frame);
      Array.prototype.forEach.call(bars, function (b) { b.style.transition = ""; b.style.width = b.getAttribute("data-w") + "%"; });
    });
  }

  var CSS = '.pg{display:grid;gap:12px}.pg-head{display:flex;align-items:center;gap:16px}.pg-dial{position:relative;flex:none}' +
    '.pg-num{position:absolute;inset:0;display:grid;place-content:center;text-align:center}.pg-num b{font-size:44px;line-height:1;font-weight:700;letter-spacing:-.04em;font-variant-numeric:tabular-nums}' +
    '.pg-num span{font-size:11px;opacity:.65;margin-top:3px}.pg-sum{display:grid;gap:3px}.pg-sum b{font-size:19px;letter-spacing:-.02em}.pg-sum span{font-size:12.5px;opacity:.75}' +
    '.pg-mt{font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;opacity:.7}.pg-math{display:grid;gap:9px}' +
    '.pg-pt{display:flex;justify-content:space-between;gap:8px;font-size:13px}.pg-pt b{font-variant-numeric:tabular-nums;font-weight:600}' +
    '.pg-bar{height:7px;border-radius:99px;background:rgba(127,127,127,.18);overflow:hidden;margin:4px 0 2px}.pg-bar i{display:block;height:100%;border-radius:inherit;transition:width .9s cubic-bezier(.2,.8,.2,1)}' +
    '.pg-part small,.pg-note{font-size:11.5px;opacity:.7;line-height:1.35}.pg-part.off{opacity:.6}' +
    '.pg-chips,.pg-legend{display:flex;flex-wrap:wrap;gap:5px}.pg-legend{opacity:.75}.pg-legend .pg-chip{font-size:10.5px;padding:1px 7px}' +
    '.pg-chip{font-size:12px;padding:2px 9px;border-radius:99px;border:1px solid transparent}.pg-chip em{font-style:normal;font-size:10px;opacity:.7;margin-left:4px}' +
    '.pg-chip.proven{background:rgba(31,157,85,.16)}.pg-chip.mentioned,.pg-chip.found{background:rgba(56,89,249,.13)}.pg-chip.listed{background:rgba(214,138,0,.15)}' +
    '.pg-chip.missing{border:1px dashed currentColor;opacity:.75}' +
    '@media (prefers-reduced-motion:reduce){.pg-bar i{transition:none}}';

  root.PropeloGauge = { html: html, animate: animate, css: CSS, tone: tone };
})(typeof window !== "undefined" ? window : this);

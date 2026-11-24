// node scripts/peeps/fit.js file.svg ... : crop each SVG's viewBox to its drawn content (+pad) and save a PNG preview
// Needs Playwright (npm i playwright).
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 800, height: 800 } });
  for (const f of process.argv.slice(2)) {
    const src = fs.readFileSync(f, 'utf8');
    await p.setContent(`<!doctype html><body style="margin:0;background:#FAF3E6">${src}</body>`);
    const bb = await p.evaluate(() => { const s = document.querySelector('svg'); const r = s.getBBox(); return [r.x, r.y, r.width, r.height]; });
    const pad = 6, vb = [bb[0] - pad, bb[1] - pad, bb[2] + 2 * pad, bb[3] + 2 * pad].map(v => Math.round(v));
    const out = src.replace(/viewBox="[^"]*"/, `viewBox="${vb.join(' ')}"`);
    fs.writeFileSync(f, out);
    await p.setContent(`<!doctype html><body style="margin:0;background:#FAF3E6">${out.replace('<svg ', '<svg style="height:600px;width:auto" ')}</body>`);
    const el = await p.$('svg'); await el.screenshot({ path: f.replace(/\.svg$/, '.png') });
    console.log(f.split('/').pop(), vb.join(' '), (out.length / 1024).toFixed(1) + 'KB');
  }
  await b.close();
})();

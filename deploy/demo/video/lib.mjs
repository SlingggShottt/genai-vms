// Screen recorder for the demo video: drives the real UI in headless Brave and captures it with the
// DevTools screencast (JPEG frames + timestamps), so quality is ours to choose at encode time
// (encode.py). Captions, a visible cursor and "sped up" badges are drawn inside the page, so they are
// part of the picture.
import { chromium } from 'playwright-core';
import fs from 'node:fs';
import path from 'node:path';

export const BRAVE = process.env.BRAVE ?? '/opt/brave.com/brave/brave';
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const now = () => Date.now() / 1000;

// Runs in every page (also after a full reload). Captions survive reloads through sessionStorage.
const OVERLAY = () => {
  const css = `
  #__cap{position:fixed;left:50%;bottom:34px;transform:translateX(-50%);max-width:1560px;z-index:2147483646;
    pointer-events:none;background:rgba(15,23,42,.90);color:#fff;border-radius:14px;padding:14px 26px;
    font:600 28px/1.25 system-ui,-apple-system,'Segoe UI',sans-serif;text-align:center;box-shadow:0 6px 24px rgba(0,0,0,.35);
    transition:opacity .25s;opacity:0}
  #__cap small{display:block;margin-top:4px;font:400 21px/1.3 system-ui,sans-serif;color:#cbd5e1}
  #__badge{position:fixed;top:18px;right:22px;z-index:2147483646;pointer-events:none;background:#b45309;color:#fff;
    border-radius:999px;padding:8px 18px;font:700 20px system-ui,sans-serif;display:none}
  #__cur{position:fixed;left:0;top:0;width:26px;height:26px;margin:-13px 0 0 -13px;border-radius:50%;z-index:2147483647;
    pointer-events:none;border:3px solid #2563eb;background:rgba(37,99,235,.25);display:none}
  .__rip{position:fixed;z-index:2147483647;pointer-events:none;width:26px;height:26px;margin:-13px 0 0 -13px;border-radius:50%;
    border:3px solid #2563eb;animation:__rip .55s ease-out forwards}
  @keyframes __rip{to{transform:scale(2.8);opacity:0}}
  #__slide{position:fixed;inset:0;z-index:2147483645;background:#f8fafc;display:none;flex-direction:column;align-items:center;
    justify-content:center;gap:16px;padding:24px 60px 130px;color:#0f172a;font-family:system-ui,sans-serif;text-align:center}
  #__slide h1{margin:0;font:800 46px/1.1 system-ui,sans-serif}
  #__slide p{margin:0;font:400 28px/1.4 system-ui,sans-serif;color:#334155;max-width:1400px}
  #__slide svg{width:1700px;height:auto;max-height:800px;background:#fff;border:1px solid #e2e8f0;border-radius:12px}
  #__slide .big{font:800 46px/1.2 system-ui,sans-serif}`;
  const make = () => {
    if (document.getElementById('__cap')) return;
    const st = document.createElement('style');
    st.textContent = css;
    document.documentElement.append(st);
    for (const id of ['__cap', '__badge', '__cur', '__slide']) {
      const d = document.createElement('div');
      d.id = id;
      document.documentElement.append(d);
    }
    const saved = sessionStorage.getItem('__cap');
    if (saved) window.__cap(...JSON.parse(saved));
    window.addEventListener(
      'mousemove',
      (e) => {
        const c = document.getElementById('__cur');
        c.style.display = 'block';
        c.style.left = e.clientX + 'px';
        c.style.top = e.clientY + 'px';
      },
      true,
    );
    window.addEventListener(
      'mousedown',
      (e) => {
        const r = document.createElement('div');
        r.className = '__rip';
        r.style.left = e.clientX + 'px';
        r.style.top = e.clientY + 'px';
        document.documentElement.append(r);
        setTimeout(() => r.remove(), 600);
      },
      true,
    );
  };
  window.__cap = (title, sub) => {
    const el = document.getElementById('__cap');
    if (!el) return;
    if (!title) {
      el.style.opacity = 0;
      sessionStorage.removeItem('__cap');
      return;
    }
    el.innerHTML = '';
    el.append(document.createTextNode(title));
    if (sub) {
      const s = document.createElement('small');
      s.textContent = sub;
      el.append(s);
    }
    el.style.opacity = 1;
    sessionStorage.setItem('__cap', JSON.stringify([title, sub ?? '']));
  };
  window.__badge = (text) => {
    const b = document.getElementById('__badge');
    b.textContent = text ?? '';
    b.style.display = text ? 'block' : 'none';
  };
  window.__slide = (html) => {
    const s = document.getElementById('__slide');
    s.innerHTML = html ?? '';
    s.style.display = html ? 'flex' : 'none';
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', make);
  else make();
};

export async function startRecording({ outDir, width = 1920, height = 1080, headless = true, storageState }) {
  fs.rmSync(outDir, { recursive: true, force: true });
  fs.mkdirSync(path.join(outDir, 'frames'), { recursive: true });
  const browser = await chromium.launch({
    executablePath: BRAVE,
    headless,
    args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required', '--force-device-scale-factor=1'],
  });
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1, ...(storageState ? { storageState } : {}) });
  await context.addInitScript(OVERLAY);
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);

  const tl = { width, height, frames: [], captions: [], speed: [], marks: [] };
  let n = 0;
  cdp.on('Page.screencastFrame', ({ data, metadata, sessionId }) => {
    const i = n++;
    fs.writeFileSync(path.join(outDir, 'frames', `${String(i).padStart(6, '0')}.jpg`), Buffer.from(data, 'base64'));
    tl.frames.push([i, metadata?.timestamp ?? now()]);
    cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => {});
  });
  await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 92, maxWidth: width, maxHeight: height, everyNthFrame: 1 });

  const save = () => fs.writeFileSync(path.join(outDir, 'timeline.json'), JSON.stringify(tl));
  const saver = setInterval(save, 15000);
  let pos = { x: width / 2, y: height / 2 };

  const rec = {
    page,
    context,
    tl,
    /** caption: big line + optional small line */
    async cap(title, sub = '') {
      tl.captions.push({ t: now(), title: title ?? '', sub });
      await page.evaluate(([t, s]) => window.__cap(t, s), [title, sub]);
    },
    async badge(text) {
      await page.evaluate((t) => window.__badge(t), text);
    },
    /** everything between speedStart and speedEnd is shown `factor` times faster in the final video */
    async speedStart(factor = 8, label) {
      tl.speed.push({ t0: now(), t1: null, factor });
      await rec.badge(label ?? `sped up ${factor}x`);
    },
    async speedEnd() {
      const s = tl.speed.at(-1);
      if (s && s.t1 === null) s.t1 = now();
      await rec.badge(null);
    },
    mark(name) {
      tl.marks.push({ t: now(), name });
    },
    async slide(html) {
      await page.evaluate((h) => window.__slide(h), html);
    },
    async hold(ms) {
      await sleep(ms);
    },
    async glide(x, y, ms = 650) {
      const n2 = Math.max(10, Math.round(ms / 16));
      const { x: x0, y: y0 } = pos;
      for (let i = 1; i <= n2; i++) {
        const k = i / n2;
        const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        await page.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e);
        await sleep(ms / n2);
      }
      pos = { x, y };
    },
    /** move the visible cursor to an element, then click it */
    async click(locator, { ms = 650, after = 450 } = {}) {
      const el = locator.first();
      await el.scrollIntoViewIfNeeded();
      const b = await el.boundingBox();
      await rec.glide(b.x + b.width / 2, b.y + b.height / 2, ms);
      await sleep(150);
      await el.click({ delay: 70 });
      await sleep(after);
    },
    async hover(locator, { ms = 650 } = {}) {
      const el = locator.first();
      await el.scrollIntoViewIfNeeded();
      const b = await el.boundingBox();
      await rec.glide(b.x + b.width / 2, b.y + b.height / 2, ms);
    },
    async type(locator, text, { delay = 55 } = {}) {
      await rec.click(locator, { after: 200 });
      await locator.first().pressSequentially(text, { delay });
    },
    /** smooth scroll of the page (or of an element) by dy pixels */
    async scroll(dy, { ms = 900, target = null } = {}) {
      const steps = Math.max(6, Math.round(ms / 30));
      for (let i = 0; i < steps; i++) {
        if (target) await target.evaluate((el, d) => el.scrollBy(0, d), dy / steps);
        else await page.mouse.wheel(0, dy / steps);
        await sleep(ms / steps);
      }
    },
    async finish() {
      clearInterval(saver);
      await cdp.send('Page.stopScreencast').catch(() => {});
      save();
      await browser.close();
    },
  };
  return rec;
}

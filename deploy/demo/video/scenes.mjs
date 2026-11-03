// The scenes of the demo video, in order. Each one gets a recorder `r` (lib.mjs) and the context `c`.
// Locators are the app's own labels, so they double as a check that the UI still reads the same.
import fs from 'node:fs';
import path from 'node:path';

const fig = (HERE, name) => fs.readFileSync(path.join(HERE, 'slides', `${name}.svg`), 'utf8');
const slide = (title, body = '', svg = '') => `<h1>${title}</h1>${body ? `<p>${body}</p>` : ''}${svg}`;
const pick = async (select, re) => {
  // choose an <option> by a regular expression on its text
  const value = await select.evaluate((el, src) => {
    const o = [...el.options].find((x) => new RegExp(src, 'i').test(x.textContent));
    return o?.value ?? null;
  }, re);
  if (value === null) throw new Error(`no option matching ${re}`);
  await select.selectOption(value);
};
/** scroll the page content: the wheel scrolls whatever is under the cursor, so park the cursor on it first */
const scrollContent = async (r, dy) => {
  await r.glide(760, 620, 450);
  await r.scroll(dy);
};
const nav = (r, href) => r.click(r.page.locator(`a[href="${href}"]`));

export const scenes = [
  {
    id: '00-intro',
    title: 'Title, the problem, the system on one page',
    run: async (r, c) => {
      await r.page.goto(`${c.BASE}/login`);
      await r.slide(
        `<div class="big" style="font-size:84px">GenAI-VMS</div><h1 style="font-size:44px;font-weight:600">Reasoning-based video analytics for CCTV</h1>` +
          `<p>Search what happened in plain words · understand incidents phase by phase · ask questions and get cited answers</p>` +
          `<p style="font-size:22px">Local-first: the whole pipeline runs on a laptop with a 4 GB GPU</p>`,
      );
      await r.hold(6500);
      await r.slide(slide('The problem', '', fig(c.HERE, 'problem')));
      await r.cap('Cameras record far more video than anyone can watch', 'Finding one moment means scrubbing hours of footage');
      await r.hold(9000);
      await r.slide(slide('The system on one page', '', fig(c.HERE, 'big_picture')));
      await r.cap('Record once, understand once, reuse everywhere', 'Cameras → 10-second segments → a "digital twin" of each → search, events, reasoning, reports');
      await r.hold(15000);
      await r.slide(slide('One clip, from camera to answer', '', fig(c.HERE, 'clip_journey')));
      await r.cap('Follow one 10-second clip through the pipeline', 'Now the real thing, running on this laptop');
      await r.hold(11000);
      await r.slide(null);
    },
  },
  {
    id: '01-live',
    title: 'Login and the live wall',
    login: true,
    run: async (r, c) => {
      const { page } = r;
      await page.goto(`${c.BASE}/login`);
      await r.cap('Sign in', 'Roles: admin, operator, viewer — checked by the API on every request');
      await r.type(page.getByLabel('Email'), c.env.VMS_ADMIN_EMAIL);
      await r.type(page.getByLabel('Password'), c.env.VMS_ADMIN_PASSWORD);
      await r.click(page.getByRole('button', { name: /sign in/i }));
      await page.waitForURL(`${c.BASE}/`);
      await r.cap('Live wall', 'Every camera live over WebRTC, with its online / offline status');
      await r.hold(7000);
      await r.click(page.getByRole('button', { name: '1 tile' }));
      await r.cap('One tile for a closer look', 'Layouts: 1, 4 or 6 tiles');
      await r.hold(4500);
      await r.click(page.getByRole('button', { name: '4 tiles' }));
      await r.cap('Alerts arrive here the moment they are created', 'Pushed over a WebSocket; acknowledge, resolve or open each one');
      await r.hover(page.getByRole('button', { name: 'Acknowledge' }).first());
      await r.hold(5500);
    },
  },

  {
    id: '02-playback',
    title: 'Playback with the digital twin drawn over the video',
    run: async (r, c) => {
      const { page } = r;
      await nav(r, '/playback');
      await r.cap('Playback', 'Pick a camera and a time range; the recording is served as video you can scrub');
      const cam = page.locator('#playback-camera');
      await r.hover(cam);
      await pick(cam, 'waiting room');
      const t0 = c.window.start.getTime() + 195_000;
      for (const [id, at] of [['#playback-start', t0], ['#playback-end', t0 + 240_000]]) {
        const el = page.locator(id);
        await r.hover(el, { ms: 450 });
        await el.fill(c.localInput(new Date(at)));
        await r.hold(300);
      }
      await r.click(page.getByRole('button', { name: 'Load' }));
      await page.waitForFunction(() => {
        const v = document.querySelector('video');
        return v && v.readyState >= 2;
      }, null, { timeout: 60000 });
      // the detection canvas sits over the player's own play button, so start it directly
      const vb = await page.locator('video').first().boundingBox();
      await r.glide(vb.x + 50, vb.y + vb.height - 56, 800);
      await page.locator('video').first().evaluate((v) => v.play());
      await page.waitForFunction(() => document.querySelector('video').currentTime > 1, null, { timeout: 30000 });
      await r.cap('The coloured boxes are the "digital twin"', 'What the AI found and is tracking: people, bags, vehicles — each with an id that follows it');
      await r.hold(10000);
      await r.click(page.getByRole('button', { name: /Detections on/ }));
      await r.cap('Detections can be switched off', 'The video itself is never altered');
      await r.hold(3500);
      await r.click(page.getByRole('button', { name: /Detections off/ }));
      await r.cap('Scrub anywhere on the timeline', 'The bar above it shows how much footage exists, minute by minute');
      const bar = page.getByRole('slider', { name: 'Playback timeline' });
      const b = await bar.boundingBox();
      await r.glide(b.x + b.width * 0.62, b.y + b.height / 2, 900);
      await page.mouse.click(b.x + b.width * 0.62, b.y + b.height / 2);
      await r.hold(6000);
      await r.cap('Find similar here', 'Pause on any frame to search all footage for things that look like something in it');
      await page.locator('video').first().evaluate((v) => v.pause());
      await r.hold(1200);
      await r.click(page.getByRole('button', { name: 'Find similar here' }));
      const dlg = page.getByRole('dialog');
      await dlg.waitFor();
      await r.cap('Draw a box around the person or object', 'The server cuts that region out of the stored frame and searches every recording with it');
      const img = dlg.locator('img, canvas').first();
      const ib = await img.boundingBox();
      const pt = (fx, fy) => [ib.x + ib.width * fx, ib.y + ib.height * fy];
      await r.glide(...pt(0.40, 0.58), 900);
      await page.mouse.down();
      for (let i = 1; i <= 14; i++) {
        const [x, y] = pt(0.40 + 0.20 * (i / 14), 0.58 + 0.30 * (i / 14));
        await page.mouse.move(x, y);
        await r.hold(45);
      }
      await page.mouse.up();
      await r.hold(900);
      await r.click(dlg.getByRole('button', { name: 'Find similar' }));
      await dlg.getByRole('img').nth(1).waitFor({ timeout: 40000 }).catch(() => {});
      await r.cap('Ranked matches across the recordings, with a similarity score', 'Picture similarity again, so this works even for things nobody ever labelled');
      await r.hold(9000);
      await page.keyboard.press('Escape');
    },
  },
  {
    id: '03-search',
    title: 'Search in plain words: fast, reason, image',
    llm: true,
    run: async (r, c) => {
      const { page } = r;
      const resultsReady = () =>
        page.locator('section[aria-label="Results"] article, section[aria-label="Results"] li').first().waitFor({ timeout: 120000 });
      await nav(r, '/search');
      await r.cap('Search footage in plain words', 'No camera, no time range needed — describe what you are looking for');
      await r.click(page.getByRole('button', { name: 'Fast', exact: true }));
      await r.type(page.getByLabel('Describe what to find'), 'a person carrying a suitcase');
      await r.hold(600);
      await r.click(page.getByRole('button', { name: 'Search', exact: true }));
      await resultsReady();
      await page.waitForTimeout(1500);
      await r.cap('Fast mode: about a quarter of a second', 'The sentence becomes a vector; frames and tracks with the closest meaning come back, merged into 10-second windows');
      await r.hold(9000);
      await r.click(page.getByRole('button', { name: 'Reason', exact: true }));
      await r.click(page.getByRole('button', { name: 'Search', exact: true }));
      await r.cap('Reason mode: a language model re-reads the best candidates', 'It understands the question, scores each candidate 0–1 and says what it could not confirm (about 10–15 s on this laptop)');
      await page.getByText(/ranked with reasoning/).waitFor({ timeout: 120000 });
      await page.waitForTimeout(1500);
      await r.hold(5500);
      await r.cap('"Why this result"', 'The model score, its reason, and the facts the records could not show — and the outline of the matched object');
      await r.hover(page.getByText('Why this result').first());
      await r.hold(9000);
      await scrollContent(r, 420);
      await r.hold(2500);
      await r.cap('Search by image', 'Upload a photo — or any frame — to find the same kind of thing in the footage');
      const still = path.join(c.HERE, 'out', 'search-still.png');
      await page.locator('section[aria-label="Results"] img').first().screenshot({ path: still });
      await page.locator('input[type="file"]').setInputFiles(still);
      await resultsReady();
      await page.waitForTimeout(1500);
      await r.hold(6500);
      await r.cap('Every result opens at that moment', 'One click from a search hit to the recording, the event or the incident report');
      await r.click(page.getByRole('link', { name: /Open in playback/ }).first());
      await page.waitForFunction(() => document.querySelector('video')?.readyState >= 2, null, { timeout: 60000 });
      await page.locator('video').first().evaluate((v) => v.play()).catch(() => {});
      await r.hold(7000);
    },
  },
  {
    id: '04-events',
    title: 'Events verified by the vision model',
    run: async (r, c) => {
      const { page } = r;
      await nav(r, '/events');
      await r.cap('Events: what the rules noticed and the vision model confirmed', 'Six cheap rules watch every segment; only their candidates reach the (slow) vision model');
      await r.hold(5500);
      const sev = page.locator('#events-severity');
      await r.hover(sev);
      await pick(sev, 'high');
      await r.cap('Filter by severity, camera, status or time', 'High severity: an abandoned bag and a possible intrusion');
      await r.hold(4500);
      await r.click(page.getByRole('link', { name: /Abandoned object on bus-g331/ }));
      await page.locator('video').first().waitFor();
      await page.waitForFunction(() => document.querySelector('video')?.readyState >= 2, null, { timeout: 60000 });
      await r.cap('One event: the clip, the keyframes and what the AI saw', 'A caption written by the vision model, with its confidence and the rule that fired');
      await page.locator('video').first().evaluate((v) => v.play()).catch(() => {});
      await r.hold(9000);
      await r.hover(page.getByText(/Verified by the vision model/));
      await r.cap('"Verified by the vision model"', 'If it had said "no", this event would have been kept but never shown to an operator');
      await r.hold(6000);
      await scrollContent(r, 500);
      await r.cap('Keyframes are the evidence the model looked at', 'Stored separately so they outlive the video retention');
      await r.hold(5000);
      const ack = page.locator('main').getByRole('button', { name: 'Acknowledge' }).first();
      if (!(await ack.count())) throw new Error('this event is already acknowledged - pick another one');
      await r.click(ack);
      await r.cap('Acknowledge, resolve or save it to a case', 'Every action is audited; two operators clicking at once — the database lets exactly one win');
      const dlg = page.getByRole('dialog');
      await r.type(dlg.getByRole('textbox'), 'Bag left on the bench — checked on camera, owner returned');
      await r.hold(700);
      await r.click(dlg.getByRole('button', { name: 'Acknowledge' }));
      await r.hold(4500);
    },
  },
  {
    id: '05-analyze',
    title: 'Click Analyse: phases, evidence, report (sped up)',
    llm: true,
    run: async (r, c) => {
      const { page } = r;
      await nav(r, '/events');
      await r.hold(1200);
      // a medium event nobody has analysed yet (ANALYZE_ROW picks which one: an analysed event offers "Analyse again")
      await r.click(page.locator('main a[href^="/events/"]').nth(Number(process.env.ANALYZE_ROW ?? 1)));
      await page.locator('video').first().waitFor();
      await r.cap('Why did this happen? Click "Analyse incident"', 'The reasoning service finds the five phases, reads each camera, and writes a cited report');
      await r.hold(3500);
      await r.click(page.getByRole('button', { name: 'Analyse incident' }));
      await r.speedStart(10, 'sped up 10x: the models are working (2–4 min on this laptop)');
      // the captions follow the job's own progress text
      const stages = [
        [/locating|queued|starting/i, 'Phase 1: where are the five phases in time?', 'A vision model is shown 5 frames and asked which stage each one is (baseline → precursor → escalation → action → aftermath)'],
        [/reading/i, 'Phase 2: read each stage, camera by camera', 'Two frames plus questions from a question bank; every answer becomes an evidence item with an id'],
        [/writ|report|final/i, 'Phase 3: write the report — every claim must cite evidence', 'Claims that cite nothing are dropped, not invented'],
      ];
      let shown = -1;
      const done = page.locator('main a[href^="/incidents/"]').filter({ hasNotText: /^Analysing/ });
      for (let waited = 0; waited < 600000 && !(await done.count()); waited += 1500) {
        const txt = await page.getByRole('status').first().innerText().catch(() => '');
        const k = stages.findIndex(([re]) => re.test(txt));
        if (k > shown) {
          shown = k;
          await r.cap(stages[k][1], stages[k][2]);
        }
        await page.waitForTimeout(1500);
      }
      await r.speedEnd();
      await r.cap('The report is ready', 'Summary here; the full report has the phase timeline, the evidence frames and a PDF');
      await r.hold(6000);
    },
  },
  {
    id: '06-incident',
    title: 'Incidents: the written report with citations',
    run: async (r, c) => {
      const { page } = r;
      await nav(r, '/incidents');
      await r.cap('Incidents: reports written from the footage', 'What happened, which phases, and why — each with a severity and a confidence');
      await r.hold(5500);
      await r.click(page.locator('a[href^="/incidents/"]').first());
      await page.getByRole('heading', { name: 'Phases' }).waitFor({ timeout: 30000 });
      await r.cap('The phase timeline', 'Baseline, action, aftermath… each phase is a clickable span of the recording');
      await r.hold(6500);
      await r.click(page.getByRole('button', { name: 'Play' }).first());
      await r.cap('Play any phase', 'The player jumps to that stretch of the footage');
      await r.hold(7000);
      await scrollContent(r, 520);
      await r.cap('Every sentence cites evidence', 'The small chips (ev-cap-01, ev-fr-02…) point at the exact frame or answer the claim came from');
      await r.hold(5500);
      const chip = page.getByRole('button', { name: /^Evidence ev-/ }).first();
      await r.click(chip);
      await r.hold(5500);
      await scrollContent(r, 700);
      await r.cap('"What this report cannot tell"', 'The report states its own limits and records which model wrote it, and how long each step took');
      await r.hold(6500);
      await r.hover(page.getByRole('button', { name: /Download PDF/ }));
      await r.cap('Download a PDF', 'Stored with the report, with the same citations');
      await r.hold(4000);
    },
  },
  {
    id: '07-assistant',
    title: 'Assistant: ask in chat, get cited answers',
    llm: true,
    run: async (r, c) => {
      const { page } = r;
      await nav(r, '/assistant');
      // visual only: the sessions list is full of empty "New conversation" entries from testing
      await page.evaluate(() => {
        for (const li of document.querySelectorAll('[aria-label="Conversations"] li')) {
          if (li.textContent.trim() === 'New conversation') li.style.display = 'none';
        }
      });
      await r.cap('Assistant: ask about your cameras in chat', 'It can only call seven fixed, parameterised lookups — it never writes database queries');
      await r.hold(5000);
      const box = page.getByLabel('Ask a question');
      const wait = async (sub) => {
        await r.cap(sub[0], sub[1]);
        await page.getByRole('button', { name: 'Stop' }).waitFor({ timeout: 20000 }).catch(() => {});
        await page.getByRole('button', { name: 'Stop' }).waitFor({ state: 'detached', timeout: 180000 });
        await r.hold(8000);
      };
      const ask = async (q, sub) => {
        await r.type(box, q);
        await r.hold(500);
        await r.click(page.getByRole('button', { name: 'Send' }));
        await wait(sub);
      };
      await r.click(page.getByRole('button', { name: 'Were there any crowding events today?' }));
      await wait(['Question 1: one of the suggested questions', 'A keyword router picks the tool; the answer starts with what the tool returned, then a short explanation']);
      await ask('How many people were on bus-g331 at the busiest time today?', ['Question 2: a count', 'Counts come from a fixed, pre-written query — the language model never does arithmetic on the footage']);
      await r.hover(page.getByLabel('What the assistant looked up').last());
      await r.cap('Every answer shows what it looked up', 'And the citation chips are real records — click one to open the event or the footage');
      await r.hold(6500);
      await ask("Summarise today's incident reports", ['Question 3: summarise the incident reports', 'It reads the stored reports — it does not re-analyse the video']);
    },
  },
  {
    id: '08-timeline',
    title: 'Timeline: lanes per camera, synced playback',
    run: async (r, c) => {
      const { page } = r;
      await nav(r, '/timeline');
      await r.cap('Timeline: one lane per camera', 'Events (bars) and incident reports (thin bars) across all cameras over a chosen period');
      await r.hold(5500);
      const lane = page.getByRole('group', { name: /Timeline of bus-g331/ });
      const drag = async (f0, f1) => {
        const lb = await lane.boundingBox();
        await r.glide(lb.x + lb.width * f0, lb.y + lb.height * 0.75, 800);
        await page.mouse.down();
        for (let i = 1; i <= 16; i++) {
          await page.mouse.move(lb.x + lb.width * (f0 + (f1 - f0) * (i / 16)), lb.y + lb.height * 0.75);
          await r.hold(45);
        }
        await page.mouse.up();
      };
      // the day's events sit together at the right: drag over them and zoom in
      await r.cap('Drag across a lane to pick a period', 'Then zoom to it, open the recording, search inside it, save it to a case — or play the cameras together');
      await drag(0.862, 0.93);
      await r.hold(2500);
      await r.click(page.getByRole('button', { name: 'Zoom to selection' }));
      await r.cap('Zoom in: every event is a bar you can press', 'Severity, type, time — and links to the event, the footage or the incident report');
      await r.hold(3000);
      const marker = page.locator('button[aria-label*=" event at "]').nth(1);
      const mb = await marker.boundingBox();
      await r.glide(mb.x + mb.width / 2, mb.y + mb.height / 2, 800);
      await page.mouse.click(mb.x + mb.width / 2, mb.y + mb.height / 2);
      await r.hold(6500);
      await r.cap('Select a period on one lane…', 'Then open its recording, search inside it, save it to a case, or play the cameras together');
      await drag(0.26, 0.50);
      await r.hold(3500);
      const together = page.getByRole('button', { name: /Play \d cameras together/ });
      await r.click(together);
      await page.waitForFunction(() => [...document.querySelectorAll('video')].some((v) => v.readyState >= 2), null, { timeout: 60000 });
      await r.cap('…the same moment on every camera, played in sync', 'One playhead drives all the videos; measured drift stays well under 300 ms');
      await page.waitForTimeout(1500);
      await scrollContent(r, 280);
      await r.hold(13000);
    },
  },
  {
    id: '10-reports',
    title: 'Daily security report',
    llm: true,
    run: async (r, c) => {
      const { page } = r;
      await nav(r, '/reports');
      await r.cap('Daily security reports', 'Facts from fixed queries; a language model writes the narrative; every number in it is checked against the facts');
      await r.hold(5000);
      await r.click(page.getByRole('button', { name: 'Generate report' }));
      await r.cap('Generate one for today', 'It is also written automatically every morning for the previous day');
      const today = c.localInput(new Date()).slice(0, 10);
      const dlg = page.getByRole('dialog');
      for (const id of ['#report-from', '#report-to']) {
        await r.hover(dlg.locator(id), { ms: 450 });
        await dlg.locator(id).fill(today);
        await r.hold(300);
      }
      await r.click(dlg.getByRole('button', { name: 'Generate report' }));
      await r.speedStart(4, 'sped up 4x: the narrative is being written');
      const ready = page.locator('main a[href^="/reports/"]').filter({ hasText: /Ready/ }).first();
      await ready.waitFor({ timeout: 300000 });
      await r.speedEnd();
      await r.hold(2500);
      await r.click(page.locator('main a[href^="/reports/"]').first());
      await page.getByRole('heading', { name: /Daily security report/ }).waitFor({ timeout: 60000 });
      await r.cap('The report: narrative, then the figures it was checked against', 'Verified events, high-severity, incident reports, alerts');
      await r.hold(8000);
      await scrollContent(r, 600);
      await r.cap('Events by hour, by type, camera and severity', 'Response times of the operators, and how many events were linked across cameras');
      await r.hold(7000);
      await scrollContent(r, 700);
      await r.hold(5000);
      await r.hover(page.getByRole('button', { name: /Download PDF/ }));
      await r.cap('Exported as a PDF', 'The same page, ready to print or send');
      await r.hold(4000);
    },
  },
  {
    id: '09-cases',
    title: 'Cases: collect evidence into an investigation',
    run: async (r, c) => {
      const { page } = r;
      await nav(r, '/cases');
      await r.cap('Cases', 'Bookmark events, incident reports, footage moments and searches into one investigation');
      await r.hold(3500);
      await r.click(page.locator('a[href^="/cases/"]').first());
      await r.cap('A case holds the evidence and the notes', 'Each item links back to the footage, event or report it came from');
      await r.hold(7000);
    },
  },
  {
    id: '11-settings',
    title: 'Settings: cameras, zones, camera links',
    run: async (r, c) => {
      const { page } = r;
      await r.click(page.locator('a[href="/settings"]'));
      await r.cap('Settings (admin only)', 'Cameras can be added, edited, enabled or disabled without restarting anything');
      await r.hold(6500);
      await r.click(page.getByRole('link', { name: 'Zones' }));
      await pick(page.locator('#zones-camera'), 'waiting room');
      await r.hold(1500);
      await r.cap('Zones: polygons drawn on a camera frame', 'The rules use them — "restricted area", "waiting room", "staff doorway"');
      await r.hold(6500);
      await r.click(page.getByRole('link', { name: 'Camera links' }));
      await r.cap('Camera links: the map that lets events join across cameras', 'Overlap = two views of one area; transit = walking from one camera to the next (5–90 s here)');
      await r.hold(9000);
    },
  },
  {
    id: '12-observability',
    title: 'Grafana dashboard (optional: only when the scrape targets are healthy)',
    optional: true,
    run: async (r, c) => {
      const { page } = r;
      await page.goto('http://127.0.0.1:3000/login');
      await r.cap('Observability', 'Prometheus metrics and a Grafana dashboard: lag, latency, GPU memory, alerts');
      await r.type(page.locator('input[name="user"]'), 'admin');
      await r.type(page.locator('input[name="password"]'), c.env.GRAFANA_ADMIN_PASSWORD ?? 'admin');
      await page.keyboard.press('Enter');
      const skip = page.getByText('Skip', { exact: true });
      if (await skip.waitFor({ timeout: 6000 }).then(() => true, () => false)) await r.click(skip);
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 15000 });
      await page.goto('http://127.0.0.1:3000/dashboards');
      await r.hold(2500);
      await r.click(page.locator('a[href^="/dashboards/f/"]').first());
      await r.click(page.locator('a[href^="/d/"]').first());
      await page.waitForTimeout(6000);
      await r.hold(5000);
    },
  },
  {
    id: '13-outro',
    title: 'What we measured, honest limits, close',
    run: async (r, c) => {
      const { page } = r;
      await page.goto(`${c.BASE}/login`);
      await r.slide(slide('Speed on a 4 GB laptop GPU', '', fig(c.HERE, 'latency_chart')));
      await r.cap('Fast search 0.22 s · reason search about 15 s · perception uses 966 MB of GPU memory', 'Measured on this laptop (RTX 3050 4 GB, local models)');
      await r.hold(11000);
      await r.slide(slide('Does search find the right clip?', '', fig(c.HERE, 'retrieval_chart')));
      await r.cap('36 plain-language queries on real MEVA footage', 'Top-10 hit rate: random 24 %, fast mode 56 %, reason mode 67 %');
      await r.hold(11000);
      await r.slide(
        slide(
          'What we are honest about',
          '',
          `<ul style="text-align:left;font:400 30px/1.55 system-ui,sans-serif;max-width:1300px;margin:0"><li>The fine-tuned phase model learned the format, <b>not yet</b> the understanding: its gain is only on labels made by a rule.</li>` +
            `<li>Cloud-VM and Kubernetes deployments are written and validated, <b>never run</b> on real infrastructure.</li>` +
            `<li>The clean retrieval ablation and the usability study are not done.</li>` +
            `<li>Cross-camera linking uses time and the camera map — it does not recognise people.</li></ul>`,
        ),
      );
      await r.cap('Every number here was measured; every claim in a report cites evidence', 'Evidence, or it did not happen');
      await r.hold(13000);
      await r.slide(
        `<div class="big" style="font-size:72px">GenAI-VMS</div><p>Search · understand · explain · ask — on a laptop</p><p style="font-size:22px">Thank you</p>`,
      );
      await r.cap('');
      await r.hold(5000);
    },
  },
];

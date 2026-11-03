// Records the demo video scene by scene (each scene = its own recording, so one that goes wrong is
// re-recorded alone), then `assemble.py` joins them.
//
//   node record.mjs                  # every scene, in order
//   node record.mjs 03-search 05-assistant
//   node record.mjs --list
//
// Needs the stack up (deploy/demo/start.sh) and fresh footage (make demo-refresh) - see README.md.
import { execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';
import { BRAVE, startRecording } from './lib.mjs';
import { scenes } from './scenes.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../../..');
const OUT = path.join(HERE, 'out');
const BASE = process.env.VMS_DEMO_URL ?? 'http://127.0.0.1:5173';

function readEnv() {
  const wanted = ['VMS_ADMIN_EMAIL', 'VMS_ADMIN_PASSWORD', 'GRAFANA_ADMIN_PASSWORD'];
  const env = {};
  for (const line of fs.readFileSync(path.join(ROOT, '.env'), 'utf8').split('\n')) {
    const k = line.split('=')[0];
    if (wanted.includes(k)) env[k] = line.slice(line.indexOf('=') + 1).replace(/^["']|["']$/g, '');
  }
  return env;
}

if (process.argv.includes('--list')) {
  for (const s of scenes) console.log(s.id, '-', s.title);
  process.exit(0);
}
const wanted = process.argv.slice(2).filter((a) => !a.startsWith('--'));
const todo = wanted.length ? scenes.filter((s) => wanted.some((w) => s.id.startsWith(w))) : scenes.filter((s) => !s.optional);
const env = readEnv();
fs.mkdirSync(OUT, { recursive: true });

// A logged-in session for every scene except the one that shows the login itself. The refresh
// cookie is single-use, so each scene gets its own fresh login (not recorded).
const authFile = path.join(OUT, 'auth.json');
async function freshLogin() {
  const b = await chromium.launch({ executablePath: BRAVE, headless: true, args: ['--no-sandbox'] });
  const c = await b.newContext();
  const p = await c.newPage();
  await p.goto(`${BASE}/login`);
  await p.getByLabel('Email').fill(env.VMS_ADMIN_EMAIL);
  await p.getByLabel('Password').fill(env.VMS_ADMIN_PASSWORD);
  await p.getByRole('button', { name: /sign in/i }).click();
  await p.waitForURL(`${BASE}/`);
  await c.storageState({ path: authFile });
  await b.close();
}

// The newest stretch of recorded footage that has a digital twin (what the last `make demo-refresh`
// produced), as Date objects: playback and search are pointed at it.
function recordingWindow() {
  const sql = "select min(start_ts), max(end_ts) from media.segments where camera_id='bus-g331' and start_ts > now() - interval '12 hours'";
  const out = execSync(`sg docker -c "docker exec vms-postgres psql -U vms -d vms -tAc \\"${sql}\\""`).toString().trim();
  const [a, b] = out.split('|');
  if (!a || !b) throw new Error('no recent footage with a digital twin - run make demo-refresh first');
  return { start: new Date(a.replace(' ', 'T').replace(/\+00$/, 'Z')), end: new Date(b.replace(' ', 'T').replace(/\+00$/, 'Z')) };
}
/** "YYYY-MM-DDTHH:mm" in the browser's (= this machine's) local time, as <input type=datetime-local> wants */
const localInput = (d) => {
  const z = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}T${z(d.getHours())}:${z(d.getMinutes())}`;
};

const ctx = { BASE, ROOT, env, HERE, localInput, window: recordingWindow() };
console.log(`footage window: ${ctx.window.start.toISOString()} .. ${ctx.window.end.toISOString()}`);
for (const scene of todo) {
  const outDir = path.join(OUT, scene.id);
  console.log(`\n== ${scene.id}: ${scene.title}`);
  if (scene.llm) {
    // answers cached by the gateway would make a model step look instant: clear them so the video shows real latency
    execSync(`sg docker -c "docker exec vms-redis sh -c \\"redis-cli --scan --pattern 'vms:llm:cache:*' | xargs -r redis-cli del >/dev/null\\""`);
  }
  if (!scene.login) await freshLogin();
  const r = await startRecording({ outDir, storageState: scene.login ? undefined : authFile });
  const t0 = Date.now();
  try {
    if (!scene.login) {
      await r.page.goto(`${BASE}/`);
      await r.page.locator('a[href="/playback"]').waitFor({ timeout: 15000 });
    }
    await scene.run(r, ctx);
    await r.cap('');
    await r.hold(900);
    console.log(`   ok (${((Date.now() - t0) / 1000).toFixed(0)} s)`);
  } catch (e) {
    console.error(`   FAILED: ${e.message.split('\n')[0]}`);
    fs.writeFileSync(path.join(outDir, 'error.txt'), String(e.stack ?? e));
    await r.page.screenshot({ path: path.join(outDir, 'error.png') }).catch(() => {});
  } finally {
    await r.finish();
  }
}

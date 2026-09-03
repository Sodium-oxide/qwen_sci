import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const ROOT = path.resolve(".");
const OUT = path.join(ROOT, "WebApp-V2", "demo", "screenshots");
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const DEBUG_PORT = 9446;
const HOST = `http://127.0.0.1:${DEBUG_PORT}`;
const WEB = "http://127.0.0.1:8090/WebApp-V2/app/index.html";
const PROFILE = path.join(ROOT, "WebApp-V2", "demo", `.chrome-profile-${Date.now()}`);
let seq = 1;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForJson(url, timeoutMs = 10000, init = {}) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const response = await fetch(url, init);
      if (response.ok) return await response.json();
    } catch {}
    await sleep(250);
  }
  throw new Error(`Timed out waiting for ${url}`);
}

class Cdp {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.nextId = 1;
    this.pending = new Map();
  }
  async open() {
    await new Promise((resolve, reject) => {
      this.ws.addEventListener("open", resolve, { once: true });
      this.ws.addEventListener("error", reject, { once: true });
    });
    this.ws.addEventListener("message", (event) => {
      const msg = JSON.parse(event.data);
      if (!msg.id || !this.pending.has(msg.id)) return;
      const { resolve, reject } = this.pending.get(msg.id);
      this.pending.delete(msg.id);
      if (msg.error) reject(new Error(JSON.stringify(msg.error)));
      else resolve(msg.result);
    });
  }
  send(method, params = {}) {
    const id = this.nextId++;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }
  close() {
    this.ws.close();
  }
}

async function page(width, height) {
  const target = await waitForJson(`${HOST}/json/new?about:blank`, 10000, { method: "PUT" });
  const cdp = new Cdp(target.webSocketDebuggerUrl);
  await cdp.open();
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: width < 700,
  });
  return cdp;
}

async function evaluate(cdp, expression) {
  return cdp.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
}

async function shot(cdp, name) {
  await sleep(450);
  const data = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const filename = `${String(seq++).padStart(2, "0")}-${name}.png`;
  await fs.writeFile(path.join(OUT, filename), Buffer.from(data.data, "base64"));
}

async function run() {
  await fs.mkdir(OUT, { recursive: true });
  const chrome = spawn(CHROME, [
    "--headless=new",
    `--remote-debugging-port=${DEBUG_PORT}`,
    "--disable-gpu",
    "--hide-scrollbars",
    "--window-size=1920,1080",
    `--user-data-dir=${PROFILE}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: ["ignore", "ignore", "pipe"] });

  chrome.stderr.on("data", (chunk) => {
    const text = String(chunk);
    if (text.includes("DevTools") || text.includes("ERROR")) process.stderr.write(text);
  });

  try {
    await waitForJson(`${HOST}/json/version`);
    const cdp = await page(1920, 1080);
    await cdp.send("Page.navigate", { url: WEB });
    await sleep(1800);
    await shot(cdp, "v2-hero-console");

    await evaluate(cdp, "document.querySelector('#launcher').scrollIntoView({block:'start'})");
    await shot(cdp, "v2-launcher");
    await evaluate(cdp, "document.querySelector('#previewCreate').click()");
    await sleep(900);
    await shot(cdp, "v2-command-preview");

    await evaluate(cdp, "document.querySelector('#searchInput').value='astr'; document.querySelector('#searchInput').dispatchEvent(new Event('input'))");
    await shot(cdp, "v2-session-search");
    await evaluate(cdp, "[...document.querySelectorAll('.session-card')].find(x => x.textContent.includes('astr_16'))?.click()");
    await sleep(600);
    await shot(cdp, "v2-astr16-selected");

    await evaluate(cdp, "document.querySelector('#workflow').scrollIntoView({block:'start'})");
    await shot(cdp, "v2-workflow-map");
    await evaluate(cdp, "document.querySelector('#quant').scrollIntoView({block:'start'})");
    await shot(cdp, "v2-quant-governance");
    await evaluate(cdp, "document.querySelector('#simulateBtn').click()");
    await sleep(700);
    await shot(cdp, "v2-execution-guard");

    await evaluate(cdp, "document.querySelector('#artifacts').scrollIntoView({block:'start'}); document.querySelector('#artifactFilter').value='PDF'; document.querySelector('#artifactFilter').dispatchEvent(new Event('change'))");
    await shot(cdp, "v2-pdf-filter");
    await evaluate(cdp, "document.querySelector('.artifact-item button')?.click()");
    await sleep(1400);
    await shot(cdp, "v2-pdf-preview");
    await evaluate(cdp, "document.querySelector('#artifactFilter').value='Quantitative'; document.querySelector('#artifactFilter').dispatchEvent(new Event('change'))");
    await shot(cdp, "v2-quant-artifacts");
    cdp.close();

    const mobile = await page(390, 844);
    await mobile.send("Page.navigate", { url: WEB });
    await sleep(1600);
    await shot(mobile, "v2-mobile-hero");
    await evaluate(mobile, "document.querySelector('#launcher').scrollIntoView({block:'start'})");
    await shot(mobile, "v2-mobile-launcher");
    await evaluate(mobile, "document.querySelector('#quant').scrollIntoView({block:'start'})");
    await shot(mobile, "v2-mobile-quant");
    mobile.close();
  } finally {
    chrome.kill();
    await fs.rm(PROFILE, { recursive: true, force: true }).catch(() => {});
  }
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});

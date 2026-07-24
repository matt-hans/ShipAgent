import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync } from 'node:fs';
import {
  mkdtemp,
  readFile,
  readdir,
  rm,
} from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(scriptDirectory, '..');
const repositoryRoot = path.resolve(frontendRoot, '..');
const distRoot = path.join(frontendRoot, 'dist', 'apps');
const sessionCookieName = 'shipagent_browser_session';

function run(command, args, cwd) {
  const result = spawnSync(command, args, {
    cwd,
    env: process.env,
    encoding: 'utf8',
    stdio: 'inherit',
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${command} exited with status ${result.status}`);
  }
}

function findPython() {
  if (process.env.SHIPAGENT_PYTHON) return process.env.SHIPAGENT_PYTHON;

  const candidates = [
    path.join(repositoryRoot, '.venv', 'bin', 'python'),
    path.resolve(repositoryRoot, '..', '..', '.venv', 'bin', 'python'),
  ];
  return candidates.find((candidate) => existsSync(candidate)) ?? 'python3';
}

function waitForBackendPort(backend) {
  return new Promise((resolve, reject) => {
    let stdoutBuffer = '';
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(new Error('Timed out waiting for the ShipAgent backend port'));
    }, 45_000);

    const finish = (callback) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      callback();
    };

    backend.stdout.on('data', (chunk) => {
      const text = chunk.toString();
      process.stdout.write(text);
      stdoutBuffer += text;
      const match = stdoutBuffer.match(/SHIPAGENT_PORT=(\d+)/);
      if (match) {
        finish(() => resolve(Number(match[1])));
      } else if (stdoutBuffer.length > 16_384) {
        stdoutBuffer = stdoutBuffer.slice(-8_192);
      }
    });
    backend.stderr.on('data', (chunk) => process.stderr.write(chunk));
    backend.once('error', (error) => finish(() => reject(error)));
    backend.once('exit', (code) => {
      finish(() => reject(
        new Error(`ShipAgent backend exited before startup with status ${code}`),
      ));
    });
  });
}

async function stopBackend(backend) {
  if (!backend || backend.exitCode !== null) return;
  const exited = new Promise((resolve) => backend.once('exit', resolve));
  backend.kill('SIGTERM');
  const stopped = await Promise.race([
    exited.then(() => true),
    new Promise((resolve) => setTimeout(() => resolve(false), 5_000)),
  ]);
  if (!stopped && backend.exitCode === null) {
    backend.kill('SIGKILL');
    await exited;
  }
}

async function launchBrowser() {
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  if (executablePath) {
    return chromium.launch({ executablePath, headless: true });
  }

  const channel = process.env.SHIPAGENT_BROWSER_CHANNEL ?? 'chrome';
  try {
    return await chromium.launch({ channel, headless: true });
  } catch (channelError) {
    try {
      return await chromium.launch({ headless: true });
    } catch (bundledError) {
      throw new AggregateError(
        [channelError, bundledError],
        'No Playwright-compatible Chrome or Chromium installation was found',
      );
    }
  }
}

async function emittedFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...await emittedFiles(entryPath));
    } else if (entry.isFile()) {
      files.push(entryPath);
    }
  }
  return files;
}

async function assertKeyAbsentFromBundles(runtimeKey) {
  const needle = Buffer.from(runtimeKey);
  for (const file of await emittedFiles(distRoot)) {
    const content = await readFile(file);
    assert.equal(
      content.includes(needle),
      false,
      `Runtime API key was found in emitted asset ${path.relative(frontendRoot, file)}`,
    );
  }
}

function waitForSettings(page) {
  return page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === '/api/v1/settings'
      && response.request().method() === 'GET'
      && response.status() === 200
    );
  });
}

if (process.env.SHIPAGENT_SMOKE_SKIP_BUILD !== '1') {
  run(
    'npx',
    [
      'nx',
      'run-many',
      '-t',
      'build',
      '--all',
      '--configuration=production',
    ],
    frontendRoot,
  );
  run('sh', ['./scripts/link-remotes.sh'], frontendRoot);
}

const runtimeKey = randomBytes(48).toString('base64url');
const filterTokenSecret = randomBytes(48).toString('base64url');
const temporaryDirectory = await mkdtemp(
  path.join(tmpdir(), 'shipagent-auth-smoke-'),
);
const databasePath = path.join(temporaryDirectory, 'shipagent.db');
const labelsPath = path.join(temporaryDirectory, 'labels');
const python = findPython();

let backend;
let browser;
let context;

try {
  backend = spawn(
    python,
    [
      '-m',
      'src.bundle_entry',
      'serve',
      '--host',
      '127.0.0.1',
      '--port',
      '0',
    ],
    {
      cwd: repositoryRoot,
      env: {
        ...process.env,
        AGENT_AUDIT_ENABLED: 'false',
        DATABASE_URL: `sqlite:///${databasePath}`,
        FILTER_TOKEN_SECRET: filterTokenSecret,
        SHIPAGENT_API_KEY: runtimeKey,
        SHIPAGENT_DISABLE_DOCS: 'true',
        SHIPAGENT_KEYRING_DISABLED: '1',
        SHIPAGENT_SKIP_SDK_CHECK: 'true',
        UPS_LABELS_OUTPUT_DIR: labelsPath,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    },
  );
  const port = await waitForBackendPort(backend);
  const baseUrl = `http://127.0.0.1:${port}`;

  browser = await launchBrowser();
  context = await browser.newContext();
  const page = await context.newPage();
  const browserErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push(message.text());
  });
  page.on('pageerror', (error) => browserErrors.push(error.message));

  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
  await page.getByLabel('Docker API key').waitFor({ state: 'visible' });
  assert.equal(
    await page.locator('body').evaluate((body) => body.innerText.trim().length > 0),
    true,
  );

  const firstSettings = waitForSettings(page);
  await page.getByLabel('Docker API key').fill(runtimeKey);
  await page.getByRole('button', { name: 'Unlock ShipAgent' }).click();
  const firstSettingsResponse = await firstSettings;
  console.log(`authenticated settings request: ${firstSettingsResponse.status()}`);

  const firstCookie = (await context.cookies()).find(
    (cookie) => cookie.name === sessionCookieName,
  );
  assert.ok(firstCookie, 'Browser session cookie was not created');
  assert.equal(firstCookie.httpOnly, true);
  assert.equal(firstCookie.sameSite, 'Strict');
  assert.equal(firstCookie.value.includes(runtimeKey), false);

  const onboarding = await page.request.post(
    `${baseUrl}/api/v1/settings/onboarding/complete`,
  );
  assert.equal(onboarding.status(), 200);
  const reloadSettings = waitForSettings(page);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await reloadSettings;
  await page.getByRole('button', { name: 'Clear API session' }).click();
  await page.getByLabel('Docker API key').waitFor({ state: 'visible' });
  assert.equal(
    (await context.cookies()).some(
      (cookie) => cookie.name === sessionCookieName,
    ),
    false,
  );
  console.log('session cleared and gate restored');

  const retrySettings = waitForSettings(page);
  await page.getByLabel('Docker API key').fill(runtimeKey);
  await page.getByRole('button', { name: 'Unlock ShipAgent' }).click();
  const retrySettingsResponse = await retrySettings;
  console.log(
    `authenticated retry settings request: ${retrySettingsResponse.status()}`,
  );

  const persistedKey = await page.evaluate((candidate) => {
    const localValues = Object.values(localStorage);
    const sessionValues = Object.values(sessionStorage);
    return [...localValues, ...sessionValues].some(
      (value) => String(value).includes(candidate),
    );
  }, runtimeKey);
  assert.equal(persistedKey, false, 'Runtime API key was persisted in browser storage');
  assert.equal(
    await page.locator(
      '[data-nextjs-dialog], .vite-error-overlay, #webpack-dev-server-client-overlay',
    ).count(),
    0,
  );
  assert.deepEqual(browserErrors, []);

  await assertKeyAbsentFromBundles(runtimeKey);
  console.log('runtime API key absent from production bundles');
} finally {
  if (context) await context.close();
  if (browser) await browser.close();
  await stopBackend(backend);
  await rm(temporaryDirectory, { recursive: true, force: true });
}

import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(scriptDirectory, '..');
const repositoryRoot = path.resolve(frontendRoot, '..');
const distRoot = path.join(frontendRoot, 'dist', 'apps');
const sessionCookieName = 'shipagent_browser_session';
const federationPaths = [
  '/federation.manifest.json',
  '/chat-remote/remoteEntry.json',
  '/sidebar-remote/remoteEntry.json',
  '/settings-remote/remoteEntry.json',
  '/domain-remote/remoteEntry.json',
];

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
      finish(() =>
        reject(
          new Error(
            `ShipAgent backend exited before startup with status ${code}`
          )
        )
      );
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
        'No Playwright-compatible Chrome or Chromium installation was found'
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
      files.push(...(await emittedFiles(entryPath)));
    } else if (entry.isFile()) {
      files.push(entryPath);
    }
  }
  return files;
}

async function assertSecretsAbsentFromBundles(secrets) {
  const needles = secrets.map((secret) => Buffer.from(secret));
  for (const file of await emittedFiles(distRoot)) {
    const content = await readFile(file);
    for (const needle of needles) {
      assert.equal(
        content.includes(needle),
        false,
        `A runtime browser credential was found in emitted asset ${path.relative(
          frontendRoot,
          file
        )}`
      );
    }
  }
}

async function readAuthenticatedSession(page) {
  const result = await page.evaluate(async () => {
    const response = await fetch('/api/v1/auth/session', {
      credentials: 'same-origin',
    });
    return {
      status: response.status,
      body: await response.json(),
    };
  });
  assert.equal(result.status, 200);
  assert.equal(result.body.required, true);
  assert.equal(result.body.authenticated, true);
  assert.equal(
    typeof result.body.csrf_token === 'string' &&
      /^v1\.[A-Za-z0-9_-]{43}$/.test(result.body.csrf_token),
    true,
    'Authenticated browser status did not return a valid CSRF token'
  );
  return result.body.csrf_token;
}

function waitForSettings(page) {
  return page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === '/api/v1/settings' &&
      response.request().method() === 'GET' &&
      response.status() === 200
    );
  });
}

function waitForEventSourceSessionCheck(page) {
  return page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === '/api/v1/auth/session' &&
      response.request().method() === 'GET' &&
      response.status() === 200
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
      '--parallel=1',
    ],
    frontendRoot
  );
  run('sh', ['./scripts/link-remotes.sh'], frontendRoot);
}

const runtimeKey = randomBytes(48).toString('base64url');
const filterTokenSecret = randomBytes(48).toString('base64url');
const credentialEncryptionKey = randomBytes(32).toString('base64');
const temporaryDirectory = await mkdtemp(
  path.join(tmpdir(), 'shipagent-auth-smoke-')
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
    ['-m', 'src.bundle_entry', 'serve', '--host', '127.0.0.1', '--port', '0'],
    {
      cwd: repositoryRoot,
      env: {
        ...process.env,
        AGENT_AUDIT_ENABLED: 'false',
        DATABASE_URL: `sqlite:///${databasePath}`,
        FILTER_TOKEN_SECRET: filterTokenSecret,
        SHIPAGENT_AGENT_RUNTIME: 'fake',
        SHIPAGENT_API_KEY: runtimeKey,
        SHIPAGENT_CREDENTIAL_KEY: credentialEncryptionKey,
        SHIPAGENT_DISABLE_DOCS: 'true',
        SHIPAGENT_KEYRING_DISABLED: '1',
        SHIPAGENT_SKIP_SDK_CHECK: 'true',
        UPS_LABELS_OUTPUT_DIR: labelsPath,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    }
  );
  const port = await waitForBackendPort(backend);
  const baseUrl = `http://127.0.0.1:${port}`;

  browser = await launchBrowser();
  context = await browser.newContext();
  const page = await context.newPage();
  const browserErrors = [];
  const browserMessages = [];
  const requestUrls = [];
  const observedCookieValues = [];
  const csrfTokens = new Set();
  let pageLoadCount = 0;
  let eventSourceRequestCount = 0;
  page.on('load', () => {
    pageLoadCount += 1;
  });
  page.on('console', (message) => {
    const text = message.text();
    browserMessages.push(text);
    if (message.type() !== 'error') return;
    browserErrors.push(text);
  });
  page.on('pageerror', (error) => browserErrors.push(error.message));
  page.on('request', (request) => {
    requestUrls.push(request.url());
    const url = new URL(request.url());
    if (
      /^\/api\/v1\/conversations\/[^/]+\/stream$/.test(url.pathname) &&
      request.method() === 'GET'
    ) {
      eventSourceRequestCount += 1;
    }
  });

  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
  assert.equal(
    new URL(page.url()).origin,
    new URL(baseUrl).origin,
    'Production shell did not remain on the sidecar origin'
  );
  const federationResponses = await page.evaluate(async (paths) => {
    return Promise.all(
      paths.map(async (resourcePath) => {
        const response = await fetch(resourcePath, {
          credentials: 'same-origin',
        });
        return {
          resourcePath,
          status: response.status,
          url: response.url,
        };
      })
    );
  }, federationPaths);
  for (const response of federationResponses) {
    assert.equal(
      response.status,
      200,
      `Sidecar did not serve ${response.resourcePath}`
    );
    assert.equal(
      new URL(response.url).origin,
      new URL(baseUrl).origin,
      `${response.resourcePath} was not loaded from the sidecar origin`
    );
  }
  await page.getByLabel('Docker API key').waitFor({ state: 'visible' });
  assert.equal(
    await page
      .locator('body')
      .evaluate((body) => body.innerText.trim().length > 0),
    true
  );

  const firstSettings = waitForSettings(page);
  await page.getByLabel('Docker API key').fill(runtimeKey);
  await page.getByRole('button', { name: 'Unlock ShipAgent' }).click();
  const firstSettingsResponse = await firstSettings;
  console.log(
    `authenticated settings request: ${firstSettingsResponse.status()}`
  );

  const firstCookie = (await context.cookies()).find(
    (cookie) => cookie.name === sessionCookieName
  );
  assert.ok(firstCookie, 'Browser session cookie was not created');
  assert.equal(firstCookie.httpOnly, true);
  assert.equal(firstCookie.sameSite, 'Strict');
  assert.equal(firstCookie.value.includes(runtimeKey), false);
  observedCookieValues.push(firstCookie.value);
  const firstCsrfToken = await readAuthenticatedSession(page);
  csrfTokens.add(firstCsrfToken);

  const onboardingStatus = await page.evaluate(async (csrfToken) => {
    const response = await fetch('/api/v1/settings/onboarding/complete', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'X-CSRF-Token': csrfToken,
      },
    });
    return response.status;
  }, firstCsrfToken);
  assert.equal(onboardingStatus, 200);
  const reloadSettings = waitForSettings(page);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await reloadSettings;
  await page.getByRole('button', { name: 'Clear API session' }).click();
  await page.getByLabel('Docker API key').waitFor({ state: 'visible' });
  assert.equal(
    (await context.cookies()).some(
      (cookie) => cookie.name === sessionCookieName
    ),
    false
  );
  console.log('session cleared and gate restored');

  const retrySettings = waitForSettings(page);
  await page.getByLabel('Docker API key').fill(runtimeKey);
  await page.getByRole('button', { name: 'Unlock ShipAgent' }).click();
  const retrySettingsResponse = await retrySettings;
  console.log(
    `authenticated retry settings request: ${retrySettingsResponse.status()}`
  );
  const retryCsrfToken = await readAuthenticatedSession(page);
  csrfTokens.add(retryCsrfToken);

  const activeCookie = (await context.cookies()).find(
    (cookie) => cookie.name === sessionCookieName
  );
  assert.ok(activeCookie, 'Browser session cookie was not recreated');
  observedCookieValues.push(activeCookie.value);

  const chatInput = page.locator('app-rich-chat-input textarea');
  await chatInput.waitFor({ state: 'visible' });
  assert.equal(
    await page.locator('button[title="New chat"]').count(),
    1,
    'Federated chat content did not load before the expiry check'
  );

  const messagePath = /\/api\/v1\/conversations\/[^/]+\/messages(?:\?.*)?$/;
  await page.route(messagePath, async (route) => {
    if (route.request().method() !== 'POST') {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    const sessionId = url.pathname.split('/').at(-2);
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'accepted',
        session_id: sessionId,
      }),
    });
  });

  const conversationCreated = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === '/api/v1/conversations/' &&
      response.request().method() === 'POST' &&
      response.status() === 201
    );
  });
  const eventSourceConnected = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      /^\/api\/v1\/conversations\/[^/]+\/stream$/.test(url.pathname) &&
      response.request().method() === 'GET' &&
      response.status() === 200
    );
  });
  const simulatedBrowserMessage = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      messagePath.test(url.pathname) &&
      response.request().method() === 'POST' &&
      response.status() === 202
    );
  });
  await chatInput.fill('Verify browser session stream expiry');
  await chatInput.press('Enter');
  const conversationResponse = await conversationCreated;
  const conversation = await conversationResponse.json();
  assert.equal(
    typeof conversation.session_id === 'string' &&
      conversation.session_id.length > 0,
    true,
    'Chat did not create a conversation for the EventSource smoke path'
  );
  await Promise.all([eventSourceConnected, simulatedBrowserMessage]);

  await context.addCookies([
    {
      name: activeCookie.name,
      value: 'invalid-browser-session',
      domain: activeCookie.domain,
      path: activeCookie.path,
      expires: activeCookie.expires,
      httpOnly: activeCookie.httpOnly,
      secure: activeCookie.secure,
      sameSite: activeCookie.sameSite,
    },
  ]);

  const pageLoadCountBeforeExpiry = pageLoadCount;
  const sessionCheck = waitForEventSourceSessionCheck(page);
  const agentMessageResponse = await fetch(
    `${baseUrl}/api/v1/conversations/${conversation.session_id}/messages`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': runtimeKey,
      },
      body: JSON.stringify({
        content: 'Complete the production EventSource smoke turn',
      }),
    }
  );
  assert.equal(agentMessageResponse.status, 202);
  const sessionCheckResponse = await sessionCheck;
  const sessionCheckBody = await sessionCheckResponse.json();
  assert.equal(sessionCheckBody.required, true);
  assert.equal(sessionCheckBody.authenticated, false);
  assert.equal(sessionCheckBody.csrf_token, null);
  await page.getByLabel('Docker API key').waitFor({ state: 'visible' });
  assert.equal(
    await page.getByLabel('Docker API key').inputValue(),
    '',
    'Restored API-key gate retained transient input'
  );
  assert.equal(
    await page.getByRole('button', { name: 'Clear API session' }).count(),
    0,
    'Authenticated shell remained visible after session expiry'
  );
  assert.equal(
    await page.locator('app-rich-chat-input textarea').count(),
    0,
    'Federated chat content remained visible after session expiry'
  );
  assert.equal(
    pageLoadCount,
    pageLoadCountBeforeExpiry,
    'Session expiry reloaded the shell'
  );
  const eventSourceRequestsAtExpiry = eventSourceRequestCount;
  await page.waitForTimeout(3_500);
  assert.equal(
    eventSourceRequestCount,
    eventSourceRequestsAtExpiry,
    'Expired EventSource entered a reconnect loop'
  );
  console.log(
    `invalidated EventSource session status check: ${sessionCheckResponse.status()}`
  );
  await page.unroute(messagePath);

  const recoveredSettings = waitForSettings(page);
  await page.getByLabel('Docker API key').fill(runtimeKey);
  await page.getByRole('button', { name: 'Unlock ShipAgent' }).click();
  const recoveredSettingsResponse = await recoveredSettings;
  console.log(
    `authenticated recovery settings request: ${recoveredSettingsResponse.status()}`
  );
  const recoveredCsrfToken = await readAuthenticatedSession(page);
  csrfTokens.add(recoveredCsrfToken);
  assert.equal(
    csrfTokens.size,
    3,
    'Browser sessions did not receive distinct session-bound CSRF tokens'
  );
  await page
    .getByRole('button', { name: 'Clear API session' })
    .waitFor({ state: 'visible' });
  observedCookieValues.push(
    ...(await context.cookies()).map((cookie) => cookie.value)
  );

  const runtimeSecrets = [runtimeKey, ...csrfTokens];
  const persistedSecret = await page.evaluate((candidates) => {
    const containsCandidate = (storage) => {
      for (let index = 0; index < storage.length; index += 1) {
        const key = storage.key(index) ?? '';
        const value = storage.getItem(key) ?? '';
        if (
          candidates.some(
            (candidate) => key.includes(candidate) || value.includes(candidate)
          )
        ) {
          return true;
        }
      }
      return false;
    };
    return containsCandidate(localStorage) || containsCandidate(sessionStorage);
  }, runtimeSecrets);
  assert.equal(
    persistedSecret,
    false,
    'A runtime browser credential was persisted in browser storage'
  );
  assert.equal(
    observedCookieValues.some((value) =>
      runtimeSecrets.some((secret) => value.includes(secret))
    ),
    false,
    'A runtime browser credential was embedded in a cookie value'
  );
  assert.equal(
    requestUrls.some((url) =>
      runtimeSecrets.some((secret) => url.includes(secret))
    ),
    false,
    'A runtime browser credential was exposed in a request URL'
  );
  assert.equal(
    requestUrls
      .filter((url) => new URL(url).pathname.startsWith('/api/v1'))
      .every((url) => new URL(url).origin === new URL(baseUrl).origin),
    true,
    'A production API request escaped the shell/cookie sidecar origin'
  );
  assert.equal(
    requestUrls.some((url) =>
      decodeURIComponent(new URL(url).pathname).startsWith('/@shipagent/')
    ),
    false,
    'The pre-federation bootstrap requested an unresolved workspace import'
  );
  assert.equal(
    browserMessages.some((message) =>
      runtimeSecrets.some((secret) => message.includes(secret))
    ),
    false,
    'A runtime browser credential was exposed in browser console output'
  );
  const renderedDocument = await page.content();
  assert.equal(
    runtimeSecrets.some((secret) => renderedDocument.includes(secret)),
    false,
    'A runtime browser credential remained in the rendered document'
  );
  assert.equal(
    await page
      .locator(
        '[data-nextjs-dialog], .vite-error-overlay, #webpack-dev-server-client-overlay'
      )
      .count(),
    0
  );
  assert.deepEqual(browserErrors, []);

  await assertSecretsAbsentFromBundles(runtimeSecrets);
  console.log(
    'same-origin sidecar shell/remotes/API passed with runtime secrets absent'
  );
} finally {
  if (context) await context.close();
  if (browser) await browser.close();
  await stopBackend(backend);
  await rm(temporaryDirectory, { recursive: true, force: true });
}

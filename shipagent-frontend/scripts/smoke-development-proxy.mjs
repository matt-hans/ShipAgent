import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(scriptDirectory, '..');
const repositoryRoot = path.resolve(frontendRoot, '..');
// `localhost`, as documented: the dev server may bind only ::1 or only 127.0.0.1.
const frontendOrigin = 'http://localhost:4200';
const backendOrigin = 'http://127.0.0.1:8080';

function findPython() {
  if (process.env.SHIPAGENT_PYTHON) return process.env.SHIPAGENT_PYTHON;

  const candidates = [
    path.join(repositoryRoot, '.venv', 'bin', 'python'),
    path.resolve(repositoryRoot, '..', '..', '.venv', 'bin', 'python'),
  ];
  return candidates.find((candidate) => existsSync(candidate)) ?? 'python3';
}

function forwardOutput(child, label) {
  child.stdout.on('data', (chunk) =>
    process.stdout.write(`[${label}] ${chunk}`)
  );
  child.stderr.on('data', (chunk) =>
    process.stderr.write(`[${label}] ${chunk}`)
  );
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function waitForResponse(
  url,
  child,
  label,
  timeoutMilliseconds = 120_000
) {
  const deadline = Date.now() + timeoutMilliseconds;
  let lastError;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`${label} exited with status ${child.exitCode}`);
    }
    try {
      const response = await fetch(url);
      if (response.ok) return response;
      lastError = new Error(`${url} returned ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await delay(250);
  }
  throw new Error(`Timed out waiting for ${label} at ${url}`, {
    cause: lastError,
  });
}

async function stopProcessGroup(child) {
  if (!child || child.exitCode !== null) return;
  const exited = new Promise((resolve) => child.once('exit', resolve));
  try {
    process.kill(-child.pid, 'SIGTERM');
  } catch {
    child.kill('SIGTERM');
  }
  const stopped = await Promise.race([
    exited.then(() => true),
    delay(5_000).then(() => false),
  ]);
  if (!stopped && child.exitCode === null) {
    try {
      process.kill(-child.pid, 'SIGKILL');
    } catch {
      child.kill('SIGKILL');
    }
    await exited;
  }
}

const temporaryDirectory = await mkdtemp(
  path.join(tmpdir(), 'shipagent-dev-proxy-smoke-')
);
const environmentFile = path.join(temporaryDirectory, 'backend.env');
const databasePath = path.join(temporaryDirectory, 'shipagent.db');
const labelsPath = path.join(temporaryDirectory, 'labels');
const backendEnvironment = {
  ...process.env,
  SHIPAGENT_ENV_FILE: environmentFile,
  SHIPAGENT_PYTHON: findPython(),
};
delete backendEnvironment.SHIPAGENT_PORT;

await writeFile(
  environmentFile,
  [
    'AGENT_AUDIT_ENABLED=false',
    `DATABASE_URL=sqlite:///${databasePath}`,
    `FILTER_TOKEN_SECRET=${randomBytes(32).toString('hex')}`,
    'SHIPAGENT_AGENT_RUNTIME=fake',
    `SHIPAGENT_CREDENTIAL_KEY=${randomBytes(32).toString('base64')}`,
    'SHIPAGENT_DISABLE_DOCS=true',
    'SHIPAGENT_KEYRING_DISABLED=1',
    'SHIPAGENT_SKIP_SDK_CHECK=true',
    `UPS_LABELS_OUTPUT_DIR=${labelsPath}`,
    '',
  ].join('\n'),
  { mode: 0o600 }
);

let backend;
let frontend;
try {
  backend = spawn('./scripts/start-backend.sh', [], {
    cwd: repositoryRoot,
    detached: true,
    env: backendEnvironment,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  forwardOutput(backend, 'backend');
  await waitForResponse(`${backendOrigin}/health`, backend, 'backend');

  frontend = spawn('npx', ['nx', 'serve', 'shell'], {
    cwd: frontendRoot,
    detached: true,
    env: process.env,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  forwardOutput(frontend, 'frontend');
  await waitForResponse(frontendOrigin, frontend, 'frontend dev server');

  const apiResponse = await fetch(`${frontendOrigin}/api/v1/auth/session`, {
    redirect: 'manual',
  });
  assert.equal(apiResponse.status, 200);
  assert.match(
    apiResponse.headers.get('content-type') ?? '',
    /^application\/json\b/
  );
  assert.deepEqual(await apiResponse.json(), {
    required: false,
    authenticated: true,
    csrf_token: null,
  });
  console.log(
    'development shell served backend JSON through relative /api/v1 on port 4200'
  );
} finally {
  await stopProcessGroup(frontend);
  await stopProcessGroup(backend);
  await rm(temporaryDirectory, { recursive: true, force: true });
}

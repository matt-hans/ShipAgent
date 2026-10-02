import { lstat, readFile } from 'node:fs/promises';
import path from 'node:path';

const [remoteDirectory, expectedRemoteName] = process.argv.slice(2);

function fail(message) {
  console.error(`ERROR: ${expectedRemoteName} remoteEntry.json ${message}`);
  process.exit(1);
}

if (!remoteDirectory || !expectedRemoteName) {
  fail('validator requires a remote directory and expected name');
}

const entryPath = path.join(remoteDirectory, 'remoteEntry.json');
let entryStat;
try {
  entryStat = await lstat(entryPath);
} catch {
  fail('is missing');
}
if (!entryStat.isFile() || entryStat.isSymbolicLink()) {
  fail('is not a regular file');
}

let manifest;
try {
  manifest = JSON.parse(await readFile(entryPath, 'utf8'));
} catch {
  fail('is not valid JSON');
}

if (
  manifest === null ||
  typeof manifest !== 'object' ||
  Array.isArray(manifest) ||
  manifest.name !== expectedRemoteName
) {
  fail('does not identify the expected remote');
}

if (!Array.isArray(manifest.exposes) || manifest.exposes.length === 0) {
  fail('must expose at least one chunk');
}
if (!Array.isArray(manifest.shared)) {
  fail('must declare a shared chunk array');
}

const chunkNamePattern = /^[A-Za-z0-9_][A-Za-z0-9._-]*\.js$/;
const referencedChunks = new Map();
for (const exposed of manifest.exposes) {
  if (
    exposed === null ||
    typeof exposed !== 'object' ||
    Array.isArray(exposed) ||
    typeof exposed.key !== 'string' ||
    !exposed.key.startsWith('./') ||
    typeof exposed.outFileName !== 'string' ||
    !chunkNamePattern.test(exposed.outFileName)
  ) {
    fail('contains an invalid exposed chunk');
  }
  referencedChunks.set(exposed.outFileName, true);
}
for (const shared of manifest.shared) {
  if (
    shared === null ||
    typeof shared !== 'object' ||
    Array.isArray(shared) ||
    typeof shared.outFileName !== 'string' ||
    !chunkNamePattern.test(shared.outFileName)
  ) {
    fail('contains an invalid shared chunk');
  }
  if (!referencedChunks.has(shared.outFileName)) {
    referencedChunks.set(shared.outFileName, false);
  }
}

for (const [chunkName, requiresContent] of referencedChunks) {
  const chunkPath = path.join(remoteDirectory, chunkName);
  let chunkStat;
  try {
    chunkStat = await lstat(chunkPath);
  } catch {
    fail(`referenced chunk is missing: ${chunkName}`);
  }
  if (!chunkStat.isFile() || chunkStat.isSymbolicLink()) {
    fail(`referenced chunk is not a regular file: ${chunkName}`);
  }
  const chunkBody = await readFile(chunkPath, 'utf8');
  if (
    (requiresContent && chunkBody.trim().length === 0) ||
    /^\s*(?:<!doctype\s+html|<html\b)/i.test(chunkBody)
  ) {
    fail(`referenced chunk is empty or HTML: ${chunkName}`);
  }
}

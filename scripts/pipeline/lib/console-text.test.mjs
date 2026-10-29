import { test } from 'node:test';
import assert from 'node:assert/strict';
import { consoleText } from './console-text.mjs';
const text = 'IAC_ED25519_FP_BEGIN\nSHA256:abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG\nIAC_ED25519_FP_END\n';
test('binary provider frames preserve complete fingerprint framing', async () => {
  const decoder = new TextDecoder();
  const bytes = new TextEncoder().encode(text);
  assert.equal(await consoleText(bytes.buffer, decoder), text);
  assert.equal(await consoleText(bytes, decoder), text);
  assert.equal(await consoleText(new Blob([bytes]), decoder), text);
});
test('split UTF-8 frames preserve ordering and partial characters', async () => {
  const decoder = new TextDecoder();
  const bytes = new TextEncoder().encode('启动\n' + text);
  const out = await consoleText(bytes.subarray(0, 1), decoder)
    + await consoleText(bytes.subarray(1, 4), decoder)
    + await consoleText(bytes.subarray(4), decoder) + decoder.decode();
  assert.equal(out, '启动\n' + text);
});
test('text frames remain unchanged and unknown objects are rejected', async () => {
  assert.equal(await consoleText(text, new TextDecoder()), text);
  await assert.rejects(consoleText({}, new TextDecoder()), /Unsupported/);
});

import { scrollbackFrames, readScrollback } from './console-scrollback.mjs';
test('provider scrollback controls are finite and contain no guest command text', () => {
  const sent = [];
  const socket = { readyState: 1, send: (x) => sent.push(x) };
  const old = globalThis.WebSocket;
  globalThis.WebSocket = { OPEN: 1 };
  try {
    readScrollback(socket, (fn) => fn());
    assert.equal(sent.length, 18);
    assert.equal(sent[0], '\x01\x1b');
    assert.equal(sent.at(-1), '\x1b');
    assert.ok(sent.every((x) => ['\x01\x1b', '\x02', '\x1b'].includes(x)));
    assert.ok(scrollbackFrames.every(([ms]) => ms >= 0 && ms <= 9000));
  } finally { globalThis.WebSocket = old; }
});

import { ConsoleRenderer } from './console-renderer.mjs';
test('actual terminal rendering restores overwritten and wrapped public host keys', async () => {
  const wire = Buffer.concat([Buffer.from('0000000b7373682d6564323535313900000020', 'hex'), Buffer.alloc(32, 7)]);
  const key = wire.toString('base64');
  const renderer = new ConsoleRenderer();
  try {
    await renderer.write('\x1b[2J\x1b[1;1H-----BEGIN SSH HOST KEY KEYS-----');
    await renderer.write('\x1b[2;1Hssh-ed25519 ' + key.slice(0, 20) + 'X\b' + key.slice(20));
    await renderer.write('\x1b[4;1H-----END SSH HOST KEY KEYS-----');
    const snapshot = renderer.snapshot();
    assert.ok(snapshot.includes('ssh-ed25519 ' + key));
    assert.ok(snapshot.includes('-----END SSH HOST KEY KEYS-----'));
    assert.ok(!snapshot.includes('\x1b') && !snapshot.includes('\b'));
  } finally { renderer.dispose(); }
});

import { spawnSync } from 'node:child_process';
test('complete terminal evidence is flushed across pipe backpressure before exit', () => {
  const moduleUrl = new URL('./console-text.mjs', import.meta.url).href;
  const source = `import { writeConsole } from ${JSON.stringify(moduleUrl)}; const x='IAC_ED25519_FP_BEGIN\\n'+'x'.repeat(1024*1024)+'\\nIAC_ED25519_FP_END'; await writeConsole(x); process.exit(0);`;
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', source], { maxBuffer: 2*1024*1024 });
  assert.equal(result.status, 0);
  assert.ok(result.stdout.toString().endsWith('IAC_ED25519_FP_END'));
  assert.ok(result.stdout.length > 1024*1024);
});

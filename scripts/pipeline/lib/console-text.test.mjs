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

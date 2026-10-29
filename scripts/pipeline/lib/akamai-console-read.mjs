// Provider console reads only; only fixed read-only scrollback controls are allowed.
import { consoleText } from './console-text.mjs';
import { readScrollback } from './console-scrollback.mjs';
import { ConsoleRenderer } from './console-renderer.mjs';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const config = JSON.parse(input);
const socket = new WebSocket(config.weblish_url, config.ws_protocols);
socket.binaryType = 'arraybuffer';
socket.addEventListener('open', () => readScrollback(socket));
const decoder = new TextDecoder('utf-8');
const renderer = new ConsoleRenderer();
const snapshots = [];
let pending = Promise.resolve();
let idle;
function capture() {
  if (snapshots.length < 64) snapshots.push(renderer.snapshot());
}
socket.addEventListener('message', (event) => {
  clearTimeout(idle);
  pending = pending.then(async () => {
    await renderer.write(await consoleText(event.data, decoder));
    clearTimeout(idle);
    idle = setTimeout(() => { pending = pending.then(capture); }, 150);
  });
  pending.catch(() => process.exit(1));
});
socket.addEventListener('error', () => process.exit(1));
setTimeout(async () => {
  socket.close();
  clearTimeout(idle);
  await pending;
  await renderer.write(decoder.decode());
  capture();
  process.stdout.write(snapshots.join('\n'));
  renderer.dispose();
  process.exit(0);
}, Number(process.argv[2]));

// Provider console reads only; only fixed read-only scrollback controls are allowed.
import { consoleText } from './console-text.mjs';
import { readScrollback } from './console-scrollback.mjs';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const config = JSON.parse(input);
const socket = new WebSocket(config.weblish_url, config.ws_protocols);
socket.binaryType = 'arraybuffer';
socket.addEventListener('open', () => readScrollback(socket));
const decoder = new TextDecoder('utf-8');
let output = '';
let pending = Promise.resolve();
socket.addEventListener('message', (event) => {
  pending = pending.then(async () => { output += await consoleText(event.data, decoder); });
  pending.catch(() => process.exit(1));
});
socket.addEventListener('error', () => process.exit(1));
setTimeout(async () => {
  socket.close();
  await pending;
  process.stdout.write(output + decoder.decode());
  process.exit(0);
}, Number(process.argv[2]));

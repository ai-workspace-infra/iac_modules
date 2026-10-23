// Provider console reads only; never send keyboard input or log session tokens.
let input = '';
for await (const chunk of process.stdin) input += chunk;
const config = JSON.parse(input);
const socket = new WebSocket(config.weblish_url, config.ws_protocols);
let output = '';
socket.addEventListener('message', (event) => {
  output += event.data;
});
socket.addEventListener('error', () => process.exit(1));
setTimeout(() => {
  socket.close();
  process.stdout.write(output);
  process.exit(0);
}, Number(process.argv[2]));

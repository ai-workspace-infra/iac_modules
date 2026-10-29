// Read-only GNU screen/Lish copy-mode navigation. No printable text, newline,
// credential or guest command is ever sent; exit copy mode before closing.
export const scrollbackFrames = Object.freeze([
  [1500, '\x01\x1b'],
  ...Array.from({ length: 16 }, (_, i) => [2000 + i * 400, '\x02']),
  [9000, '\x1b'],
]);
export function readScrollback(socket, schedule = setTimeout) {
  for (const [delay, data] of scrollbackFrames) {
    schedule(() => {
      if (socket.readyState === WebSocket.OPEN) socket.send(data);
    }, delay);
  }
}

import headless from '@xterm/headless';
const { Terminal } = headless;
// Match the official Weblish client viewport; terminal redraws are not a log.
export class ConsoleRenderer {
  constructor() {
    this.terminal = new Terminal({ cols: 80, rows: 40, scrollback: 5000, allowProposedApi: true });
  }
  async write(text) { await new Promise((resolve) => this.terminal.write(text, resolve)); }
  snapshot() {
    const buffer = this.terminal.buffer.active;
    return Array.from({ length: this.terminal.rows }, (_, i) =>
      buffer.getLine(buffer.baseY + i)?.translateToString(true) ?? '').join('\n') + '\n';
  }
  dispose() { this.terminal.dispose(); }
}

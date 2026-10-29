// Decode provider binary terminal frames without emitting session metadata.
export async function consoleText(data, decoder) {
  if (typeof data === 'string') return data;
  if (data instanceof Blob) data = await data.arrayBuffer();
  if (data instanceof ArrayBuffer) return decoder.decode(new Uint8Array(data), { stream: true });
  if (ArrayBuffer.isView(data)) return decoder.decode(data, { stream: true });
  throw new Error('Unsupported provider console frame type');
}

export async function writeConsole(text, stream = process.stdout) {
  await new Promise((resolve, reject) => stream.write(text, (error) => error ? reject(error) : resolve()));
}

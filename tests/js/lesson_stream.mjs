// Runs studio/src/lessonStream.ts in node (type stripping) against a slow fake server stream and prints what the
// cell would have shown, and when, as one JSON line. Used by tests/test_studio_stream.py.
import { pathToFileURL } from 'node:url';

const [, , modPath, mode] = process.argv;
const { readLessonStream } = await import(pathToFileURL(modPath).href);
const enc = new TextEncoder();
const ev = (o) => enc.encode('data: ' + JSON.stringify(o) + '\n\n');
const deltas = ['If someone asks', ' about paying by card,', ' say PayPal', ' takes cards too.'];
const log = [];
const t0 = Date.now();
let sent = 0;
const body = new ReadableStream({
  async start(c) {
    c.enqueue(ev({ type: 'TEXT_MESSAGE_START', messageId: 'm', role: 'assistant' }));
    for (const d of deltas) {
      await new Promise((r) => setTimeout(r, 60));
      // split one event across two chunks, as a proxy can
      const bytes = ev({ type: 'TEXT_MESSAGE_CONTENT', messageId: 'm', delta: d });
      c.enqueue(bytes.slice(0, 7)); c.enqueue(bytes.slice(7));
      sent += 1;
    }
    await new Promise((r) => setTimeout(r, 60));
    c.enqueue(ev({ type: 'TEXT_MESSAGE_END', messageId: 'm' }));
    if (mode === 'error') c.enqueue(ev({ type: 'RUN_ERROR', message: "Today's AI budget is used up." }));
    else if (mode !== 'cut') c.enqueue(ev({ type: 'RUN_FINISHED', lesson: deltas.join(''), usable: true }));
    c.close();
  },
});
await readLessonStream(body, {
  text: (s) => log.push({ kind: 'text', text: s, deltas_sent: sent, ms: Date.now() - t0 }),
  done: (lesson, usable) => log.push({ kind: 'done', lesson, usable, ms: Date.now() - t0 }),
  error: (m) => log.push({ kind: 'error', message: m, ms: Date.now() - t0 }),
});
console.log(JSON.stringify({ log, total_ms: Date.now() - t0 }));

// "Draft a lesson": reads the AG-UI events our server sends (TEXT_MESSAGE_START / _CONTENT / _END, then RUN_FINISHED
// or RUN_ERROR) and hands every token to the cell the moment it arrives. Nothing is buffered or typed out again
// afterwards: what the cell shows while the model writes is the model's own stream (final judges 08.11 P0-2).
// Kept free of React and of TypeScript-only syntax, so node runs it directly in tests/js/lesson_stream.mjs.

export type LessonStreamHandlers = {
  text: (soFar: string) => void;                     // after every TEXT_MESSAGE_CONTENT: the lesson so far
  done: (lesson: string, usable: boolean) => void;   // RUN_FINISHED: the finished sentence, and whether the shop can match it
  error: (message: string) => void;                  // RUN_ERROR, or the stream ended without RUN_FINISHED
};

export async function readLessonStream(body: ReadableStream<Uint8Array>, on: LessonStreamHandlers): Promise<void> {
  const reader = body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  let text = '';
  let finished = false;
  const handle = (block: string) => {
    if (!block.startsWith('data: ')) return;
    const ev = JSON.parse(block.slice(6));
    if (ev.type === 'TEXT_MESSAGE_CONTENT' && typeof ev.delta === 'string') {
      text += ev.delta;
      on.text(text);
    } else if (ev.type === 'RUN_FINISHED') {
      finished = true;
      on.done(typeof ev.lesson === 'string' ? ev.lesson : text.trim(), !!ev.usable);
    } else if (ev.type === 'RUN_ERROR') {
      finished = true;
      on.error(String(ev.message || 'The draft stopped.'));
    }
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      handle(block);
    }
  }
  if (buf.trim()) handle(buf.trim());
  if (!finished) on.error('The draft stopped before it finished.');
}

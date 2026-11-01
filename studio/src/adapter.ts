// AG Studio's model adapter, pointed at our own server (/api/studio/llm), which calls Nemotron with the key kept there.
// The server answers a whole turn at once; here it is replayed as the AG-UI events Studio reads.
import type { AgAiEvent, AgAiOutputItem, AgLlmAdapter, AgLlmRequest, AgLlmResponse } from 'ag-studio';

type Turn = { text: string; tool_calls: { id: string; name: string; arguments: string }[]; model: string;
  usage?: { inputTokens: number; outputTokens: number } | null; error?: string };

export function shopAdapter(endpoint = '/api/studio/llm'): AgLlmAdapter {
  return {
    executeTurn(request: AgLlmRequest, options) {
      const events: AgAiEvent[] = [];
      let done!: (r: AgLlmResponse) => void;
      const complete = new Promise<AgLlmResponse>((res) => (done = res));
      const id = `turn-${Date.now()}`;
      const run = (async () => {
        try {
          const r = await fetch(endpoint, {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'x-visitor': visitor() },
            body: JSON.stringify(request), signal: options?.signal,
          });
          const t: Turn = await r.json();
          if (!r.ok) throw new Error(t.error || `HTTP ${r.status}`);
          const output: AgAiOutputItem[] = [];
          if (t.text) {
            const mid = `${id}-msg`;
            events.push({ type: 'TEXT_MESSAGE_START', messageId: mid, role: 'assistant' } as AgAiEvent,
              { type: 'TEXT_MESSAGE_CONTENT', messageId: mid, delta: t.text } as AgAiEvent,
              { type: 'TEXT_MESSAGE_END', messageId: mid } as AgAiEvent);
            output.push({ id: mid, kind: 'output', type: 'message', role: 'assistant', status: 'completed',
              content: [{ type: 'text', text: t.text, annotations: [] }] });
          }
          for (const c of t.tool_calls) {
            events.push({ type: 'TOOL_CALL_START', toolCallId: c.id, toolCallName: c.name } as AgAiEvent,
              { type: 'TOOL_CALL_ARGS', toolCallId: c.id, delta: c.arguments } as AgAiEvent,
              { type: 'TOOL_CALL_END', toolCallId: c.id } as AgAiEvent);
            output.push({ id: c.id, kind: 'output', type: 'function_call', callId: c.id, name: c.name,
              arguments: c.arguments, status: 'completed' });
          }
          done({ id, createdAt: Date.now(), output, status: 'completed', model: t.model,
            usage: t.usage ? ({ inputTokens: t.usage.inputTokens, outputTokens: t.usage.outputTokens } as never) : undefined });
        } catch (e) {
          done({ id, createdAt: Date.now(), output: [], status: 'failed',
            error: { code: 'request_failed', message: String((e as Error).message || e) } });
        }
      })();
      return {
        stream: { async *[Symbol.asyncIterator]() { await run; yield* events; } },
        complete,
      };
    },
  };
}

function visitor(): string {
  let v = localStorage.getItem('oc-visitor');
  if (!v) { v = Math.random().toString(36).slice(2, 14); localStorage.setItem('oc-visitor', v); }
  return v;
}

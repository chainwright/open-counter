import React, { useEffect, useRef, useState } from 'react';

// "Where my agent got stuck — this week": the hero custom widget of Lena's studio (design B v2, WOW plan).
// Data comes from the shop's own endpoint (/api/maker/agent_misses), computed in code; this component only shows it,
// lets Lena draft and accept a lesson, and polls so a new chat that follows a lesson draws its tick live.

type Later = { chat: string; no?: number; at: number; followed: boolean };
type Taught = { lesson: string; note: string; chat: string; asked: string; said: string; later: Later[];
  followed: number; missed: number; orders_usd: number; at: number };
type Open = { chat: string; no?: number; at: number; asked: string; said: string };
type Data = { taught: Taught[]; open: Open[]; orders_usd: number; days: number };

const visitor = () => {
  let v = localStorage.getItem('oc_visitor');
  if (!v) { v = 'v' + Math.random().toString(36).slice(2, 12); localStorage.setItem('oc_visitor', v); }
  return v;
};
const headers = () => ({ 'content-type': 'application/json', 'x-visitor': visitor() });
const usd = (n: number) => '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function StuckWidget(props: any) {
  const [data, setData] = useState<Data>();
  const [drafts, setDrafts] = useState<Record<string, { text: string; busy: boolean; err?: string }>>({});
  const seen = useRef<Set<string> | null>(null);       // ticks already on screen: only NEW ones animate
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const days = props?.format?.days ?? 7;
  const animateStrike = props?.widgetId && props.widgetId !== 'stuck';   // the page's own widget is 'stuck'; one an agent adds gets a new id

  async function load() {
    const r = await fetch(`/api/maker/agent_misses?days=${days}`, { headers: headers() });
    const d: Data = await r.json();
    const keys = d.taught.flatMap((t) => t.later.map((l) => `${t.lesson}:${l.chat}:${l.at}`));
    if (seen.current === null) seen.current = new Set(keys);  // first load: draw everything still
    else {
      const add = keys.filter((k) => !seen.current!.has(k));
      add.forEach((k) => seen.current!.add(k));
      if (add.length) setFresh(new Set(add));
    }
    setData(d);
    props?.widgetApi?.setDisplayState?.(d.taught.length || d.open.length ? 'displayed' : 'noData');
  }
  useEffect(() => {
    props?.widgetApi?.setDisplayState?.('loading');
    load().catch(() => props?.widgetApi?.setDisplayState?.('noData'));
    const id = setInterval(() => load().catch(() => {}), 3000);
    return () => clearInterval(id);
  }, [days]);

  // The lesson streams into the cell token by token: AG-UI events (TEXT_MESSAGE_CONTENT) from our server, which
  // forwards the model's own stream. Accept appears only once the finished sentence passes the shop's matcher.
  async function draft(chat: string) {
    setDrafts((d) => ({ ...d, [chat]: { text: '', busy: true } }));
    const set = (patch: any) => setDrafts((d) => ({ ...d, [chat]: { ...(d[chat] || { text: '', busy: true }), ...patch } }));
    try {
      const r = await fetch('/api/maker/agent_misses/draft_stream', { method: 'POST', headers: headers(), body: JSON.stringify({ chat }) });
      if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);
      const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = '', text = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf('\n\n')) >= 0) {
          const line = buf.slice(0, i); buf = buf.slice(i + 2);
          if (!line.startsWith('data: ')) continue;
          const ev = JSON.parse(line.slice(6));
          if (ev.type === 'TEXT_MESSAGE_CONTENT') { text += ev.delta; set({ text }); }
          else if (ev.type === 'RUN_FINISHED') set({ text: ev.lesson, busy: false, err: ev.usable ? undefined : "This draft isn't in the 'If someone asks about…, say…' form the shop can match. Edit it before accepting." });
          else if (ev.type === 'RUN_ERROR') set({ busy: false, err: ev.message });
        }
      }
    } catch (e: any) {
      set({ busy: false, err: 'No lesson drafted: ' + (e?.message || e) });
    }
  }
  async function accept(chat: string) {
    const note = drafts[chat]?.text;
    if (!note) return;
    await fetch('/api/maker/coach', { method: 'POST', headers: headers(), body: JSON.stringify({ chat_id: chat, note }) });
    setDrafts((d) => { const n = { ...d }; delete n[chat]; return n; });
    load();
  }

  if (!data) return <div className="sw" />;
  return (
    <div className="sw">
      <h2 className="sw-title">Where my agent got stuck — this week</h2>
      <table className="sw-table">
        <thead><tr><th>Shopper asked</th><th>Agent said <span>(original reply)</span></th><th>Lesson</th><th>Later chats</th></tr></thead>
        <tbody>
          {data.taught.map((t) => {
            const total = t.later.length;
            return (
              <tr key={t.lesson}>
                <td>{t.asked}</td>
                <td><span className={"sw-struck" + (animateStrike ? " draw" : "")}>{t.said}</span></td>
                <td>{t.note}</td>
                <td>{total === 0 ? <span className="sw-watch">watching…</span> : (
                  <>
                    <div className="sw-ticks">{t.later.map((l) => {
                      const k = `${t.lesson}:${l.chat}:${l.at}`;
                      return <Tick key={k} ok={l.followed} fresh={fresh.has(k)} />;
                    })}</div>
                    <div className="sw-count">{t.followed} of {total} followed</div>
                  </>)}
                </td>
              </tr>);
          })}
          {data.open.map((o) => {
            const d = drafts[o.chat];
            return (
              <tr key={o.chat}>
                <td>{o.asked}</td>
                <td><span className={"sw-struck" + (animateStrike ? " draw" : "")}>{o.said}</span></td>
                <td>{!d ? <button className="sw-primary" onClick={() => draft(o.chat)}>Draft a lesson</button>
                  : d.busy ? <em className="sw-draft">{d.text ? <>{d.text}<span className="sw-caret" /></> : "Lena's shop analyst is writing…"}</em>
                  : d.err ? <span className="sw-err">{d.err}</span>
                  : (<>
                      <em className="sw-draft">{d.text}</em>
                      <div className="sw-actions"><button className="sw-primary" onClick={() => accept(o.chat)}>Accept</button>
                        <button className="sw-secondary" onClick={() => setDrafts((x) => ({ ...x, [o.chat]: { ...d, text: prompt('Edit the lesson', d.text) || d.text } }))}>Edit</button></div>
                    </>)}
                </td>
                <td />
              </tr>);
          })}
        </tbody>
      </table>
      <div className="sw-pay"><span>Paid orders from chats these lessons touched</span><strong>{usd(data.orders_usd)}</strong></div>
    </div>
  );
}

function Tick({ ok, fresh }: { ok: boolean; fresh: boolean }) {
  return ok ? (
    <svg className={'sw-tick ok' + (fresh ? ' fresh' : '')} viewBox="0 0 24 24" aria-label="followed"><path d="M4 13 L10 19 L20 5" /></svg>
  ) : (
    <svg className={'sw-tick no' + (fresh ? ' fresh' : '')} viewBox="0 0 24 24" aria-label="not followed"><path d="M5 5 L19 19 M19 5 L5 19" /></svg>
  );
}

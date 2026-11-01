import React, { useEffect, useRef, useState } from 'react';

// "Sold to an agent · this week": the studio's KPI strip (custom widget, design B v2 + WOW judge #5).
// Who sold this week's orders: an outside AI agent over MCP (the accent), Lena's own sales chat, a made-to-order build.
// When a new MCP sale lands, only that one digit rolls up (no odometer) and the PayPal chip flips to its new status.

type Sales = { via_mcp: number; her_chat: number; made_to_order: number;
  last_mcp: { id: string; status: string; paypal: string } | null };

function Roll({ value }: { value: number }) {
  const prev = useRef(value);
  const [from, setFrom] = useState<number | null>(null);
  useEffect(() => {
    if (value !== prev.current) { setFrom(prev.current); prev.current = value; const t = setTimeout(() => setFrom(null), 700); return () => clearTimeout(t); }
  }, [value]);
  return (
    <span className="ss-roll">
      {from !== null && <span className="ss-out">{from}</span>}
      <span className={from !== null ? 'ss-in' : ''}>{value}</span>
    </span>
  );
}

export default function SoldStrip(props: any) {
  const [s, setS] = useState<Sales>();
  const [flip, setFlip] = useState(false);
  const lastChip = useRef<string>('');
  const days = props?.format?.days ?? 7;
  useEffect(() => {
    let alive = true;
    const load = () => fetch(`/api/maker/agent_sales?days=${days}`).then((r) => r.json()).then((d: Sales) => {
      if (!alive) return;
      const chip = d.last_mcp ? `${d.last_mcp.id}:${d.last_mcp.paypal}` : '';
      if (lastChip.current && chip !== lastChip.current) { setFlip(true); setTimeout(() => setFlip(false), 600); }
      lastChip.current = chip;
      setS(d);
      props?.widgetApi?.setDisplayState?.('displayed');
    }).catch(() => {});
    props?.widgetApi?.setDisplayState?.('loading');
    load();
    const id = setInterval(load, 3000);
    return () => { alive = false; clearInterval(id); };
  }, [days]);
  if (!s) return <div className="ss" />;
  return (
    <div className="ss">
      <div className="ss-head">
        <span className="ss-label">Sold to an agent · this week</span>
        {s.last_mcp && <span className={'ss-chip' + (flip ? ' flip' : '')}>PayPal · {s.last_mcp.id} · {s.last_mcp.paypal}</span>}
      </div>
      <div className="ss-row">
        <div className="ss-cell accent"><div className="ss-k">Via outside AI (MCP)</div><div className="ss-v"><Roll value={s.via_mcp} /></div></div>
        <div className="ss-cell"><div className="ss-k">Her sales chat</div><div className="ss-v">{s.her_chat}</div></div>
        <div className="ss-cell"><div className="ss-k">Made to order</div><div className="ss-v">{s.made_to_order}</div></div>
      </div>
    </div>
  );
}

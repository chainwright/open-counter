window.addEventListener('error', (e) => { (window as any).__errs = [...((window as any).__errs || []), String(e.message)]; });
window.addEventListener('unhandledrejection', (e) => { (window as any).__errs = [...((window as any).__errs || []), String((e as any).reason)]; });
import React, { StrictMode, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AgStudio, AgStudioProvider } from 'ag-studio-react';
import { AgStudioAiModule, createAiHarness, type AgAiHarnessSetup, type AgDataSourcesDefinition } from 'ag-studio';
import { shopAdapter } from './adapter';

// Spike: Lena's orders as one flat table (one row per car line), Studio's own agents on Nemotron through our server.
type Order = { id: string; created: number; status: string; channel: string; ship_state: string;
  lines?: { title: string; qty: number; unit_usd: number }[]; shipping_usd: number };

function rows(orders: Order[]) {
  return orders.flatMap((o) => (o.lines?.length ? o.lines : [{ title: (o as any).title || 'Made to order', qty: (o as any).qty || 1, unit_usd: (o as any).unit_usd || 0 }]).map((l) => ({
    order: o.id, date: new Date(o.created * 1000).toISOString().slice(0, 10), status: o.status,
    via: o.channel === 'mcp' ? 'outside AI agent (MCP)' : "Lena's sales agent", state: o.ship_state,
    car: l.title, colour: l.title.split(' ')[0], qty: l.qty, revenue: Math.round(l.qty * l.unit_usd * 100) / 100,
  })));
}

const adapter = shopAdapter();

function App() {
  const [data, setData] = useState<AgDataSourcesDefinition>();
  useEffect(() => {
    fetch('/api/maker/orders').then((r) => r.json()).then((o: Order[]) => { const r = rows(o); (window as any).__rows = r; setData({ sources: [{ id: 'sales', data: r }] }); })
      .catch((e) => { (window as any).__err = String(e); });
  }, []);
  const ai = useMemo<AgAiHarnessSetup>(() => ({ api }) => createAiHarness(api, {
    adapter,
    promptStarters: [
      { label: 'Cars sold by model', prompt: 'Add a bar chart of cars sold (qty) by car.' },
      { label: 'Sales by state', prompt: 'Add a bar chart of revenue by state.' },
    ],
  }), []);
  return <AgStudio style={{ height: '100%', width: '100%' }} data={data} mode="edit" ai={ai} />;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode><AgStudioProvider licenseKey={import.meta.env.VITE_AG_STUDIO_LICENSE} modules={[AgStudioAiModule]}><App /></AgStudioProvider></StrictMode>,
);

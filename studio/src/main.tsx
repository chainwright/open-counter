window.addEventListener('error', (e) => { (window as any).__errs = [...((window as any).__errs || []), String(e.message)]; });
window.addEventListener('unhandledrejection', (e) => { (window as any).__errs = [...((window as any).__errs || []), String((e as any).reason)]; });
import React, { StrictMode, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AgStudio, AgStudioProvider, createWidgets } from 'ag-studio-react';
import StuckWidget from './StuckWidget';
import SoldStrip from './SoldStrip';
import './widgets.css';
import { AgStudioAiModule, createAiHarness, type AgAiHarnessSetup, type AgDataSourcesDefinition } from 'ag-studio';
import { shopAdapter } from './adapter';
import { workshopTheme } from './theme';

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
    Promise.all([fetch('/api/maker/orders').then((r) => r.json()), fetch('/api/maker/daily?days=14').then((r) => (r.ok ? r.json() : [])).catch(() => [])])
      .then(([o, d]: [Order[], any[]]) => { const r = rows(o); (window as any).__rows = r;
        setData({ sources: [{ id: 'sales', data: r }, { id: 'daily', data: d.map((x) => ({ ...x, day: x.day })) }] }); })
      .catch((e) => { (window as any).__err = String(e); });
  }, []);
  const ai = useMemo<AgAiHarnessSetup>(() => ({ api }) => createAiHarness(api, {
    adapter,
    promptStarters: [
      { label: 'Cars sold by model', prompt: 'Add a bar chart of cars sold (qty) by car.' },
      { label: 'Sales by state', prompt: 'Add a bar chart of revenue by state.' },
    ],
  }), []);
  const widgets = useMemo(() => (cfg: any) => createWidgets({
    additionalTypes: [{
      id: 'agent-stuck',
      label: 'Where my agent got stuck',
      // the shape of this widget's format: just the period. Studio exposes its shape builder to command factories,
      // so we borrow it there (public api.defineAiCommand) instead of reaching into internals.
      formatShape: ({ api }: any) => {
        let shape: any;
        api.defineAiCommand((b: any) => {
          shape = b.object({ days: b.number({ description: 'How many days back to look (default 7).' }).optional(),
                              widget: b.object({}).optional() });
          return { input: shape, execute: () => null };
        });
        return shape;
      },
      ai: {
        label: 'Where my agent got stuck',
        description: "A ledger of the shop's AI sales agent's mistakes: what the shopper asked, the agent's original reply struck through, the lesson Lena wrote, and for every later chat the lesson applied to a tick (followed) or a cross (not followed), plus the paid value of orders from those chats. Rows with no lesson yet have a 'Draft a lesson' button.",
        usage: "Use when the user asks where the shop's agent went wrong, what it got stuck on, which lessons work, or how to teach/coach the agent. Not for sales totals.",
        configuration: 'No data mapping: it reads the shop\'s own records. Give it a large slot (about 16 tracks wide).',
      },
      form: (params: any) => params.createDefaults({ dataMappingItems: [] }),
      comp: StuckWidget,
      defaultSize: { width: 900, height: 520 },
      minSize: { width: 520, height: 300 },
    } as any, {
      id: 'agent-sold',
      label: 'Sold to an agent',
      formatShape: ({ api }: any) => {
        let shape: any;
        api.defineAiCommand((b: any) => {
          shape = b.object({ days: b.number({ description: 'Period in days (default 7).' }).optional(), widget: b.object({}).optional() });
          return { input: shape, execute: () => null };
        });
        return shape;
      },
      ai: {
        label: 'Sold to an agent',
        description: "A strip of three big numbers for the period: orders an outside AI agent placed over MCP (red accent), orders from Lena's own sales chat, and made-to-order builds, plus the newest MCP sale with its PayPal status.",
        usage: 'Use when the user asks how many sales came from AI agents, MCP, or by channel. Not for revenue trends.',
        configuration: 'No data mapping. Full width, short (about 6 rows).',
      },
      form: (params: any) => params.createDefaults({ dataMappingItems: [] }),
      comp: SoldStrip,
      defaultSize: { width: 1200, height: 150 },
      minSize: { width: 480, height: 120 },
    } as any],
    menu: [{ label: "Lena's shop", widgetIds: ['agent-stuck', 'agent-sold'] }, ...cfg.menu],
  }), []);
  const initialState = useMemo(() => ({
    pages: [{ id: 'week', name: 'This week',
      widgets: { sold: { type: 'agent-sold', format: { days: 7 } }, stuck: { type: 'agent-stuck', format: { days: 7 } },
        funnel: { type: 'column-chart-grouped', format: { title: { enabled: true, text: 'Chats vs orders · last 14 days' } },
          dataMapping: { categoryKey: [{ id: 'daily.day' }], valueKey: [{ id: 'daily.chats', aggregation: 'sum' }, { id: 'daily.orders', aggregation: 'sum' }] } } },
      widgetLayout: { sold: { xTrack: 0, yTrack: 0, xSpan: 24, ySpan: 11 }, stuck: { xTrack: 0, yTrack: 11, xSpan: 16, ySpan: 52 }, funnel: { xTrack: 16, yTrack: 11, xSpan: 8, ySpan: 30 } } }],
    selectedPageId: 'week',
    panels: { filters: { collapsed: true }, compose: { collapsed: true }, data: { collapsed: true } },
  }), []);
  return <AgStudio style={{ height: '100%', width: '100%' }} data={data} mode="edit" ai={ai} theme={workshopTheme}
    widgets={widgets as any} initialState={initialState as any} />;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode><AgStudioProvider licenseKey={import.meta.env.VITE_AG_STUDIO_LICENSE} modules={[AgStudioAiModule]}><App /></AgStudioProvider></StrictMode>,
);

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
import { studioAi } from './harness';

// Spike: Lena's orders as one flat table (one row per car line), Studio's own agents on Nemotron through our server.
type Order = { id: string; created: number; status: string; channel: string; ship_state: string;
  lines?: { title: string; qty: number; unit_usd: number }[]; shipping_usd: number };

// the order's state in a few words, so the grid's narrow slot shows it whole
const STATUS: Record<string, string> = { awaiting_approval: 'in PayPal', pending: 'in PayPal', deposit_paid: 'deposit in',
  refunded_out_of_stock: 'refunded', refund_due: 'refund due', payment_failed: 'failed' };

function rows(orders: Order[]) {
  return [...orders].sort((a, b) => b.created - a.created).flatMap((o) => (o.lines?.length ? o.lines : [{ title: (o as any).title || 'Made to order', qty: (o as any).qty || 1, unit_usd: (o as any).unit_usd || 0 }]).map((l) => ({
    order: o.id, date: new Date(o.created * 1000).toISOString().slice(0, 10), status: STATUS[o.status] || o.status.replace(/_/g, ' '), order_at: o.created,
    day: new Date(o.created * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
    via: o.channel === 'mcp' ? 'MCP' : 'chat', state: o.ship_state,
    car: l.title, colour: l.title.split(' ')[0], qty: l.qty, amount: Math.round(l.qty * l.unit_usd * 100) / 100,
    record: (o as any).sample ? 'SAMPLE' : 'live',
  })));
}

const adapter = shopAdapter();

function App() {
  const [data, setData] = useState<AgDataSourcesDefinition>();
  useEffect(() => {
    Promise.all([fetch('/api/maker/orders').then((r) => r.json()), fetch('/api/maker/daily?days=14').then((r) => (r.ok ? r.json() : [])).catch(() => [])])
      .then(([o, d]: [Order[], any[]]) => { const r = rows(o); (window as any).__rows = r;
        setData({ sources: [{ id: 'sales', data: r }, { id: 'daily', data: d.map((x) => ({ day: new Date(x.day + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' }), Chats: x.chats, Orders: x.orders })) }] }); })
      .catch((e) => { (window as any).__err = String(e); });
  }, []);
  const ai = useMemo<AgAiHarnessSetup>(() => studioAi([
    { label: 'Where did my agent go wrong?', prompt: "Ask Lena's shop analyst where my agent went wrong this week and whether her lessons worked." },
    { label: 'Agent checkouts', prompt: 'How many checkouts did outside AI agents start this week, and how many are paid?' },
    { label: 'Cars sold by model', prompt: 'Add a bar chart of cars sold (qty) by car.' },
  ]), []);
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
      label: 'Agent checkouts',
      formatShape: ({ api }: any) => {
        let shape: any;
        api.defineAiCommand((b: any) => {
          shape = b.object({ days: b.number({ description: 'Period in days (default 7).' }).optional(), widget: b.object({}).optional() });
          return { input: shape, execute: () => null };
        });
        return shape;
      },
      ai: {
        label: 'Agent checkouts',
        description: "A strip of three big numbers for the period: checkouts an outside AI agent started over MCP (red accent), checkouts from Lena's own sales chat, and made-to-order builds (each counted once started, paid or still awaiting the buyer's approval in PayPal), plus the newest MCP checkout with its PayPal status.",
        usage: 'Use when the user asks how many checkouts or sales came from AI agents, MCP, or by channel. Not for revenue trends.',
        configuration: 'No data mapping. Full width, short (about 6 rows).',
      },
      form: (params: any) => params.createDefaults({ dataMappingItems: [] }),
      comp: SoldStrip,
      defaultSize: { width: 1200, height: 150 },
      minSize: { width: 480, height: 120 },
    } as any],
    menu: [{ label: "Lena's shop", widgetIds: ['agent-stuck', 'agent-sold'] }, ...cfg.menu],
  }), []);
  // Laid out for a judge's laptop (1280–1440 wide, final judges 08.11): the ledger and its payoff above the fold, the
  // chart's title whole, and under the chart a stock AG Grid widget on the orders source.
  // the ledger's height follows the window (one grid track is about 16-17 px), so its payoff line is in view at 720 px too
  const tall = Math.max(28, Math.min(42, Math.floor((innerHeight - 215) / 17)));
  const chartH = Math.round(tall * 0.45);
  // on a 1280-1400 px window the right column takes one more track, so the orders grid shows Via too
  const right = innerWidth < 1400 ? 10 : 9;
  const initialState = useMemo(() => ({
    pages: [{ id: 'week', name: 'This week',
      widgets: { sold: { type: 'agent-sold', format: { days: 7 } }, stuck: { type: 'agent-stuck', format: { days: 7 } },
        funnel: { type: 'column-chart-grouped', format: { title: { enabled: true, text: 'Chats vs orders' },
          subtitle: { enabled: true, text: 'Last 14 days, by day' },
          style: { theme: { common: { legend: { enabled: true, position: 'bottom' } } } } },
          dataMapping: { categoryKey: [{ id: 'daily.day' }], valueKey: [{ id: 'daily.Chats', aggregation: 'sum' }, { id: 'daily.Orders', aggregation: 'sum' }] } },
        orders: { type: 'grid', format: { title: { enabled: true, text: 'Orders · newest first' }, style: { columnAutoSize: true } },
          sort: [{ field: { id: 'sales.order_at' }, direction: 'desc' }],
          // money, PayPal status, channel and the SAMPLE mark first, the long car name last, so a 290-530 px slot
          // shows the columns that make it an orders grid (round-2 judges 08.11: only Day and Car were in view)
          dataMapping: { cols: [{ id: 'sales.day' }, { id: 'sales.record' }, { id: 'sales.amount' }, { id: 'sales.status' },
            { id: 'sales.via' }, { id: 'sales.car' }] } } },
      widgetLayout: { sold: { xTrack: 0, yTrack: 0, xSpan: 24, ySpan: 8 }, stuck: { xTrack: 0, yTrack: 8, xSpan: 24 - right, ySpan: tall },
        funnel: { xTrack: 24 - right, yTrack: 8, xSpan: right, ySpan: chartH },
        orders: { xTrack: 24 - right, yTrack: 8 + chartH, xSpan: right, ySpan: tall - chartH } } }],
    selectedPageId: 'week',
    panels: { filters: { collapsed: true }, edit: { collapsed: true }, data: { collapsed: true }, ai: { width: 300 } },
  }), []);
  const q = new URLSearchParams(location.search);
  const focus = q.get('focus') === 'loop';
  const viewOnly = focus || q.has('view');   // recording: no edit frame when a widget button is clicked
  const loopState = useMemo(() => ({
    pages: [{ id: 'week', name: 'This week',
      widgets: { sold: { type: 'agent-sold', format: { days: 7 } }, stuck: { type: 'agent-stuck', format: { days: 7 } } },
      widgetLayout: { sold: { xTrack: 0, yTrack: 0, xSpan: 24, ySpan: 11 }, stuck: { xTrack: 0, yTrack: 11, xSpan: 24, ySpan: 46 } } }],
    selectedPageId: 'week', panels: { filters: { collapsed: true } },
  }), []);
  return <AgStudio style={{ height: '100%', width: '100%' }} data={data} mode={viewOnly ? 'view' : 'edit'} ai={ai} theme={workshopTheme}
    widgets={widgets as any} initialState={(focus ? loopState : initialState) as any} />;
}

// A phone (or the loop page's pane on a phone) gets the two widgets on their own, one under the other: Studio's
// editor needs about 600 px and would scroll sideways (final judges 08.11). The widgets are the same components, so
// Draft a lesson, Accept and the live ticks work here too; the top bar says Studio is best on a laptop.
function PhoneView() {
  return (
    <div className="oc-phone-view">
      <div className="oc-phone-card"><SoldStrip format={{ days: 7 }} /></div>
      <div className="oc-phone-card"><StuckWidget format={{ days: 7 }} /></div>
    </div>
  );
}

const narrow = matchMedia('(max-width: 900px)').matches;
createRoot(document.getElementById('root')!).render(narrow ? <StrictMode><PhoneView /></StrictMode> :
  <StrictMode><AgStudioProvider licenseKey={(window as any).__AG_STUDIO_LICENSE__ || import.meta.env.VITE_AG_STUDIO_LICENSE} modules={[AgStudioAiModule]}><App /></AgStudioProvider></StrictMode>,
);

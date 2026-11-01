import { createAiHarness, directLlmRunner } from 'ag-studio';
import type { AgAiHarnessSetup } from 'ag-studio';
import { shopAdapter } from './adapter';

// The studio's AI: AG's five built-in agents plus ours, "Lena's shop analyst", all on Nemotron through our server.
// Ours knows the shop (its agent's mistakes and lessons, who sold this week's orders) through two tools that call the
// shop's own endpoints, so every number is computed in code. The Lead hands it shop questions; it hands widget work on
// to Studio's Widget agent — the chain the chat panel shows as Lead → Lena's shop analyst → Widget agent.

const adapter = shopAdapter();
const visitor = () => localStorage.getItem('oc_visitor') || '';
const get = (url: string) => fetch(url, { headers: { 'x-visitor': visitor() } }).then((r) => r.json());

const SHOP_INSTRUCTIONS = `You are Lena's shop analyst. Lena hand-paints 1:43 model cars and sells them through her own AI sales
agent and to outside AI agents over MCP. You answer questions about that sales agent: where it got stuck, which of
Lena's lessons it followed, and who sold this week's orders.
Use your tools for every number; never estimate. Keep answers to two or three plain sentences.
When the user wants to SEE it on the dashboard, delegate to the widget agent and ask it to add the custom widget
"agent-stuck" (where the agent got stuck, lessons, ticks) or "agent-sold" (sold to an agent strip), not a generic chart.
To CHANGE a widget already on the page, hand it to the widget agent with its type and id:
delegate_to({"type": {"id": "widget", "widgetType": "agent-stuck", "widgetId": "stuck"}, "instructions": "<what to change>"})
To ADD a new one, hand it to the page agent, which places widgets on the grid:
delegate_to({"type": {"id": "page", "pageId": "week"}, "instructions": "Add an agent-stuck widget (where my agent got stuck) for the last 14 days next to the chart"})
Never say a widget was added unless the page agent reported placing it.`;

export const studioAi = (promptStarters: { label: string; prompt: string }[]): AgAiHarnessSetup => ({ api }) => {
  const agentMisses = api.defineAiTool({
    name: 'agent_misses',
    description: "The shop's AI sales agent this period: each lesson Lena wrote, the answer it corrected, and for every later chat whether the agent followed it; plus replies where it got stuck with no lesson yet, and the paid value of orders from chats the lessons touched.",
    params: (s: any) => s.object({ days: s.number({ description: 'Days back, default 7.' }).optional() }),
    execute: async (args: any, ctx: any) => {
      const d = await get(`/api/maker/agent_misses?days=${args?.days ?? 7}`);
      return ctx.success({
        lessons: d.taught.map((t: any) => ({ lesson: t.note, asked: t.asked, followed: t.followed, missed: t.missed })),
        stuck_without_lesson: d.open.map((o: any) => ({ asked: o.asked, agent_said: o.said })),
        paid_orders_usd_from_touched_chats: d.orders_usd,
      });
    },
  } as any);
  const agentSales = api.defineAiTool({
    name: 'agent_sales',
    description: "This period's orders by who sold them: an outside AI agent over MCP, Lena's own sales chat, or a made-to-order build; plus the newest MCP sale and its PayPal status.",
    params: (s: any) => s.object({ days: s.number({ description: 'Days back, default 7.' }).optional() }),
    execute: async (args: any, ctx: any) => ctx.success(await get(`/api/maker/agent_sales?days=${args?.days ?? 7}`)),
  } as any);

  return createAiHarness(api, ({ tools, builtIn }: any) => {
    const builtIns = ['planning', 'data', 'page', 'widget'] as const;
    const lead = directLlmRunner({
      ...builtIn.lead,
      adapter,
      instructions: (ctx: any, p: any) => builtIn.lead.instructions(ctx, p) +
        "\n\nThis dashboard belongs to Lena's shop. Questions about the shop's AI sales agent — its mistakes, Lena's lessons, " +
        "whether it followed them, or sales by channel (outside AI over MCP vs her chat) — go to 'shop' (Lena's shop analyst). " +
        'Call it exactly like this: delegate_to({"type": {"id": "shop"}, "instructions": "<the question>"}). ' +
        "Do not re-configure the shop's custom widgets yourself; the shop analyst knows them.",
      tools: (ctx: any) => {
        const orig = builtIn.lead.tools?.(ctx) ?? [];
        const mine = ctx.tools.delegateTo([...builtIns, 'shop']);   // Studio's own delegate tool, with our agent added
        return [...orig.filter((t: any) => t.name !== mine.name), mine];
      },
    });
    const shop = directLlmRunner({
      id: 'shop',
      name: "Lena's shop analyst",
      description: "Knows the shop's AI sales agent: where it got stuck, Lena's lessons and whether they were followed, and orders by channel (MCP vs her chat). Can ask the page agent to add the shop's custom widgets and the widget agent to change them.",
      adapter,
      instructions: () => SHOP_INSTRUCTIONS,
      tools: (ctx: any) => [agentMisses, agentSales, ctx.tools.delegateTo(['page', 'widget'])],
    } as any);
    return {
      agents: [lead, ...builtIns.map((id) => directLlmRunner({ ...builtIn[id], adapter })), shop],
      primary: 'lead',
      promptStarters,
    };
  });
};

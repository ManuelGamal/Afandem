const $ = (s) => document.querySelector(s);

// Lucide icon paths (ISC licence), inlined so the page has no icon dependency.
const ICONS = {
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  cart: '<circle cx="8" cy="21" r="1"/><circle cx="19" cy="21" r="1"/><path d="M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  reset: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
  send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
  pen: '<path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.375 2.625a1 1 0 0 1 3 3l-9.013 9.014a2 2 0 0 1-.853.505l-2.873.84a.5.5 0 0 1-.62-.62l.84-2.873a2 2 0 0 1 .506-.852z"/>',
  menu: '<line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="6" y2="6"/><line x1="4" x2="20" y1="18" y2="18"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  chart: '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
  calc: '<rect width="16" height="20" x="4" y="2" rx="2"/><line x1="8" x2="16" y1="6" y2="6"/><line x1="16" x2="16" y1="14" y2="18"/><path d="M16 10h.01M12 10h.01M8 10h.01M12 14h.01M8 14h.01M12 18h.01M8 18h.01"/>',
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  message: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  timer: '<line x1="10" x2="14" y1="2" y2="2"/><line x1="12" x2="15" y1="14" y2="11"/><circle cx="12" cy="14" r="8"/>',
  check: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/>',
  cash: '<rect width="20" height="12" x="2" y="6" rx="2"/><circle cx="12" cy="12" r="2"/><path d="M6 12h.01M18 12h.01"/>',
  trend: '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
  truck: '<path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/><path d="M15 18H9"/><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.624l-3.48-4.35A1 1 0 0 0 17.52 8H14"/><circle cx="17" cy="18" r="2"/><circle cx="7" cy="18" r="2"/>',
  user: '<circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/>',
  box: '<path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
  chevron: '<path d="m15 18-6-6 6-6"/>',
};
const icon = (name, cls = "") =>
  `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;

const STATUS = {
  draft: ["Draft", ""], pending_confirmation: ["Awaiting confirmation", "info"],
  confirmed: ["Confirmed", "ok"], shipped: ["Shipped", "ok"], cancelled: ["Cancelled", "danger"],
  needs_human: ["With a person", "warn"],
};
const RISK = { low: ["Low", "ok"], medium: ["Medium", "warn"], high: ["High", "danger"] };
const CANCEL = { customer_declined: "customer declined", unreachable: "no reply", duplicate: "duplicate",
  out_of_stock: "out of stock", other: "other" };
const TOOL_LABEL = { search_products: "Search products", get_product: "Product details",
  recommend_size: "Size recommendation", quote_delivery: "Delivery quote", create_order: "Create order",
  update_order: "Update order", confirm_order: "Confirm order", cancel_order: "Cancel order",
  schedule_delivery: "Schedule delivery", flag_risk: "Flag risk", handoff_to_human: "Hand off to a person" };
const STOCK_REASON = { order_confirmed: "order confirmed", order_cancelled: "order cancelled",
  owner_update: "owner update" };
const PANELS = { dashboard: "Dashboard", inventory: "Inventory", roi: "ROI calculator", activity: "Agent activity",
  handoffs: "Needs a person" };
// What a customer would actually type (Egyptian Arabic / Franco), with an English caption.
const SUGGESTIONS = [
  ["الهودي التقيل بكام؟", "Price, sizes and colours from the catalog"],
  ["طولي 178 ووزني 80، آخد مقاس ايه في الهودي؟", "Size from the product's size chart"],
  ["3ayez jeans slim 32 eswed, delivery le el maadi kam?", "Franco (Arabic in English letters): price and delivery"],
  ["التيشيرت اللي جالي مقطوع وعايز فلوسي", "Complaint → handed to a person"],
];

let info = null, state = null, current = "chat-1", busy = false, es = null, timer = null;
let chatCount = 1, openPanelName = null;
const seen = new Set();  // event seq numbers already in the activity log
// ?view=whatsapp&key=… shows the WhatsApp line's conversations to the shop owner
// (read-only here; chat from the phone). The key keeps real customers' details private.
const PARAMS = new URLSearchParams(location.search);
const VIEW = PARAMS.get("view");
const VIEW_Q = VIEW ? `?view=${encodeURIComponent(VIEW)}&key=${encodeURIComponent(PARAMS.get("key") || "")}` : "";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString("en-US"));

async function api(path, body) {
  const opts = body === undefined ? {} : { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opts);
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    throw new Error(typeof e.detail === "string" ? e.detail : r.statusText);
  }
  return r.json();
}

function notice(msg, sticky = false) {
  const n = $("#notice");
  n.textContent = msg;
  n.hidden = false;
  if (!sticky) setTimeout(() => (n.hidden = true), 6000);
}

async function refresh() {
  state = await api(`/api/state${VIEW_Q}`);
  render();
}
function scheduleRefresh() {
  clearTimeout(timer);
  timer = setTimeout(() => { refresh(); if (openPanelName === "inventory") loadInventory(); }, 250);
}

function connect() {
  if (es) es.close();
  es = new EventSource(`/api/events${VIEW_Q}`);
  es.onmessage = (m) => {
    const e = JSON.parse(m.data);
    if (VIEW && e.conversation_id) current = e.conversation_id;  // follow the live phone chat
    logEvent(e);
    scheduleRefresh();
  };
  es.onerror = () => { es.close(); setTimeout(connect, 2000); };
}

function optimistic(convId, text) {
  let c = state.conversations.find((x) => x.id === convId);
  if (!c) {
    c = { id: convId, messages: [], handed_off: false };
    state.conversations.push(c);
  }
  c.messages.push({ role: "customer", text });
}

// --- naming ---------------------------------------------------------------------
function convTitle(c) {
  if (c.id.startsWith("checkout-")) return `Website order ${c.id.split("-")[1]}`;
  if (c.id.startsWith("wa-")) return `WhatsApp +${c.id.slice(3)}`;
  const first = c.messages.find((m) => m.role === "customer");
  if (first) return first.text.length > 32 ? first.text.slice(0, 32) + "…" : first.text;
  return "New chat";
}

// --- render ---------------------------------------------------------------------
const chip = ([text, tone], title = "") =>
  `<span class="chip ${tone}"${title ? ` title="${esc(title)}"` : ""}>${esc(text)}</span>`;

function kpiCard(ic, title, value, unit, hi) {
  return `<div class="kpi${hi ? " highlight" : ""}">
    <span class="kpi-label">${icon(ic)}${esc(title)}</span>
    <span class="kpi-value">${esc(value)}${unit ? `<span class="kpi-unit">${esc(unit)}</span>` : ""}</span>
  </div>`;
}

function renderSidebar() {
  const convs = state.conversations.slice();
  if (!VIEW && !convs.some((c) => c.id === current)) convs.push({ id: current, messages: [] });
  if (VIEW && !convs.some((c) => c.id === current) && convs.length) current = convs[convs.length - 1].id;
  $("#convs").innerHTML = convs.slice().reverse().map((c) => `
    <button class="side-item" type="button" data-conv="${esc(c.id)}" aria-current="${c.id === current}">
      ${icon(c.id.startsWith("checkout-") ? "cart" : "message")}<span>${esc(convTitle(c))}</span>
      ${c.handed_off ? '<span class="dot" aria-label="With a person"></span>' : ""}
    </button>`).join("");
  const handed = state.conversations.filter((c) => c.handed_off).length;
  $("#open-handoffs").innerHTML = `${icon("user")}<span>Needs a person</span>${handed ? `<span class="badge">${handed}</span>` : ""}`;
  const conv = state.conversations.find((c) => c.id === current);
  $("#conv-title").textContent = conv && conv.messages.length ? convTitle(conv) : "Afandem · AI sales assistant for Hodoom";
}

function renderChat() {
  const conv = state.conversations.find((c) => c.id === current);
  const msgs = conv ? conv.messages : [];
  if (!msgs.length && !busy) {
    $("#chat").innerHTML = `<div class="empty">
      <h2>How can I help?</h2>
      <p>Write as a customer of a clothing shop on WhatsApp or Facebook, in Egyptian Arabic, Franco or English, or try one of these:</p>
      <div class="suggestions">${SUGGESTIONS.map(([t, s]) =>
        `<button class="suggestion" type="button" data-say="${esc(t)}"><span dir="auto">${esc(t)}</span><small>${esc(s)}</small></button>`).join("")}</div>
      ${VIEW ? "" : `<button class="start-demo" type="button" data-demo>${icon("play")}Play the full demo (7 scenarios)</button>`}
    </div>`;
    return;
  }
  $("#chat").innerHTML = msgs.map((m) => m.role === "customer"
    ? `<div class="turn customer"><div class="bubble" dir="auto">${esc(m.text)}</div></div>`
    : `<div class="turn agent"><span class="avatar" aria-hidden="true">A</span><div class="text" dir="auto">${esc(m.text)}</div></div>`).join("")
    + (busy ? `<div class="turn agent"><span class="avatar" aria-hidden="true">A</span><div class="typing" aria-label="Typing"><span></span><span></span><span></span></div></div>` : "")
    + (conv && conv.handed_off ? `<div class="sys"><span>${icon("user")}Handed to a person on the team</span></div>` : "");
  $("#chat").scrollTop = 1e9;
}

function renderDashboard() {
  const k = state.impact;
  $("#impact").innerHTML = [
    kpiCard("message", "Messages answered", fmt(k.messages_handled), ""),
    kpiCard("timer", "Median reply time", k.median_reply_s == null ? "—" : k.median_reply_s, "s"),
    kpiCard("check", "Orders confirmed", fmt(k.orders_confirmed), ""),
    kpiCard("shield", "Refusals prevented", fmt(k.refusals_prevented), ""),
    kpiCard("cash", "Delivery cost saved", fmt(k.egp_saved), "EGP", true),
    kpiCard("trend", "Extra sales", fmt(k.upsell_revenue), "EGP", true),
  ].join("");
  const orders = state.orders.slice().reverse();
  $("#orders-count").textContent = orders.length;
  $("#orders tbody").innerHTML = orders.length ? orders.map((o) => {
    const status = STATUS[o.status] || [o.status, ""];
    const reason = o.cancel_reason ? `<span class="sub">${esc(CANCEL[o.cancel_reason] || o.cancel_reason)}</span>` : "";
    const first = o.items[0] ? `<span class="sub">${esc(o.items[0].name_ar)}${o.items.length > 1 ? ` +${o.items.length - 1}` : ""}</span>` : "";
    const why = o.risk.reasons.join(" · ");
    return `<tr>
      <td class="mono">${o.id}</td>
      <td dir="auto">${esc(o.customer_name)}${first}</td>
      <td dir="auto">${esc(o.area)}</td>
      <td class="num">${fmt(o.total)}</td>
      <td>${chip(status)}${reason}</td>
      <td>${chip(RISK[o.risk.level], why)}<span class="sr-only">${esc(why)}</span></td>
      <td>${o.status === "confirmed" ? `<button class="btn-sm" type="button" data-ship="${o.id}">${icon("truck")}Ship</button>` : ""}</td>
    </tr>`;
  }).join("") : `<tr class="empty-row"><td colspan="7">No orders yet. Try “New website order” or “Play demo”.</td></tr>`;

  const handed = state.conversations.filter((c) => c.handed_off);
  $("#handoffs").innerHTML = handed.length
    ? handed.map((c) => `<li><button class="item" type="button" data-conv="${esc(c.id)}">
        <span>${icon("user")} ${esc(convTitle(c))}</span>${icon("chevron")}</button></li>`).join("")
    : `<li class="muted">No conversations are waiting for a person.</li>`;
}

function renderControls() {
  const replay = info && info.mode === "replay";
  const readOnly = replay || VIEW === "whatsapp";
  $("#text").disabled = busy || readOnly;
  $("#btn-send").disabled = busy || readOnly;
  if (replay) $("#text").placeholder = "Recorded demo mode — press “Play demo”";
  if (VIEW === "whatsapp") $("#text").placeholder = "WhatsApp view — write from the phone; the chat appears here";
  for (const id of ["#btn-demo", "#btn-checkout", "#btn-advance", "#btn-reset", "#btn-new"]) {
    $(id).disabled = busy || VIEW === "whatsapp";
  }
}

function render() {
  if (!state) return;
  renderSidebar();
  renderChat();
  renderDashboard();
  renderControls();
  state.events.forEach(logEvent);  // catch up on events missed while disconnected
}

function logEvent(e) {
  if (seen.has(e.seq)) return;
  seen.add(e.seq);
  let kind = "", text = "", tool = "";
  if (e.kind === "tool_call") {
    kind = e.data.ok ? "ok" : "bad";
    text = (TOOL_LABEL[e.data.name] || e.data.name) + (e.data.ok ? "" : ` — ${e.data.error || "error"}`);
    tool = e.data.name;
  } else if (e.kind === "order_status") {
    kind = "order";
    const from = STATUS[e.data.old] ? STATUS[e.data.old][0] : "New";
    text = `Order ${e.data.order_id}: ${from} → ${STATUS[e.data.new][0]}`;
  } else if (e.kind === "stock") {
    kind = "order";
    const d = e.data.delta;
    text = `Stock ${e.data.product_id} ${e.data.size}: ${d > 0 ? "+" : ""}${d} → ${e.data.stock_after} (${STOCK_REASON[e.data.reason] || e.data.reason})`;
  } else if (e.kind === "handoff") {
    kind = "human";
    text = `Handed to a person (${e.data.reason})`;
  } else if (e.kind === "llm_error") {
    kind = "bad";
    text = "Model unavailable right now";
    notice("The free model quota is used up for now. Press “Play demo” to watch the recorded run, or try again later.", true);
  } else {
    return;
  }
  const li = document.createElement("li");
  li.innerHTML = `<time>${esc(e.ts.slice(11))}</time><span class="k ${kind}" aria-hidden="true"></span>
    <span class="t">${esc(text)}${tool ? `<span class="tool" dir="ltr">${esc(tool)}</span>` : ""}</span>`;
  $("#log").prepend(li);
  while ($("#log").children.length > 60) $("#log").lastChild.remove();
}

// --- drawer + sidebar -------------------------------------------------------------
function openPanel(name) {
  openPanelName = name;
  $("#drawer-title").textContent = PANELS[name];
  for (const p of document.querySelectorAll(".panel")) p.classList.toggle("on", p.dataset.panel === name);
  for (const b of document.querySelectorAll(".side-item[data-panel]")) {
    b.setAttribute("aria-current", String(b.dataset.panel === name));
  }
  $("#drawer").hidden = false;
  $("#scrim").hidden = false;
  closeSidebar();
  if (name === "inventory") loadInventory();
  $("#btn-close-drawer").focus();
}
function closePanel() {
  openPanelName = null;
  $("#drawer").hidden = true;
  $("#scrim").hidden = !$("#sidebar").classList.contains("open");
  for (const b of document.querySelectorAll(".side-item[data-panel]")) b.setAttribute("aria-current", "false");
}
function openSidebar() { $("#sidebar").classList.add("open"); $("#scrim").hidden = false; }
function closeSidebar() {
  $("#sidebar").classList.remove("open");
  if (!openPanelName) $("#scrim").hidden = true;
}

// --- actions --------------------------------------------------------------------
async function run(fn) {
  if (busy) return;
  busy = true;
  render();
  try { await fn(); } catch (err) { notice(err.message); }
  finally { busy = false; await refresh(); }
}

async function say(text) {
  optimistic(current, text);
  closeSidebar();
  await run(() => api("/api/chat", { conversation_id: current, text }));
}

async function resetSandbox() {
  await api("/api/reset", {});
  $("#log").innerHTML = "";
  seen.clear();
  chatCount = 1;
  current = "chat-1";
  await refresh();
  connect();
}

async function playDemo() {
  closePanel();
  await resetSandbox();
  for (const script of info.demo_scripts) {
    let conv = script.conversation_id;
    for (const step of script.steps) {
      if (step.checkout !== undefined) {
        const r = await api("/api/checkout", { preset: step.checkout });
        conv = r.conversation_id;
        current = conv;
      } else if (step.advance !== undefined) {
        await api("/api/advance", { hours: step.advance });
      } else {
        current = conv;
        optimistic(conv, step.say);
        render();
        await sleep(600);
        await api("/api/chat", { conversation_id: conv, text: step.say });
      }
      await refresh();
      await sleep(1200);
    }
  }
}

// --- inventory (the shop's database) ----------------------------------------------
async function loadInventory() {
  const inv = await api(`/api/inventory${VIEW_Q}`);
  const source = $("#catalog-source");  // set when the catalog was imported from a real store
  source.hidden = !inv.catalog_source;
  source.textContent = inv.catalog_source ? `Catalog imported from ${inv.catalog_source}. ${inv.stock_note || ""}` : "";
  const byProduct = new Map();
  for (const r of inv.rows) {
    if (!byProduct.has(r.product_id)) byProduct.set(r.product_id, { name: r.name, name_en: r.name_en, sizes: [] });
    byProduct.get(r.product_id).sizes.push(r);
  }
  $("#inventory").innerHTML = [...byProduct.entries()].map(([pid, p]) => `
    <div class="inv-row">
      <div class="inv-name"><span dir="auto">${esc(p.name)}</span><small>${esc(pid)} · ${esc(p.name_en)}</small></div>
      <div class="inv-sizes">${p.sizes.map((s) => `
        <label class="stock-cell${s.stock === 0 ? " out" : s.low ? " low" : ""}">${esc(s.size)}
          <input type="number" min="0" max="10000" value="${s.stock}" data-pid="${esc(pid)}" data-size="${esc(s.size)}"
                 aria-label="${esc(p.name_en)} size ${esc(s.size)} stock">
        </label>`).join("")}</div>
    </div>`).join("");
  $("#movements").innerHTML = inv.movements.length ? inv.movements.map((m) => `
    <li><time>${esc(m.product_id)} ${esc(m.size)}</time><span class="k order" aria-hidden="true"></span>
      <span class="t">${m.delta > 0 ? "+" : ""}${m.delta} → ${m.stock_after} · ${esc(STOCK_REASON[m.reason] || m.reason)}${m.order_id ? ` (order ${m.order_id})` : ""}</span></li>`).join("")
    : `<li class="muted">No stock movements yet. Confirm an order or edit a number above.</li>`;
}

$("#inventory").addEventListener("change", async (ev) => {
  const input = ev.target.closest("input[data-pid]");
  if (!input || input.value === "") return;
  try {
    await api(`/api/inventory${VIEW_Q}`, { product_id: input.dataset.pid, size: input.dataset.size,
      stock: Number(input.value) });
  } catch (err) { notice(err.message); }
  loadInventory();
});

// --- ROI calculator ---------------------------------------------------------------
const ROI_FIELDS = { orders: "#roi-orders", dms: "#roi-dms", salary: "#roi-salary",
  refusal: "#roi-refusal", aov: "#roi-aov" };
let roiTimer = null;

async function updateRoi() {
  const q = new URLSearchParams();
  for (const [k, sel] of Object.entries(ROI_FIELDS)) {
    const v = $(sel).value;
    if (v !== "") q.set(k, k === "refusal" ? String(Number(v) / 100) : v);
  }
  let r;
  try { r = await api(`/api/roi?${q}`); } catch (err) { return; }  // invalid input: keep last result
  const days = r.payback_days == null ? "—" : r.payback_days < 1 ? "< 1 day" : `${r.payback_days} days`;
  $("#roi-out").innerHTML = [
    kpiCard("cash", "Net saved / month", fmt(r.net_cost_saved), "EGP", true),
    kpiCard("timer", "Pays for itself in", days, "", true),
    kpiCard("clock", "Hours saved / week", r.hours_saved_week, ""),
    kpiCard("shield", "Refusals prevented / month", fmt(r.refusals_prevented), ""),
    kpiCard("trend", "Extra sales / month (estimate)", fmt(r.revenue_total), "EGP"),
  ].join("") + `<p class="roi-note">Running cost (model + hosting) is about ${fmt(r.running_cost_egp)} EGP/month.
       Same model as the bench report, with your numbers; the other assumptions are cited there.</p>`;
}

async function initRoi() {
  const r = await api("/api/roi");
  const d = r.defaults;
  $("#roi-orders").value = d.cod_orders_per_day;
  $("#roi-dms").value = d.dms_per_day;
  $("#roi-salary").value = d.moderator_salary_egp_month;
  $("#roi-refusal").value = Math.round(d.refusal_rate_without_confirmation * 100);
  $("#roi-aov").value = d.average_order_egp;
  $("#roi-form").addEventListener("input", () => { clearTimeout(roiTimer); roiTimer = setTimeout(updateRoi, 300); });
  $("#roi-form").addEventListener("submit", (ev) => ev.preventDefault());
  updateRoi();
}

// --- wiring -----------------------------------------------------------------------
$("#btn-new").innerHTML = `${icon("pen")}<span>New chat</span>`;
$("#btn-demo").innerHTML = `${icon("play")}<span>Play demo</span>`;
$("#btn-checkout").innerHTML = `${icon("cart")}<span>New website order</span>`;
$("#btn-advance").innerHTML = `${icon("clock")}<span>Skip ahead 2 hours</span>`;
$("#btn-reset").innerHTML = `${icon("reset")}<span>Start over</span>`;
$("#open-dashboard").innerHTML = `${icon("chart")}<span>Dashboard</span>`;
$("#open-inventory").innerHTML = `${icon("box")}<span>Inventory</span>`;
$("#open-roi").innerHTML = `${icon("calc")}<span>ROI calculator</span>`;
$("#open-activity").innerHTML = `${icon("activity")}<span>Agent activity</span>`;
$("#btn-send").innerHTML = icon("send");
$("#btn-open-side").innerHTML = icon("menu");
$("#btn-close-side").innerHTML = icon("x");
$("#btn-close-drawer").innerHTML = icon("x");

$("#composer").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const text = $("#text").value.trim();
  if (!text) return;
  $("#text").value = "";
  say(text);
});
$("#btn-new").onclick = () => { chatCount += 1; current = `chat-${chatCount}`; closeSidebar(); render(); $("#text").focus(); };
$("#btn-checkout").onclick = () => { closeSidebar(); run(async () => {
  const r = await api("/api/checkout", { preset: null });
  current = r.conversation_id;
}); };
$("#btn-advance").onclick = () => { closeSidebar(); run(() => api("/api/advance", { hours: 2 })); };
$("#btn-reset").onclick = () => { closeSidebar(); run(resetSandbox); };
$("#btn-demo").onclick = () => { closeSidebar(); run(playDemo); };
$("#btn-open-side").onclick = openSidebar;
$("#btn-close-side").onclick = closeSidebar;
$("#btn-close-drawer").onclick = closePanel;
$("#scrim").onclick = () => { closePanel(); closeSidebar(); };
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") { closePanel(); closeSidebar(); }
});
document.addEventListener("click", (ev) => {
  const panel = ev.target.closest(".side-item[data-panel]");
  if (panel) return openPanel(panel.dataset.panel);
  const ship = ev.target.closest("[data-ship]");
  if (ship) return run(() => api(`/api/orders/${ship.dataset.ship}/ship`, {}));
  const suggestion = ev.target.closest("[data-say]");
  if (suggestion && !$("#text").disabled) return say(suggestion.dataset.say);
  if (ev.target.closest("[data-demo]")) return run(playDemo);
  const conv = ev.target.closest("[data-conv]");
  if (conv) { current = conv.dataset.conv; closePanel(); closeSidebar(); render(); }
});

(async () => {
  info = await api("/api/info");
  const replay = info.mode === "replay";
  const mode = $("#mode");
  mode.textContent = VIEW === "whatsapp" ? "WhatsApp · live" : replay ? "Recorded demo" : "Live";
  mode.classList.add(replay ? "replay" : "live");
  if (info.notice) {
    notice("No model API key found, so this is the recorded demo: press “Play demo”. "
      + "Add a free GEMINI_API_KEY to chat live (see the README).", true);
    $("#notice").title = info.notice;
  }
  await refresh();
  connect();
  initRoi();
})();

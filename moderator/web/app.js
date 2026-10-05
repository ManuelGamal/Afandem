const $ = (s) => document.querySelector(s);

// Lucide icon paths (ISC licence), inlined so the page has no icon dependency.
const ICONS = {
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  cart: '<circle cx="8" cy="21" r="1"/><circle cx="19" cy="21" r="1"/><path d="M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  reset: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
  send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
  message: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  timer: '<line x1="10" x2="14" y1="2" y2="2"/><line x1="12" x2="15" y1="14" y2="11"/><circle cx="12" cy="14" r="8"/>',
  check: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/>',
  cash: '<rect width="20" height="12" x="2" y="6" rx="2"/><circle cx="12" cy="12" r="2"/><path d="M6 12h.01M18 12h.01"/>',
  trend: '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
  truck: '<path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/><path d="M15 18H9"/><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.624l-3.48-4.35A1 1 0 0 0 17.52 8H14"/><circle cx="17" cy="18" r="2"/><circle cx="7" cy="18" r="2"/>',
  user: '<circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/>',
  chevron: '<path d="m15 18-6-6 6-6"/>',
};
const icon = (name, cls = "") =>
  `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;

const STATUS = {
  draft: ["مسودة", ""], pending_confirmation: ["مستني تأكيد", "info"], confirmed: ["متأكد", "ok"],
  shipped: ["اتشحن", "ok"], cancelled: ["اتلغى", "danger"], needs_human: ["مع موظف", "warn"],
};
const RISK = { low: ["قليلة", "ok"], medium: ["متوسطة", "warn"], high: ["عالية", "danger"] };
const CANCEL = { customer_declined: "العميل رفض", unreachable: "مبيردش", duplicate: "مكرر",
  out_of_stock: "خلص من المخزون", other: "سبب تاني" };
const TOOL_AR = { search_products: "بحث في المنتجات", get_product: "تفاصيل منتج",
  recommend_size: "ترشيح مقاس", quote_delivery: "سعر الشحن", create_order: "إنشاء طلب",
  update_order: "تعديل طلب", confirm_order: "تأكيد طلب", cancel_order: "إلغاء طلب",
  schedule_delivery: "تحديد معاد التوصيل", flag_risk: "ملاحظة مخاطرة", handoff_to_human: "تحويل لموظف" };

let info = null, state = null, current = "chat-1", busy = false, es = null, timer = null;
// ?view=whatsapp shows the WhatsApp line's conversations (read-only here; chat from the phone).
const VIEW = new URLSearchParams(location.search).get("view");
const VIEW_Q = VIEW ? `?view=${encodeURIComponent(VIEW)}` : "";
const seen = new Set();  // event seq numbers already in the activity log
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

function label(id) {
  if (id.startsWith("checkout-")) return "طلب موقع " + id.split("-")[1];
  if (id === "chat-1") return "شات جديد";
  return id.replace("demo-", "");
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
  timer = setTimeout(refresh, 250);
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

const chip = ([text, tone], title = "") =>
  `<span class="chip ${tone}"${title ? ` title="${esc(title)}"` : ""}>${esc(text)}</span>`;

function renderKpis(k) {
  const cards = [
    ["message", "رسايل اتردّ عليها", fmt(k.messages_handled), ""],
    ["timer", "متوسط وقت الرد", k.median_reply_s == null ? "—" : k.median_reply_s, "ثانية"],
    ["check", "طلبات اتأكدت", fmt(k.orders_confirmed), ""],
    ["shield", "مرتجعات اتمنعت", fmt(k.refusals_prevented), ""],
    ["cash", "توفير في الشحن", fmt(k.egp_saved), "ج.م", true],
    ["trend", "مبيعات إضافية", fmt(k.upsell_revenue), "ج.م", true],
  ];
  $("#impact").innerHTML = cards.map(([ic, t, v, unit, hi]) => `
    <div class="kpi${hi ? " highlight" : ""}">
      <span class="kpi-label">${icon(ic)}${esc(t)}</span>
      <span class="kpi-value">${esc(v)}${unit ? `<span class="kpi-unit">${esc(unit)}</span>` : ""}</span>
    </div>`).join("");
}

function renderChat() {
  const ids = state.conversations.map((c) => c.id);
  const tabs = VIEW ? ids : (ids.includes("chat-1") ? ids : ["chat-1", ...ids]);
  if (VIEW && !ids.includes(current) && ids.length) current = ids[ids.length - 1];
  $("#tabs").innerHTML = tabs.map((id) => {
    const c = state.conversations.find((x) => x.id === id);
    const on = id === current;
    return `<button class="tab" role="tab" type="button" aria-selected="${on}" data-id="${esc(id)}">
      ${c && c.handed_off ? '<span class="flag" aria-hidden="true"></span>' : ""}${esc(label(id))}</button>`;
  }).join("");

  const conv = state.conversations.find((c) => c.id === current);
  const msgs = conv ? conv.messages : [];
  if (!msgs.length && !busy) {
    $("#chat").innerHTML = `<div class="empty"><strong>ابدأ محادثة</strong>
      اكتب سؤال كعميل، أو دوس «شغّل الديمو» تشوف ٧ سيناريوهات كاملة.</div>`;
  } else {
    $("#chat").innerHTML = msgs.map((m) => `
      <div class="msg ${m.role}">
        <span class="who">${m.role === "customer" ? "العميل" : "وصلة"}</span>
        <div class="bubble">${esc(m.text).replace(/\n/g, "<br>")}</div>
      </div>`).join("")
      + (busy ? `<div class="msg agent typing" aria-label="بيكتب"><div class="bubble"><span></span><span></span><span></span></div></div>` : "")
      + (conv && conv.handed_off ? `<div class="sys">${icon("user")}اتحوّلت لموظف من الفريق</div>` : "");
  }
  $("#chat").scrollTop = 1e9;
}

function renderOrders() {
  const orders = state.orders.slice().reverse();
  $("#orders-count").textContent = orders.length;
  $("#orders tbody").innerHTML = orders.length ? orders.map((o) => {
    const status = STATUS[o.status] || [o.status, ""];
    const reason = o.cancel_reason ? `<span class="sub">${esc(CANCEL[o.cancel_reason] || o.cancel_reason)}</span>` : "";
    const first = o.items[0] ? `<span class="sub">${esc(o.items[0].name_ar)}${o.items.length > 1 ? ` +${o.items.length - 1}` : ""}</span>` : "";
    const why = o.risk.reasons.join(" · ");
    return `<tr>
      <td class="mono">${o.id}</td>
      <td>${esc(o.customer_name)}${first}</td>
      <td>${esc(o.area)}</td>
      <td class="num">${fmt(o.total)}</td>
      <td>${chip(status)}${reason}</td>
      <td>${chip(RISK[o.risk.level], why)}<span class="sr-only">${esc(why)}</span></td>
      <td>${o.status === "confirmed" ? `<button class="btn btn-sm" type="button" data-ship="${o.id}">${icon("truck")}شحن</button>` : ""}</td>
    </tr>`;
  }).join("") : `<tr class="empty-row"><td colspan="7">لسه مفيش طلبات. دوس «طلب من الموقع» أو «شغّل الديمو».</td></tr>`;

  const handed = state.conversations.filter((c) => c.handed_off);
  $("#handoff-count").textContent = handed.length;
  $("#handoffs").innerHTML = handed.length
    ? handed.map((c) => `<li><button class="item" type="button" data-id="${esc(c.id)}">
        <span>${icon("user")} ${esc(label(c.id))}</span>${icon("chevron")}</button></li>`).join("")
    : `<li class="muted">مفيش محادثات مستنية موظف.</li>`;
}

function renderControls() {
  const replay = info && info.mode === "replay";
  const readOnly = replay || VIEW === "whatsapp";
  $("#text").disabled = busy || readOnly;
  $("#btn-send").disabled = busy || readOnly;
  if (VIEW === "whatsapp") $("#text").placeholder = "واتساب: اكتب من الموبايل والمحادثة هتظهر هنا";
  if (replay) $("#text").placeholder = "وضع العرض المسجّل: دوس «شغّل الديمو»";
  for (const b of document.querySelectorAll(".actions .btn")) b.disabled = busy || VIEW === "whatsapp";
}

function render() {
  if (!state) return;
  renderKpis(state.impact);
  renderChat();
  renderOrders();
  renderControls();
  state.events.forEach(logEvent);  // catch up on events missed while disconnected
}

function logEvent(e) {
  if (seen.has(e.seq)) return;
  seen.add(e.seq);
  let kind = "", text = "", tool = "";
  if (e.kind === "tool_call") {
    kind = e.data.ok ? "ok" : "bad";
    text = (TOOL_AR[e.data.name] || e.data.name) + (e.data.ok ? "" : ` — ${e.data.error || "خطأ"}`);
    tool = e.data.name;
  } else if (e.kind === "order_status") {
    kind = "order";
    const from = STATUS[e.data.old] ? STATUS[e.data.old][0] : "جديد";
    text = `طلب ${e.data.order_id}: ${from} ← ${STATUS[e.data.new][0]}`;
  } else if (e.kind === "handoff") {
    kind = "human";
    text = `تحويل لموظف (${e.data.reason})`;
  } else if (e.kind === "llm_error") {
    kind = "bad";
    text = "الموديل مش متاح دلوقتي";
    notice("حصة الموديل المجانية خلصت دلوقتي — دوس «شغّل الديمو» تشوف العرض المسجّل، أو جرّب بعد شوية.", true);
  } else {
    return;
  }
  const li = document.createElement("li");
  li.innerHTML = `<time>${esc(e.ts.slice(11))}</time><span class="k ${kind}" aria-hidden="true"></span>
    <span class="t">${esc(text)}${tool ? `<span class="tool" dir="ltr">${esc(tool)}</span>` : ""}</span>`;
  $("#log").prepend(li);
  while ($("#log").children.length > 40) $("#log").lastChild.remove();
}

async function run(fn) {
  if (busy) return;
  busy = true;
  render();
  try { await fn(); } catch (err) { notice(err.message); }
  finally { busy = false; await refresh(); }
}

async function resetSandbox() {
  await api("/api/reset", {});
  $("#log").innerHTML = "";
  seen.clear();
  current = "chat-1";
  await refresh();
  connect();
}

async function playDemo() {
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

// --- ROI calculator ------------------------------------------------------------
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
  const days = r.payback_days == null ? "—" : r.payback_days < 1 ? "أقل من يوم" : `${r.payback_days} يوم`;
  const cards = [
    ["cash", "توفير صافي / شهر", fmt(r.net_cost_saved), "ج.م", true],
    ["timer", "يغطي تكلفته في", days, "", true],
    ["clock", "ساعات موفرة / أسبوع", r.hours_saved_week, ""],
    ["shield", "مرتجعات اتمنعت / شهر", fmt(r.refusals_prevented), ""],
    ["trend", "مبيعات إضافية / شهر (تقديرية)", fmt(r.revenue_total), "ج.م"],
  ];
  $("#roi-out").innerHTML = cards.map(([ic, t, v, unit, hi]) => `
    <div class="kpi${hi ? " highlight" : ""}">
      <span class="kpi-label">${icon(ic)}${esc(t)}</span>
      <span class="kpi-value">${esc(v)}${unit ? `<span class="kpi-unit">${esc(unit)}</span>` : ""}</span>
    </div>`).join("")
    + `<p class="roi-note">تكلفة التشغيل (موديل + استضافة) حوالي ${fmt(r.running_cost_egp)} ج.م/شهر.
       الحسبة: نفس نموذج التقرير بالأرقام اللي فوق، والباقي افتراضات مذكور مصدرها.</p>`;
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

$("#btn-demo").innerHTML = `${icon("play")}شغّل الديمو`;
$("#btn-checkout").innerHTML = `${icon("cart")}طلب من الموقع`;
$("#btn-advance").innerHTML = `${icon("clock")}عدّي ساعتين`;
$("#btn-reset").innerHTML = `${icon("reset")}ابدأ من جديد`;
$("#btn-send").innerHTML = icon("send", "flip");

$("#composer").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const text = $("#text").value.trim();
  if (!text) return;
  $("#text").value = "";
  optimistic(current, text);
  run(() => api("/api/chat", { conversation_id: current, text }));
});
$("#btn-checkout").onclick = () => run(async () => {
  const r = await api("/api/checkout", { preset: null });
  current = r.conversation_id;
});
$("#btn-advance").onclick = () => run(() => api("/api/advance", { hours: 2 }));
$("#btn-reset").onclick = () => run(resetSandbox);
$("#btn-demo").onclick = () => run(playDemo);
document.addEventListener("click", (ev) => {
  const ship = ev.target.closest("[data-ship]");
  if (ship) return run(() => api(`/api/orders/${ship.dataset.ship}/ship`, {}));
  const tab = ev.target.closest("[data-id]");
  if (tab) { current = tab.dataset.id; render(); }
});

(async () => {
  info = await api("/api/info");
  const replay = info.mode === "replay";
  const mode = $("#mode");
  mode.textContent = VIEW === "whatsapp" ? "واتساب مباشر" : replay ? "عرض مسجّل" : "مباشر";
  mode.classList.add(replay ? "replay" : "live");
  if (info.notice) {
    notice("مفيش مفتاح للموديل، فبنعرض الديمو المسجّل — دوس «شغّل الديمو». "
      + "(Add a free GEMINI_API_KEY to chat live — see README.)", true);
    $("#notice").title = info.notice;
  }
  await refresh();
  connect();
  initRoi();
})();

const $ = (s) => document.querySelector(s);
const STATUS = { draft: "مسودة", pending_confirmation: "مستني تأكيد", confirmed: "متأكد",
  shipped: "اتشحن", cancelled: "اتلغى", needs_human: "مع موظف" };
const RISK = { low: "قليلة", medium: "متوسطة", high: "عالية" };
const TOOL_AR = { search_products: "بحث في المنتجات", get_product: "تفاصيل منتج",
  recommend_size: "ترشيح مقاس", quote_delivery: "سعر الشحن", create_order: "إنشاء طلب",
  update_order: "تعديل طلب", confirm_order: "تأكيد طلب", cancel_order: "إلغاء طلب",
  schedule_delivery: "تحديد معاد", flag_risk: "ملاحظة مخاطرة", handoff_to_human: "تحويل لموظف" };

let info = null, state = null, current = "chat-1", busy = false, es = null, timer = null;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

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
  state = await api("/api/state");
  render();
}
function scheduleRefresh() {
  clearTimeout(timer);
  timer = setTimeout(refresh, 250);
}

function connect() {
  if (es) es.close();
  es = new EventSource("/api/events");
  es.onmessage = (m) => { logEvent(JSON.parse(m.data)); scheduleRefresh(); };
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

function render() {
  if (!state) return;
  const ids = state.conversations.map((c) => c.id);
  const tabs = ids.includes("chat-1") ? ids : ["chat-1", ...ids];
  $("#tabs").innerHTML = tabs.map((id) =>
    `<button class="tab ${id === current ? "on" : ""}" data-id="${esc(id)}">${esc(label(id))}</button>`).join("");

  const conv = state.conversations.find((c) => c.id === current);
  $("#chat").innerHTML = (conv ? conv.messages : []).map((m) =>
    `<div class="msg ${m.role}">${esc(m.text).replace(/\n/g, "<br>")}</div>`).join("")
    + (busy ? `<div class="msg agent typing">بيكتب…</div>` : "")
    + (conv && conv.handed_off ? `<div class="sys">اتحوّل لموظف</div>` : "");
  $("#chat").scrollTop = 1e9;

  const k = state.impact;
  const cards = [["رسايل اتردّ عليها", k.messages_handled],
    ["متوسط وقت الرد", k.median_reply_s == null ? "—" : `${k.median_reply_s} ث`],
    ["طلبات اتأكدت", k.orders_confirmed], ["مرتجعات اتمنعت", k.refusals_prevented],
    ["توفير شحن (ج)", k.egp_saved], ["مبيعات إضافية (ج)", k.upsell_revenue]];
  $("#impact").innerHTML = cards.map(([t, v]) =>
    `<div class="card"><b>${esc(v)}</b><span>${esc(t)}</span></div>`).join("");

  $("#orders tbody").innerHTML = state.orders.slice().reverse().map((o) => `<tr>
    <td>${o.id}</td><td>${esc(o.customer_name)}</td><td>${esc(o.area)}</td><td>${o.total}</td>
    <td><span class="st ${o.status}">${STATUS[o.status]}</span>${o.cancel_reason ? ` <small>(${esc(o.cancel_reason)})</small>` : ""}</td>
    <td><span class="risk ${o.risk.level}" title="${esc(o.risk.reasons.join(" · "))}">${RISK[o.risk.level]}</span></td>
    <td>${o.status === "confirmed" ? `<button class="ship" data-ship="${o.id}">شحن</button>` : ""}</td></tr>`).join("");

  const handed = state.conversations.filter((c) => c.handed_off);
  $("#handoffs").innerHTML = handed.length
    ? handed.map((c) => `<li><button class="link" data-id="${esc(c.id)}">${esc(label(c.id))}</button></li>`).join("")
    : `<li class="muted">مفيش</li>`;

  const replay = info && info.mode === "replay";
  $("#text").disabled = busy || replay;
  if (replay) $("#text").placeholder = "وضع العرض المسجّل: دوس ▶ شغّل الديمو";
  for (const b of document.querySelectorAll("header button")) b.disabled = busy;
}

function logEvent(e) {
  let text = null;
  if (e.kind === "tool_call") text = `🔧 ${TOOL_AR[e.data.name] || e.data.name} ${e.data.ok ? "✓" : "✗ " + (e.data.error || "")}`;
  else if (e.kind === "order_status") text = `📦 طلب ${e.data.order_id}: ${STATUS[e.data.old] || "جديد"} ⬅ ${STATUS[e.data.new]}`;
  else if (e.kind === "handoff") text = `🙋 تحويل لموظف: ${e.data.reason}`;
  else if (e.kind === "llm_error") {
    text = `⚠️ ${e.data.error}`;
    notice("حصة الموديل المجانية خلصت دلوقتي — دوس ▶ شغّل الديمو تشوف العرض المسجّل، أو جرّب بعد شوية.", true);
  }
  if (!text) return;
  const li = document.createElement("li");
  li.textContent = `${e.ts.slice(11)} ${text}`;
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
  $("#mode").textContent = info.mode === "replay" ? "عرض مسجّل (من غير مفتاح)" : "مباشر";
  if (info.notice) {
    notice("مفيش مفتاح للموديل، فبنعرض الديمو المسجّل — دوس ▶ شغّل الديمو. "
      + "(Add a free GEMINI_API_KEY to chat live — see README.)", true);
    $("#notice").title = info.notice;
  }
  await refresh();
  connect();
})();

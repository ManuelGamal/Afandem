"""One tool-calling loop for inbound sales chats and outbound order confirmations."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal

from moderator.agent.prompt import build_system_prompt
from moderator.agent.tools import TOOL_SCHEMAS, ToolContext, run_tool
from moderator.clock import Clock
from moderator.events import EventBus
from moderator.providers.client import ProviderError
from moderator.store.catalog import Catalog
from moderator.store.orders import OrderBook, order_fingerprint, summary_ar
from moderator.text import clean_digits, fold_text, is_latin_script, money_mentions

INTERNAL_PREFIX = "[حدث داخلي]"
FALLBACK_TEXT = "معلش عندنا مشكلة تقنية صغيرة دلوقتي 🙏 حد من فريقنا هيرد عليك في أقرب وقت."
OVERFLOW_TEXT = "ثانية واحدة يا فندم، هحوّلك لحد من الفريق يساعدك أحسن 🙏"
LATIN_HINT = ("\nREPLY STYLE FOR THIS TURN: the customer wrote in Latin letters. Reply in Latin "
              "letters too: Arabizi (Egyptian Arabic with 3, 7, 2, 5 for Arabic sounds) if they "
              "wrote Egyptian words, English if they wrote English.")
_ASSISTANT_KEYS = ("role", "content", "tool_calls", "extra_content")
# Deliberately digit-free, so the correction itself never becomes an "allowed" amount.
AMOUNT_GUARD_NOTE = (f"{INTERNAL_PREFIX} ردك الأخير فيه مبلغ مش طالع من نتايج الأدوات في المحادثة دي. "
                     "متكتبش أي سعر أو مصاريف شحن أو إجمالي إلا لو رجع من أداة؛ استخدم الأداة المناسبة "
                     "واكتب الرد تاني.")
MAX_AMOUNT_CORRECTIONS = 2
CLAIM_NOTES = {
    "confirmed": (f"{INTERNAL_PREFIX} ردك بيقول إن الطلب اتأكد، لكنه لسه مش متأكد في النظام. "
                  "متقولش كده؛ لو العميل وافق بوضوح استخدم confirm_order، وإلا ابعت الملخص واسأله يأكد."),
    "cancelled": (f"{INTERNAL_PREFIX} ردك بيقول إن الطلب اتلغى، لكنه لسه مش ملغي في النظام. "
                  "لو العميل طلب الإلغاء استخدم cancel_order الأول، وإلا متقولش إنه اتلغى."),
}
# Matched on fold_text(reply).
_CLAIMS = {
    "confirmed": re.compile(r"تم( \S+){0,2} (ال)?تاكيد|اتاكد|اكدت|اكدنا|الطلب موكد|"
                            r"confirmed|akadna|a2adna|akkedna|a2kedna|et2ak+[ae]d"),
    "cancelled": re.compile(r"تم (ال)?الغاء|اتلغ|لغيت|لغينا|cancelled|canceled|lagheena|elghena"),
}
_HANDOFF_PROMISE = re.compile(r"هحول|بحول|حولت|هنحول|حولنا|تحويل (الشات|المحادثه|حضرتك|طلبك)|ha7awel|ha7wel|7awelt")
_TOOL_NAMES = [t["function"]["name"] for t in TOOL_SCHEMAS]
_LEAKED_CALL = re.compile(r"\[?\s*(" + "|".join(_TOOL_NAMES) + r")\s*\([^)]*\)\s*\]?")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _greeting(name: str) -> str:
    first = (name or "").split()[0] if (name or "").strip() else ""
    return f"أهلاً يا {first}!" if len(first) > 1 else "أهلاً بحضرتك!"


def _false_claim(text: str, order) -> str | None:
    """'confirmed'/'cancelled' when the reply claims that about the conversation's latest order
    but the system says otherwise (an open order, or one held for a person)."""
    if order is None:
        return None
    actual = {"confirmed": order.status in ("confirmed", "shipped"),
              "cancelled": order.status == "cancelled"}
    folded = fold_text(text)
    for kind, pattern in _CLAIMS.items():
        if not actual[kind] and pattern.search(folded):
            return kind
    return None


def _strip_leaked_calls(text: str) -> tuple[str, list[str]]:
    """Remove tool calls the model wrote as plain text; return the clean text and their names."""
    names = _LEAKED_CALL.findall(text)
    return _LEAKED_CALL.sub("", text).strip(), names


def _unsupported_amounts(text: str, messages: list[dict]) -> list[Decimal]:
    """Amounts next to a currency word that no tool result or customer message contains."""
    allowed: set[Decimal] = set()
    for m in messages:
        if m["role"] in ("tool", "user") and isinstance(m.get("content"), str):
            allowed |= {Decimal(n) for n in _NUMBER.findall(clean_digits(m["content"]).replace(",", ""))}
    return [a for a in money_mentions(text) if a not in allowed]


@dataclass
class Conversation:
    id: str
    messages: list[dict] = field(default_factory=list)
    handed_off: bool = False
    order_id: int | None = None
    reminders_sent: int = 0
    awaiting_reply: bool = False
    shown_fingerprint: str | None = None  # the order as last shown with its total

    def last_agent_text(self) -> str:
        for m in reversed(self.messages):
            if m["role"] == "assistant" and isinstance(m.get("content"), str) and m["content"]:
                return m["content"]
        return ""

    def visible(self) -> list[dict]:
        out = []
        for m in self.messages:
            if m["role"] == "user" and not m["content"].startswith(INTERNAL_PREFIX):
                out.append({"role": "customer", "text": m["content"]})
            elif m["role"] == "assistant" and m.get("content"):
                out.append({"role": "agent", "text": m["content"]})
        return out


class Agent:
    def __init__(self, catalog: Catalog, book: OrderBook, bus: EventBus, clock: Clock, provider,
                 max_tool_calls: int = 6):
        self.catalog = catalog
        self.book = book
        self.bus = bus
        self.clock = clock
        self.provider = provider
        self.max_tool_calls = max_tool_calls

    # --- entry points ---------------------------------------------------------
    def reply(self, conv: Conversation, text: str) -> list[str]:
        started = time.perf_counter()
        self.bus.publish("message_in", conv.id, text=text)
        if conv.handed_off:
            return []
        last_agent = conv.last_agent_text()
        conv.messages.append({"role": "user", "content": text})
        conv.awaiting_reply = False
        return self._run(conv, text, last_agent, started)

    # Business-initiated messages are fixed templates (as WhatsApp Business requires), so the
    # opening always carries the exact summary and costs no model call. Replies use the model.
    def start_confirmation(self, conv: Conversation, order_id: int) -> list[str]:
        conv.order_id = order_id
        order = self.book.get(order_id)
        summary = summary_ar(order, self.catalog.find_zone(order.area))
        text = (f"{_greeting(order.customer_name)} شكراً لطلبك من موقع "
                f"{self.catalog.shop['name_ar']} 🌸\nده ملخص الطلب قبل ما نجهزه للشحن:\n\n"
                f"{summary}\n\nأأكد الطلب؟")
        conv.messages.append({"role": "user", "content": (
            f"{INTERNAL_PREFIX} طلب جديد من الموقع رقم {order_id} محتاج تأكيد قبل الشحن. "
            "اتبعت للعميل رسالة التأكيد الثابتة بالملخص ده:\n" + summary)})
        conv.messages.append({"role": "assistant", "content": text})
        self._sent(conv, text, time.perf_counter())
        conv.awaiting_reply = True
        return [text]

    def remind(self, conv: Conversation) -> list[str]:
        if not conv.awaiting_reply or conv.handed_off or conv.order_id is None:
            return []
        order = self.book.get(conv.order_id)
        if order.status != "pending_confirmation":
            return []
        if conv.reminders_sent == 0:
            conv.reminders_sent = 1
            text = (f"{_greeting(order.customer_name)} بنفكّرك بطلبك رقم {order.id} "
                    f"(الإجمالي {order.total} جنيه). نأكده ونجهزه للشحن؟ ولو حابب تعدّل حاجة قولّي.")
            conv.messages.append({"role": "user", "content": (
                f"{INTERNAL_PREFIX} العميل مردش من ساعتين؛ اتبعتله تذكير ثابت بالطلب رقم "
                f"{order.id} والإجمالي {order.total} جنيه.")})
            conv.messages.append({"role": "assistant", "content": text})
            self._sent(conv, text, time.perf_counter())
            return [text]
        order, old = self.book.set_status(order.id, "cancelled", "unreachable")
        self.bus.publish("order_status", conv.id, order_id=order.id, old=old, new="cancelled",
                         reason="unreachable", total=order.total, source=order.source)
        conv.awaiting_reply = False
        return []

    # --- internals ------------------------------------------------------------
    def _run(self, conv: Conversation, customer_message: str, last_agent: str,
             started: float) -> list[str]:
        ctx = ToolContext(self.catalog, self.book, self.bus, self.clock, conv.id,
                          last_agent, customer_message, shown_fingerprint=conv.shown_fingerprint)
        calls = 0
        corrections = 0
        while True:
            prompt = build_system_prompt(self.catalog, self.clock.now())
            if is_latin_script(customer_message):
                prompt += LATIN_HINT
            system = {"role": "system", "content": prompt}
            t0 = time.perf_counter()
            try:
                raw = self.provider.complete([system] + conv.messages, TOOL_SCHEMAS)
            except ProviderError as e:
                self.bus.publish("llm_error", conv.id, provider=self.provider.name,
                                 error=str(e)[:300])
                return self._fallback(conv, ctx, FALLBACK_TEXT, "provider_failure", started)
            usage = raw.get("usage") or {}
            self.bus.publish("llm_call", conv.id, provider=raw.get("_provider", "?"),
                             tokens_in=usage.get("prompt_tokens", 0),
                             tokens_out=usage.get("completion_tokens", 0),
                             latency_s=round(time.perf_counter() - t0, 2))
            try:
                msg = raw["choices"][0]["message"]
            except (KeyError, IndexError, TypeError):
                return self._fallback(conv, ctx, FALLBACK_TEXT, "bad_response", started)
            tool_calls = msg.get("tool_calls") or []
            conv.messages.append({k: msg[k] for k in _ASSISTANT_KEYS if msg.get(k) is not None}
                                 | {"role": "assistant"})
            if not tool_calls:
                text, leaked = _strip_leaked_calls(msg.get("content") or "")
                if "handoff_to_human" in leaked and not ctx.handed_off:
                    run_tool("handoff_to_human", {"reason": "agent_requested"}, ctx)
                if not text:
                    conv.messages.pop()
                    if corrections >= MAX_AMOUNT_CORRECTIONS:
                        return self._fallback(conv, ctx, FALLBACK_TEXT, "empty_response", started)
                    corrections += 1
                    continue
                if _unsupported_amounts(text, conv.messages):
                    conv.messages.pop()
                    if corrections >= MAX_AMOUNT_CORRECTIONS:
                        return self._fallback(conv, ctx, OVERFLOW_TEXT, "unsupported_amount",
                                              started)
                    corrections += 1
                    conv.messages.append({"role": "user", "content": AMOUNT_GUARD_NOTE})
                    continue
                claim = _false_claim(text, self.book.latest_for(conv.id))
                if claim:
                    conv.messages.pop()
                    if corrections >= MAX_AMOUNT_CORRECTIONS:
                        return self._fallback(conv, ctx, OVERFLOW_TEXT, f"false_{claim}_claim",
                                              started)
                    corrections += 1
                    conv.messages.append({"role": "user", "content": CLAIM_NOTES[claim]})
                    continue
                if _HANDOFF_PROMISE.search(fold_text(text)) and not ctx.handed_off:
                    run_tool("handoff_to_human", {"reason": "agent_promised_handoff"}, ctx)
                conv.messages[-1]["content"] = text
                conv.handed_off = conv.handed_off or ctx.handed_off
                self._sent(conv, text, started)
                return [text]
            for call in tool_calls:
                calls += 1
                fn = call.get("function", {})
                if calls > self.max_tool_calls:
                    result = {"ok": False, "error": "too_many_calls"}
                else:
                    result = run_tool(fn.get("name", ""), fn.get("arguments") or "{}", ctx)
                conv.messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                      "content": json.dumps(result, ensure_ascii=False)})
            if calls > self.max_tool_calls:
                return self._fallback(conv, ctx, OVERFLOW_TEXT, "too_many_tool_calls", started)

    def _fallback(self, conv: Conversation, ctx: ToolContext, text: str, reason: str,
                  started: float) -> list[str]:
        if not ctx.handed_off:
            run_tool("handoff_to_human", {"reason": reason}, ctx)
        conv.handed_off = True
        conv.messages.append({"role": "assistant", "content": text})
        self._sent(conv, text, started)
        return [text]

    def _sent(self, conv: Conversation, text: str, started: float) -> None:
        self.bus.publish("message_out", conv.id, text=text,
                         latency_s=round(time.perf_counter() - started, 2))
        order = self.book.open_for(conv.id)
        if order is not None and str(order.total) in clean_digits(text).replace(",", ""):
            conv.shown_fingerprint = order_fingerprint(order)

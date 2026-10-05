"""One tool-calling loop for inbound sales chats and outbound order confirmations."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from moderator.agent.prompt import build_system_prompt
from moderator.agent.tools import TOOL_SCHEMAS, ToolContext, run_tool
from moderator.clock import Clock
from moderator.events import EventBus
from moderator.providers.client import ProviderError
from moderator.store.catalog import Catalog
from moderator.store.orders import OrderBook, summary_ar
from moderator.text import is_latin_script

INTERNAL_PREFIX = "[حدث داخلي]"
FALLBACK_TEXT = "معلش عندنا مشكلة تقنية صغيرة دلوقتي 🙏 حد من فريقنا هيرد عليك في أقرب وقت."
OVERFLOW_TEXT = "ثانية واحدة يا فندم، هحوّلك لحد من الفريق يساعدك أحسن 🙏"
LATIN_HINT = ("\nREPLY STYLE FOR THIS TURN: the customer wrote in Latin letters. Reply in Latin "
              "letters too: Arabizi (Egyptian Arabic with 3, 7, 2, 5 for Arabic sounds) if they "
              "wrote Egyptian words, English if they wrote English.")
_ASSISTANT_KEYS = ("role", "content", "tool_calls", "extra_content")


@dataclass
class Conversation:
    id: str
    messages: list[dict] = field(default_factory=list)
    handed_off: bool = False
    order_id: int | None = None
    reminders_sent: int = 0
    awaiting_reply: bool = False

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

    def start_confirmation(self, conv: Conversation, order_id: int) -> list[str]:
        conv.order_id = order_id
        order = self.book.get(order_id)
        zone = self.catalog.find_zone(order.area)
        conv.messages.append({"role": "user", "content": (
            f"{INTERNAL_PREFIX} طلب جديد من الموقع رقم {order_id} محتاج تأكيد قبل الشحن. "
            "ابعت للعميل رسالة ترحيب قصيرة باسمه وبعدها ملخص الطلب ده بالنص واسأله يأكد:\n"
            + summary_ar(order, zone))})
        out = self._run(conv, "", "", time.perf_counter())
        conv.awaiting_reply = not conv.handed_off
        return out

    def remind(self, conv: Conversation) -> list[str]:
        if not conv.awaiting_reply or conv.handed_off or conv.order_id is None:
            return []
        order = self.book.get(conv.order_id)
        if order.status != "pending_confirmation":
            return []
        if conv.reminders_sent == 0:
            conv.reminders_sent = 1
            conv.messages.append({"role": "user", "content": (
                f"{INTERNAL_PREFIX} العميل مردش من ساعتين. ابعت تذكير واحد قصير ولطيف بالطلب "
                f"والإجمالي ({order.total} جنيه) واسأله يأكد.")})
            return self._run(conv, "", "", time.perf_counter())
        order, old = self.book.set_status(order.id, "cancelled", "unreachable")
        self.bus.publish("order_status", conv.id, order_id=order.id, old=old, new="cancelled",
                         reason="unreachable", total=order.total, source=order.source)
        conv.awaiting_reply = False
        return []

    # --- internals ------------------------------------------------------------
    def _run(self, conv: Conversation, customer_message: str, last_agent: str,
             started: float) -> list[str]:
        ctx = ToolContext(self.catalog, self.book, self.bus, self.clock, conv.id,
                          last_agent, customer_message)
        calls = 0
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
                text = (msg.get("content") or "").strip()
                if not text:
                    conv.messages.pop()
                    return self._fallback(conv, ctx, FALLBACK_TEXT, "empty_response", started)
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

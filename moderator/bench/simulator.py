"""An LLM plays the customer from a card. It sees only the card and the visible chat."""

from __future__ import annotations

import re

from moderator.bench.cards import Card

_THOUGHT = re.compile(r"<thought>.*?</thought>", re.S)

STYLES = {
    "arabic": "Write only in Egyptian Arabic (Arabic script), casual and short, like WhatsApp.",
    "arabizi": "Write only in Arabizi: Egyptian Arabic in Latin letters with numbers "
               "(3=ع, 7=ح, 2=ء, 5=خ), casual and short, like WhatsApp.",
    "mixed": "Mix Egyptian Arabic (Arabic script) with English words, like many Cairo "
             "customers, casual and short.",
}

PROMPT = """You are role-playing a customer chatting on WhatsApp with an Egyptian online clothing shop.
{persona}
Writing style: {style}
Your goal: {goal}
Hidden facts (reveal only when relevant): {facts}

Rules:
- Write ONLY your next message as the customer: 1-2 short lines, no quotes, no narration.
- Stay consistent with your persona and facts. Don't volunteer details before you are asked.
- When your goal is complete (order confirmed or cancelled as you wanted, you got your answer and
  left, or you were told a human will contact you) or the shop has nothing more to offer, reply
  exactly [DONE]."""


class CustomerSim:
    def __init__(self, provider, card: Card):
        self.provider = provider
        self.system = PROMPT.format(persona=card.persona, style=STYLES[card.script],
                                    goal=card.goal,
                                    facts="; ".join(card.hidden_facts) or "none")

    def next_message(self, transcript: list[dict]) -> str | None:
        messages = [{"role": "system", "content": self.system},
                    {"role": "user", "content": "[the shop chat is open]"}]
        for m in transcript:
            role = "assistant" if m["role"] == "customer" else "user"
            if messages[-1]["role"] == role:
                messages[-1]["content"] += "\n" + m["text"]
            else:
                messages.append({"role": role, "content": m["text"]})
        text = self._ask(messages)
        if text is None and transcript and transcript[-1]["role"] == "agent" \
                and _asks_question(transcript[-1]["text"]):
            # Simulators tend to quit on an open question (e.g. "أأكد الطلب؟"); that would be a
            # simulator failure scored against the agent, so nudge once.
            text = self._ask(messages + [{"role": "system", "content": NUDGE}])
        return text

    def _ask(self, messages: list[dict]) -> str | None:
        raw = self.provider.complete(messages, [])
        text = _THOUGHT.sub("", raw["choices"][0]["message"].get("content") or "").strip()
        if not text or "[DONE]" in text:
            return None
        return text


NUDGE = ("The shop just asked you a question (for example whether to confirm the order). Answer it "
         "according to your goal and hidden facts instead of ending the chat.")


def _asks_question(text: str) -> bool:
    """A question mark near the end, allowing for a trailing emoji or two."""
    tail = text.strip()[-15:]
    return "?" in tail or "؟" in tail

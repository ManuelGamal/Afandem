"""Run bench cards. Resumable: one JSON per card; a provider failure aborts without saving.

    uv run python -m moderator.bench.runner --out bench/results/run1 [--limit 10] [--category declines]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from moderator.bench.cards import Card, load_cards
from moderator.bench.simulator import CustomerSim
from moderator.providers.client import ProviderError
from moderator.providers.config import build_provider
from moderator.session import Session


class RunAborted(Exception):
    pass


def run_card(card: Card, agent_provider, sim_provider) -> dict:
    s = Session(agent_provider)
    ended = None
    if card.flow == "checkout":
        conv_id, _, _ = s.checkout_order(card.checkout)
        if card.no_reply:
            s.advance(2)
            s.advance(2)
            ended = "no_reply"
    else:
        conv_id = f"bench-{card.id}"
        s.chat(conv_id, card.opening)
    turns = 0 if card.flow == "checkout" else 1
    sim = CustomerSim(sim_provider, card)
    while ended is None:
        conv = s.conversations[conv_id]
        if any(e.kind == "llm_error" for e in s.bus.events):
            raise RunAborted(f"{card.id}: agent provider failed")
        if conv.handed_off:
            ended = "handoff"
        elif turns >= card.max_turns:
            ended = "max_turns"
        else:
            try:
                msg = sim.next_message(conv.visible())
            except ProviderError as e:
                raise RunAborted(f"{card.id}: simulator provider failed: {e}") from e
            if msg is None:
                ended = "done"
            else:
                s.chat(conv_id, msg)
                turns += 1
    if any(e.kind == "llm_error" for e in s.bus.events):
        raise RunAborted(f"{card.id}: agent provider failed")
    conv = s.conversations[conv_id]
    return {"card_id": card.id, "category": card.category, "script": card.script,
            "flow": card.flow, "turns": turns, "ended_by": ended,
            "transcript": conv.visible(), "raw_messages": conv.messages,
            "orders": [o.to_dict() for o in s.book.all()],
            "events": [e.to_dict() for e in s.bus.events]}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--category")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    agent_provider = build_provider("live", cache_path=Path("cache/bench-agent.jsonl"))
    sim_provider = build_provider("live", cache_path=Path("cache/bench-sim.jsonl"))
    cards = [c for c in load_cards() if not args.category or c.category == args.category]
    done = 0
    for card in cards:
        path = out / f"{card.id}.json"
        if path.exists():
            continue
        if args.limit is not None and done >= args.limit:
            break
        try:
            result = run_card(card, agent_provider, sim_provider)
        except RunAborted as e:
            print(f"stopped: {e}. Re-run the same command later to resume.")
            sys.exit(2)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        done += 1
        print(f"{card.id:14} {result['ended_by']:9} turns={result['turns']}")
    print(f"ran {done} cards; {len(list(out.glob('*.json')))}/{len(cards)} done in {out}")


if __name__ == "__main__":
    main()

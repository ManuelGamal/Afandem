"""Run bench cards. Resumable: one JSON per card; a provider failure aborts without saving.

    uv run python -m moderator.bench.runner --out bench/results/run1 [--limit 10] [--category declines]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from moderator.bench.cards import CARDS_DIR, Card, load_cards
from moderator.bench.simulator import CustomerSim, HumanSim
from moderator.providers.client import ProviderError
from moderator.providers.config import build_provider
from moderator.session import Session


SIM_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "providers-sim.yaml"


class RunAborted(Exception):
    pass


def run_card(card: Card, agent_provider, sim_provider, sim=None) -> dict:
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
    sim = sim or CustomerSim(sim_provider, card)
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


def run_with_retries(card: Card, agent_provider, sim_provider, attempts: int = 3,
                     wait_s: float = 60.0, sleep=time.sleep, run=None) -> dict:
    """Free-tier models hit short spikes of 429/503; wait and retry a card before giving up."""
    run = run or run_card
    for attempt in range(1, attempts + 1):
        try:
            return run(card, agent_provider, sim_provider)
        except RunAborted:
            if attempt == attempts:
                raise
            sleep(wait_s)
    raise AssertionError("unreachable")


def make_providers(cache_dir: Path, sim_config: Path = SIM_CONFIG):
    """The agent (MODERATOR_PROVIDERS may replace its config) and the simulated customer (never
    replaced by it), each with its own response cache in `cache_dir`."""
    agent = build_provider("live", cache_path=cache_dir / "bench-agent.jsonl")
    sim = build_provider("live", config_path=sim_config, cache_path=cache_dir / "bench-sim.jsonl",
                         env_override=False)
    return agent, sim


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--category")
    ap.add_argument("--human", action="store_true", help="you play the customer in the terminal")
    ap.add_argument("--ids", help="comma-separated card ids to run")
    ap.add_argument("--cards", default=str(CARDS_DIR), help="card folder (bench/cards-heldout for final numbers)")
    ap.add_argument("--sim-config", default=str(SIM_CONFIG), help="models for the simulated customer")
    ap.add_argument("--cache-dir", default="cache",
                    help="response cache; an empty folder makes every model call live")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    agent_provider, sim_provider = make_providers(Path(args.cache_dir), Path(args.sim_config))
    ids = set(args.ids.split(",")) if args.ids else None
    cards = [c for c in load_cards(Path(args.cards)) if (not args.category or c.category == args.category)
             and (ids is None or c.id in ids)]
    done = 0
    for card in cards:
        path = out / f"{card.id}.json"
        if path.exists():
            continue
        if args.limit is not None and done >= args.limit:
            break
        try:
            if args.human:
                result = run_card(card, agent_provider, None, sim=HumanSim(card))
            else:
                result = run_with_retries(card, agent_provider, sim_provider)
        except RunAborted as e:
            print(f"stopped: {e}. Re-run the same command later to resume.")
            sys.exit(2)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        done += 1
        print(f"{card.id:14} {result['ended_by']:9} turns={result['turns']}")
    print(f"ran {done} cards; {len(list(out.glob('*.json')))}/{len(cards)} done in {out}")


if __name__ == "__main__":
    main()

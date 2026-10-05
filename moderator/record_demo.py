"""Record or check the demo replay.

    uv run python -m moderator.record_demo --mode record   # needs a key; writes replay/demo.jsonl
    uv run python -m moderator.record_demo --mode replay   # no key; exits 1 on any miss
"""

from __future__ import annotations

import argparse
import sys

from moderator.demo_scripts import DEMO_SCRIPTS
from moderator.providers.config import build_provider
from moderator.session import Session


def play(session: Session, scripts: list[dict], echo=print) -> None:
    for script in scripts:
        echo(f"\n=== {script['title']}")
        conv = script["conversation_id"]
        for step in script["steps"]:
            if "checkout" in step:
                conv, order_id, replies = session.checkout(step["checkout"])
                echo(f"[checkout -> order {order_id} in {conv}]")
            elif "advance" in step:
                sent = session.advance(step["advance"])
                echo(f"[+{step['advance']}h]")
                replies = [r for rs in sent.values() for r in rs]
            else:
                echo(f"customer> {step['say']}")
                replies = session.chat(conv, step["say"])
            for r in replies:
                echo(f"agent> {r}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["record", "replay"], required=True)
    args = ap.parse_args()
    provider = build_provider(args.mode)
    session = Session(provider)
    play(session, DEMO_SCRIPTS)
    errors = [e for e in session.bus.events if e.kind == "llm_error"]
    print(f"\ncache hits {provider.hits}, misses {provider.misses}, llm errors {len(errors)}")
    for e in errors:
        print(f"  [{e.conversation_id}] {e.data.get('error')}")
    for o in session.book.all():
        print(o.id, o.status, o.total, o.cancel_reason)
    if errors or (args.mode == "replay" and provider.misses):
        sys.exit(1)


if __name__ == "__main__":
    main()

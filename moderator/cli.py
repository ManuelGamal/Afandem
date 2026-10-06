"""Terminal chat for smoke tests.

    uv run python -m moderator.cli            # live (needs GEMINI_API_KEY or GROQ_API_KEY)
    uv run python -m moderator.cli --mode replay

Commands: /checkout [n]   /advance [hours]   /orders   /new   /quit
"""

from __future__ import annotations

import argparse
import json
import sys

from moderator.providers.config import build_provider
from moderator.session import Session


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="live", choices=["live", "replay", "record"])
    args = ap.parse_args()
    s = Session(build_provider(args.mode))
    conv, n, seen = "cli-1", 1, 0
    print("Afandem جاهز. اكتب رسالتك (أو /quit).")
    while True:
        try:
            line = input("انت> ").strip()
        except EOFError:
            break
        if not line:
            continue
        if line == "/quit":
            break
        if line == "/new":
            n += 1
            conv = f"cli-{n}"
            continue
        if line.startswith("/checkout"):
            parts = line.split()
            conv, oid, replies = s.checkout(int(parts[1]) if len(parts) > 1 else None)
            print(f"[order {oid} in {conv}]")
        elif line.startswith("/advance"):
            parts = line.split()
            for cid, out in s.advance(float(parts[1]) if len(parts) > 1 else 2).items():
                print(f"[{cid}]", *out, sep="\n")
            continue
        elif line == "/orders":
            st = s.state(120)
            for o in st["orders"]:
                print(o["id"], o["status"], o["total"], o["risk"]["level"], o["cancel_reason"])
            print(json.dumps(st["impact"], ensure_ascii=False))
            continue
        else:
            replies = s.chat(conv, line)
        for r in replies:
            print(f"afandem> {r}\n")
        for e in s.bus.events[seen:]:
            if e.kind in ("llm_error", "handoff"):
                print(f"[{e.kind}] {e.data}")
        seen = len(s.bus.events)


if __name__ == "__main__":
    main()

from pathlib import Path

import pytest

from moderator.demo_scripts import DEMO_SCRIPTS
from moderator.providers.client import CachedProvider
from moderator.record_demo import play
from moderator.session import Session

REPLAY = Path(__file__).resolve().parents[1] / "replay" / "demo.jsonl"


@pytest.mark.skipif(not REPLAY.exists(), reason="replay not recorded yet")
def test_demo_replays_without_a_single_miss():
    provider = CachedProvider(None, REPLAY)
    s = Session(provider)
    play(s, DEMO_SCRIPTS, echo=lambda *a: None)
    assert provider.misses == 0
    assert not [e for e in s.bus.events if e.kind == "llm_error"]


class AlwaysText:
    name = "always"

    def complete(self, messages, tools):
        return {"choices": [{"message": {"role": "assistant", "content": "تمام يا فندم"}}],
                "usage": {}, "_provider": self.name}


def test_play_runs_every_step_with_the_page_call_sequence():
    lines = []
    s = Session(AlwaysText())
    play(s, DEMO_SCRIPTS, echo=lines.append)
    assert sum(line.lstrip().startswith("===") for line in lines) == len(DEMO_SCRIPTS)
    says = sum(1 for sc in DEMO_SCRIPTS for st in sc["steps"] if "say" in st)
    assert sum(line.startswith("customer>") for line in lines) == says
    assert [c for c in s.conversations if c.startswith("checkout-")] == [
        "checkout-1", "checkout-2", "checkout-3", "checkout-4"]

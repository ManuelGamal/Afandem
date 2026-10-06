import json

import pytest

from moderator.providers.client import (
    CachedProvider, FallbackChain, ProviderError, ProviderSpec, RateLimited, request_key,
)

MSGS = [{"role": "user", "content": "بكام؟"}]


class Fake:
    def __init__(self, name, outcomes):
        self.name = name
        self.outcomes = list(outcomes)
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return {**out, "_provider": self.name}


def test_request_key_is_stable_and_sensitive():
    assert request_key(MSGS, []) == request_key(json.loads(json.dumps(MSGS)), [])
    assert request_key(MSGS, []) != request_key([{"role": "user", "content": "x"}], [])


def test_chain_falls_back_and_cools_down():
    clock = [0.0]
    a = Fake("a", [RateLimited("429"), {"id": "a2"}])
    b = Fake("b", [{"id": "b1"}, {"id": "b2"}])
    chain = FallbackChain([a, b], cooldown_s=60, now=lambda: clock[0])
    assert chain.complete(MSGS, [])["_provider"] == "b"
    assert chain.complete(MSGS, [])["_provider"] == "b"  # a still cooling down
    assert a.calls == 1
    clock[0] = 61
    assert chain.complete(MSGS, [])["_provider"] == "a"


def test_chain_all_fail_raises():
    chain = FallbackChain([Fake("a", [ProviderError("500")]), Fake("b", [RateLimited("429")])])
    with pytest.raises(ProviderError, match="all providers failed"):
        chain.complete(MSGS, [])


def test_cache_records_then_replays(tmp_path):
    path = tmp_path / "c.jsonl"
    inner = Fake("a", [{"id": "r1"}])
    cached = CachedProvider(inner, path)
    assert cached.complete(MSGS, [])["id"] == "r1"
    again = cached.complete(MSGS, [])
    assert again["id"] == "r1" and again["_provider"] == "cache" and inner.calls == 1
    replay = CachedProvider(None, path)
    assert replay.complete(MSGS, [])["id"] == "r1"
    with pytest.raises(ProviderError, match="not recorded"):
        replay.complete([{"role": "user", "content": "other"}], [])


def test_cache_reads_seed_files_but_writes_only_its_own(tmp_path):
    seed = tmp_path / "seed.jsonl"
    CachedProvider(Fake("a", [{"id": "seeded"}]), seed).complete(MSGS, [])
    own = tmp_path / "own.jsonl"
    cached = CachedProvider(Fake("b", []), own, seed_paths=(seed,))
    assert cached.complete(MSGS, [])["id"] == "seeded"
    assert not own.exists()


def test_cache_skips_corrupt_lines(tmp_path):
    path = tmp_path / "c.jsonl"
    key = request_key(MSGS, [])
    path.write_text('{"key": "x", "resp\n' + json.dumps({"key": key, "response": {"id": "ok"}})
                    + "\n", encoding="utf-8")
    assert CachedProvider(None, path).complete(MSGS, [])["id"] == "ok"


def test_build_provider_without_keys_explains(monkeypatch, tmp_path):
    from moderator.providers.config import build_provider, load_specs
    monkeypatch.delenv("MODERATOR_PROVIDERS", raising=False)
    for spec in load_specs():  # every key the config can use, whatever this machine has set
        monkeypatch.delenv(spec.api_key_env, raising=False)
    with pytest.raises(ProviderError, match="MODERATOR_MODE=replay"):
        build_provider("live", cache_path=tmp_path / "c.jsonl")
    assert build_provider("replay", replay_path=tmp_path / "r.jsonl").inner is None


def test_moderator_providers_env_overrides_the_config(monkeypatch, tmp_path):
    from moderator.providers.config import build_provider
    cfg = tmp_path / "p.yaml"
    cfg.write_text("providers:\n  - name: only-one\n    model: m\n    base_url: http://x\n"
                   "    api_key_env: FAKE_KEY\n", encoding="utf-8")
    monkeypatch.setenv("FAKE_KEY", "k")
    monkeypatch.setenv("MODERATOR_PROVIDERS", str(cfg))
    chain = build_provider("live", cache_path=tmp_path / "c.jsonl").inner
    assert [p.name for p in chain.providers] == ["only-one"]


def test_chain_waits_for_the_earliest_cooldown_instead_of_failing():
    clock, slept = [0.0], []

    def sleep(s):
        slept.append(s)
        clock[0] += s

    a = Fake("a", [RateLimited("429"), {"id": "a-after-wait"}])
    chain = FallbackChain([a], cooldown_s=30, max_wait_s=40, now=lambda: clock[0], sleep=sleep)
    assert chain.complete(MSGS, [])["id"] == "a-after-wait"
    assert slept == [30]


def test_chain_does_not_wait_longer_than_max_wait():
    a = Fake("a", [RateLimited("429")])
    chain = FallbackChain([a], cooldown_s=30, max_wait_s=5, sleep=lambda s: None)
    with pytest.raises(ProviderError, match="all providers failed"):
        chain.complete(MSGS, [])


def test_service_unavailable_counts_as_temporary():
    import httpx
    import openai
    from moderator.providers.client import OpenAICompatProvider, ProviderSpec

    class Boom:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    req = httpx.Request("POST", "http://x")
                    raise openai.InternalServerError("busy", response=httpx.Response(503, request=req),
                                                     body=None)

    p = OpenAICompatProvider(ProviderSpec("p", "m", "http://x", "K"), client=Boom())
    with pytest.raises(RateLimited):
        p.complete(MSGS, [])


def test_timeouts_count_as_temporary_and_spec_sets_timeout(monkeypatch):
    monkeypatch.setenv("K", "test-key")
    import httpx
    import openai
    from moderator.providers.client import OpenAICompatProvider, ProviderSpec

    class Slow:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    raise openai.APITimeoutError(request=httpx.Request("POST", "http://x"))

    p = OpenAICompatProvider(ProviderSpec("p", "m", "http://x", "K"), client=Slow())
    with pytest.raises(RateLimited):
        p.complete(MSGS, [])
    q = OpenAICompatProvider(ProviderSpec("q", "m", "http://x", "K", timeout_s=180))
    assert q.client.timeout == 180


def test_a_cache_file_that_cannot_be_written_never_costs_the_reply(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")  # the cache's parent "directory" is a file
    cached = CachedProvider(Fake("a", [{"id": "live"}]), blocker / "cache.jsonl")
    assert cached.complete(MSGS, [])["id"] == "live"
    assert cached.complete(MSGS, [])["_provider"] == "cache"  # still kept in memory


def test_daily_budget_counts_live_calls_and_resets_each_day():
    from datetime import date
    from moderator.providers.client import DailyBudget

    today = [date(2026, 10, 8)]
    budget = DailyBudget(Fake("a", [{"id": "1"}, {"id": "2"}, {"id": "3"}]), limit=2,
                         today=lambda: today[0])
    budget.complete(MSGS, [])
    budget.complete(MSGS, [])
    assert budget.exhausted
    with pytest.raises(ProviderError, match="budget"):
        budget.complete(MSGS, [])
    today[0] = date(2026, 10, 9)
    assert not budget.exhausted and budget.complete(MSGS, [])["id"] == "3"


def _one_provider_config(tmp_path, name, key_env="FAKE_KEY"):
    cfg = tmp_path / f"{name}.yaml"
    cfg.write_text(f"providers:\n  - name: {name}\n    model: m\n    base_url: http://x\n"
                   f"    api_key_env: {key_env}\n", encoding="utf-8")
    return cfg


def test_daily_budget_is_only_applied_when_asked(monkeypatch, tmp_path):
    from moderator.providers.client import DailyBudget
    from moderator.providers.config import build_provider
    monkeypatch.setenv("FAKE_KEY", "k")
    cfg = _one_provider_config(tmp_path, "a")
    bench = build_provider("live", config_path=cfg, cache_path=tmp_path / "c.jsonl")
    assert not isinstance(bench.inner, DailyBudget)  # the bench is not the hosted demo
    demo = build_provider("live", config_path=cfg, cache_path=tmp_path / "c.jsonl", daily_live_calls=5)
    assert isinstance(demo.inner, DailyBudget) and demo.inner.limit == 5


def test_the_simulator_config_is_not_replaced_by_the_agent_override(monkeypatch, tmp_path):
    from moderator.bench.runner import make_providers
    monkeypatch.setenv("FAKE_KEY", "k")
    monkeypatch.setenv("MODERATOR_PROVIDERS", str(_one_provider_config(tmp_path, "agent-x")))
    agent, sim = make_providers(tmp_path / "cache", _one_provider_config(tmp_path, "sim-y"))
    assert [p.name for p in agent.inner.providers] == ["agent-x"]
    assert [p.name for p in sim.inner.providers] == ["sim-y"]
    assert agent.path.parent == tmp_path / "cache" and sim.path.parent == tmp_path / "cache"


def test_spend_cap_prices_each_call_and_stops_before_the_cap(tmp_path):
    from moderator.providers.client import SpendCapped, SpendLedger
    ledger = SpendLedger(tmp_path / "spend.jsonl", cap_usd=10.0, margin_usd=1.0)
    spec = ProviderSpec(name="paid", model="m", base_url="http://x", api_key_env="K",
                        usd_per_mtok_in=1.0, usd_per_mtok_out=2.0)
    reply = {"choices": [{"message": {"content": "ok"}}],
             "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}}  # $3 a call
    paid = SpendCapped(Fake("paid", [reply] * 5), spec, ledger)
    for _ in range(3):
        paid.complete(MSGS, [])
    assert ledger.total() == pytest.approx(9.0)
    with pytest.raises(ProviderError, match="spend cap"):  # $9 spent: stop, a fourth call could pass $10
        paid.complete(MSGS, [])
    assert SpendLedger(tmp_path / "spend.jsonl", 10.0, 1.0).total() == pytest.approx(9.0)  # survives restarts


def test_a_call_without_usage_is_charged_at_its_worst_case(tmp_path):
    from moderator.providers.client import SpendCapped, SpendLedger
    ledger = SpendLedger(tmp_path / "spend.jsonl", cap_usd=10.0, margin_usd=1.0)
    spec = ProviderSpec(name="paid", model="m", base_url="http://x", api_key_env="K", max_tokens=1000,
                        usd_per_mtok_in=1.0, usd_per_mtok_out=1000.0)
    SpendCapped(Fake("paid", [{"choices": [{"message": {"content": "ok"}}]}]), spec, ledger).complete(MSGS, [])
    assert ledger.total() >= 1.0  # max_tokens x output price, at least


def test_priced_providers_are_capped_and_free_ones_are_not(monkeypatch, tmp_path):
    from moderator.providers.client import SpendCapped
    from moderator.providers.config import build_provider
    cfg = tmp_path / "p.yaml"
    cfg.write_text("providers:\n  - name: free\n    model: m\n    base_url: http://x\n    api_key_env: FAKE_KEY\n"
                   "  - name: paid\n    model: m\n    base_url: http://x\n    api_key_env: FAKE_KEY\n"
                   "    usd_per_mtok_in: 0.15\n    usd_per_mtok_out: 0.5\n", encoding="utf-8")
    monkeypatch.setenv("FAKE_KEY", "k")
    monkeypatch.setenv("MODERATOR_SPEND_LEDGER", str(tmp_path / "spend.jsonl"))
    free, paid = build_provider("live", config_path=cfg, cache_path=tmp_path / "c.jsonl").inner.providers
    assert not isinstance(free, SpendCapped) and isinstance(paid, SpendCapped)
    assert paid.ledger.cap_usd == 10.0 and paid.name == "paid"


def test_every_nebius_model_in_every_config_is_priced():
    """An unpriced Nebius model would bypass the $10 spend cap."""
    from pathlib import Path

    from moderator.providers.config import load_specs
    for cfg in Path("configs").glob("*.yaml"):
        for spec in load_specs(cfg):
            if spec.api_key_env == "NEBIUS_API_KEY":
                assert spec.usd_per_mtok_in and spec.usd_per_mtok_out, f"{cfg.name}: {spec.name}"


def test_reported_bench_runs_use_one_agent_model():
    from pathlib import Path

    from moderator.providers.config import load_specs
    specs = load_specs(Path("configs/providers-gemini.yaml"))
    assert {s.model for s in specs} == {"gemini-3.5-flash-lite"} and len({s.api_key_env for s in specs}) == 5


def test_bench_providers_start_with_an_empty_cache(monkeypatch, tmp_path):
    """A fresh bench run must call the live model every time, not answer from the demo recording."""
    from moderator.bench.runner import make_providers
    monkeypatch.setenv("FAKE_KEY", "k")
    monkeypatch.setenv("MODERATOR_PROVIDERS", str(_one_provider_config(tmp_path, "agent-x")))
    agent, sim = make_providers(tmp_path / "empty", _one_provider_config(tmp_path, "sim-y"))
    assert agent._data == {} and sim._data == {}

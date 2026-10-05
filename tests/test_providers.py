import json

import pytest

from moderator.providers.client import (
    CachedProvider, FallbackChain, ProviderError, RateLimited, request_key,
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
    from moderator.providers.config import build_provider
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
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

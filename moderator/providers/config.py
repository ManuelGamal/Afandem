"""Build the provider stack from configs/providers.yaml and the environment."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from moderator.providers.client import (
    CachedProvider, DailyBudget, FallbackChain, OpenAICompatProvider, ProviderError, ProviderSpec,
    SpendCapped, SpendLedger,
)

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "providers.yaml"
REPO = Path(__file__).resolve().parents[2]


def spend_ledger() -> SpendLedger:
    """One ledger for every paid call made from this machine (bench, CLI, local server).
    The hard cap is $10; calls stop $1 early."""
    path = os.environ.get("MODERATOR_SPEND_LEDGER") or REPO / "spend" / "ledger.jsonl"
    return SpendLedger(path, cap_usd=float(os.environ.get("MODERATOR_SPEND_CAP_USD", "10")), margin_usd=1.0)


def _provider(spec: ProviderSpec, ledger: SpendLedger):
    p = OpenAICompatProvider(spec)
    return p if spec.usd_per_mtok_in is None and spec.usd_per_mtok_out is None else SpendCapped(p, spec, ledger)


def load_specs(path: Path = DEFAULT_CONFIG) -> list[ProviderSpec]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [ProviderSpec(**p) for p in data["providers"]]


def build_provider(mode: str, config_path: Path = DEFAULT_CONFIG,
                   cache_path: Path = Path("cache/responses.jsonl"),
                   replay_path: Path = Path("replay/demo.jsonl"),
                   daily_live_calls: int | None = None, env_override: bool = True) -> CachedProvider:
    """The provider stack. `daily_live_calls` caps live calls per day (the hosted demo sets it);
    MODERATOR_PROVIDERS replaces the agent's config unless `env_override` is off (the simulator)."""
    if mode == "replay":
        return CachedProvider(None, replay_path)
    if env_override:
        config_path = Path(os.environ.get("MODERATOR_PROVIDERS") or config_path)
    specs = [s for s in load_specs(config_path) if os.environ.get(s.api_key_env)]
    if not specs:
        raise ProviderError(
            "No model API key found. Set GEMINI_API_KEY (free at https://aistudio.google.com/apikey)"
            " or GROQ_API_KEY, or run without a key using MODERATOR_MODE=replay.")
    ledger = spend_ledger()
    chain = FallbackChain([_provider(s, ledger) for s in specs], cooldown_s=30, max_wait_s=35)
    if mode == "record":
        return CachedProvider(chain, replay_path)
    inner = chain if daily_live_calls is None else DailyBudget(chain, daily_live_calls)
    return CachedProvider(inner, cache_path, seed_paths=(replay_path,))

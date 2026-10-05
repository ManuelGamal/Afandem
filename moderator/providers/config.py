"""Build the provider stack from configs/providers.yaml and the environment."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from moderator.providers.client import (
    CachedProvider, FallbackChain, OpenAICompatProvider, ProviderError, ProviderSpec,
)

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "providers.yaml"


def load_specs(path: Path = DEFAULT_CONFIG) -> list[ProviderSpec]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [ProviderSpec(**p) for p in data["providers"]]


def build_provider(mode: str, config_path: Path = DEFAULT_CONFIG,
                   cache_path: Path = Path("cache/responses.jsonl"),
                   replay_path: Path = Path("replay/demo.jsonl")) -> CachedProvider:
    if mode == "replay":
        return CachedProvider(None, replay_path)
    config_path = Path(os.environ.get("MODERATOR_PROVIDERS") or config_path)
    specs = [s for s in load_specs(config_path) if os.environ.get(s.api_key_env)]
    if not specs:
        raise ProviderError(
            "No model API key found. Set GEMINI_API_KEY (free at https://aistudio.google.com/apikey)"
            " or GROQ_API_KEY, or run without a key using MODERATOR_MODE=replay.")
    chain = FallbackChain([OpenAICompatProvider(s) for s in specs])
    if mode == "record":
        return CachedProvider(chain, replay_path)
    return CachedProvider(chain, cache_path, seed_paths=(replay_path,))

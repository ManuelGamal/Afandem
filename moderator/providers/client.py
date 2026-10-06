"""Model access: OpenAI-compatible providers, a fallback chain, and a JSONL cache that
doubles as replay cassettes. Cache format adapted from the author's amin repo (MIT)."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import openai


class ProviderError(Exception):
    pass


class RateLimited(ProviderError):
    pass


@dataclass
class ProviderSpec:
    name: str
    model: str
    base_url: str
    api_key_env: str
    max_tokens: int = 800
    temperature: float | None = 0.3
    timeout_s: float = 60.0


class OpenAICompatProvider:
    def __init__(self, spec: ProviderSpec, client=None):
        self.spec = spec
        self.name = spec.name
        self.client = client or openai.OpenAI(base_url=spec.base_url,
                                              api_key=os.environ.get(spec.api_key_env, ""),
                                              timeout=spec.timeout_s, max_retries=0)

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        req = {"model": self.spec.model, "messages": messages, "max_tokens": self.spec.max_tokens}
        if tools:
            req["tools"] = tools
        if self.spec.temperature is not None:
            req["temperature"] = self.spec.temperature
        try:
            raw = self.client.chat.completions.create(**req).model_dump(exclude_none=True)
        except (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError) as e:
            raise RateLimited(f"{self.name}: {e}") from e
        except openai.APIStatusError as e:
            if e.status_code in (500, 502, 503, 504):  # overloaded: temporary, like a rate limit
                raise RateLimited(f"{self.name}: {e}") from e
            raise ProviderError(f"{self.name}: {e}") from e
        except openai.OpenAIError as e:
            raise ProviderError(f"{self.name}: {e}") from e
        raw["_provider"] = self.name
        return raw


class FallbackChain:
    name = "chain"

    def __init__(self, providers: list, cooldown_s: float = 60.0, max_wait_s: float = 0.0,
                 now=time.monotonic, sleep=time.sleep):
        self.providers = providers
        self.cooldown_s = cooldown_s
        self.max_wait_s = max_wait_s
        self._now = now
        self._sleep = sleep
        self._cool_until: dict[str, float] = {}

    def _try_all(self, messages: list[dict], tools: list[dict], errors: list[str]) -> dict | None:
        for p in self.providers:
            if self._cool_until.get(p.name, 0) > self._now():
                errors.append(f"{p.name}: cooling down")
                continue
            try:
                return p.complete(messages, tools)
            except RateLimited as e:
                self._cool_until[p.name] = self._now() + self.cooldown_s
                errors.append(str(e)[:200])
            except ProviderError as e:
                errors.append(str(e)[:200])
        return None

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        errors: list[str] = []
        raw = self._try_all(messages, tools, errors)
        if raw is None and self._cool_until:
            wait = min(self._cool_until.values()) - self._now()
            if 0 < wait <= self.max_wait_s:  # every model is busy: wait for the first to free up
                self._sleep(wait)
                raw = self._try_all(messages, tools, errors)
        if raw is None:
            raise ProviderError("all providers failed: " + " | ".join(errors))
        return raw


def request_key(messages: list[dict], tools: list[dict]) -> str:
    payload = json.dumps({"messages": messages, "tools": tools}, sort_keys=True,
                         ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CachedProvider:
    def __init__(self, inner, path: str | Path, seed_paths: tuple = ()):
        self.inner = inner
        self.name = "replay" if inner is None else f"cached:{inner.name}"
        self.path = Path(path)
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        for p in (*map(Path, seed_paths), self.path):
            if not p.exists():
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and "key" in row and "response" in row:
                    self._data[row["key"]] = row["response"]

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        key = request_key(messages, tools)
        hit = self._data.get(key)
        if hit is not None:
            self.hits += 1
            return {**hit, "_provider": "cache"}
        self.misses += 1
        if self.inner is None:
            raise ProviderError("not recorded: this conversation is not in the replay file")
        raw = self.inner.complete(messages, tools)
        with self._lock:
            self._data[key] = raw
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                    f.write(json.dumps({"key": key, "response": raw}, ensure_ascii=False) + "\n")
            except OSError:  # a read-only disk costs the cache file, never the reply
                pass
        return raw

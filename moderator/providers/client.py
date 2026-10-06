"""Model access: OpenAI-compatible providers, a fallback chain, and a JSONL cache that
doubles as replay cassettes. Cache format adapted from the author's amin repo (MIT)."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import date
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
    usd_per_mtok_in: float | None = None  # set for paid models: their calls count against the spend cap
    usd_per_mtok_out: float | None = None


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


class SpendLedger:
    """Every paid call's cost, on disk, so a cap holds across runs and restarts. Calls stop once
    the total reaches cap - margin; the margin covers one in-flight call and billing differences."""

    def __init__(self, path: str | Path, cap_usd: float, margin_usd: float = 1.0):
        self.path = Path(path)
        self.cap_usd = cap_usd
        self.margin_usd = margin_usd
        self._lock = threading.Lock()

    def total(self) -> float:
        with self._lock:
            if not self.path.exists():
                return 0.0
            return sum(json.loads(line)["usd"] for line in self.path.read_text(encoding="utf-8").splitlines()
                       if line.strip())

    def allows_another_call(self) -> bool:
        return self.total() < self.cap_usd - self.margin_usd

    def record(self, model: str, tokens_in: int, tokens_out: int, usd: float) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": model,
                                    "tokens_in": tokens_in, "tokens_out": tokens_out,
                                    "usd": round(usd, 6)}) + "\n")


class SpendCapped:
    """A paid provider behind the spend ledger: refuses calls at the cap, prices each call from its
    usage (or its worst case when usage is missing)."""

    def __init__(self, inner, spec: ProviderSpec, ledger: SpendLedger):
        self.inner = inner
        self.spec = spec
        self.name = inner.name
        self.ledger = ledger

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        if not self.ledger.allows_another_call():
            raise ProviderError(f"spend cap reached: ${self.ledger.total():.2f} of "
                                f"${self.ledger.cap_usd:.2f} (stops ${self.ledger.margin_usd:.2f} early)")
        raw = self.inner.complete(messages, tools)
        usage = raw.get("usage") or {}
        tokens_in = usage.get("prompt_tokens") or len(json.dumps(messages, ensure_ascii=False)) + len(json.dumps(tools))
        tokens_out = usage.get("completion_tokens") or self.spec.max_tokens
        usd = (tokens_in * (self.spec.usd_per_mtok_in or 0) + tokens_out * (self.spec.usd_per_mtok_out or 0)) / 1e6
        self.ledger.record(self.spec.model, tokens_in, tokens_out, usd)
        return raw


class DailyBudget:
    """Caps live model calls per day, so one visitor of the hosted demo cannot spend the free
    tier's daily quota for everyone. Sits behind the cache: recorded answers cost nothing."""

    def __init__(self, inner, limit: int, today=date.today):
        self.inner = inner
        self.name = inner.name
        self.limit = limit
        self._today = today
        self._day = today()
        self.used = 0
        self._lock = threading.Lock()

    def _roll(self) -> None:
        if self._today() != self._day:
            self._day, self.used = self._today(), 0

    @property
    def exhausted(self) -> bool:
        with self._lock:
            self._roll()
            return self.used >= self.limit

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        with self._lock:
            self._roll()
            if self.used >= self.limit:
                raise ProviderError("the daily live-model budget for this demo is used up")
            self.used += 1
        return self.inner.complete(messages, tools)


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

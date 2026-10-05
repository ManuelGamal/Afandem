"""Scripted model responses for deterministic agent tests."""

import json

from moderator.providers.client import ProviderError


def tool_raw(*calls):
    return {"choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant",
        "tool_calls": [{"id": f"call_{i}", "type": "function",
                        "function": {"name": n, "arguments": json.dumps(a, ensure_ascii=False)}}
                       for i, (n, a) in enumerate(calls)]}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 20}}


def text_raw(text):
    return {"choices": [{"finish_reason": "stop",
                         "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 60}}


class ScriptedProvider:
    name = "scripted"

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append(json.loads(json.dumps(messages, ensure_ascii=False)))
        if not self.responses:
            raise ProviderError("script exhausted")
        out = self.responses.pop(0)
        if isinstance(out, Exception):
            raise out
        return {**out, "_provider": self.name}

"""Print the model ids each configured key can use: `uv run python -m moderator.providers.list_models`."""

import os

import openai

from moderator.providers.config import load_specs


def main() -> None:
    seen = set()
    for spec in load_specs():
        if (spec.base_url, spec.api_key_env) in seen or not os.environ.get(spec.api_key_env):
            continue
        seen.add((spec.base_url, spec.api_key_env))
        client = openai.OpenAI(base_url=spec.base_url, api_key=os.environ[spec.api_key_env])
        print(f"== {spec.base_url}")
        for m in client.models.list():
            print("  ", m.id)


if __name__ == "__main__":
    main()

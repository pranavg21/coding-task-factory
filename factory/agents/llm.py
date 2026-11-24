"""Claude client with record/replay, so a factory run can be reproduced exactly.

Every request is keyed by a SHA-256 of its parameters. In "record" mode the response is saved under
`recordings/<key>.json`; in "replay" mode the saved response is returned and no API call is made, so a
replayed run produces byte-identical packages at no cost. "live" calls the API without saving.

Responses are handled as plain dicts (the SDK's `model_dump()`), so recorded and live runs go through
exactly the same code. Thinking blocks are passed back unchanged, as the API requires.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import os

PROVIDER = os.environ.get("FACTORY_PROVIDER", "gemini")
DEFAULT_MODELS = {"gemini": os.environ.get("GEMINI_MODEL", "gemini-2.5-pro"), "anthropic": "claude-opus-5-5"}
MODEL = DEFAULT_MODELS[PROVIDER]
# USD per million tokens (input, output), for the cost report only. Set FACTORY_PRICE_IN / FACTORY_PRICE_OUT
# from your provider's price list; without them the report shows token counts and no dollar figure.
PRICE_PER_MTOK = (float(os.environ.get("FACTORY_PRICE_IN", "0")), float(os.environ.get("FACTORY_PRICE_OUT", "0")))

Mode = Literal["live", "record", "replay"]


class ReplayMissError(RuntimeError):
    """Replay mode found no recording for a request: the inputs changed since the recorded run."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    @property
    def cost_usd(self) -> float:
        return round(self.input_tokens / 1e6 * PRICE_PER_MTOK[0] + self.output_tokens / 1e6 * PRICE_PER_MTOK[1], 4)


def request_key(params: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class LLM:
    mode: Mode = "record"
    provider: str = PROVIDER  # "gemini" (Google AI Studio key) or "anthropic"
    model: str = ""  # empty: the provider's default
    recordings: Path = Path("recordings")
    client: Any = None  # anthropic.Anthropic(); created lazily so replay needs no credentials
    usage: Usage = field(default_factory=Usage)

    def create(self, **params: Any) -> dict[str, Any]:
        if not self.model:
            self.model = DEFAULT_MODELS[self.provider]
        params.setdefault("model", self.model)
        params.setdefault("provider", self.provider)  # part of the recording key, never sent
        key = request_key(params)
        path = self.recordings / f"{key}.json"
        if self.mode == "replay":
            if not path.exists():
                raise ReplayMissError(f"no recording for request {key[:12]}")
            response = json.loads(path.read_text(encoding="utf-8"))
        else:
            request = {k: v for k, v in params.items() if k != "provider"}
            if self.provider == "gemini":
                from factory.agents import gemini

                if self.client is None:
                    from google import genai

                    # GEMINI_API_KEY (or GOOGLE_API_KEY) from Google AI Studio. Where a network proxy adds the
                    # x-goog-api-key header itself (a stored network secret), set GEMINI_KEY_VIA_PROXY=1 instead;
                    # the SDK then sends a placeholder that the proxy replaces.
                    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
                    if not key and os.environ.get("GEMINI_KEY_VIA_PROXY") == "1":
                        key = "replaced-by-proxy"
                    if not key:
                        raise RuntimeError("Set GEMINI_API_KEY to a Google AI Studio API key")
                    self.client = genai.Client(api_key=key)
                response = gemini.call(self.client, request)
            else:
                if self.client is None:
                    import anthropic

                    self.client = anthropic.Anthropic()
                response = self.client.messages.create(**request).model_dump(mode="json", exclude_none=True)
            if self.mode == "record":
                self.recordings.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(response, indent=1), encoding="utf-8", newline="\n")  # original order
                # The request is kept too, so every prompt the factory sent can be audited.
                path.with_suffix(".request.json").write_text(json.dumps(params, indent=1, sort_keys=True, default=str),
                                                             encoding="utf-8", newline="\n")
        usage = response.get("usage", {})
        self.usage.input_tokens += int(usage.get("input_tokens", 0)) + int(usage.get("cache_read_input_tokens", 0) or 0)
        self.usage.output_tokens += int(usage.get("output_tokens", 0))
        self.usage.calls += 1
        return response

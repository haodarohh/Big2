"""Thin client for OpenRouter's jev-1.13 decision model.

jev answers structured `choice` questions (pick one key out of a fixed set)
rather than generating free text, so it can never return cards that aren't
in the option set we hand it. Whether its choice actually beats the
current trick is judged by the caller (game.py), which retries with
feedback when it doesn't — that's the "is jev smart enough" test.

The endpoint defaults to OpenRouter's hosted jev. Setting BIG2_AI_URL points
the same payload at a local `rapid-mlx system-one` (laya) server instead.
"""

from __future__ import annotations

import os

import requests

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"
# Local laya servers expose the same request shape at /v1/systemone.
URL_ENV = "BIG2_AI_URL"
MODEL_ENV = "BIG2_AI_MODEL"
REQUEST_TIMEOUT_SECONDS = 30


class JevError(Exception):
    """Raised for any failure to get a usable choice back from jev."""


def request_choice(state: str, options: dict[str, str]) -> str:
    """Ask jev to pick one key from `options`, given `state` as context.

    Returns the chosen option key. Raises JevError on network failure,
    non-2xx response, or a response that doesn't name one of `options`.
    """
    url = os.environ.get(URL_ENV) or DECISIONS_URL
    api_key = os.environ.get("OPENROUTER_API_KEY")
    # Only the hosted default needs a key; a local server runs without
    # --api-key, so demanding one there would block laya for no reason.
    if url == DECISIONS_URL and not api_key:
        raise JevError("OPENROUTER_API_KEY environment variable is not set")

    payload = {
        "state": state,
        "questions": {
            "move": {
                "type": "choice",
                "instructions": (
                    "You are an AI player in a game of Big Two (大老二 / Dai Di). "
                    "Choose which option to play this turn. "
                    "Rules: ranks ascend 3,4,5,6,7,8,9,10,J,Q,K,A,2; suits ascend "
                    "clubs,diamonds,hearts,spades. Only a combo with the same card count "
                    "and a strictly higher rank (ties broken by suit) beats the current "
                    "combo; an option that does not beat it is illegal. Choose 'pass' if "
                    "no option beats the required combo."
                ),
                "criteria": options,
            }
        },
    }

    # "typesafe/jev-1.13" is meaningless to a local server (it would 404), so
    # omit model and let it use its default unless explicitly overridden.
    model = os.environ.get(MODEL_ENV) or (MODEL if url == DECISIONS_URL else None)
    if model:
        payload["model"] = model

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        choice = data["answers"]["move"]["choice"]
    except requests.RequestException as exc:
        raise JevError(f"request to jev failed: {exc}") from exc
    except (KeyError, ValueError) as exc:
        raise JevError(f"unexpected response shape from jev: {exc}") from exc

    if choice not in options:
        raise JevError(f"jev returned unknown option key: {choice!r}")

    return choice

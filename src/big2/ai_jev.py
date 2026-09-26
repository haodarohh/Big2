"""Thin client for OpenRouter's jev-1.13 decision model.

jev answers structured `choice` questions (pick one key out of a fixed set)
rather than generating free text, so it can never return cards that aren't
in the option set we hand it. Whether its choice actually beats the
current trick is judged by the caller (game.py), which retries with
feedback when it doesn't — that's the "is jev smart enough" test.
"""

from __future__ import annotations

import os

import requests

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"
REQUEST_TIMEOUT_SECONDS = 30


class JevError(Exception):
    """Raised for any failure to get a usable choice back from jev."""


def request_choice(state: str, options: dict[str, str]) -> str:
    """Ask jev to pick one key from `options`, given `state` as context.

    Returns the chosen option key. Raises JevError on network failure,
    non-2xx response, or a response that doesn't name one of `options`.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise JevError("OPENROUTER_API_KEY environment variable is not set")

    payload = {
        "model": MODEL,
        "state": state,
        "questions": {
            "move": {
                "type": "choice",
                "instructions": (
                    "You are an AI player in a game of Big Two (大老二 / Dai Di). "
                    "Choose which option to play this turn."
                ),
                "criteria": options,
            }
        },
    }

    try:
        response = requests.post(
            DECISIONS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
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

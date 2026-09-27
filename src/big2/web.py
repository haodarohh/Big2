"""Flask app for the browser version of 大老二.

There is exactly one game in memory at a time (`_STATE`, module-level) —
this is a single local player's page, not a multi-tenant server (see ADR
0001 for why turns are handled synchronously instead of streamed). Every
request that changes the game (`/api/new_game`, `/api/move`) runs the
engine forward with `run_ai_batch` until it's the human seat's turn again
(or the game ends) and returns the full list of `TurnEvent`s from that
batch alongside the resulting snapshot — the frontend replays that list as
an animation instead of jumping straight to the final state.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

from .cards import Card, Suit
from .game import (
    AIController,
    Controller,
    GameEngine,
    IllegalMoveError,
    TurnEvent,
    deal,
    run_ai_batch,
    validate_move,
)
from .logging_util import GameLogger

STATIC_DIR = Path(__file__).parent / "static"

# Human seats always come first (seat 0), matching the CLI's seating order.
HUMAN_SEAT = 0


@dataclass
class GameSession:
    engine: GameEngine
    controllers: list[Controller]
    is_human: list[bool]

    @property
    def has_human(self) -> bool:
        return any(self.is_human)


_STATE: GameSession | None = None


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.post("/api/new_game")
    def new_game():
        body = request.get_json(force=True) or {}
        num_players = body.get("players")
        num_humans = body.get("human")
        if num_players not in (2, 3, 4):
            return jsonify(error="players 必須是 2、3 或 4"), 400
        if num_humans not in (0, 1):
            return jsonify(error="human 必須是 0 或 1"), 400

        global _STATE
        names = [f"玩家{i + 1}(你)" if i < num_humans else f"AI-{i + 1}" for i in range(num_players)]
        is_human = [i < num_humans for i in range(num_players)]
        logger = GameLogger()
        engine = GameEngine(deal(num_players), names, logger)
        controllers: list[Controller] = [
            AIController(name=names[i], logger=logger) for i in range(num_players)
        ]
        _STATE = GameSession(engine=engine, controllers=controllers, is_human=is_human)

        events = run_ai_batch(_STATE.engine, _STATE.controllers, _STATE.is_human)
        return jsonify(events=[_serialize_event(e) for e in events], state=_serialize_state(_STATE))

    @app.get("/api/state")
    def state():
        if _STATE is None:
            return jsonify(error="尚未開局"), 404
        return jsonify(state=_serialize_state(_STATE))

    @app.post("/api/move")
    def move():
        if _STATE is None:
            return jsonify(error="尚未開局"), 404
        if _STATE.engine.finished:
            return jsonify(error="遊戲已結束"), 400
        if not _STATE.is_human[_STATE.engine.current]:
            return jsonify(error="現在不是你的回合"), 400

        body = request.get_json(force=True) or {}
        indices = body.get("indices") or []
        if len(set(indices)) != len(indices):
            return jsonify(error="牌的編號重複了"), 400

        sorted_hand = sorted(_STATE.engine.hand)
        try:
            cards: list[Card] = [sorted_hand[i - 1] for i in indices]
        except IndexError:
            return jsonify(error="牌的編號超出範圍"), 400

        try:
            combo = validate_move(_STATE.engine, cards)
        except IllegalMoveError as exc:
            return jsonify(error=str(exc)), 400

        events = [_STATE.engine.apply(combo)]
        events += run_ai_batch(_STATE.engine, _STATE.controllers, _STATE.is_human)
        return jsonify(events=[_serialize_event(e) for e in events], state=_serialize_state(_STATE))

    return app


def _serialize_card(card: Card) -> dict[str, Any]:
    color = "red" if card.suit in (Suit.DIAMOND, Suit.HEART) else "black"
    return {"label": str(card), "rank": card.rank.symbol, "suit": card.suit.symbol, "color": color}


def _serialize_combo(combo) -> dict[str, Any] | None:
    if combo is None:
        return None
    return {"type": combo.type.name, "cards": [_serialize_card(c) for c in combo.cards]}


def _serialize_event(event: TurnEvent) -> dict[str, Any]:
    return {
        "player": event.player_name,
        "kind": event.kind,
        "combo": _serialize_combo(event.combo),
        "remaining": event.remaining,
    }


def _serialize_state(session: GameSession) -> dict[str, Any]:
    engine = session.engine
    finished = engine.finished
    current_is_human = (not finished) and session.is_human[engine.current]
    return {
        "finished": finished,
        "winner_name": engine.names[engine.winner_seat] if finished else None,
        "seat_names": engine.names,
        "remaining": {engine.names[i]: len(engine.hands[i]) for i in range(engine.n)},
        "current_is_human": current_is_human,
        "human_hand": [_serialize_card(c) for c in sorted(engine.hands[HUMAN_SEAT])] if session.has_human else None,
        "is_leading": engine.is_leading,
        "must_play_3c": engine.must_include_3c and engine.is_leading,
        "required": _serialize_combo(engine.required),
    }

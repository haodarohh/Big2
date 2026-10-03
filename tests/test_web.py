"""Verify browser game requests advance incrementally without live AI calls."""

from unittest.mock import Mock

import pytest

from big2 import web
from big2.cards import THREE_OF_CLUBS, Card, Rank, Suit
from big2.logging_util import GameLogger
from big2.rules import classify


@pytest.fixture
def client(monkeypatch, tmp_path):
    """Return an isolated Flask client with deterministic hands and mocked AI."""
    monkeypatch.setattr(web, "_STATE", None)
    monkeypatch.setattr(web, "GameLogger", lambda: GameLogger(tmp_path))
    monkeypatch.setattr(web, "deal", lambda count: [
        [THREE_OF_CLUBS, Card(Rank.FOUR, Suit.CLUB)],
        [Card(Rank.FIVE, Suit.CLUB), Card(Rank.SIX, Suit.CLUB)],
    ])
    return web.create_app().test_client()


def test_spectator_start_does_not_wait_for_ai(client, monkeypatch):
    """The table arrives before even the first external decision is requested."""
    choose = Mock(return_value=classify([THREE_OF_CLUBS]))
    monkeypatch.setattr(web.AIController, "choose_move", choose)
    response = client.post("/api/new_game", json={"players": 2, "human": 0})
    assert response.status_code == 200
    assert response.json["events"] == []
    assert response.json["state"]["finished"] is False
    choose.assert_not_called()


def test_spectator_step_advances_one_turn(client, monkeypatch):
    """Each request returns one applied turn and stops before the next AI call."""
    client.post("/api/new_game", json={"players": 2, "human": 0})
    choose = Mock(return_value=classify([THREE_OF_CLUBS]))
    monkeypatch.setattr(web.AIController, "choose_move", choose)
    response = client.post("/api/spectate", json={})
    assert response.status_code == 200
    assert len(response.json["events"]) == 1
    assert response.json["state"]["remaining"]["AI-1"] == 1
    assert response.json["state"]["finished"] is False
    choose.assert_called_once()


def test_spectator_step_requires_spectator_session(client):
    """Missing sessions and human games cannot be advanced through spectating."""
    assert client.post("/api/spectate", json={}).status_code == 404
    client.post("/api/new_game", json={"players": 2, "human": 1})
    assert client.post("/api/spectate", json={}).status_code == 400


def test_spectator_step_stops_at_winner(client, monkeypatch):
    """A winning move is returned once; subsequent requests do not invoke AI."""
    client.post("/api/new_game", json={"players": 2, "human": 0})
    web._STATE.engine.hands[0] = [THREE_OF_CLUBS]
    choose = Mock(return_value=classify([THREE_OF_CLUBS]))
    monkeypatch.setattr(web.AIController, "choose_move", choose)
    response = client.post("/api/spectate", json={})
    assert response.json["state"]["finished"] is True
    assert len(response.json["events"]) == 1
    assert client.post("/api/spectate", json={}).json["events"] == []
    choose.assert_called_once()


def test_human_game_opens_before_ai_decision(client, monkeypatch):
    """AI opening hands must not delay rendering a human game's table."""
    monkeypatch.setattr(web, "deal", lambda count: [
        [Card(Rank.FIVE, Suit.CLUB), Card(Rank.SIX, Suit.CLUB)],
        [THREE_OF_CLUBS, Card(Rank.FOUR, Suit.CLUB)],
    ])
    choose = Mock(side_effect=AssertionError("opening must not call AI"))
    monkeypatch.setattr(web.AIController, "choose_move", choose)
    response = client.post("/api/new_game", json={"players": 2, "human": 1})
    assert response.status_code == 200
    assert response.json["events"] == []
    assert response.json["state"]["current_is_human"] is False
    choose.assert_not_called()


def test_human_move_returns_before_ai_and_steps_back_to_human(client, monkeypatch):
    """Human moves and subsequent AI turns are separate requests with fresh context."""
    client.post("/api/new_game", json={"players": 2, "human": 1})
    choose = Mock(return_value=classify([Card(Rank.FIVE, Suit.CLUB)]))
    monkeypatch.setattr(web.AIController, "choose_move", choose)
    response = client.post("/api/move", json={"indices": [1]})
    assert len(response.json["events"]) == 1
    assert response.json["state"]["current_is_human"] is False
    choose.assert_not_called()
    context = web._STATE.engine.turn_context()
    response = client.post("/api/ai_turn", json={})
    assert response.status_code == 200
    assert len(response.json["events"]) == 1
    assert response.json["state"]["current_is_human"] is True
    assert response.json["state"]["human_hand"][0]["rank"] == "4"
    choose.assert_called_once()
    assert choose.call_args.kwargs["context"] == context
    assert client.post("/api/ai_turn", json={}).status_code == 400
    choose.assert_called_once()


def test_ai_turn_rejects_missing_game(client):
    """Advancing AI before opening a game returns a missing-session error."""
    assert client.post("/api/ai_turn", json={}).status_code == 404


def test_three_ai_seats_advance_in_separate_requests(client, monkeypatch):
    """A four-seat game returns each AI move before computing the following seat."""
    monkeypatch.setattr(web, "deal", lambda count: [
        [THREE_OF_CLUBS, Card(Rank.SEVEN, Suit.CLUB)],
        [Card(Rank.FOUR, Suit.CLUB), Card(Rank.EIGHT, Suit.CLUB)],
        [Card(Rank.FIVE, Suit.CLUB), Card(Rank.NINE, Suit.CLUB)],
        [Card(Rank.SIX, Suit.CLUB), Card(Rank.TEN, Suit.CLUB)],
    ])
    choose = Mock(side_effect=[classify([Card(rank, Suit.CLUB)]) for rank in
                              (Rank.FOUR, Rank.FIVE, Rank.SIX)])
    monkeypatch.setattr(web.AIController, "choose_move", choose)
    client.post("/api/new_game", json={"players": 4, "human": 1})
    client.post("/api/move", json={"indices": [1]})
    choose.assert_not_called()
    for turn in range(1, 4):
        response = client.post("/api/ai_turn", json={})
        assert response.status_code == 200
        assert len(response.json["events"]) == 1
        assert response.json["events"][0]["player"] == f"AI-{turn + 1}"
        assert response.json["state"]["current_is_human"] is (turn == 3)
        assert choose.call_count == turn


def test_human_winner_does_not_trigger_ai(client, monkeypatch):
    """Playing the last human card ends the game without a subsequent AI call."""
    client.post("/api/new_game", json={"players": 2, "human": 1})
    web._STATE.engine.hands[0] = [THREE_OF_CLUBS]
    choose = Mock(side_effect=AssertionError("finished game must not call AI"))
    monkeypatch.setattr(web.AIController, "choose_move", choose)
    response = client.post("/api/move", json={"indices": [1]})
    assert response.json["state"]["finished"] is True
    assert len(response.json["events"]) == 1
    assert client.post("/api/ai_turn", json={}).json["events"] == []
    choose.assert_not_called()

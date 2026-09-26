"""Command-line entry point: argument parsing, seat setup, and the
top-level `uv run big2` command."""

from __future__ import annotations

import argparse

from .game import AIController, HumanController, deal, run_game
from .logging_util import GameLogger


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="big2", description="大老二 CLI（台灣規則）")
    parser.add_argument("--players", type=int, choices=(2, 3, 4), help="總人數 (2-4)")
    parser.add_argument("--human", type=int, choices=(0, 1), help="真人玩家人數 (0 或 1)")
    return parser.parse_args(argv)


def _prompt_choice(prompt_text: str, choices: tuple[int, ...]) -> int:
    options = "/".join(str(c) for c in choices)
    while True:
        raw = input(f"{prompt_text} ({options}): ").strip()
        try:
            value = int(raw)
        except ValueError:
            print(f"請輸入 {options} 其中之一。")
            continue
        if value not in choices:
            print(f"請輸入 {options} 其中之一。")
            continue
        return value


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    num_players = args.players or _prompt_choice("幾人遊戲？", (2, 3, 4))
    num_humans = args.human if args.human is not None else _prompt_choice("真人玩家人數？", (0, 1))

    logger = GameLogger()
    hands = deal(num_players)

    controllers = []
    for i in range(num_players):
        if i < num_humans:
            controllers.append(HumanController(name=f"玩家{i + 1}(你)"))
        else:
            controllers.append(AIController(name=f"AI-{i + 1}", logger=logger))

    print(f"開局：{num_players} 人，{num_humans} 位真人玩家。牌局紀錄：{logger.path}\n")
    result = run_game(hands, controllers, logger)
    print(f"\n贏家：{result.winner_name}")

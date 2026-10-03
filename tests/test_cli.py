"""Verify CLI server defaults and forwarding without starting a server."""

from unittest.mock import Mock

import pytest

from big2.cli import main, parse_args


def test_default_server_settings():
    """Parsing no arguments returns local server defaults with mode disabled."""
    args = parse_args([])
    assert args.server_mode is False
    assert args.host == "127.0.0.1"
    assert args.port == 8765


@pytest.mark.parametrize(
    "options, host, port",
    [([], "127.0.0.1", 8765), (["--host", "0.0.0.0", "--port", "9000"], "0.0.0.0", 9000)],
)
def test_server_mode_forwards_settings(monkeypatch, capsys, options, host, port):
    """Server mode forwards CLI settings and prints the matching URL."""
    app = Mock()
    monkeypatch.setattr("big2.web.create_app", lambda: app)

    main(["--server-mode", *options])

    app.run.assert_called_once_with(host=host, port=port)
    assert f"http://{host}:{port}/" in capsys.readouterr().out

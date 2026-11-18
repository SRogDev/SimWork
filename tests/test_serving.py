"""Tests for the one serving lifecycle (architecture review 2026-11-18,
candidate 4).

`serve` enters a context-manager server, prints its banner, blocks
until Ctrl-C, and stops it. The wait is faked by patching
`threading.Event` so the suite never blocks.
"""

import pytest

from simwork.serving import serve


class _FakeServer:
    def __init__(self):
        self.entered = False
        self.stopped = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *exc):
        self.stopped = True


class _ImmediateCtrlC:
    def wait(self):
        raise KeyboardInterrupt


@pytest.fixture()
def _ctrl_c(monkeypatch):
    monkeypatch.setattr("simwork.serving.threading.Event", lambda: _ImmediateCtrlC())


def test_serve_enters_banners_and_stops_on_ctrl_c(_ctrl_c, capsys):
    server = _FakeServer()
    serve(
        server,
        banner=lambda s: ["running at http://127.0.0.1:9999", "KEY=value"],
        stopping="Stopping.",
    )
    assert server.entered and server.stopped
    out = capsys.readouterr().out
    assert "running at http://127.0.0.1:9999" in out
    assert "KEY=value" in out
    assert "Press Ctrl-C to stop." in out
    assert "\nStopping." in out


def test_serve_banner_receives_started_server(_ctrl_c, capsys):
    server = _FakeServer()
    seen: list[bool] = []

    def banner(s):
        seen.append(s.entered)
        return ["ok"]

    serve(server, banner=banner, stopping="Bye.")
    assert seen == [True]  # the banner runs after __enter__


def test_serve_start_failure_propagates_without_stopping_message(_ctrl_c, capsys):
    class _BrokenServer(_FakeServer):
        def __enter__(self):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        serve(_BrokenServer(), banner=lambda s: ["never"], stopping="Stopping.")
    out = capsys.readouterr().out
    assert "never" not in out
    assert "Stopping." not in out

import asyncio

from radar_agent import main as agent_main


def test_keyboard_interrupt_is_a_clean_shutdown(monkeypatch, capsys) -> None:
    def interrupt(coroutine) -> None:
        coroutine.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(asyncio, "run", interrupt)

    agent_main.main()

    assert "Scanner agent stopped" in capsys.readouterr().err

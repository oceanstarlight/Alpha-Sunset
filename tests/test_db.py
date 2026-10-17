from app.db import connect, db_path


def test_live_and_sandbox_are_separate_files():
    assert db_path("live") != db_path("sandbox")


def test_writes_do_not_leak_between_modes():
    sandbox = connect("sandbox")
    with sandbox:
        sandbox.execute(
            "INSERT INTO shadow_log (event_id, doc_id, event_type, cited, rank, feedback, mode, ts) "
            "VALUES ('svb_2023', 'LIQ-01', 'banking_stress', 1, 1, NULL, 'backtest', '2023-03-10')"
        )
    sandbox.close()

    live = connect("live")
    assert live.execute("SELECT COUNT(*) FROM shadow_log").fetchone()[0] == 0
    live.close()

    sandbox = connect("sandbox")
    assert sandbox.execute("SELECT COUNT(*) FROM shadow_log").fetchone()[0] == 1
    sandbox.close()


def test_unknown_mode_rejected():
    import pytest

    with pytest.raises(ValueError):
        connect("prod")  # type: ignore[arg-type]

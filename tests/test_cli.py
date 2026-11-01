from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nqcockpit.cli import main


def test_cli_help(capsys):
    """Verify that --help exits cleanly with 0 and prints usage."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "nqcockpit" in captured.out
    assert "check-sources" in captured.out


def test_cli_no_args(capsys):
    """Verify that running with no args displays help without error."""
    code = main([])
    assert code == 0
    captured = capsys.readouterr()
    assert "nqcockpit" in captured.out


@pytest.mark.parametrize("subcmd", ["run", "check-sources", "snapshot", "brief", "ui"])
def test_cli_subcommands(subcmd, capsys):
    """Verify each required subcommand runs and outputs notification."""
    from nqcockpit.data.models import BarSeries, DataStatus

    empty_series = BarSeries(
        symbol="NQ=F", interval="1m", bars=[], source="mock",
        fetched_at_utc=datetime.now(timezone.utc), status=DataStatus.OK,
        latency_seconds=None, notes="",
    )
    snap = _fake_snapshot()

    with (
        patch("nqcockpit.sources.health.run_all_checks") as mock_checks,
        patch("nqcockpit.cli._handle_ui", return_value=0),
        patch("nqcockpit.levels.scheduler.LevelsScheduler"),
        patch("nqcockpit.data.cboe.fetch_cboe_options_chain", return_value=None),
        patch("nqcockpit.data.fetcher.DataFetcher.fetch_yahoo_bars", return_value=empty_series),
        patch("nqcockpit.levels.engine.LevelsEngine.compute_snapshot", return_value=snap),
    ):
        mock_report = MagicMock()
        mock_report.render_console_table.return_value = "Mock Table"
        mock_report.save_json.return_value = "reports/source_check.json"
        mock_checks.return_value = mock_report

        code = main([subcmd])
        assert code == 0
        captured = capsys.readouterr()
        assert f"'{subcmd}'" in captured.out


def _fake_snapshot() -> SimpleNamespace:
    """Snapshot minimal (tous champs None) pour un rendu console sans crash."""
    from dataclasses import fields
    from datetime import datetime, timezone

    from nqcockpit.data.models import DataStatus
    from nqcockpit.levels.models import LevelsSnapshot

    names = [f.name for f in fields(LevelsSnapshot)]
    snap = SimpleNamespace(**{name: None for name in names})
    snap.timestamp_utc = datetime.now(timezone.utc)
    snap.status = DataStatus.OK
    snap.basis_status = DataStatus.OK
    snap.live_basis_status = DataStatus.OK
    snap.spot_ndx = 0.0
    snap.spot_nq = 0.0
    snap.basis = 0.0
    snap.net_gex = 0.0
    snap.regime = ""
    snap.basis_label = ""
    snap.oi_flag = ""
    snap.wall_window_pct = 0.03
    snap.cboe_reloaded = False
    snap.spot_nq_is_stale = False
    snap.basis_is_aligned = True
    snap.basis_tolerance_minutes = 1.0
    snap.cboe_age_stats = {}
    return snap


def test_cli_run_launches_scheduler_and_ui():
    """Vérifie formellement que 'run' démarre le planificateur et invoque Streamlit."""
    with (
        patch("nqcockpit.levels.scheduler.LevelsScheduler") as mock_sched_cls,
        patch("subprocess.run") as mock_subproc,
    ):
        mock_sched_instance = mock_sched_cls.return_value
        code = main(["run", "--port", "8555"])
        assert code == 0

        # Vérifie le cycle de vie du planificateur
        mock_sched_instance.start.assert_called_once()
        mock_sched_instance.stop.assert_called_once()

        # Vérifie les arguments exacts passés au sous-processus Streamlit
        mock_subproc.assert_called_once()
        args_passed = mock_subproc.call_args[0][0]
        assert "-m" in args_passed
        assert "streamlit" in args_passed
        assert "run" in args_passed
        assert any("app.py" in str(arg) for arg in args_passed)
        assert "--server.port" in args_passed
        assert "8555" in args_passed
        assert "--theme.base" in args_passed
        assert "dark" in args_passed


def test_cli_ui_launches_streamlit():
    """Vérifie formellement que 'ui' invoque Streamlit avec port et app.py."""
    with patch("subprocess.run") as mock_subproc:
        code = main(["ui", "--port", "8501"])
        assert code == 0
        mock_subproc.assert_called_once()
        args_passed = mock_subproc.call_args[0][0]
        assert "-m" in args_passed
        assert "streamlit" in args_passed
        assert "run" in args_passed
        assert any("app.py" in str(arg) for arg in args_passed)
        assert "--server.port" in args_passed
        assert "8501" in args_passed
        assert "--theme.base" in args_passed
        assert "dark" in args_passed


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
    with (
        patch("nqcockpit.sources.health.run_all_checks") as mock_checks,
        patch("nqcockpit.cli._handle_ui", return_value=0),
        patch("nqcockpit.levels.scheduler.LevelsScheduler"),
    ):
        mock_report = MagicMock()
        mock_report.render_console_table.return_value = "Mock Table"
        mock_report.save_json.return_value = "reports/source_check.json"
        mock_checks.return_value = mock_report

        code = main([subcmd])
        assert code == 0
        captured = capsys.readouterr()
        assert f"'{subcmd}'" in captured.out

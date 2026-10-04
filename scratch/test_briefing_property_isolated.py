"""Test minimal et isolé d'instanciation de PreSessionBriefing et d'accès à timestamp_alg."""

from datetime import datetime, timezone

from nqcockpit.briefing.models import PreSessionBriefing


def test_presession_briefing_timestamp_alg_property():
    """Instancie PreSessionBriefing et vérifie l'accès à timestamp_alg et timestamp_algiers_str."""
    now_utc = datetime.now(timezone.utc)
    briefing = PreSessionBriefing(
        timestamp_utc=now_utc,
        session_date_ny="2026-10-01",
        timestamp_algiers_str="2026-10-01 04:15:00",
        status="OK",
        status_warnings=["Source P02 dégradée"],
        markdown_briefing="# Briefing Test Factice",
    )

    # Vérification explicite des accès d'attributs
    assert briefing.timestamp_algiers_str == "2026-10-01 04:15:00"
    assert briefing.timestamp_alg == "2026-10-01 04:15:00"
    assert briefing.status == "OK"
    assert briefing.session_date_ny == "2026-10-01"

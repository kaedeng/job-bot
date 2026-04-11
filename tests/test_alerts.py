from __future__ import annotations

from datetime import timezone
from unittest.mock import patch

from bot.alerts import (
    _AlertSetup,
    _build_summary,
    _is_quiet_time,
    _loc_display,
    interval_display,
)

# ─── _is_quiet_time ───────────────────────────────────────────────────────────


class TestIsQuietTime:
    def _prefs(self, start: str | None, end: str | None) -> dict:
        return {"quiet_hours_start": start, "quiet_hours_end": end}

    def test_no_quiet_hours_returns_false(self):
        assert _is_quiet_time(self._prefs(None, None)) is False

    def test_only_start_set_returns_false(self):
        assert _is_quiet_time(self._prefs("22:00", None)) is False

    def test_only_end_set_returns_false(self):
        assert _is_quiet_time(self._prefs(None, "08:00")) is False

    def _mock_now(self, hhmm: str):
        """Patch datetime.now inside bot.alerts to return a fixed UTC time."""
        from datetime import datetime as _dt

        class _FakeDT(_dt):
            @classmethod
            def now(cls, tz=None):  # noqa: ARG003
                h, m = map(int, hhmm.split(":"))
                return _dt(2026, 1, 1, h, m, 0, tzinfo=timezone.utc)

        return patch("bot.alerts.datetime", _FakeDT)

    # Same-day window (start < end): e.g. 02:00 – 08:00
    def test_inside_same_day_window(self):
        with self._mock_now("05:00"):
            assert _is_quiet_time(self._prefs("02:00", "08:00")) is True

    def test_at_start_same_day_window(self):
        with self._mock_now("02:00"):
            assert _is_quiet_time(self._prefs("02:00", "08:00")) is True

    def test_at_end_same_day_window_excluded(self):
        with self._mock_now("08:00"):
            assert _is_quiet_time(self._prefs("02:00", "08:00")) is False

    def test_before_same_day_window(self):
        with self._mock_now("01:00"):
            assert _is_quiet_time(self._prefs("02:00", "08:00")) is False

    def test_after_same_day_window(self):
        with self._mock_now("09:00"):
            assert _is_quiet_time(self._prefs("02:00", "08:00")) is False

    # Overnight window (start > end): e.g. 22:00 – 08:00
    def test_inside_overnight_window_after_start(self):
        with self._mock_now("23:00"):
            assert _is_quiet_time(self._prefs("22:00", "08:00")) is True

    def test_inside_overnight_window_before_end(self):
        with self._mock_now("07:00"):
            assert _is_quiet_time(self._prefs("22:00", "08:00")) is True

    def test_at_start_overnight_window(self):
        with self._mock_now("22:00"):
            assert _is_quiet_time(self._prefs("22:00", "08:00")) is True

    def test_outside_overnight_window(self):
        with self._mock_now("12:00"):
            assert _is_quiet_time(self._prefs("22:00", "08:00")) is False

    def test_at_end_overnight_window_excluded(self):
        with self._mock_now("08:00"):
            assert _is_quiet_time(self._prefs("22:00", "08:00")) is False


# ─── _loc_display ─────────────────────────────────────────────────────────────


class TestLocDisplay:
    def _setup(self, scope: str, states=None, country="") -> _AlertSetup:
        s = _AlertSetup()
        s.location_scope = scope
        s.states = states or []
        s.country_code = country
        return s

    def test_us(self):
        assert _loc_display(self._setup("us")) == "Anywhere in the US"

    def test_remote(self):
        assert _loc_display(self._setup("remote")) == "Remote only"

    def test_state_single(self):
        assert _loc_display(self._setup("state", states=["CO"])) == "State(s): CO"

    def test_state_multiple(self):
        result = _loc_display(self._setup("state", states=["CO", "WA"]))
        assert result == "State(s): CO, WA"

    def test_country(self):
        assert _loc_display(self._setup("country", country="GB")) == "Country: GB"

    def test_worldwide(self):
        assert _loc_display(self._setup("worldwide")) == "Anywhere worldwide"


# ─── interval_display ────────────────────────────────────────────────────────


class TestIntervalDisplay:
    def test_1_minute(self):
        assert interval_display(1) == "1 minute (testing)"

    def test_30_minutes(self):
        assert interval_display(30) == "every 30 minutes"

    def test_60_minutes(self):
        assert interval_display(60) == "every hour"

    def test_120_minutes(self):
        assert interval_display(120) == "every 2 hours"

    def test_480_minutes(self):
        assert interval_display(480) == "every 8 hours"

    def test_1440_minutes(self):
        assert interval_display(1440) == "once a day"


# ─── _build_summary ───────────────────────────────────────────────────────────


class TestBuildSummary:
    def _base_setup(self) -> _AlertSetup:
        s = _AlertSetup()
        s.role_types = ["intern"]
        s.disciplines = ["swe"]
        s.location_scope = "us"
        s.interval_minutes = 60
        return s

    def test_contains_role(self):
        assert "Internships" in _build_summary(self._base_setup())

    def test_contains_new_grad(self):
        s = self._base_setup()
        s.role_types = ["new_grad"]
        assert "New Grad" in _build_summary(s)

    def test_both_roles(self):
        s = self._base_setup()
        s.role_types = ["intern", "new_grad"]
        summary = _build_summary(s)
        assert "Internships" in summary
        assert "New Grad" in summary

    def test_discipline_swe(self):
        assert "SWE" in _build_summary(self._base_setup())

    def test_discipline_both_shows_all(self):
        s = self._base_setup()
        s.disciplines = []
        assert "SWE + EE (all)" in _build_summary(s)

    def test_location_us(self):
        assert "Anywhere in the US" in _build_summary(self._base_setup())

    def test_keywords_shown(self):
        s = self._base_setup()
        s.keywords = ["rust", "kubernetes"]
        summary = _build_summary(s)
        assert "rust" in summary
        assert "kubernetes" in summary

    def test_keywords_omitted_when_empty(self):
        assert "Keywords" not in _build_summary(self._base_setup())

    def test_companies_shown(self):
        s = self._base_setup()
        s.companies = ["stripe"]
        assert "stripe" in _build_summary(s)

    def test_companies_omitted_when_empty(self):
        assert "Companies" not in _build_summary(self._base_setup())

    def test_quiet_hours_shown(self):
        s = self._base_setup()
        s.quiet_hours_start = "22:00"
        s.quiet_hours_end = "08:00"
        summary = _build_summary(s)
        assert "22:00" in summary
        assert "08:00" in summary

    def test_quiet_hours_omitted_when_none(self):
        assert "Quiet" not in _build_summary(self._base_setup())

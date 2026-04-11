from bot.commands import _PLATFORM_SCRAPERS, _build_filter_str, _fmt_csv
from bot.scrapers import ashby, greenhouse, lever


class TestFmtCsv:
    def test_single_value(self):
        assert _fmt_csv("stripe") == "stripe"

    def test_two_values(self):
        assert _fmt_csv("CO,WA") == "CO, WA"

    def test_trims_whitespace(self):
        assert _fmt_csv(" stripe , ramp ") == "stripe, ramp"

    def test_empty_string(self):
        assert _fmt_csv("") == ""

    def test_trailing_comma(self):
        assert _fmt_csv("stripe,") == "stripe"

    def test_leading_comma(self):
        assert _fmt_csv(",ramp") == "ramp"

    def test_many_values(self):
        result = _fmt_csv("a,b,c,d")
        assert result == "a, b, c, d"


class TestBuildFilterStr:
    def test_no_filters(self):
        assert _build_filter_str(None, None, None, None, None, None) == "no filters"

    def test_keyword_only(self):
        assert _build_filter_str("Python", None, None, None, None, None) == "keyword=**Python**"

    def test_company_only(self):
        assert _build_filter_str(None, "stripe", None, None, None, None) == "company=**stripe**"

    def test_role_only(self):
        assert _build_filter_str(None, None, "intern", None, None, None) == "role=**intern**"

    def test_discipline_only(self):
        assert _build_filter_str(None, None, None, "swe", None, None) == "discipline=**swe**"

    def test_state_only(self):
        assert _build_filter_str(None, None, None, None, "co", None) == "state=**CO**"

    def test_state_uppercased(self):
        result = _build_filter_str(None, None, None, None, "ca,wa", None)
        assert "CA, WA" in result

    def test_season_only(self):
        assert _build_filter_str(None, None, None, None, None, "Summer") == "season=**Summer**"

    def test_multiple_filters_joined(self):
        result = _build_filter_str("Python", "stripe", "intern", "swe", "CA", "Summer")
        assert "keyword=**Python**" in result
        assert "company=**stripe**" in result
        assert "role=**intern**" in result
        assert "discipline=**swe**" in result
        assert "state=**CA**" in result
        assert "season=**Summer**" in result

    def test_csv_keyword(self):
        result = _build_filter_str("Python,React", None, None, None, None, None)
        assert "Python, React" in result

    def test_csv_company(self):
        result = _build_filter_str(None, "stripe,ramp", None, None, None, None)
        assert "stripe, ramp" in result


# ---------------------------------------------------------------------------
# _PLATFORM_SCRAPERS
# ---------------------------------------------------------------------------


class TestPlatformScrapers:
    def test_contains_all_platforms(self):
        assert set(_PLATFORM_SCRAPERS) == {"greenhouse", "lever", "ashby"}

    def test_maps_to_correct_scrape_functions(self):
        assert _PLATFORM_SCRAPERS["greenhouse"] is greenhouse.scrape
        assert _PLATFORM_SCRAPERS["lever"] is lever.scrape
        assert _PLATFORM_SCRAPERS["ashby"] is ashby.scrape

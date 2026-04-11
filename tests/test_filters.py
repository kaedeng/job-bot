from bot.filters import passes_filter
from bot.models import Job


def _job(title: str = "Software Engineer Intern", location: str = "San Francisco, CA") -> Job:
    return Job(id="1", title=title, company="test", location=location, url="", source="test")


class TestTitleInclude:
    def test_intern(self):
        assert passes_filter(_job("Software Engineer Intern"))

    def test_internship(self):
        assert passes_filter(_job("SWE Internship - Summer 2025"))

    def test_new_grad(self):
        assert passes_filter(_job("New Grad Software Engineer"))

    def test_entry_level(self):
        assert passes_filter(_job("Entry Level Backend Engineer"))

    def test_entry_level_hyphen(self):
        assert passes_filter(_job("Entry-Level SWE"))

    def test_university_grad(self):
        assert passes_filter(_job("University Grad - Software Engineer"))

    def test_swe_i(self):
        assert passes_filter(_job("SWE I"))

    def test_l3(self):
        assert passes_filter(_job("Software Engineer L3"))

    def test_no_match(self):
        assert not passes_filter(_job("Software Engineer"))

    def test_mid_level(self):
        assert not passes_filter(_job("Software Engineer II"))


class TestTitleExclude:
    def test_senior(self):
        assert not passes_filter(_job("Senior Software Engineer Intern"))

    def test_staff(self):
        assert not passes_filter(_job("Staff Engineer - New Grad"))

    def test_principal(self):
        assert not passes_filter(_job("Principal Engineer Intern"))

    def test_manager(self):
        assert not passes_filter(_job("Engineering Manager - Entry Level"))

    def test_lead(self):
        assert not passes_filter(_job("Lead Software Engineer Intern"))

    def test_sr_dot(self):
        assert not passes_filter(_job("Sr. Software Engineer Intern"))


class TestLocation:
    def test_state_abbrev(self):
        assert passes_filter(_job(location="San Francisco, CA"))

    def test_state_name(self):
        assert passes_filter(_job(location="Austin, Texas"))

    def test_city(self):
        assert passes_filter(_job(location="Seattle"))

    def test_united_states(self):
        assert passes_filter(_job(location="United States"))

    def test_usa(self):
        assert passes_filter(_job(location="USA"))

    def test_remote(self):
        assert passes_filter(_job(location="Remote"))

    def test_non_us(self):
        assert not passes_filter(_job(location="London, UK"))

    def test_canada(self):
        assert not passes_filter(_job(location="Toronto, Ontario, Canada"))

    def test_empty(self):
        assert not passes_filter(_job(location=""))

    def test_multiple_locations_with_us(self):
        assert passes_filter(_job(location="New York, NY / London, UK"))

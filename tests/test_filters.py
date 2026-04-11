from bot.filters import (
    classify_discipline,
    classify_job,
    is_tech_job,
    parse_location,
    parse_locations,
    passes_filter,
)
from bot.models import Job


def _job(
    title: str = "Software Engineer Intern",
    location: str = "San Francisco, CA",
    source: str = "test",
    description: str | None = None,
) -> Job:
    return Job(
        id="1",
        title=title,
        company="test",
        location=location,
        url="",
        source=source,
        description=description,
    )


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

    def test_non_swe_intern_rejected(self):
        assert not passes_filter(_job("Marketing Intern"))

    def test_non_swe_new_grad_rejected(self):
        assert not passes_filter(_job("New Grad - Sales Associate"))


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


class TestClassifyJob:
    # --- Source trust ---
    def test_simplify_intern_source(self):
        assert classify_job(_job(source="simplify-intern")) == (True, False)

    def test_simplify_newgrad_source(self):
        assert classify_job(_job(source="simplify-newgrad")) == (False, True)

    # --- Title signals ---
    def test_title_intern(self):
        is_intern, _ = classify_job(_job(title="Software Engineer Intern"))
        assert is_intern

    def test_title_internship(self):
        is_intern, _ = classify_job(_job(title="SWE Internship"))
        assert is_intern

    def test_title_coop(self):
        is_intern, _ = classify_job(_job(title="Software Engineer Co-op"))
        assert is_intern

    def test_title_new_grad(self):
        _, is_new_grad = classify_job(_job(title="New Grad Software Engineer"))
        assert is_new_grad

    def test_title_entry_level(self):
        _, is_new_grad = classify_job(_job(title="Entry Level SWE"))
        assert is_new_grad

    def test_title_junior(self):
        _, is_new_grad = classify_job(_job(title="Junior Software Engineer"))
        assert is_new_grad

    def test_title_associate(self):
        _, is_new_grad = classify_job(_job(title="Associate Software Engineer"))
        assert is_new_grad

    def test_title_both(self):
        # Some postings cover both intern and new grad
        is_intern, is_new_grad = classify_job(_job(title="Intern / New Grad Software Engineer"))
        assert is_intern
        assert is_new_grad

    def test_title_neither(self):
        assert classify_job(_job(title="Software Engineer")) == (False, False)

    # --- Description signals ---
    def test_desc_intern_signal(self):
        job = _job(title="Software Engineer", description="This is an internship position.")
        is_intern, _ = classify_job(job)
        assert is_intern

    def test_desc_new_grad_signal(self):
        job = _job(title="Software Engineer", description="Recent graduates are welcome.")
        _, is_new_grad = classify_job(job)
        assert is_new_grad

    def test_desc_senior_exp_overrides(self):
        job = _job(title="Software Engineer Intern", description="Requires 5 years of experience.")
        assert classify_job(job) == (False, False)

    def test_desc_html_stripped(self):
        job = _job(title="Software Engineer", description="<p>Internship role for students</p>")
        is_intern, _ = classify_job(job)
        assert is_intern

    def test_no_description_uses_title_only(self):
        job = _job(title="Software Engineer Intern", description=None)
        assert classify_job(job) == (True, False)


class TestClassifyDiscipline:
    def test_swe(self):
        assert classify_discipline(_job(title="Software Engineer Intern")) == "swe"

    def test_swe_backend(self):
        assert classify_discipline(_job(title="Backend Engineer Intern")) == "swe"

    def test_swe_ml(self):
        assert classify_discipline(_job(title="ML Engineer Intern")) == "swe"

    def test_ee(self):
        assert classify_discipline(_job(title="Electrical Engineer Intern")) == "ee"

    def test_ee_firmware(self):
        assert classify_discipline(_job(title="Firmware Engineer Intern")) == "ee"

    def test_ee_fpga(self):
        assert classify_discipline(_job(title="FPGA Design Intern")) == "ee"

    def test_both_swe_and_ee(self):
        # "Embedded Software Engineer" matches both disciplines
        assert classify_discipline(_job(title="Embedded Software Engineer Intern")) == "swe,ee"

    def test_unknown(self):
        assert classify_discipline(_job(title="Marketing Intern")) == "unknown"

    def test_unknown_generic_engineer(self):
        # "Engineer" alone without a discipline qualifier → no SWE/EE signal
        assert classify_discipline(_job(title="Engineer I")) == "unknown"


class TestIsTechJob:
    def test_software_engineer(self):
        assert is_tech_job(_job(title="Software Engineer"))

    def test_swe(self):
        assert is_tech_job(_job(title="SWE Intern"))

    def test_electrical_engineer(self):
        assert is_tech_job(_job(title="Electrical Engineer"))

    def test_embedded_firmware(self):
        assert is_tech_job(_job(title="Embedded Firmware Engineer"))

    def test_data_engineer(self):
        assert is_tech_job(_job(title="Data Engineer"))

    def test_non_tech(self):
        assert not is_tech_job(_job(title="Marketing Manager"))

    def test_chef(self):
        assert not is_tech_job(_job(title="Chef"))

    def test_hr(self):
        assert not is_tech_job(_job(title="HR Business Partner"))


class TestParseLocation:
    def test_city_state(self):
        assert parse_location("San Francisco, CA") == ("US", "CA", "San Francisco")

    def test_city_full_state(self):
        country, state, city = parse_location("Austin, Texas")
        assert country == "US"
        assert state == "TX"
        assert city == "Austin"

    def test_new_york(self):
        assert parse_location("New York, NY") == ("US", "NY", "New York")

    def test_remote(self):
        country, state, _ = parse_location("Remote")
        assert country == "US"
        assert state is None

    def test_united_states(self):
        country, state, city = parse_location("United States")
        assert country == "US"
        assert state is None
        assert city is None

    def test_usa(self):
        country, _, _ = parse_location("USA")
        assert country == "US"

    def test_empty(self):
        assert parse_location("") == (None, None, None)

    def test_london_uk(self):
        assert parse_location("London, UK") == ("GB", None, "London")

    def test_united_kingdom(self):
        country, _, city = parse_location("London, United Kingdom")
        assert country == "GB"
        assert city == "London"

    def test_canada(self):
        country, _, city = parse_location("Toronto, Ontario, Canada")
        assert country == "CA"
        assert city == "Toronto"

    def test_germany(self):
        country, _, city = parse_location("Berlin, Germany")
        assert country == "DE"
        assert city == "Berlin"

    def test_no_country_no_state(self):
        # Unrecognized single token
        country, state, city = parse_location("Somewhere Unknown")
        assert country is None
        assert state is None


class TestParseLocations:
    def test_single_us(self):
        locs = parse_locations("San Francisco, CA")
        assert len(locs) == 1
        assert locs[0]["country"] == "US"
        assert locs[0]["state"] == "CA"
        assert locs[0]["city"] == "San Francisco"
        assert locs[0]["is_remote"] is False

    def test_remote_flag(self):
        locs = parse_locations("Remote")
        assert locs[0]["is_remote"] is True

    def test_multi_segment(self):
        locs = parse_locations("San Francisco, CA; Seattle, WA")
        assert len(locs) == 2
        states = {loc["state"] for loc in locs}
        assert states == {"CA", "WA"}

    def test_mixed_remote_and_onsite(self):
        locs = parse_locations("New York, NY; Remote")
        assert len(locs) == 2
        remote_flags = {loc["is_remote"] for loc in locs}
        assert True in remote_flags
        assert False in remote_flags

    def test_empty_string(self):
        assert parse_locations("") == []

    def test_international_segment(self):
        locs = parse_locations("London, UK")
        assert locs[0]["country"] == "GB"

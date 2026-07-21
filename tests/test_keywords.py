from bot.keywords import extract_keywords


class TestChemEKeywords:
    def test_extracts_process_software_and_lab_tools(self):
        keywords = extract_keywords(
            "Process Engineer Intern",
            "Use Aspen+, Aspen HYSYS, AFT Fathom, X-ray Diffraction, and Atomic Layer Deposition.",
        )

        assert "process engineer" in keywords
        assert "aspen+" in keywords
        assert "aspen hysys" in keywords
        assert "hysys" in keywords
        assert "aft fathom" in keywords
        assert "x-ray diffraction" in keywords
        assert "atomic layer deposition" in keywords

    def test_skips_generic_office_tools(self):
        keywords = extract_keywords("Chemical Engineer Intern", "Excel and PowerPoint.")

        assert "chemical engineer" in keywords
        assert "excel" not in keywords
        assert "powerpoint" not in keywords

from bot.company_names import resolve, search_by_slug


class TestIndustryCompanyNames:
    def test_oil_and_gas_aliases(self):
        assert resolve("slb") == "SLB"
        assert resolve("hfsinclair") == "HF Sinclair"
        assert resolve("enterpriseproductspartners") == "Enterprise Products Partners"
        assert resolve("mpc") == "Marathon Petroleum"

    def test_semiconductor_aliases(self):
        assert resolve("globalfoundries") == "GlobalFoundries"
        assert resolve("onsemi") == "onsemi"
        assert resolve("adi") == "Analog Devices"
        assert resolve("asml") == "ASML"

    def test_autocomplete_uses_new_aliases(self):
        assert "Applied Materials" in search_by_slug("applied")
        assert "NXP Semiconductors" in search_by_slug("nxp")

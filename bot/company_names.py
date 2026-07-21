from __future__ import annotations

# Maps scraper slugs / org identifiers → human-readable display names.
# Covers all platforms (Greenhouse, Lever, Ashby, Workday).
# Add entries here whenever a new slug produces an ugly name.
_DISPLAY_NAMES: dict[str, str] = {
    # --- Greenhouse ---
    "andurilindustries": "Anduril Industries",
    "lucidmotors": "Lucid Motors",
    "agilityrobotics": "Agility Robotics",
    "rocketlab": "Rocket Lab",
    "doordashusa": "DoorDash",
    "scaleai": "Scale AI",
    "mongodb": "MongoDB",
    "gleanwork": "Glean",
    "cerebrassystems": "Cerebras Systems",
    "xai": "xAI",
    "launchdarkly": "LaunchDarkly",
    "cockroachlabs": "Cockroach Labs",
    "grafanalabs": "Grafana Labs",
    "hubspot": "HubSpot",
    "spacex": "SpaceX",
    "janestreet": "Jane Street",
    "gitlab": "GitLab",
    "hrttalentcommunity": "Hudson River Trading",
    "coupang": "Coupang",
    # --- Ashby ---
    "openai": "OpenAI",
    "1password": "1Password",
    # --- Lever ---
    "spotify": "Spotify",
    "palantir": "Palantir",
    "blueorigin": "Blue Origin",
    # --- Workday (org / subdomain prefix) ---
    "nvidia": "NVIDIA",
    "capitalone": "Capital One",
    "micron": "Micron",
    "bpinternational": "BP",
    # --- Chemicals / energy targets ---
    "basf": "BASF",
    "dupont": "DuPont",
    "chemours": "Chemours",
    "burnsmcd": "Burns & McDonnell",
    "jacobs": "Jacobs",
    "chevron": "Chevron",
    "shell": "Shell",
    "cenovus": "Cenovus Energy",
    "exxonmobil": "ExxonMobil",
    "conocophillips": "ConocoPhillips",
    "phillips66": "Phillips 66",
    "valero": "Valero",
    "oxy": "Oxy",
    "occidental": "Occidental",
    "occidentalpetroleum": "Occidental Petroleum",
    "marathonpetroleum": "Marathon Petroleum",
    "marathon": "Marathon Petroleum",
    "mpc": "Marathon Petroleum",
    "globalhr": "Raytheon",
    "ngc": "Northrop Grumman",
    "tmobile": "T-Mobile",
    "snapchat": "Snap",
    # --- Oil / gas operators, refiners, midstream ---
    "bp": "BP",
    "eog": "EOG Resources",
    "eogresources": "EOG Resources",
    "devon": "Devon Energy",
    "devonenergy": "Devon Energy",
    "ovintiv": "Ovintiv",
    "hess": "Hess",
    "hfsinclair": "HF Sinclair",
    "hf": "HF Sinclair",
    "pbfenergy": "PBF Energy",
    "pbf": "PBF Energy",
    "citgo": "CITGO",
    "suncor": "Suncor Energy",
    "suncorenergy": "Suncor Energy",
    "enterpriseproducts": "Enterprise Products Partners",
    "enterpriseproductspartners": "Enterprise Products Partners",
    "enterpriseproductspar": "Enterprise Products Partners",
    "energytransfer": "Energy Transfer",
    "kindermorgan": "Kinder Morgan",
    # --- Oilfield services / equipment ---
    "slb": "SLB",
    "schlumberger": "SLB",
    "halliburton": "Halliburton",
    "bakerhughes": "Baker Hughes",
    "technipfmc": "TechnipFMC",
    "nov": "NOV",
    "weatherford": "Weatherford",
    "championx": "ChampionX",
    # --- Semiconductor manufacturing ---
    "tsmc": "TSMC",
    "taiwansemiconductor": "TSMC",
    "samsungsemiconductor": "Samsung Semiconductor",
    "samsung": "Samsung Semiconductor",
    "globalfoundries": "GlobalFoundries",
    "texasinstruments": "Texas Instruments",
    "ti": "Texas Instruments",
    "analogdevices": "Analog Devices",
    "adi": "Analog Devices",
    "onsemi": "onsemi",
    "wolfspeed": "Wolfspeed",
    "infineon": "Infineon",
    "nxp": "NXP Semiconductors",
    "nxpsemiconductors": "NXP Semiconductors",
    "skywater": "SkyWater Technology",
    "skywatertechnology": "SkyWater Technology",
    "qorvo": "Qorvo",
    "broadcom": "Broadcom",
    "microchip": "Microchip Technology",
    "microchiptechnology": "Microchip Technology",
    "towersemiconductor": "Tower Semiconductor",
    "coherent": "Coherent",
    "appliedoptoelectronics": "Applied Optoelectronics",
    # --- Semiconductor equipment ---
    "appliedmaterials": "Applied Materials",
    "lamresearch": "Lam Research",
    "kla": "KLA",
    "asml": "ASML",
    "tokyoelectron": "Tokyo Electron",
    "tel": "Tokyo Electron",
    "asminternational": "ASM International",
    "asm": "ASM International",
    "axcelis": "Axcelis Technologies",
    "axcelistechnologies": "Axcelis Technologies",
    "veeco": "Veeco",
    "ontoinnovation": "Onto Innovation",
    "entegris": "Entegris",
}


def resolve(slug: str) -> str:
    """Return the display name for a slug, falling back to a capitalized version."""
    return _DISPLAY_NAMES.get(slug, slug.capitalize())


def search_by_slug(prefix: str, limit: int = 25) -> list[str]:
    """Return display names whose slug starts with *prefix* (case-insensitive)."""
    prefix_lower = prefix.lower()
    return [
        display
        for slug, display in _DISPLAY_NAMES.items()
        if slug.startswith(prefix_lower)
    ][:limit]

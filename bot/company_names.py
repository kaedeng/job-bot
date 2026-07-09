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
    "globalhr": "Raytheon",
    "ngc": "Northrop Grumman",
    "tmobile": "T-Mobile",
    "snapchat": "Snap",
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

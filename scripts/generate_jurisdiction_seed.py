"""Generate the deterministic jurisdiction catalog candidate seed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from langgraph_graph.meta_legal.jurisdictions import default_catalog_path
from langgraph_graph.meta_legal.models import slugify

REPO_ROOT = Path(__file__).resolve().parents[1]
ISO_PATH = Path("/usr/share/iso-codes/json/iso_3166-1.json")

US_STATES = (
    "Alabama",
    "Alaska",
    "Arizona",
    "Arkansas",
    "California",
    "Colorado",
    "Connecticut",
    "Delaware",
    "Florida",
    "Georgia",
    "Hawaii",
    "Idaho",
    "Illinois",
    "Indiana",
    "Iowa",
    "Kansas",
    "Kentucky",
    "Louisiana",
    "Maine",
    "Maryland",
    "Massachusetts",
    "Michigan",
    "Minnesota",
    "Mississippi",
    "Missouri",
    "Montana",
    "Nebraska",
    "Nevada",
    "New Hampshire",
    "New Jersey",
    "New Mexico",
    "New York",
    "North Carolina",
    "North Dakota",
    "Ohio",
    "Oklahoma",
    "Oregon",
    "Pennsylvania",
    "Rhode Island",
    "South Carolina",
    "South Dakota",
    "Tennessee",
    "Texas",
    "Utah",
    "Vermont",
    "Virginia",
    "Washington",
    "West Virginia",
    "Wisconsin",
    "Wyoming",
    "District of Columbia",
)
US_TERRITORIES = (
    "Puerto Rico",
    "Guam",
    "American Samoa",
    "U.S. Virgin Islands",
    "Northern Mariana Islands",
)
CANADA = (
    "Alberta",
    "British Columbia",
    "Manitoba",
    "New Brunswick",
    "Newfoundland and Labrador",
    "Nova Scotia",
    "Ontario",
    "Prince Edward Island",
    "Québec",
    "Saskatchewan",
    "Northwest Territories",
    "Nunavut",
    "Yukon",
)
GERMANY = (
    "Baden-Württemberg",
    "Bavaria",
    "Berlin",
    "Brandenburg",
    "Bremen",
    "Hamburg",
    "Hesse",
    "Lower Saxony",
    "Mecklenburg-Western Pomerania",
    "North Rhine-Westphalia",
    "Rhineland-Palatinate",
    "Saarland",
    "Saxony",
    "Saxony-Anhalt",
    "Schleswig-Holstein",
    "Thuringia",
)
AUSTRALIA = (
    "New South Wales",
    "Queensland",
    "South Australia",
    "Tasmania",
    "Victoria",
    "Western Australia",
    "Australian Capital Territory",
    "Northern Territory",
)


def _entry(name: str, level: str, parent_id: str | None = None) -> dict[str, Any]:
    """Create a stable seed entry."""
    base = slugify(name)
    identifier = f"{base}_{parent_id}" if parent_id else base
    return {"id": identifier, "name": name, "level": level, "parent_id": parent_id}


def generate(output: Path) -> None:
    """Generate ISO countries plus curated subnational coverage."""
    iso = json.loads(ISO_PATH.read_text(encoding="utf-8"))["3166-1"]
    candidates = [
        _entry("European Union", "supranational"),
        _entry("Council of Europe", "supranational"),
        _entry("African Union", "supranational"),
    ] + [_entry(item["name"], "country") for item in iso if item["name"] not in {"United Nations"}]
    candidates.extend(
        _entry(name, "us_state", "united_states") for name in US_STATES + US_TERRITORIES
    )
    candidates.extend(_entry(name, "state_province", "canada") for name in CANADA)
    candidates.extend(_entry(name, "state_province", "germany") for name in GERMANY)
    candidates.extend(_entry(name, "state_province", "australia") for name in AUSTRALIA)
    current = json.loads(default_catalog_path().read_text(encoding="utf-8"))
    candidates.extend(item for item in current["jurisdictions"] if item.get("level") == "us_city")
    by_id = {item["id"]: item for item in candidates}
    discovered = []
    if output.is_file():
        try:
            previous = json.loads(output.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
        discovered = list(previous.get("discovered_candidates") or [])
    discovered_by_id = {item["id"]: item for item in discovered if item.get("id")}
    document = {
        "version": "2",
        "source": "ISO 3166-1 from iso-codes plus curated ISO 3166-2-style subnational sets and current US cities",
        "candidates": [by_id[key] for key in sorted(by_id)],
    }
    if discovered_by_id:
        document["discovered_candidates"] = list(discovered_by_id.values())
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    """Parse CLI arguments and generate the seed."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "data/jurisdictions/jurisdiction_catalog_seed.json",
    )
    args = parser.parse_args()
    generate(args.output)


if __name__ == "__main__":
    main()

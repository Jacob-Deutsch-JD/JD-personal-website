#!/usr/bin/env python3
"""
Generate holidays.json for Annual Events Editor using Vacanza holidays.

Install:
    python -m pip install --upgrade holidays

Typical use:
    python build_holidays.py

Defaults:
    start year: current calendar year
    end year:   current year + 9 (10-year rolling window)
    output:     holidays.json
    countries:  every Vacanza-supported country (aliases excluded)

The resulting holidays.json is intended to sit beside the HTML file:

    annual-events-editor.html
    holidays.json

The webpage loads ./holidays.json automatically.

Important:
Future holidays are calculations according to the rules/data available in the
installed Vacanza version. Some countries/categories also use finite date
tables, so the default is a rolling 10-year window beginning with the year the
generator is run. Regenerating periodically with a current Vacanza release lets
those finite tables move forward as upstream data is extended. Governments can
change holiday laws and one-off dates can be announced later.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    import holidays
    from holidays import country_holidays, list_supported_countries
except ImportError:
    raise SystemExit(
        "Vacanza holidays is not installed.\n"
        "Install it with:\n"
        "  python -m pip install --upgrade holidays"
    )


PREFERRED_ENGLISH_LANGUAGES = (
    "en_US",
    "en_GB",
    "en_IN",
    "en_AU",
    "en_CA",
    "en_NZ",
    "en",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate static holidays.json data using Vacanza holidays."
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=None,
        help=(
            "First year to generate. Default: the current calendar year at "
            "generation time."
        ),
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=None,
        help=(
            "Last year to generate, inclusive. Default: 9 years after the "
            "resolved start year (10 years total)."
        ),
    )
    parser.add_argument(
        "--years",
        type=int,
        default=10,
        help=(
            "Rolling window length used only when --end-year is omitted "
            "(default: 10)."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("holidays.json"),
        help="Output JSON path (default: holidays.json).",
    )
    parser.add_argument(
        "--countries",
        default="all",
        help=(
            "Comma-separated ISO country codes, e.g. US,IN,GB. "
            "Default: all supported countries."
        ),
    )
    parser.add_argument(
        "--chunk-years",
        type=int,
        default=25,
        help=(
            "Generate this many years at a time per country/category. "
            "Smaller values use less memory and isolate errors better (default: 25)."
        ),
    )
    parser.add_argument(
        "--no-observed",
        action="store_true",
        help="Do not include substitute/observed holiday dates.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON. The default compact JSON is much smaller.",
    )
    return parser.parse_args()


def chunks(start: int, end: int, size: int) -> Iterable[range]:
    current = start
    while current <= end:
        stop = min(end, current + size - 1)
        yield range(current, stop + 1)
        current = stop + 1


def preferred_language(instance) -> str | None:
    supported = tuple(getattr(instance, "supported_languages", ()) or ())

    for candidate in PREFERRED_ENGLISH_LANGUAGES:
        if candidate in supported:
            return candidate

    for language in supported:
        if str(language).lower().startswith("en"):
            return str(language)

    return None


def normalize_categories(instance) -> list[str]:
    categories = getattr(instance, "supported_categories", None) or ("public",)

    result = []
    seen = set()

    for category in categories:
        value = str(category).lower()
        if value not in seen:
            seen.add(value)
            result.append(value)

    if "public" not in seen:
        result.insert(0, "public")

    return result


def get_country_codes(requested: str) -> list[str]:
    supported = list_supported_countries(include_aliases=False)
    supported_codes = sorted(supported)

    if requested.strip().lower() == "all":
        return supported_codes

    wanted = []
    for raw in requested.split(","):
        code = raw.strip().upper()
        if not code:
            continue
        if code not in supported:
            raise SystemExit(
                f"Unsupported country code: {code}\n"
                f"Use ISO alpha-2 codes supported by Vacanza."
            )
        wanted.append(code)

    return sorted(set(wanted))


def generate_country(
    code: str,
    start_year: int,
    end_year: int,
    observed: bool,
    chunk_years: int,
) -> tuple[dict, int]:
    """
    Return (country_record, event_count).

    Each event is stored compactly as:
        ["MM-DD", "Holiday name", ["category", ...]]

    Generating each supported category separately preserves category information,
    which the browser uses to distinguish public from cultural/optional events.
    """
    prototype = country_holidays(
        code,
        years=None,
        expand=False,
        observed=observed,
    )

    categories = normalize_categories(prototype)
    language = preferred_language(prototype)

    # year -> (MM-DD, name) -> categories
    collected: dict[int, dict[tuple[str, str], set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    errors: list[str] = []
    generation_warnings: set[str] = set()

    for category in categories:
        for year_chunk in chunks(start_year, end_year, chunk_years):
            kwargs = dict(
                years=year_chunk,
                expand=False,
                observed=observed,
                categories=category,
            )
            if language:
                kwargs["language"] = language

            try:
                with warnings.catch_warnings(record=True) as caught_warnings:
                    warnings.simplefilter("always")
                    calendar = country_holidays(code, **kwargs)
            except Exception as exc:
                errors.append(
                    f"{category} {year_chunk.start}-{year_chunk.stop - 1}: "
                    f"{type(exc).__name__}: {exc}"
                )
                continue

            for warning in caught_warnings:
                generation_warnings.add(
                    f"{category} {year_chunk.start}-{year_chunk.stop - 1}: "
                    f"{warning.category.__name__}: {warning.message}"
                )

            for day in sorted(calendar):
                if not (start_year <= day.year <= end_year):
                    continue

                # get_list() keeps distinct holidays separate when several
                # share one calendar date.
                try:
                    names = calendar.get_list(day)
                except Exception:
                    names = [str(calendar[day])]

                for holiday_name in names:
                    name = str(holiday_name).strip()
                    if not name:
                        continue

                    month_day = f"{day.month:02d}-{day.day:02d}"
                    collected[day.year][(month_day, name)].add(category)

    years_json: dict[str, list] = {}
    total = 0

    for year in sorted(collected):
        rows = []
        for (month_day, name), event_categories in sorted(
            collected[year].items(),
            key=lambda item: (item[0][0], item[0][1].casefold()),
        ):
            rows.append(
                [
                    month_day,
                    name,
                    sorted(event_categories),
                ]
            )

        if rows:
            years_json[str(year)] = rows
            total += len(rows)

    record = {
        "categories": categories,
        "language": language,
        "library_start_year": getattr(prototype, "start_year", None),
        "library_end_year": getattr(prototype, "end_year", None),
        "years": years_json,
    }

    if generation_warnings:
        record["generation_warnings"] = sorted(generation_warnings)

    if errors:
        record["generation_errors"] = errors

    return record, total


def main() -> int:
    args = parse_args()

    current_year = datetime.now().year

    if args.years < 1:
        raise SystemExit("--years must be >= 1")

    if args.start_year is None:
        args.start_year = current_year

    if args.end_year is None:
        args.end_year = args.start_year + args.years - 1

    if args.start_year > args.end_year:
        raise SystemExit("--start-year must be <= --end-year")

    if args.chunk_years < 1:
        raise SystemExit("--chunk-years must be >= 1")

    country_codes = get_country_codes(args.countries)
    observed = not args.no_observed

    countries = {}
    total_events = 0
    countries_with_errors = 0
    countries_with_warnings = 0
    problem_details = []

    print(
        f"Current year: {current_year}"
    )
    print(
        f"Generating {args.start_year}-{args.end_year} for "
        f"{len(country_codes)} countries using holidays {holidays.__version__}..."
    )

    for index, code in enumerate(country_codes, 1):
        print(f"[{index:>3}/{len(country_codes)}] {code}", flush=True)

        try:
            record, count = generate_country(
                code=code,
                start_year=args.start_year,
                end_year=args.end_year,
                observed=observed,
                chunk_years=args.chunk_years,
            )
        except Exception as exc:
            countries[code] = {
                "categories": [],
                "language": None,
                "years": {},
                "generation_errors": [
                    f"Country generation failed: {type(exc).__name__}: {exc}"
                ],
            }
            countries_with_errors += 1
            problem_details.append(
                ("ERROR", code, f"Country generation failed: {type(exc).__name__}: {exc}")
            )
            continue

        countries[code] = record
        total_events += count

        if record.get("generation_warnings"):
            countries_with_warnings += 1
            for message in record["generation_warnings"]:
                problem_details.append(("WARNING", code, message))

        if record.get("generation_errors"):
            countries_with_errors += 1
            for message in record["generation_errors"]:
                problem_details.append(("ERROR", code, message))

    payload = {
        "schema": 1,
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generator": "build_holidays.py",
            "source": "Vacanza holidays / Open World Holidays Framework",
            "source_url": "https://github.com/vacanza/holidays",
            "source_license": "MIT",
            "library_version": holidays.__version__,
            "generation_current_year": current_year,
            "rolling_window_years": args.end_year - args.start_year + 1,
            "start_year": args.start_year,
            "end_year": args.end_year,
            "observed": observed,
            "country_count": len(country_codes),
            "event_count": total_events,
            "countries_with_generation_warnings": countries_with_warnings,
            "countries_with_generation_errors": countries_with_errors,
            "future_date_note": (
                "Future dates are calculations according to rules/data available "
                "when this file was generated; future government declarations "
                "and law changes cannot be known in advance."
            ),
        },
        "countries": countries,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)

    if args.pretty:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
        ) + "\n"
    else:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=False,
        )

    args.output.write_text(encoded, encoding="utf-8")

    size_mb = args.output.stat().st_size / (1024 * 1024)
    print()
    print(f"Wrote: {args.output}")
    print(f"Countries: {len(country_codes)}")
    print(f"Holiday records: {total_events:,}")
    print(f"File size: {size_mb:.2f} MiB")
    if countries_with_warnings:
        print(f"Countries with generation warnings: {countries_with_warnings}")

    if countries_with_errors:
        print(f"Countries with generation errors: {countries_with_errors}")

    if problem_details:
        print()
        print("Generation diagnostics:")
        for level, code, message in problem_details:
            print(f"  [{level}] {code}: {message}")

        print()
        print(
            "Warnings/errors are also stored inside each country's "
            "generation_warnings / generation_errors fields in holidays.json."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())

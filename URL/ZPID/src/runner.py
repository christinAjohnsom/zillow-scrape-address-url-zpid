import argparse
import json
import logging
from pathlib import Path
from typing import List

from extractors.zillow_parser import (
    ZillowClient,
    PropertyData,
    InputRecord,
    classify_input,
)
from extractors.formatting_utils import (
    load_inputs_from_file,
    properties_to_serializable,
)
from outputs.exporters import export_to_json_file, export_to_csv_file

DEFAULT_SETTINGS = {
    "base_url": "https://www.zillow.com",
    "timeout": 15,
    "concurrency": 2,
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "output_format": "json",
}

def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

def load_settings(settings_path: Path | None) -> dict:
    if settings_path is None:
        logging.debug("No settings path provided, using default settings.")
        return DEFAULT_SETTINGS.copy()

    if not settings_path.exists():
        logging.warning(
            "Settings file %s not found, falling back to defaults.",
            settings_path,
        )
        return DEFAULT_SETTINGS.copy()

    try:
        with settings_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        merged = DEFAULT_SETTINGS.copy()
        merged.update(data or {})
        logging.info("Loaded settings from %s", settings_path)
        return merged
    except Exception as exc:  # noqa: BLE001
        logging.error("Failed to load settings from %s: %s", settings_path, exc)
        return DEFAULT_SETTINGS.copy()

def resolve_paths(
    input_path: str,
    output_path: str | None,
) -> tuple[Path, Path, Path]:
    """
    Resolve paths relative to the project root.

    runner.py lives in src/, so the project root is one level up.
    """
    src_dir = Path(__file__).resolve().parent
    project_root = src_dir.parent

    input_file = (project_root / input_path).resolve()
    if output_path:
        output_base = (project_root / output_path).resolve()
    else:
        output_base = (project_root / "data" / "output").resolve()

    output_base.parent.mkdir(parents=True, exist_ok=True)

    logging.debug("Project root resolved to %s", project_root)
    logging.debug("Input file resolved to %s", input_file)
    logging.debug("Output base resolved to %s", output_base)

    return project_root, input_file, output_base

def process_records(
    client: ZillowClient,
    records: List[InputRecord],
) -> List[PropertyData]:
    results: List[PropertyData] = []
    for idx, record in enumerate(records, start=1):
        try:
            logging.info(
                "Processing record %d/%d: %s (%s)",
                idx,
                len(records),
                record.value,
                record.kind,
            )
            property_data = client.fetch_property(record)
            results.append(property_data)
        except Exception as exc:  # noqa: BLE001
            logging.error(
                "Failed to fetch data for input '%s': %s",
                record.raw,
                exc,
            )
    return results

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Zillow Scrape: Address/URL/ZPID – property data fetcher",
    )
    parser.add_argument(
        "--input",
        "-i",
        default="data/inputs.sample.txt",
        help=(
            "Path to input file containing one address, ZPID, or URL per line. "
            "Defaults to data/inputs.sample.txt"
        ),
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help=(
            "Output file path without extension. "
            "If omitted, defaults to data/output.(json|csv)."
        ),
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["json", "csv", "both"],
        default=None,
        help="Output format: json, csv, or both. Defaults to settings.output_format.",
    )
    parser.add_argument(
        "--settings",
        "-s",
        default="src/config/settings.example.json",
        help="Path to JSON settings file. Defaults to src/config/settings.example.json",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging.",
    )
    return parser.parse_args()

def main() -> None:
    args = parse_args()
    setup_logging(verbose=args.verbose)

    project_root, input_file, output_base = resolve_paths(
        input_path=args.input,
        output_path=args.output,
    )

    settings = load_settings(Path(args.settings))

    effective_format = args.format or settings.get("output_format", "json")
    if effective_format not in {"json", "csv", "both"}:
        logging.warning(
            "Unknown format '%s', falling back to 'json'.",
            effective_format,
        )
        effective_format = "json"

    if not input_file.exists():
        logging.error("Input file %s does not exist.", input_file)
        raise SystemExit(1)

    records = load_inputs_from_file(input_file)

    if not records:
        logging.error("No valid inputs found in %s", input_file)
        raise SystemExit(1)

    client = ZillowClient(
        base_url=settings["base_url"],
        timeout=settings["timeout"],
        user_agent=settings["user_agent"],
    )

    properties = process_records(client, records)
    serializable = properties_to_serializable(properties)

    if effective_format in {"json", "both"}:
        json_path = output_base.with_suffix(".json")
        export_to_json_file(serializable, json_path)

    if effective_format in {"csv", "both"}:
        csv_path = output_base.with_suffix(".csv")
        export_to_csv_file(serializable, csv_path)

    logging.info(
        "Done. Processed %d properties. Output base: %s",
        len(properties),
        output_base,
    )

if __name__ == "__main__":
    main()
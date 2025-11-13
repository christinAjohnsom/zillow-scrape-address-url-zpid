URRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from extractors.zillow_parser import ZillowParser
from extractors.helpers_cleaning import normalize_property_record
from outputs.exporters import export_records, guess_format_from_path

def configure_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

def load_settings(settings_path: Path) -> Dict[str, Any]:
    """
    Load JSON settings. If file doesn't exist, return sensible defaults.
    """
    defaults: Dict[str, Any] = {
        "base_url": "https://www.zillow.com",
        "input_file": str(
            (CURRENT_DIR.parent / "data" / "inputs.sample.txt").resolve()
        ),
        "output_file": str(
            (CURRENT_DIR.parent / "data" / "sample_output.json").resolve()
        ),
        "output_format": "json",
        "rate_limit_per_second": 2.0,
    }

    if not settings_path.exists():
        logging.info("Settings file %s not found, using defaults.", settings_path)
        return defaults

    try:
        with settings_path.open("r", encoding="utf-8") as f:
            user_settings = json.load(f)
        if not isinstance(user_settings, dict):
            raise ValueError("Settings JSON must be an object at top-level.")
        defaults.update(user_settings)
    except Exception as exc:
        logging.error("Failed to read settings from %s: %s", settings_path, exc)
    return defaults

def read_input_values(path: Path) -> List[str]:
    """
    Read input values (address/URL/ZPID), one per line, ignoring empty and comment lines.
    """
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    values: List[str] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            values.append(stripped)
    return values

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Zillow Scrape: Address/URL/ZPID - property data scraper"
    )
    parser.add_argument(
        "-s",
        "--settings",
        help="Path to settings JSON file (defaults to src/config/settings.example.json)",
        default=str((CURRENT_DIR / "config" / "settings.example.json").resolve()),
    )
    parser.add_argument(
        "-i",
        "--input",
        help="Override input file path (one address/URL/ZPID per line).",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Override output file path (JSON/CSV/Excel/XML/JSONV).",
    )
    parser.add_argument(
        "-f",
        "--format",
        help="Output format: json, csv, excel, xml, jsonv. "
             "If omitted, guessed from output file extension.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v, -vv).",
    )
    return parser.parse_args()

def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)

    settings_path = Path(args.settings).expanduser()
    settings = load_settings(settings_path)

    if args.input:
        settings["input_file"] = args.input
    if args.output:
        settings["output_file"] = args.output
    if args.format:
        settings["output_format"] = args.format

    input_path = Path(settings["input_file"]).expanduser()
    output_path = Path(settings["output_file"]).expanduser()
    output_format = settings.get("output_format") or guess_format_from_path(output_path)
    rate_limit = float(settings.get("rate_limit_per_second") or 0)

    logging.info("Using input file: %s", input_path)
    logging.info("Using output file: %s", output_path)
    logging.info("Output format: %s", output_format)

    try:
        values = read_input_values(input_path)
    except Exception as exc:
        logging.error("Failed to read inputs: %s", exc)
        sys.exit(1)

    if not values:
        logging.warning("No input values found in %s", input_path)
        sys.exit(0)

    base_url = str(settings.get("base_url") or "https://www.zillow.com")

    records: List[Dict[str, Any]] = []
    processed = 0

    try:
        with ZillowParser(base_url=base_url, rate_limit_per_second=rate_limit) as parser:
            for raw_value in values:
                processed += 1
                try:
                    raw_record = parser.lookup(raw_value)
                    normalized = normalize_property_record(
                        raw_record,
                        source=raw_value,
                        fallback_url=base_url,
                    )
                    records.append(normalized)
                except Exception as exc:
                    logging.exception(
                        "Failed to resolve '%s' (%d/%d): %s",
                        raw_value,
                        processed,
                        len(values),
                        exc,
                    )
    except Exception as exc:
        logging.exception("Fatal error during scraping: %s", exc)
        sys.exit(1)

    if not records:
        logging.warning("No properties resolved successfully.")
        sys.exit(0)

    try:
        export_records(records, output_path, output_format)
    except Exception as exc:
        logging.exception("Failed to export records: %s", exc)
        sys.exit(1)

    print(
        f"Processed {processed} inputs, successfully resolved {len(records)} "
        f"properties.\nOutput written to: {output_path}"
    )

if __name__ == "__main__":
    main()
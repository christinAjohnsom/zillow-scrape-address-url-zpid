from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

def _ensure_parent_dir(path: Path) -> None:
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

def export_to_json_file(
    records: Sequence[Mapping[str, object]],
    path: Path,
) -> None:
    """Write records to a JSON file."""
    _ensure_parent_dir(path)
    with path.open("w", encoding="utf-8") as f:
        json.dump(list(records), f, indent=4)
    logger.info("Wrote %d records to JSON file %s", len(records), path)

def export_to_csv_file(
    records: Sequence[Mapping[str, object]],
    path: Path,
) -> None:
    """Write records to a CSV file (flat structure)."""
    _ensure_parent_dir(path)
    if not records:
        logger.warning(
            "No records provided, writing empty CSV file %s",
            path,
        )
        with path.open("w", encoding="utf-8", newline="") as f:
            f.write("")
        return

    # Use keys from the first record as header.
    fieldnames = list(records[0].keys())

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            flat_record = dict(record)
            # Serialize nested priceHistory for CSV output.
            if "priceHistory" in flat_record and isinstance(
                flat_record["priceHistory"],
                list,
            ):
                flat_record["priceHistory"] = json.dumps(
                    flat_record["priceHistory"],
                    ensure_ascii=False,
                )
            writer.writerow(flat_record)

    logger.info("Wrote %d records to CSV file %s", len(records), path)
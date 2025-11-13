from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List

from .zillow_parser import InputRecord, PropertyData, classify_input

logger = logging.getLogger(__name__)

def load_inputs_from_file(path: Path) -> List[InputRecord]:
    """Load input lines from a text file into classified InputRecord objects."""
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    records: List[InputRecord] = []
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            try:
                record = classify_input(raw)
                records.append(record)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping invalid input at line %d in %s: %s (%s)",
                    line_number,
                    path,
                    raw,
                    exc,
                )
    logger.info("Loaded %d valid inputs from %s", len(records), path)
    return records

def properties_to_serializable(
    properties: Iterable[PropertyData],
) -> List[dict]:
    """Convert PropertyData objects into JSON-serializable dictionaries."""
    result = [prop.to_dict() for prop in properties]
    logger.debug("Converted %d properties to serializable dicts", len(result))
    return result
import re
from typing import Any, Dict, Optional

def clean_text(value: str) -> str:
    """
    Trim and collapse internal whitespace.
    """
    if value is None:
        return ""
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text

def slugify_address(address: str) -> str:
    """
    Convert an address string to a Zillow-friendly slug segment.
    Example:
        "7254 Wisteria Ln, Lake Wales, FL 33898"
        -> "7254-Wisteria-Ln-Lake-Wales-FL-33898"
    """
    address = clean_text(address)
    # Remove characters that often cause issues in URLs
    address = re.sub(r"[#,/]", " ", address)
    address = re.sub(r"[^0-9a-zA-Z\s-]", "", address)
    address = re.sub(r"\s+", "-", address)
    return address.strip("-")

def parse_int(value: Any) -> Optional[int]:
    """
    Best-effort cast to int. Returns None on failure.
    """
    if value is None:
        return None
    try:
        if isinstance(value, (int,)):
            return int(value)
        if isinstance(value, float):
            return int(round(value))
        text = str(value)
        digits = re.sub(r"[^\d\-]", "", text)
        if not digits:
            return None
        return int(digits)
    except (ValueError, TypeError):
        return None

def parse_float(value: Any) -> Optional[float]:
    """
    Best-effort cast to float. Returns None on failure.
    """
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value)
        # Keep digits, minus sign, and decimal point
        cleaned = re.sub(r"[^\d\.\-]", "", text)
        if not cleaned:
            return None
        return float(cleaned)
    except (ValueError, TypeError):
        return None

def parse_price(text: str) -> Optional[int]:
    """
    Extract a numeric price from a string like "$239,900" or "USD 239900".
    """
    if not text:
        return None
    # Remove currency symbols and non-numeric characters, keep digits and commas
    cleaned = re.sub(r"[^\d]", "", text)
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None

def normalize_property_record(
    raw: Dict[str, Any],
    source: Optional[str] = None,
    fallback_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Normalize a raw record into a consistent schema with all expected fields present.
    """
    normalized: Dict[str, Any] = {}

    # Core fields we want in the final output
    fields = [
        "address",
        "zpid",
        "url",
        "zestimate",
        "rentZestimate",
        "bedrooms",
        "bathrooms",
        "livingArea",
        "lotSize",
        "homeType",
        "yearBuilt",
        "price",
        "status",
    ]

    # Copy over and coerce numeric fields as needed
    for field in fields:
        value = raw.get(field)
        if field in {"bedrooms", "bathrooms"}:
            numeric = parse_float(value)
            normalized[field] = numeric
        elif field in {"livingArea", "lotSize", "yearBuilt", "price"}:
            normalized[field] = parse_int(value)
        elif field in {"zestimate", "rentZestimate"}:
            normalized[field] = parse_float(value)
        elif field == "homeType" or field == "status":
            text = clean_text(str(value or ""))
            normalized[field] = text or None
        elif field in {"address", "url"}:
            text = clean_text(str(value or ""))
            normalized[field] = text or None
        elif field == "zpid":
            text = clean_text(str(value or ""))
            normalized[field] = text or None
        else:
            normalized[field] = value

    # Provide sensible fallbacks
    if not normalized.get("url") and fallback_url:
        normalized["url"] = clean_text(fallback_url)

    normalized["sourceInput"] = clean_text(source or "")

    return normalized
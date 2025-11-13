from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

@dataclass
class PriceEvent:
    date: str
    event: str
    price: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "event": self.event,
            "price": self.price,
        }

@dataclass
class PropertyData:
    address: str
    zpid: str
    url: str
    zestimate: Optional[int] = None
    bedrooms: Optional[float] = None
    bathrooms: Optional[float] = None
    livingArea: Optional[int] = None
    lotSize: Optional[int] = None
    yearBuilt: Optional[int] = None
    propertyType: Optional[str] = None
    priceHistory: List[PriceEvent] | None = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["priceHistory"] = [
            event.to_dict() for event in (self.priceHistory or [])
        ]
        return data

@dataclass
class InputRecord:
    raw: str
    kind: str  # "address", "zpid", "url"
    value: str

def classify_input(raw: str) -> InputRecord:
    """Classify a raw line as address, ZPID, or URL."""
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("Empty input line")

    if cleaned.lower().startswith("http://") or cleaned.lower().startswith("https://"):
        kind = "url"
        value = cleaned
    elif cleaned.isdigit():
        kind = "zpid"
        value = cleaned
    else:
        kind = "address"
        value = cleaned

    logger.debug("Classified input '%s' as %s", cleaned, kind)
    return InputRecord(raw=raw, kind=kind, value=value)

class ZillowClient:
    """
    Lightweight Zillow scraper client.

    This client does not rely on any private APIs. It attempts to extract
    property metadata from HTML/embedded JSON. Zillow may change its
    structure at any time, so this code includes defensive parsing and
    logging for troubleshooting.
    """

    def __init__(
        self,
        base_url: str = "https://www.zillow.com",
        timeout: int = 15,
        user_agent: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        headers = {
            "User-Agent": user_agent
            or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        self._client = httpx.Client(
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )

    def _build_url_for_record(self, record: InputRecord) -> str:
        if record.kind == "url":
            return record.value

        if record.kind == "zpid":
            # Common Zillow ZPID URL pattern.
            url = f"{self.base_url}/homedetails/{record.value}_zpid/"
            logger.debug("Built URL for ZPID %s: %s", record.value, url)
            return url

        # Address search fallback.
        query = httpx.QueryParams({"q": record.value})
        url = f"{self.base_url}/homes/{record.value.replace(' ', '-')}_rb/"
        logger.debug("Built URL for address '%s': %s (query=%s)", record.value, url, query)
        return url

    def fetch_property(self, record: InputRecord) -> PropertyData:
        """
        Fetch and parse property data for a single record.

        Raises an exception if the request fails or parsing is unsuccessful.
        """
        url = self._build_url_for_record(record)
        logger.info("Fetching Zillow page: %s", url)
        response = self._client.get(url)

        if response.status_code != 200:
            raise RuntimeError(
                f"Zillow responded with status {response.status_code} for URL {url}",
            )

        html = response.text
        soup = BeautifulSoup(html, "html.parser")

        json_blob = self._extract_relevant_json(soup)
        if json_blob:
            logger.debug("Found embedded JSON blob for property.")
            return self._parse_from_json_blob(json_blob, record, url)

        logger.debug("Falling back to HTML-based parsing.")
        return self._parse_from_html(soup, record, url)

    @staticmethod
    def _extract_relevant_json(soup: BeautifulSoup) -> Dict[str, Any] | None:
        """
        Try to locate embedded JSON that contains property details.

        Zillow often embeds data inside script tags. This function scans for
        JSON-like segments that mention keys such as "zestimate" and "zpid".
        """
        for script in soup.find_all("script"):
            text = script.string or ""
            if "zestimate" in text and "zpid" in text:
                # Try to extract the largest JSON-like substring.
                try:
                    # Heuristic: find first { and last } and attempt to parse.
                    start = text.find("{")
                    end = text.rfind("}")
                    if start != -1 and end != -1 and end > start:
                        candidate = text[start : end + 1]
                        data = json.loads(candidate)
                        return data
                except Exception:  # noqa: BLE001
                    continue
        return None

    def _parse_from_json_blob(
        self,
        data: Dict[str, Any],
        record: InputRecord,
        url: str,
    ) -> PropertyData:
        """
        Parse property data from an embedded JSON structure.

        Because Zillow's internal structure is not guaranteed, this function
        walks the JSON recursively to find the first object that looks like a
        property payload.
        """

        def walk(obj: Any) -> Dict[str, Any] | None:
            if isinstance(obj, dict):
                keys = obj.keys()
                required_keys = {"zpid", "zestimate"}
                if required_keys.issubset(keys):
                    return obj
                for value in obj.values():
                    found = walk(value)
                    if found is not None:
                        return found
            elif isinstance(obj, list):
                for item in obj:
                    found = walk(item)
                    if found is not None:
                        return found
            return None

        payload = walk(data) or {}
        logger.debug("Parsed payload keys from JSON: %s", list(payload.keys()))

        address = (
            payload.get("address")  # sometimes it's a plain string
            or payload.get("streetAddress")
            or payload.get("formattedAddress")
            or record.value
        )

        zpid = str(payload.get("zpid") or "")
        zestimate_raw = payload.get("zestimate") or payload.get("price")

        try:
            zestimate = int(zestimate_raw) if zestimate_raw is not None else None
        except (TypeError, ValueError):
            zestimate = None

        bedrooms = payload.get("bedrooms")
        bathrooms = payload.get("bathrooms")
        living_area = payload.get("livingArea") or payload.get("livingAreaValue")
        lot_size = payload.get("lotSize") or payload.get("lotSizeValue")
        year_built = payload.get("yearBuilt")
        property_type = payload.get("homeType") or payload.get("propertyType")

        price_history_raw = payload.get("priceHistory") or []
        price_history: List[PriceEvent] = []

        if isinstance(price_history_raw, list):
            for item in price_history_raw:
                if not isinstance(item, dict):
                    continue
                date = str(item.get("date") or item.get("eventDate") or "")
                event = str(item.get("event") or item.get("priceChangeEvent") or "")
                price_val = item.get("price")
                try:
                    price_val_int = int(price_val) if price_val is not None else None
                except (TypeError, ValueError):
                    price_val_int = None
                if date or event or price_val_int is not None:
                    price_history.append(
                        PriceEvent(
                            date=date,
                            event=event,
                            price=price_val_int,
                        ),
                    )

        return PropertyData(
            address=address,
            zpid=zpid,
            url=url,
            zestimate=zestimate,
            bedrooms=_to_float_safe(bedrooms),
            bathrooms=_to_float_safe(bathrooms),
            livingArea=_to_int_safe(living_area),
            lotSize=_to_int_safe(lot_size),
            yearBuilt=_to_int_safe(year_built),
            propertyType=property_type,
            priceHistory=price_history,
        )

    def _parse_from_html(
        self,
        soup: BeautifulSoup,
        record: InputRecord,
        url: str,
    ) -> PropertyData:
        """
        Extremely defensive HTML parsing fallback.

        Attempts to approximate fields using generic selectors and patterns.
        """
        text = soup.get_text(" ", strip=True)

        address = self._extract_address_from_html(soup, text) or record.value

        zpid_match = re.search(r"zpid[\"']?\s*[:=]\s*[\"']?(\d+)", text, re.IGNORECASE)
        zpid = zpid_match.group(1) if zpid_match else ""

        zestimate = self._extract_first_int_after_label(text, "Zestimate")

        bedrooms = self._extract_numeric_feature(text, "bd")
        bathrooms = self._extract_numeric_feature(text, "ba")
        living_area = self._extract_numeric_feature(text, "sqft")
        lot_size = None
        year_built = self._extract_year(text)
        property_type = self._extract_property_type(text)

        return PropertyData(
            address=address,
            zpid=zpid,
            url=url,
            zestimate=zestimate,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            livingArea=living_area,
            lotSize=lot_size,
            yearBuilt=year_built,
            propertyType=property_type,
            priceHistory=[],
        )

    @staticmethod
    def _extract_address_from_html(
        soup: BeautifulSoup,
        text: str,
    ) -> Optional[str]:
        # Common meta tag pattern
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"]

        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            return h1.get_text(strip=True)

        # Fallback: look for something that looks like "City, ST ZIP"
        match = re.search(
            r"\d{5}(?:-\d{4})?\s*(?:USA|United States)?",
            text,
        )
        if match:
            start_index = max(0, match.start() - 80)
            snippet = text[start_index : match.end()]
            return snippet.strip()

        return None

    @staticmethod
    def _extract_first_int_after_label(
        text: str,
        label: str,
    ) -> Optional[int]:
        pattern = rf"{re.escape(label)}[^0-9]*([\$]?\s*([\d,]+))"
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return None
        number_str = match.group(2).replace(",", "")
        try:
            return int(number_str)
        except ValueError:
            return None

    @staticmethod
    def _extract_numeric_feature(
        text: str,
        suffix: str,
    ) -> Optional[float | int]:
        pattern = rf"(\d+(\.\d+)?)\s*{re.escape(suffix)}\b"
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return None
        raw = match.group(1)
        if "." in raw:
            try:
                return float(raw)
            except ValueError:
                return None
        try:
            return int(raw)
        except ValueError:
            return None

    @staticmethod
    def _extract_year(text: str) -> Optional[int]:
        match = re.search(r"\b(19[5-9]\d|20[0-4]\d)\b", text)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _extract_property_type(text: str) -> Optional[str]:
        for candidate in [
            "Single Family",
            "Condo",
            "Townhouse",
            "Multi Family",
            "Apartment",
        ]:
            if candidate.lower() in text.lower():
                return candidate
        return None

def _to_int_safe(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def _to_float_safe(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
"""Shared date-parsing helpers for historical / archival dates.

Thin wrapper around ``edtf`` (Library of Congress Extended Date/Time Format,
already a transitive dependency). Used by connectors that ingest free-form
date strings from external sources (Biblissima, Mandragore, …) and need
to coerce them into:

- ISO ``YYYY-MM-DD`` bounds for ``date``-typed Arches tiles, and
- a century concept valueid for the project's period thesaurus.

Input is expected to be in a form edtf can understand — primarily English
natural language (``"13th century"``, ``"circa 1250"``) and standard EDTF
level 1/2 strings (``"1250"``, ``"1200/1250"``, ``"12xx"``, …). **French
century idioms (``"13e siècle"``) are not handled natively**; callers
working with French sources should obtain the English equivalent first
(e.g. by scraping the ``/en/`` variant of the portal page).

Public API:

- ``CENTURY_MAPPING``: ``{"1".."21": valueid}`` — century number → Arches
  concept valueid.
- ``parse_historical_date(date_str)`` — main parser, returns
  ``(start_iso, end_iso, century_concept_valueid)``.
- ``parse_century(date_str)`` — convenience returning only the century
  concept valueid.
"""
import re

from edtf import parse_edtf, text_to_edtf


CENTURY_MAPPING = {
    "1": "82f4c4ef-1ca8-3721-8ee0-fc9bfdd4d2e7",
    "2": "8130e10c-175c-36bd-b16f-a3f19e3bab2c",
    "3": "aa2f7cf8-216a-3b3d-8b93-d85f24d12bc5",
    "4": "a8e9c250-2c00-3eba-a26d-652621ba4e1f",
    "5": "f208e4bb-e67a-3ca4-87ac-18d6974d85e2",
    "6": "cb813afa-b776-3597-a474-e06788bc0a83",
    "7": "6aceda91-36e6-3471-9a17-155cbdb7e84d",
    "8": "9618da23-9cd1-3f39-918b-b4f72b1ea10c",
    "9": "e7b0401b-69f6-3790-b3aa-b19b96513987",
    "10": "a9856744-3b8a-397e-a6da-82f35ced1423",
    "11": "e869b370-57bf-37a6-9f28-16f2f51292ec",
    "12": "97d12923-2a27-326f-92ed-0ddb0d83bafc",
    "13": "58b33dfa-7337-368b-8272-ed5b7953493a",
    "14": "831aeae8-3c26-3c3c-a2e6-d605a5f2b09d",
    "15": "04db53cd-8a0a-3e1a-90e3-2d2ac158c29d",
    "16": "5252cc19-b82f-33bb-93c2-05d5cac9652c",
    "17": "47e91572-82f6-35a3-882c-d20a2631b9db",
    "18": "f28e962b-5441-32a9-aef3-670fb896e4f3",
    "19": "3ff0aafb-1afb-362c-b228-7a5d704ae924",
    "20": "95e228f8-2434-3e84-9092-289b3c2fac87",
    "21": "1b45307f-a121-3aef-8fe2-9d7a3535be89",
}

# Hyphen / en-dash / em-dash year range → EDTF interval.
# Example: "1200-1250" → "1200/1250".
_YEAR_RANGE_RE = re.compile(r"^(\d{3,4})\s*[-–—]\s*(\d{3,4})$")

# Plausibility window for parsed years. edtf happily returns junk
# (year 0000, year 9999) for malformed inputs — for instance it
# interprets ``"13e siècle"`` as day-of-month 13 with unknown year,
# yielding 0000-01-13 → 9999-12-13. Any year outside this range is
# treated as garbage and the parser returns None instead.
_MIN_PLAUSIBLE_YEAR = 100
_MAX_PLAUSIBLE_YEAR = 2100


def parse_historical_date(date_str):
    """Parse a historical date string and return ISO bounds + century concept.

    Tries three strategies in order:

    1. Direct ``parse_edtf`` — for strings that already look like EDTF
       (``"1250"``, ``"1200/1250"``, ``"12xx"``, ``"1250?"``, …).
    2. ``text_to_edtf`` fallback — for English natural language
       (``"13th century"``, ``"circa 1250"``).
    3. Pre-normalised year range (``"1200-1250"`` → ``"1200/1250"``).

    Returns ``(start_iso, end_iso, century_concept_valueid)``. Each element
    can be None if the input is unparseable.

    Century derivation uses the **upper bound** year with the strict rule
    ``(year - 1) // 100 + 1``, which yields the expected century whether
    edtf returns an inclusive range (``12xx`` = 1200-1299) or a strict
    EDTF interval (``1201/1300``).
    """
    if not date_str:
        return None, None, None
    s = str(date_str).strip()
    if not s:
        return None, None, None

    m = _YEAR_RANGE_RE.match(s)
    if m:
        s = f"{m.group(1)}/{m.group(2)}"

    obj = None
    try:
        obj = parse_edtf(s)
    except Exception:
        try:
            fallback = text_to_edtf(s)
            if fallback:
                obj = parse_edtf(fallback)
        except Exception:
            obj = None

    if obj is None:
        return None, None, None

    try:
        low = obj.lower_strict()
        high = obj.upper_strict()
    except Exception:
        return None, None, None

    # Plausibility check: reject obviously broken bounds (edtf returns
    # 0000 / 9999 when it can't make sense of the input).
    if not (_MIN_PLAUSIBLE_YEAR <= low.tm_year <= _MAX_PLAUSIBLE_YEAR):
        return None, None, None
    if not (_MIN_PLAUSIBLE_YEAR <= high.tm_year <= _MAX_PLAUSIBLE_YEAR):
        return None, None, None

    start_iso = f"{low.tm_year:04d}-{low.tm_mon:02d}-{low.tm_mday:02d}"
    end_iso = f"{high.tm_year:04d}-{high.tm_mon:02d}-{high.tm_mday:02d}"
    century = (high.tm_year - 1) // 100 + 1
    return start_iso, end_iso, CENTURY_MAPPING.get(str(century))


def parse_century(date_str):
    """Return just the century concept valueid for ``date_str``.

    Convenience wrapper over ``parse_historical_date``.
    """
    _, _, century = parse_historical_date(date_str)
    return century

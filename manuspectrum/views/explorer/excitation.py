"""X-ray tube excitation (anode and tube voltage) read from measurement conditions.

``excitation_of(texts)`` scans free-text statements, in any language, and
returns ``{"anode", "kV", "source": "conditions"}`` or ``None`` when neither
value is found. Each text is stripped of markup, entity-unescaped and cut to
``SCAN_LIMIT`` characters; every pattern is linear in its input.

- The anode is an element symbol or an English/French name found within
  three words after ``tube``, ``anode``, ``target`` or ``cible``, or directly
  before ``tube``/``anode`` (``Rh tube``, ``Rh-anode``). Gold (``gold``, ``Au``, ``d'or``) is accepted
  only right after the keyword, since ``or`` is also a French conjunction.
- The voltage is a number followed by ``kV`` or ``kVp``, never ``keV``, kept
  when within 1 to 100.
- Two different anodes give ``anode: None`` and two different voltages give
  ``kV: None``, each field judged on its own across all the texts.
"""

import html
import re

import nh3

SCAN_LIMIT = 4000
RAW_LIMIT = 20000
KV_MIN, KV_MAX = 1, 100
LOOKAHEAD_WORDS = 3

KEYWORDS = frozenset({"tube", "anode", "target", "cible"})
GOLD_LINKS = frozenset({"de", "d", "of", "en"})

_NAMES = {
    "rhodium": "Rh",
    "silver": "Ag",
    "argent": "Ag",
    "tungsten": "W",
    "tungstene": "W",
    "tungstène": "W",
    "molybdenum": "Mo",
    "molybdene": "Mo",
    "molybdène": "Mo",
    "chromium": "Cr",
    "chrome": "Cr",
    "copper": "Cu",
    "cuivre": "Cu",
    "palladium": "Pd",
    "titanium": "Ti",
    "titane": "Ti",
    "rhenium": "Re",
    "rhénium": "Re",
}
_SYMBOLS = frozenset({"Rh", "Ag", "W", "Mo", "Cr", "Cu", "Pd", "Ti", "Re", "Au"})

_WORD = re.compile(r"[^\W_]+")
_KV = re.compile(r"(?<![\d.,])(\d{1,4}(?:[.,]\d{1,3})?)\s{0,3}kVp?(?![a-z])", re.I)


def _plain(text):
    cleaned = nh3.clean(str(text)[:RAW_LIMIT], tags=set(), attributes={})
    return html.unescape(cleaned)[:SCAN_LIMIT]


def _element(word):
    """Symbol of *word* when it names an anode element (gold excluded), else ``None``."""
    if word in _SYMBOLS and word != "Au":
        return word
    return _NAMES.get(word.casefold())


def _gold_follows(after):
    """True when gold is the word right after the keyword, or follows ``de``/``d``/``of``/``en``."""
    if not after:
        return False
    first = after[0].casefold()
    if first in {"gold", "au"}:
        return True
    return (
        first in GOLD_LINKS and len(after) > 1 and after[1].casefold() in {"or", "gold"}
    )


def _anodes_of(text):
    words = _WORD.findall(text)
    found = set()
    for index, word in enumerate(words):
        if word.casefold() not in KEYWORDS:
            continue
        if index:
            before = _element(words[index - 1])
            if before:
                found.add(before)
        after = words[index + 1 : index + 1 + LOOKAHEAD_WORDS]
        for candidate in after:
            symbol = _element(candidate)
            if symbol:
                found.add(symbol)
        if _gold_follows(after):
            found.add("Au")
    return found


def _kvs_of(text):
    values = set()
    for match in _KV.finditer(text):
        value = float(match.group(1).replace(",", "."))
        if KV_MIN <= value <= KV_MAX:
            values.add(value)
    return values


def excitation_of(texts):
    """``{"anode", "kV", "source": "conditions"}`` read from *texts*, or ``None``."""
    anodes, voltages = set(), set()
    for raw in texts or ():
        if not raw:
            continue
        text = _plain(raw)
        anodes |= _anodes_of(text)
        voltages |= _kvs_of(text)
    anode = next(iter(anodes)) if len(anodes) == 1 else None
    voltage = next(iter(voltages)) if len(voltages) == 1 else None
    if not anodes and not voltages:
        return None
    if voltage is not None and voltage == int(voltage):
        voltage = int(voltage)
    return {"anode": anode, "kV": voltage, "source": "conditions"}

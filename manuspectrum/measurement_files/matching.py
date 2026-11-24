"""Reading a measurement file name and proposing the one Analysis it belongs to.

A name is cut on ``_ - . space``, then between letters and digits inside a
piece (``FORS046`` is ``FORS`` ``046``). The technique family of a file comes
from its content; a code in the name only checks it and picks among the
analyses. An Analysis is proposed only when family, folio and number agree
with exactly one editable card and nothing contradicts; every other outcome
carries a cause of ``constants.measurement_files.CAUSES``.

Folio forms: ``f`` + number + ``r|v`` (or ``fol``/``folio`` + number). An
unsuffixed ``f<number>`` is a folio only when another code follows it in the
name and no folder carries one; otherwise it is the code ``F`` and a number.
A lone letters+digits group before the folio (or at the start) that is neither
the shelfmark of the Document nor a known code is another shelfmark.
"""

import os
import re
from dataclasses import dataclass, field

from manuspectrum.constants.measurement_files import ALERT_WORDS, COMMON_CODES

IGNORE = "ignore"
FOLIO_WORDS = ("f", "fol", "folio")
INFORMATIVE_WORDS = ("spectrum", "spectra", "spectre")
COLOURS = (
    "rouge",
    "bleu",
    "vert",
    "jaune",
    "orange",
    "violet",
    "rose",
    "brun",
    "marron",
    "noir",
    "gris",
    "red",
    "blue",
    "green",
    "yellow",
    "black",
    "white",
    "grey",
    "gray",
    "brown",
    "purple",
    "pink",
)
_FAMILY_ALIASES = {"ftir_reflection": "ftir", "xrf_channel": "xrf"}
_SEPARATORS = re.compile(r"[\s_.\-]+")
_RUNS = re.compile(r"[^\W\d_]+|\d+")
_SEQUENCE = re.compile(r"\s*\d{4}-\d{4}(?=[-_.\s]|$)")


def family_of(preset):
    """Matching family of an ``XY_PRESETS`` key (``ftir_reflection`` is ``ftir``)."""
    return _FAMILY_ALIASES.get(preset, preset) if preset else None


@dataclass(frozen=True)
class Token:
    piece: str
    meaning: str
    source: str


@dataclass(frozen=True)
class NameReading:
    tokens: tuple[Token, ...]
    folio: str | None
    family: str | None
    number: str | None
    other_shelfmark: bool
    alerts: tuple[str, ...]
    unknown_codes: tuple[str, ...]
    families: tuple[str, ...] = ()
    pairs: tuple[tuple[str | None, str], ...] = ()
    near: bool = False


@dataclass(frozen=True)
class AnalysisKeys:
    folio: str | None
    family: str | None
    numbers: frozenset
    folios: frozenset = frozenset()


@dataclass(frozen=True)
class Proposal:
    analysis_id: str | None
    cause: str | None
    candidates: tuple[str, ...] = ()


@dataclass
class _Run:
    text: str
    digit: bool
    piece: int
    last: bool


@dataclass
class _Scan:
    tokens: list = field(default_factory=list)
    folio: str | None = None
    folio_strong: bool = False
    families: list = field(default_factory=list)
    pairs: list = field(default_factory=list)
    near: bool = False
    other_shelfmark: bool = False
    alerts: list = field(default_factory=list)
    unknown_codes: list = field(default_factory=list)


def _norm_number(text):
    return str(int(text))


def _runs(text):
    runs = []
    for index, piece in enumerate(p for p in _SEPARATORS.split(text) if p):
        for found in _RUNS.finditer(piece):
            runs.append(
                _Run(
                    found.group(),
                    found.group().isdigit(),
                    index,
                    found.end() == len(piece),
                )
            )
    return runs


def _strip_extension(name):
    stem, dot, extension = name.rpartition(".")
    if (
        dot
        and stem
        and len(extension) <= 5
        and (extension.isdigit() or extension.isalpha())
    ):
        return stem
    return name


def _code_table(codes):
    table = {key.casefold(): value for key, value in COMMON_CODES.items()}
    table.update({key.casefold(): value for key, value in codes.items()})
    return table


def _scan(text, shelfmark, tables, source, folder_has_folio=False, check_other=True):
    """Classify the pieces of one name or folder part. ``source`` is ``name`` or ``folder``."""
    table, user_keys = tables
    scan = _Scan()
    sequence = _SEQUENCE.match(text) if source == "name" else None
    if sequence:
        scan.tokens.append(Token(sequence.group().strip(), "sequence", source))
        text = text[sequence.end() :]
    runs = _runs(text)
    count = len(runs)
    meaning = [None] * count
    tokens_at = {}

    def mark(first, last, kind, origin=source):
        piece = "".join(r.text for r in runs[first : last + 1])
        for k in range(first, last + 1):
            meaning[k] = kind
        tokens_at[first] = Token(piece, kind, origin)

    wanted = re.sub(r"[\W_]+", "", shelfmark).casefold()
    shelfmark_found = False
    if wanted:
        for i in range(count):
            if meaning[i]:
                continue
            seen = ""
            for j in range(i, count):
                seen += runs[j].text.casefold()
                if seen == wanted:
                    mark(i, j, "shelfmark")
                    shelfmark_found = True
                    break
                if not wanted.startswith(seen):
                    break

    candidates = []
    for i in range(count - 1):
        if meaning[i] or runs[i].digit or runs[i].text.casefold() not in FOLIO_WORDS:
            continue
        nxt = runs[i + 1]
        if not nxt.digit or meaning[i + 1]:
            continue
        side = ""
        end = i + 1
        if (
            i + 2 < count
            and not runs[i + 2].digit
            and runs[i + 2].text.casefold() in ("r", "v")
            and runs[i + 2].piece == nxt.piece
        ):
            side = runs[i + 2].text.casefold()
            end = i + 2
        strong = bool(side) or runs[i].text.casefold() != "f"
        candidates.append((i, end, f"f{_norm_number(nxt.text)}{side}", strong))

    chosen = None
    strong = [c for c in candidates if c[3]]
    weak = [c for c in candidates if not c[3]]
    if strong:
        chosen = strong[0]
    elif weak and (folder_has_folio is False or source == "folder"):
        first = weak[0]
        other_code = len(weak) > 1 or any(
            runs[k].digit
            or (runs[k].text.casefold() in table and runs[k].text.casefold() != "f")
            for k in range(first[1] + 1, count)
        )
        if other_code or source == "folder":
            chosen = first
    if chosen:
        mark(chosen[0], chosen[1], "folio")
        scan.folio = chosen[2]
        scan.folio_strong = chosen[3]
    folio_start = chosen[0] if chosen else None

    i = 0
    while i < count:
        if meaning[i]:
            i += 1
            continue
        run = runs[i]
        nxt = (
            runs[i + 1]
            if i + 1 < count and runs[i + 1].digit and not meaning[i + 1]
            else None
        )
        if run.digit:
            after = runs[i + 1] if i + 1 < count else None
            if (
                after is not None
                and not after.digit
                and after.piece == run.piece
                and after.last
                and after.text.casefold() in ("sc", "scans")
            ):
                mark(i, i + 1, "scans")
                i += 2
            elif (
                after is not None
                and not after.digit
                and after.piece == run.piece
                and after.last
                and len(after.text) == 1
            ):
                mark(i, i + 1, "number")
                scan.pairs.append((None, _norm_number(run.text)))
                scan.near = True
                i += 2
            else:
                mark(i, i, "number")
                scan.pairs.append((None, _norm_number(run.text)))
                i += 1
            continue
        low = run.text.casefold()
        if low in COLOURS:
            mark(i, i, "colour")
        elif low in ALERT_WORDS:
            mark(i, i, "alert")
            scan.alerts.append(run.text.casefold())
        elif low in INFORMATIVE_WORDS:
            mark(i, i, "word")
        elif low in table:
            family = table[low]
            origin = "dictionary" if low in user_keys else "common"
            origin = "folder" if source == "folder" else origin
            lead = (
                check_other
                and not shelfmark_found
                and low == "ms"
                and nxt is not None
                and (i < folio_start if folio_start is not None else i == 0)
            )
            if family == IGNORE:
                last = i + 1 if nxt is not None and nxt.piece == run.piece else i
                mark(i, last, "word", "dictionary")
                i = last + 1
                continue
            if lead:
                mark(i, i + 1, "shelfmark")
                scan.other_shelfmark = True
                i += 2
                continue
            fam = family_of(family)
            scan.families.append(fam)
            if nxt is not None:
                mark(i, i + 1, "code", origin)
                scan.pairs.append((fam, _norm_number(nxt.text)))
                i += 2
                continue
            mark(i, i, "code", origin)
        elif source == "folder":
            mark(i, i, "word")
        elif nxt is not None:
            lead = (
                check_other
                and not shelfmark_found
                and (i < folio_start if folio_start is not None else i == 0)
            )
            if lead:
                mark(i, i + 1, "shelfmark")
                scan.other_shelfmark = True
            else:
                mark(i, i + 1, "unknown_code")
                scan.unknown_codes.append(run.text)
            i += 2
            continue
        else:
            mark(i, i, "word")
        i += 1

    scan.tokens.extend(tokens_at[k] for k in sorted(tokens_at))
    return scan


def _build_table(codes):
    return _code_table(codes), frozenset(key.casefold() for key in codes)


def read_name(name, relative_dir, shelfmark, codes):
    """Read a file name (and the folder it came in) into the facts matching uses."""
    tables = _build_table(codes)
    folders = [
        _scan(part, shelfmark, tables, "folder")
        for part in re.split(r"[\\/]+", relative_dir)
        if part
    ]
    folder_folio = next((s.folio for s in folders if s.folio), None)
    scan = _scan(
        _strip_extension(os.path.basename(name.replace("\\", "/"))),
        shelfmark,
        tables,
        "name",
        folder_has_folio=folder_folio is not None,
    )
    tokens = [
        t for s in folders for t in s.tokens if t.meaning != "shelfmark"
    ] + scan.tokens
    folio = scan.folio or folder_folio
    if scan.folio and folder_folio and scan.folio != folder_folio:
        folio = None
    families = tuple(
        dict.fromkeys([*scan.families, *(f for s in folders for f in s.families)])
    )
    numbers = tuple(scan.pairs)
    distinct = {n for _, n in numbers}
    return NameReading(
        tokens=tuple(tokens),
        folio=folio,
        family=families[0] if len(families) == 1 else None,
        number=next(iter(distinct)) if len(distinct) == 1 else None,
        other_shelfmark=scan.other_shelfmark,
        alerts=tuple(scan.alerts),
        unknown_codes=tuple(scan.unknown_codes),
        families=families,
        pairs=numbers,
        near=scan.near,
    )


def analysis_keys(card, codes, shelfmark=""):
    """Folio, family and numbers of an Analysis, read from its name sources by the same rules."""
    tables = _build_table(codes)
    folios = set()
    numbers = set()
    for text in card.folio_sources:
        scan = _scan(text, shelfmark, tables, "name", check_other=False)
        if scan.folio:
            folios.add(scan.folio)
        numbers.update(n for _, n in scan.pairs)
    return AnalysisKeys(
        folio=next(iter(folios)) if len(folios) == 1 else None,
        family=family_of(card.technique_preset),
        numbers=frozenset(numbers),
        folios=frozenset(folios),
    )


def propose(reading, content_family, cards, codes, shelfmark=""):
    """Propose one Analysis for a file, or say why not (``cause`` is a ``CAUSES`` key)."""
    if reading.other_shelfmark:
        return Proposal(None, "other_shelfmark")
    if reading.unknown_codes:
        return Proposal(None, "unknown_codes")
    if reading.alerts:
        return Proposal(None, "name_alert")
    if len(reading.families) > 1:
        return Proposal(None, "format_vs_technique")
    keyed = [(c, analysis_keys(c, codes, shelfmark)) for c in cards if c.editable]

    def fits(family, numbers):
        return tuple(
            sorted(
                c.id
                for c, k in keyed
                if k.family == family
                and reading.folio is not None
                and reading.folio in k.folios
                and k.numbers & numbers
            )
        )

    content = family_of(content_family)
    named = reading.family
    numbers_of = lambda family: frozenset(
        {n for f, n in reading.pairs if f == family}
        or {n for f, n in reading.pairs if f is None}
    )
    if content and named and content != named:
        return Proposal(None, "format_vs_technique", fits(named, numbers_of(named)))
    family = content or named
    if family is None:
        return Proposal(None, "no_analysis")
    numbers = numbers_of(family)
    matches = fits(family, numbers)
    if len(numbers) > 1 and matches:
        return Proposal(None, "near_name", matches)
    if len(matches) == 1:
        if reading.near:
            return Proposal(None, "near_name", matches)
        return Proposal(matches[0], None, matches)
    if matches:
        return Proposal(None, "near_name", matches)
    others = tuple(
        sorted(
            c.id
            for c, k in keyed
            if k.family != family
            and reading.folio is not None
            and reading.folio in k.folios
            and k.numbers & numbers
        )
    )
    if others and content and not named:
        return Proposal(None, "format_vs_technique", others)
    return Proposal(None, "no_analysis")

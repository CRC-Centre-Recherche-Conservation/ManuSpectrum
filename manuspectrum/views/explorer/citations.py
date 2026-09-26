"""Citations of the Analysis Explorer: one dataset entry in CSL-JSON, BibTeX, RIS and plain text.

The data package carries every form; the Explorer's payloads carry the text
and BibTeX of an entry (``shown_citation``).

The cited object is the dataset (CSL ``dataset``, RIS ``DATA``, biblatex
``@dataset``). A complete Dataverse citation stored as the dataset's label is
the recommended text as written, and its authors, year, title, DOI, publisher
and version fill the structured forms. Any other dataset, and an analysis
without dataset, is cited as its ManuSpectrum record, built from the metadata
of the analyses: title, visible operators as authors, projects, measurement
dates, permalink, licences; publisher ``settings.APP_TITLE``; no ``issued``.
Several analyses without dataset under one ``Home`` (their project, else
their document) are cited once, as that record with the analyses as parts.

No field is ever written empty: a missing value leaves its key or tag out.
The module reads no database; the caller passes what the reader may see and
the day of consultation.
"""

import hashlib
import re
from dataclasses import dataclass, field

import bibtexparser
import rispy
from bibtexparser import model as bib
from django.conf import settings
from django.utils import translation
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from pylatexenc.latexencode import unicode_to_latex

DOI = re.compile(r"(10\.\d{4,9}/\S+)", re.IGNORECASE)
DATAVERSE = re.compile(
    r"^(?P<authors>.+?),\s*(?P<year>\d{4}),\s*[\"“](?P<title>[^\"”]+)[\"”],\s*"
    r"(?P<url>https?://(?:dx\.)?doi\.org/(?P<doi>10\.\d{4,9}/[^\s,]+)),\s*"
    r"(?P<publisher>[^,]+?)"
    r"(?:,\s*(?P<version>V\d+(?:\.\d+)?))?"
    r"(?:,\s*UNF:\S+?(?:\s*\[fileUNF\])?)?"
    r"\s*[.,]?$"
)
DATE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")
VERBATIM_BIBTEX_FIELDS = {"author", "url", "doi", "urldate", "eventdate", "year"}


@dataclass(frozen=True)
class CitedAnalysis:
    """What a citation reads of one analysis; *authors* and *projects* are what the reader may name."""

    id: str
    name: str
    permalink: str
    start: str | None
    end: str | None
    authors: tuple = ()
    projects: tuple = field(default=())


@dataclass(frozen=True)
class Home:
    """The ManuSpectrum record several analyses without dataset are cited as: a project, else their document."""

    id: str
    name: str
    permalink: str


@dataclass(frozen=True)
class Dataverse:
    authors: tuple
    year: int
    title: str
    doi: str
    url: str
    publisher: str
    version: str | None


def _clean(text):
    return " ".join(str(text or "").split())


def person_name(text):
    """``{"family", "given"}`` of ``Family, Given``; ``{"literal"}`` of a name without comma."""
    family, comma, given = text.partition(",")
    family, given = family.strip(), given.strip()
    if comma and family and given:
        return {"family": family, "given": given}
    return {"literal": text.strip()}


def parse_dataverse(text):
    """The parts of a complete Dataverse citation; None when one of authors, year, quoted title, DOI or publisher is missing."""
    match = DATAVERSE.match(_clean(text))
    if not match:
        return None
    authors = tuple(
        person_name(name) for name in match["authors"].split(";") if name.strip()
    )
    if not authors:
        return None
    return Dataverse(
        authors=authors,
        year=int(match["year"]),
        title=match["title"].strip(),
        doi=match["doi"].lower(),
        url=match["url"],
        publisher=match["publisher"].strip(),
        version=match["version"],
    )


def _doi(url):
    match = DOI.search(url or "")
    return match[1].rstrip(".,;:").lower() if match else None


def dataset_id(dataset):
    """Identity of a dataset: its DOI in lowercase (``10.…``), else its URL; None without dataset."""
    if not dataset:
        return None
    return _doi(dataset["url"]) or dataset["url"]


def _dataset_url(dataset):
    url = dataset["url"]
    if url.startswith(("http://", "https://")):
        return url
    doi = _doi(url)
    return f"https://doi.org/{doi}" if doi else url


def _parts(value):
    match = DATE.match(value or "")
    return [int(p) for p in match.groups() if p] if match else None


def _event_range(analyses):
    starts = [p for p in (_parts(a.start) for a in analyses) if p]
    ends = [p for p in (_parts(a.end or a.start) for a in analyses) if p]
    if not starts:
        return None
    first, last = min(starts), max(ends)
    return [first] if first == last else [first, last]


def _iso(parts):
    return "-".join(f"{p:04d}" if i == 0 else f"{p:02d}" for i, p in enumerate(parts))


def _unique(values):
    seen = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def _name_text(author):
    if "literal" in author:
        return author["literal"]
    return f"{author['family']}, {author['given']}"


def _latex(text):
    """``unicode_to_latex`` of *text*, one ``; ``-separated piece at a time.

    pylatexenc's encoder takes a time quadratic in the length of its input;
    its rules replace one character at a time, so the pieces give the same
    result.
    """
    return "; ".join(unicode_to_latex(piece) for piece in text.split("; "))


def _bibtex_name(author):
    if "literal" in author:
        return "{" + _latex(author["literal"]) + "}"
    return f"{_latex(author['family'])}, {_latex(author['given'])}"


class _RisWriter(rispy.RisWriter):
    def set_header(self, count):
        return None


def _bibtex(key, fields):
    entry = bib.Entry(
        "dataset",
        key,
        [
            bib.Field(
                name,
                value if name in VERBATIM_BIBTEX_FIELDS else _latex(value),
            )
            for name, value in fields
            if value
        ],
    )
    library = bibtexparser.Library()
    library.add(entry)
    return bibtexparser.write_string(library).strip() + "\n"


def citation_entry(dataset, analyses, *, licences, language, accessed, home=None):
    """``Citation`` of *dataset* (a ``dataset_of`` value, or None) for *analyses* (``CitedAnalysis``).

    *licences* are the labels of the analyses' file licences; *accessed* is the
    day of consultation (``datetime.date``). Strings are in *language*.
    Without dataset, several analyses are cited as their *home* (``Home``):
    its id, name and permalink; one analysis is cited as itself. The text and
    BibTeX of a home citation give the number of analyses and the home's
    permalink; its CSL-JSON and RIS notes list every analysis.
    """
    with translation.override(language):
        return _entry(dataset, list(analyses), _unique(licences), accessed, home)


def _entry(dataset, analyses, licences, accessed, home=None):
    parsed = parse_dataverse(dataset["label"]) if dataset else None
    home = home if not dataset and home and len(analyses) > 1 else None
    entry_id = dataset_id(dataset) or (home.id if home else analyses[0].id)
    events = _event_range(analyses)
    parts = "; ".join(f"{_clean(a.name)} ({a.permalink})" for a in analyses)
    note = _("Analyses: %(parts)s") % {"parts": parts}
    count = (
        ngettext("%(count)d analysis", "%(count)d analyses", len(analyses))
        % {"count": len(analyses)}
        if home
        else None
    )
    shown_note = f"{count}: {home.permalink}" if home else note
    extra_notes = []
    if parsed:
        authors = list(parsed.authors)
        title, publisher, version = parsed.title, parsed.publisher, parsed.version
        doi, url, year = parsed.doi, parsed.url, parsed.year
        projects, licence = [], None
    else:
        authors = _unique(
            {k: _clean(v) for k, v in author.items()}
            for a in analyses
            for author in a.authors
        )
        title = _clean(dataset and dataset["label"]) or (
            _clean(home.name)
            if home
            else (
                _clean(analyses[0].name)
                if len(analyses) == 1
                else _dataset_url(dataset) if dataset else _clean(analyses[0].name)
            )
        )
        publisher, version, year = settings.APP_TITLE, None, None
        doi = _doi(dataset["url"]) if dataset else None
        url = (
            _dataset_url(dataset)
            if dataset
            else home.permalink if home else analyses[0].permalink
        )
        projects = _unique(
            _clean(p) for a in analyses for p in a.projects if _clean(p) != title
        )
        licence = "; ".join(licences) or None
        if projects:
            extra_notes.append(
                ngettext("Project: %(names)s", "Projects: %(names)s", len(projects))
                % {"names": "; ".join(projects)}
            )
        if licence:
            extra_notes.append(
                ngettext("Licence: %(names)s", "Licences: %(names)s", len(licences))
                % {"names": licence}
            )

    csl = {"type": "dataset", "id": entry_id, "title": title}
    if authors:
        csl["author"] = authors
    if projects:
        csl["collection-title"] = "; ".join(projects)
    csl["publisher"] = publisher
    if version:
        csl["version"] = version
    if doi:
        csl["DOI"] = doi
    csl["URL"] = url
    if licence:
        csl["license"] = licence
    if year:
        csl["issued"] = {"date-parts": [[year]]}
    if events:
        csl["event-date"] = {"date-parts": events}
    csl["accessed"] = {"date-parts": [[accessed.year, accessed.month, accessed.day]]}
    csl["note"] = note

    first = authors[0] if authors else None
    stem = (first.get("family") or first.get("literal")) if first else ""
    key = (
        slugify(stem or settings.APP_TITLE).replace("-", "")
        + (str(year) if year else "nd")
        + hashlib.sha1(entry_id.encode()).hexdigest()[:6]
    )
    bibtex = _bibtex(
        key,
        [
            ("author", " and ".join(_bibtex_name(a) for a in authors)),
            ("title", title),
            ("publisher", publisher),
            ("version", version),
            ("doi", doi),
            ("url", url),
            ("year", str(year) if year else None),
            ("eventdate", "/".join(_iso(p) for p in events) if events else None),
            ("urldate", accessed.isoformat()),
            ("note", ". ".join([*extra_notes, shown_note])),
        ],
    )

    ris_record = {"type_of_reference": "DATA"}
    if authors:
        ris_record["authors"] = [_name_text(a) for a in authors]
    ris_record["title"] = title
    ris_record["publisher"] = publisher
    if version:
        ris_record["edition"] = version
    if doi:
        ris_record["doi"] = doi
    ris_record["urls"] = [url]
    if year:
        ris_record["year"] = str(year)
    if events:
        ris_record["date"] = "/".join(f"{p:02d}" for p in events[0])
    ris_record["access_date"] = accessed.strftime("%Y/%m/%d")
    ris_record["notes"] = [note, *extra_notes]
    ris = rispy.dumps([ris_record], implementation=_RisWriter)

    if parsed:
        recommended = _clean(dataset["label"])
    else:
        pieces = []
        if authors:
            pieces.append("; ".join(_name_text(a) for a in authors))
        kind = _("[Dataset]")
        heading = f"{title} {kind}"
        if events:
            heading += ", " + "–".join(_iso(p) for p in events)
        pieces += [heading, *([count] if count else []), *projects, publisher, url]
        if licence:
            pieces.append(licence)
        recommended = (
            ". ".join(p.rstrip(".") for p in pieces)
            + ". "
            + _("Accessed %(date)s.") % {"date": accessed.isoformat()}
        )

    return {
        "recommended": recommended,
        "csl": csl,
        "bibtex": bibtex,
        "ris": ris,
        "availability": _availability(
            [dataset], licences, ", ".join(a.permalink for a in analyses)
        ),
    }


def shown_citation(entry):
    """The ``Citation`` of the Explorer's payloads for *entry*: its recommended ``text`` and its ``bibtex``."""
    return {"text": entry["recommended"], "bibtex": entry["bibtex"]}


def citation_entries(groups, *, language, accessed):
    """One ``Citation`` per dataset, then one per ``Home`` of the analyses without dataset.

    *groups* are ``(dataset | None, [CitedAnalysis], licence labels, Home | None)``;
    groups naming one dataset (by ``dataset_id``) are cited together, groups
    without dataset under one home (by ``Home.id``) too. An analysis without
    dataset nor home is cited alone.
    """
    datasets, records = {}, {}
    for dataset, analyses, licences, home in groups:
        key = ("dataset", dataset_id(dataset))
        if key[1] is None:
            key = ("home", home.id) if home else ("analysis", analyses[0].id)
        target = datasets if key[0] == "dataset" else records
        if key not in target:
            target[key] = (dataset, [], [], home)
        target[key][1].extend(analyses)
        target[key][2].extend(licences)
    return [
        citation_entry(
            dataset,
            analyses,
            licences=licences,
            language=language,
            accessed=accessed,
            home=home,
        )
        for dataset, analyses, licences, home in [
            *datasets.values(),
            *records.values(),
        ]
    ]


def availability(datasets, *, licences, permalink, language):
    """Data availability statement naming ManuSpectrum at *permalink*, each dataset (deduplicated) and the licence."""
    with translation.override(language):
        return _availability(datasets, _unique(licences), permalink)


def _availability(datasets, licences, permalink):
    named, seen = [], set()
    for dataset in datasets:
        key = dataset_id(dataset)
        if key is None or key in seen:
            continue
        seen.add(key)
        parsed = parse_dataverse(dataset["label"])
        doi = _doi(dataset["url"])
        locator = f"https://doi.org/{doi}" if doi else dataset["url"]
        title = parsed.title if parsed else _clean(dataset["label"])
        named.append(f"{title} ({locator})" if title else locator)
    values = {
        "site": settings.APP_TITLE,
        "permalink": permalink,
        "datasets": ", ".join(named),
        "licence": licences[0] if licences else "",
    }
    if named:
        if len(licences) > 1:
            text = _(
                "The data are available in %(site)s (%(permalink)s) and in %(datasets)s, "
                "under the licences given for each file."
            )
        elif licences:
            text = _(
                "The data are available in %(site)s (%(permalink)s) and in %(datasets)s, "
                "under %(licence)s."
            )
        else:
            text = _(
                "The data are available in %(site)s (%(permalink)s) and in %(datasets)s."
            )
    elif len(licences) > 1:
        text = _(
            "The data are available in %(site)s (%(permalink)s), "
            "under the licences given for each file."
        )
    elif licences:
        text = _(
            "The data are available in %(site)s (%(permalink)s), under %(licence)s."
        )
    else:
        text = _("The data are available in %(site)s (%(permalink)s).")
    return text % values

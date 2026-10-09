"""
EXPORT PKG

Writes the public Arches package (the `manuspectrum-pkg` repository) from the
database into a directory. Only `--out` is written; the database is read inside a
read-only transaction that is rolled back.

    manage.py export_pkg --out <dir> --public-origin https://example.org/

Output:
    graphs/resource_models/*.json, graphs/branches/*.json
        Arches' own `packages export_graphs` (one run per graph type).
    reference_data/controlled_lists/<slug>.xml
        One list per file. The SKOS triples come from arches-controlled-lists'
        `SKOSWriter`; the RDF/XML is written here from sorted triples because the
        stock serialisation differs from one process to the next. The slug is
        `[a-z0-9_]` (the stock one keeps `:`).
    post_sql/controlled_lists_searchable.sql
        The SKOS format drops `List.searchable`; this restores it by list id.
    system_settings/System_Settings.json
        The core `Arches_System_Settings.json` with `app_name`,
        `search_items_per_page` and an empty Mapbox key in every language. The
        System Settings tile of the database is never read.
    package_config.json
        Arches' `export_package_configs` (resource-to-resource constraints),
        sorted, with an empty `business_data_load_order`.
    map_layers/mapbox_spec_json/{basemaps,overlays}/.gitkeep
        Written only once every `map_layers` / `map_sources` row is checked to be
        an Arches core row; project layer settings travel in the node configs of
        the graphs.
    expected-inventory.json
        What a fresh database loaded from the package must contain, and the
        `public_origin` the lists were rewritten to. Per list,
        `digest_sortorder` covers the stored (item, parent, sortorder) rows and
        `digest_sibling_rank` the same rows with the sort order replaced by the
        rank among siblings, which is what the SKOS loader leaves behind;
        `digest_items` the order-free (item, parent) rows and `digest_values` the
        (item, value type, language, value) rows. `graphs.published` lists
        `graph|language` for the current publication of each graph, which is
        what a fresh load reproduces (the publication history is not counted).
        `manage.py check_pkg_inventory` compares a loaded database with it.

The origin `http://localhost:8000/` is replaced by `--public-origin` in every
written file, then the files written are scanned (a foreign file already in
`--out`, such as `.github/`, is never read) and `--out` is checked for business
data: any `localhost`, loopback or private address, local host name, Mapbox
token, Mapbox key value, e-mail address, port on the public origin or non-empty
`business_data` folder removes the written files and fails the command.

The SKOS loader reads `arches:sortorder` through its own
`ARCHES_NAMESPACE_FOR_DATA_EXPORT` (`PUBLIC_SERVER_ADDRESS`): it must equal
`--public-origin`, or every sort order is lost without an error.

Refuses what the SKOS format or its loader cannot carry: a dynamic list, a guide
item, a value without a language, with a
language that does not survive RDF, or of an image or foreign value type, an
origin containing the name of a note or label value type, and two graphs that
would write the same file.
"""

import hashlib
import ipaddress
import json
import os
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

import arches
from arches.app.models.system_settings import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from rdflib import RDF, Graph, Literal
from rdflib.namespace import DCTERMS, SKOS

from arches.app.models import models
from arches_controlled_lists.management.commands.packages import (
    Command as PackagesCommand,
)
from arches_controlled_lists.models import List, ListItem, ListItemValue
from arches_controlled_lists.utils.skos import ARCHES, SKOSWriter

from manuspectrum.models import RendererConfig

LOCAL_ORIGIN = "http://localhost:8000/"

APP_NAME = "Manuspectrum"
SEARCH_ITEMS_PER_PAGE = 10

LISTS_DIR = Path("reference_data") / "controlled_lists"
SEARCHABLE_SQL = Path("post_sql") / "controlled_lists_searchable.sql"
SETTINGS_FILE = Path("system_settings") / "System_Settings.json"
GRAPH_DIRS = {
    "resource": Path("graphs") / "resource_models",
    "branch": Path("graphs") / "branches",
}
MAP_DIRS = tuple(
    Path("map_layers") / "mapbox_spec_json" / kind for kind in ("basemaps", "overlays")
)
MANAGED = (
    *GRAPH_DIRS.values(),
    LISTS_DIR,
    SEARCHABLE_SQL,
    SETTINGS_FILE.parent,
    *MAP_DIRS,
    Path("package_config.json"),
    Path("expected-inventory.json"),
)

CORE_DATA_SQL = Path(arches.__file__).parent / "db" / "dml" / "db_data.sql"
CORE_SETTINGS_JSON = (
    Path(arches.__file__).parent
    / "db"
    / "system_settings"
    / "Arches_System_Settings.json"
)

# The sort order the loader gives an item whose triple is missing.
LOADER_DEFAULT_SORTORDER = 999999
LOADER_VALUE_NAMESPACES = ("skos", "arches")
LOADER_VALUE_CATEGORIES = ("label", "note")

SAFE_GRAPH_FILE = re.compile(r"\w[\w .()-]*\.json")
XML_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")
XML_FORBIDDEN = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿\ud800-\udfff]")

_OCTET = r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"


def _local_ipv6(match):
    """True for a loopback, unique-local or link-local IPv6 literal."""
    try:
        address = ipaddress.IPv6Address(match.group(0))
    except ValueError:
        return False
    return (
        address.is_loopback
        or address.is_link_local
        or address in ipaddress.IPv6Network("fc00::/7")
    )


# (name, pattern, secret, accept): a hit needs `accept(match)` when it is given.
LEAK_RULES = (
    ("localhost", re.compile(r"localhost", re.IGNORECASE), False, None),
    (
        "loopback or private IPv4 address",
        re.compile(
            rf"(?<![\d.])(?:10(?:\.{_OCTET}){{3}}|127(?:\.{_OCTET}){{3}}"
            rf"|192\.168(?:\.{_OCTET}){{2}}|172\.(?:1[6-9]|2\d|3[01])(?:\.{_OCTET}){{2}}"
            rf"|169\.254(?:\.{_OCTET}){{2}})(?!\d|\.\d)"
        ),
        False,
        None,
    ),
    (
        "loopback or private IPv6 address",
        re.compile(r"(?<![\w:.])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])"),
        False,
        _local_ipv6,
    ),
    (
        "local host name",
        re.compile(
            r"(?<![\w.-])[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.(?:local|internal|lan)(?![\w-])",
            re.IGNORECASE,
        ),
        False,
        None,
    ),
    ("Mapbox token", re.compile(r"\b[ps]k\.[A-Za-z0-9_-]{20,}"), True, None),
    (
        "Mapbox key value",
        re.compile(r"mapbox[_-]?(?:api[_-]?)?key\"?\s*[:=]\s*\"[^\"\s]", re.IGNORECASE),
        True,
        None,
    ),
    (
        "e-mail address",
        re.compile(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
        ),
        False,
        None,
    ),
)

SKOS_PREFIXES = (
    ("skos", str(SKOS)),
    ("dcterms", str(DCTERMS)),
    ("rdf", str(RDF)),
    ("arches", str(ARCHES)),
)


def slugify(name):
    """Lower-case ASCII letters and digits; any run of other characters is `_`."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", folded.lower()).strip("_")


def list_file_stems(lists):
    """{list id: file stem}; a slug shared by several lists gets the id's head."""
    slugs = {lst.id: slugify(lst.name) or str(lst.id) for lst in lists}
    counts = Counter(slugs.values())
    return {
        list_id: slug if counts[slug] == 1 else f"{slug}_{str(list_id)[:8]}"
        for list_id, slug in slugs.items()
    }


def _qname(uri):
    uri = str(uri)
    for prefix, namespace in SKOS_PREFIXES:
        local = uri[len(namespace) :]
        if uri.startswith(namespace) and XML_NAME.fullmatch(local):
            return f"{prefix}:{local}"
    raise CommandError(f"Cannot write {uri} as an XML element name")


def _escape(text, attribute=False):
    if XML_FORBIDDEN.search(text):
        raise CommandError(f"A value holds a character XML 1.0 cannot carry: {text!r}")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("\r", "&#13;")
    if attribute:
        text = text.replace('"', "&quot;").replace("\n", "&#10;").replace("\t", "&#9;")
    return text


def rdf_keeps_language(code):
    """True when an RDF literal returns the language code unchanged."""
    return Literal("x", lang=code).language == code


def _single_types(graph):
    """{subject: its one type}; a subject with none or several is refused."""
    found = defaultdict(set)
    for subject, rdf_type in graph.subject_objects(RDF.type):
        found[subject].add(rdf_type)
    wrong = sorted(
        str(subject)
        for subject in set(graph.subjects())
        if len(found.get(subject, ())) != 1
    )
    if wrong:
        raise CommandError(
            f"{len(wrong)} subject(s) without exactly one rdf:type, "
            f"which the SKOS writer would drop: {wrong[:5]}"
        )
    return {subject: next(iter(kinds)) for subject, kinds in found.items()}


def render_skos(graph):
    """Canonical RDF/XML of a SKOS graph: sorted subjects and properties, one
    typed node per subject, no blank nodes, no timestamps."""
    types = _single_types(graph)
    rank = {SKOS.ConceptScheme: 0, SKOS.Concept: 1}
    out = ['<?xml version="1.0" encoding="utf-8"?>', "<rdf:RDF"]
    out += [f'  xmlns:{prefix}="{ns}"' for prefix, ns in sorted(SKOS_PREFIXES)]
    out.append(">")
    for subject in sorted(types, key=lambda s: (rank.get(types[s], 2), str(s))):
        element = _qname(types[subject])
        out.append(f'  <{element} rdf:about="{_escape(str(subject), True)}">')
        lines = []
        for predicate, obj in graph.predicate_objects(subject):
            if predicate == RDF.type:
                continue
            name = _qname(predicate)
            if isinstance(obj, Literal):
                attrs = ""
                if obj.language:
                    attrs = f' xml:lang="{_escape(obj.language, True)}"'
                elif obj.datatype:
                    attrs = f' rdf:datatype="{_escape(str(obj.datatype), True)}"'
                text = f"    <{name}{attrs}>{_escape(str(obj))}</{name}>"
                key = (name, 1, obj.language or "", str(obj.datatype or ""), str(obj))
            else:
                text = f'    <{name} rdf:resource="{_escape(str(obj), True)}"/>'
                key = (name, 0, "", "", str(obj))
            lines.append((key, text))
        out += [text for _, text in sorted(lines)]
        out.append(f"  </{element}>")
    out += ["</rdf:RDF>", ""]
    return "\n".join(out)


def list_graph(controlled_list):
    """The SKOS graph of one list, built by arches-controlled-lists' writer."""
    items = ListItem.objects.filter(list=controlled_list).select_related(
        "list", "parent"
    )
    items = items.prefetch_related(
        "list_item_values__valuetype", "list_item_values__language", "children"
    )
    serialized = SKOSWriter().write_controlled_lists([controlled_list], items, "nt")
    if isinstance(serialized, bytes):
        serialized = serialized.decode("utf-8")
    graph = Graph()
    graph.parse(data=serialized, format="nt")
    return graph


def _effective_sortorder(sortorder):
    return LOADER_DEFAULT_SORTORDER if sortorder is None else sortorder


def sibling_ranks(rows):
    """{item id: rank among its siblings}, by (sort order, id).

    The loader ranks siblings by (sort order, best label, id) and gives an item
    without a sort order 999999. The database forbids two siblings with the same
    sort order (the list's `unique_list_sortorder` and `unique_parent_sortorder`
    constraints) and the column is not null, so the label never decides."""
    groups = defaultdict(list)
    for item_id, parent_id, sortorder in rows:
        groups[parent_id].append((_effective_sortorder(sortorder), str(item_id)))
    ranks = {}
    for members in groups.values():
        for position, (_, item_id) in enumerate(sorted(members)):
            ranks[item_id] = position
    return ranks


def items_digest(rows):
    """Order-free digest of a list's (item id, parent id) rows: who the items
    are and where they sit, whatever the sort order."""
    digest = hashlib.sha256()
    for item_id, parent_id in sorted((str(i), str(p or "")) for i, p, *_ in rows):
        digest.update(f"{item_id}|{parent_id}\n".encode())
    return digest.hexdigest()


def exported_graphs():
    """The graphs the package carries: not drafts, not the System Settings."""
    return models.GraphModel.objects.filter(source_identifier__isnull=True).exclude(
        pk=settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID
    )


def published_pairs():
    """{"graph name|language"} of the current publications of the exported
    graphs. The older publications of a graph (its history) are not counted."""
    names = {
        graph.publication_id: str(graph.name)
        for graph in exported_graphs()
        if graph.publication_id
    }
    rows = models.PublishedGraph.objects.filter(publication_id__in=names).values_list(
        "publication_id", "language_id"
    )
    return {f"{names[publication]}|{language}" for publication, language in rows}


def widget_usage():
    """(sorted widget ids, {graph id: number of card-node-widget rows}) of the
    exported graphs. A graph whose widgets failed to import has fewer rows."""
    rows = models.CardXNodeXWidget.objects.filter(
        card__graph__in=exported_graphs()
    ).values_list("card__graph_id", "widget_id")
    per_graph = {}
    for graph_id, _ in rows:
        per_graph[str(graph_id)] = per_graph.get(str(graph_id), 0) + 1
    return sorted({str(widget) for _, widget in rows}), dict(sorted(per_graph.items()))


def expected_published():
    """What a fresh load holds: the importer publishes every graph of the
    package, in every language of `settings.LANGUAGES`, once."""
    return {
        f"{graph.name}|{code}"
        for graph in exported_graphs()
        for code, _ in settings.LANGUAGES
    }


def list_digests(rows):
    """(digest of the stored sort orders, digest of the sibling ranks) of a
    list's (item id, parent id, sortorder) rows."""
    ranks = sibling_ranks(rows)
    raw, ranked = hashlib.sha256(), hashlib.sha256()
    for item_id, parent_id, sortorder in sorted(rows, key=lambda r: str(r[0])):
        head = f"{item_id}|{parent_id or ''}|"
        raw.update(f"{head}{'' if sortorder is None else sortorder}\n".encode())
        ranked.update(f"{head}{ranks[str(item_id)]}\n".encode())
    return raw.hexdigest(), ranked.hexdigest()


def values_digest(rows):
    """Digest of a list's (item id, value type id, language code, value) rows,
    independent of their order. A value's own id is regenerated by the loader
    and is not part of it."""
    digest = hashlib.sha256()
    keys = sorted((str(i), t or "", lang or "", v) for i, t, lang, v in rows)
    for key in keys:
        digest.update(json.dumps(key, ensure_ascii=False).encode("utf-8") + b"\n")
    return digest.hexdigest()


def scan_for_leaks(root, key_node_id=None, files=None, origin=None):
    """Every hit of the leak rules, as (relative path, rule, line number,
    excerpt); a secret is shown masked.

    `files` (paths relative to `root`) restricts the content rules to those
    files; without it every file under `root` is read (`.git` skipped). A
    `business_data` folder with content is reported either way. With `origin`
    (https://host/), `host:port` with a port other than 443 is a hit."""
    root = Path(root)
    hits, candidates = [], []
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        if Path(folder).name == "business_data" and any(
            f.is_file() and f.name != ".gitkeep" for f in Path(folder).rglob("*")
        ):
            hits.append((Path(folder).relative_to(root), "business data", 0, ""))
        candidates += [Path(folder).relative_to(root) / name for name in sorted(names)]
    if files is not None:
        candidates = sorted({Path(f) for f in files})
    rules = list(LEAK_RULES)
    if origin:
        host = re.escape(urlparse(origin).hostname or "")
        rules.append(
            (
                "port on the public origin",
                re.compile(rf"(?<![\w.-]){host}:(\d+)"),
                False,
                lambda m: m.group(1) != "443",
            )
        )
    for relative in candidates:
        text = (root / relative).read_bytes().decode("utf-8", errors="replace")
        for rule, pattern, secret, accept in rules:
            for match in pattern.finditer(text):
                if accept and not accept(match):
                    continue
                line = text.count("\n", 0, match.start()) + 1
                shown = match.group(0)
                hits.append(
                    (relative, rule, line, shown[:4] + "..." if secret else shown)
                )
        if key_node_id and relative == SETTINGS_FILE:
            hits += _settings_key_hits(text, str(key_node_id), relative)
    return hits


def _settings_key_hits(text, key_node_id, relative):
    try:
        document = json.loads(text)
    except ValueError:
        return [(relative, "System Settings is not valid JSON", 0, "")]
    hits = []
    for resource in document.get("business_data", {}).get("resources", []):
        for tile in resource.get("tiles", []):
            value = (tile.get("data") or {}).get(key_node_id)
            if isinstance(value, dict):
                value = [
                    v.get("value") if isinstance(v, dict) else v for v in value.values()
                ]
            elif value is not None:
                value = [value]
            if any(value or []):
                hits.append((relative, "Mapbox key value", 0, "(set)"))
    return hits


def rewrite_origin(root, files, public_origin):
    """Replace `http://localhost:8000/` by `public_origin` in the given files;
    returns the number of replacements."""
    total = 0
    old, new = LOCAL_ORIGIN.encode(), public_origin.encode()
    for relative in files:
        path = Path(root) / relative
        data = path.read_bytes()
        count = data.count(old)
        if count:
            path.write_bytes(data.replace(old, new))
            total += count
    return total


def core_map_rows():
    """({layer name: definitions}, {source name: source}) of Arches' own
    `db_data.sql`."""
    sql = CORE_DATA_SQL.read_text(encoding="utf-8")
    layers = re.findall(
        r"INSERT INTO map_layers\(.*?\)\s*VALUES \(public\.uuid_generate_v1mc\(\), "
        r"'([^']+)', '(.*?)',\s*(?:TRUE|FALSE)",
        sql,
        re.DOTALL,
    )
    sources = re.findall(
        r"INSERT INTO map_sources\(name, source\)\s*VALUES \('([^']+)', '(.*?)'\);",
        sql,
        re.DOTALL,
    )
    return (
        {name: json.loads(body) for name, body in layers},
        {name: json.loads(body) for name, body in sources},
    )


def non_core_map_rows():
    """Sorted labels of the `map_layers` / `map_sources` rows that are not
    Arches' own, or that differ from them."""
    core_layers, core_sources = core_map_rows()
    extra = [
        f"map layer {layer.name}"
        for layer in models.MapLayer.objects.all()
        if core_layers.get(layer.name) != layer.layerdefinitions
    ]
    extra += [
        f"map source {source.name}"
        for source in models.MapSource.objects.all()
        if core_sources.get(source.name) != source.source
    ]
    return sorted(extra)


class Command(BaseCommand):
    help = "Write the public Arches package from the database into --out"

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="Destination directory")
        parser.add_argument(
            "--public-origin",
            required=True,
            help="https://host/ that replaces http://localhost:8000/ in the files",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Write into a non-empty --out, clearing only the managed folders",
        )

    def handle(self, *args, **options):
        origin = options["public_origin"]
        if not (
            origin.startswith("https://")
            and origin.endswith("/")
            and len(origin) > len("https:///")
            and not re.search(r"\s|[?#]", origin)
        ):
            raise CommandError(
                "--public-origin must be https://host/ with a trailing /"
            )
        if settings.ARCHES_NAMESPACE_FOR_DATA_EXPORT != LOCAL_ORIGIN:
            raise CommandError(
                f"ARCHES_NAMESPACE_FOR_DATA_EXPORT must be {LOCAL_ORIGIN} to export"
            )

        out = Path(options["out"])
        if out.exists() and any(out.iterdir()) and not options["force"]:
            raise CommandError(f"{out} is not empty; pass --force to refresh it")
        out.mkdir(parents=True, exist_ok=True)
        self.clear_managed(out)

        self.written = []
        self.origin = origin
        self.inventory = {"format": 1, "public_origin": origin}
        self.settings_key_node_id = None
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL transaction_read_only = on")
                try:
                    self.build(out)
                finally:
                    transaction.set_rollback(True)
        except BaseException:
            self.clear_managed(out)
            raise

        replaced = rewrite_origin(out, self.written, origin)
        hits = scan_for_leaks(
            out, self.settings_key_node_id, files=self.written, origin=origin
        )
        if hits:
            self.clear_managed(out)
            lines = [
                f"  {path}:{line} {rule} {shown}".rstrip()
                for path, rule, line, shown in hits[:20]
            ]
            more = f"\n  ... and {len(hits) - 20} more" if len(hits) > 20 else ""
            raise CommandError(
                f"Refusing to leave the package: {len(hits)} leak(s) found, "
                "the written files were removed.\n" + "\n".join(lines) + more
            )
        self.stdout.write(
            f"Package written to {out}: {len(self.written)} files, "
            f"{replaced} origin replacements, no leak found."
        )

    def clear_managed(self, out):
        for relative in MANAGED:
            target = out / relative
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()

    def write(self, out, relative, content):
        path = out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        self.written.append(relative)

    def write_json(self, out, relative, document):
        text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False)
        self.write(out, relative, text + "\n")

    def build(self, out):
        self.assert_origin_readable()
        self.assert_lists_exportable()
        extra = non_core_map_rows()
        if extra:
            raise CommandError(
                "These map_layers / map_sources rows are not Arches core rows and "
                f"the package cannot carry them yet: {', '.join(extra)}"
            )
        self.export_graphs(out)
        self.export_lists(out, list(List.objects.order_by("name", "id")))
        self.export_system_settings(out)
        self.export_package_config(out)
        for folder in MAP_DIRS:
            self.write(out, folder / ".gitkeep", b"")
        self.inventory["map_layers"] = models.MapLayer.objects.count()
        self.inventory["map_sources"] = models.MapSource.objects.count()
        self.inventory["database"] = {
            "functions": models.Function.objects.count(),
            "functions_x_graphs": models.FunctionXGraph.objects.count(),
            "plugins": models.Plugin.objects.count(),
            "renderer_config": RendererConfig.objects.count(),
        }
        self.write_json(out, Path("expected-inventory.json"), self.inventory)

    def assert_origin_readable(self):
        """The loader sends a predicate whose URI contains the name of a note or
        label value type to the values, before it tests for `arches:sortorder`;
        an origin holding such a name would load every sort order as a value."""
        names = models.DValueType.objects.filter(
            namespace__in=LOADER_VALUE_NAMESPACES, category__in=LOADER_VALUE_CATEGORIES
        ).values_list("valuetype", flat=True)
        predicate = f"{self.origin}sortorder"
        clashing = sorted(name for name in names if name in predicate)
        if clashing:
            raise CommandError(
                f"--public-origin {self.origin} contains {clashing}, a note or label "
                "value type name: the lists loader would read arches:sortorder "
                "as a value of that type. Use an origin without those words."
            )

    def assert_values_loadable(self, controlled_list):
        """Refuses the values the SKOS loader cannot read back: no language, a
        language code RDF does not return unchanged, an image, or a value type
        outside the skos / arches label and note types."""
        problems = set()
        values = ListItemValue.objects.filter(list_item__list=controlled_list)
        for value in values.select_related("valuetype"):
            kind = value.valuetype
            if (
                kind.namespace not in LOADER_VALUE_NAMESPACES
                or kind.category not in LOADER_VALUE_CATEGORIES
            ):
                problems.add(f"value type {kind.valuetype} ({kind.category})")
            code = value.language_id
            if not code:
                problems.add(f"a {kind.valuetype} value without a language")
            elif not rdf_keeps_language(code):
                problems.add(f"language code {code}")
        if problems:
            raise CommandError(
                f"List {controlled_list.name!r} holds values the SKOS loader cannot "
                f"read: {sorted(problems)}"
            )

    def assert_lists_exportable(self):
        dynamic = sorted(
            List.objects.filter(dynamic=True).values_list("name", flat=True)
        )
        if dynamic:
            raise CommandError(f"Dynamic lists cannot be exported: {dynamic}")
        guides = ListItem.objects.filter(guide=True).count()
        if guides:
            raise CommandError(f"{guides} guide item(s) cannot be exported")

    def export_graphs(self, out):
        exporter = PackagesCommand()
        names, help_cards = {}, 0
        for graph_type, relative in GRAPH_DIRS.items():
            (out / relative).mkdir(parents=True, exist_ok=True)
            has_graphs = (
                models.GraphModel.objects.filter(isresource=graph_type == "resource")
                .exclude(pk=settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID)
                .exists()
            )
            # export_graphs raises IndexError on an empty selection.
            if has_graphs:
                exporter.export_graphs(str(out / relative), "", graph_type)
            names[graph_type] = sorted(p.name for p in (out / relative).iterdir())
            graphs = models.GraphModel.objects.filter(
                isresource=graph_type == "resource", source_identifier__isnull=True
            ).exclude(pk=settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID)
            if len(names[graph_type]) != graphs.count():
                raise CommandError(
                    f"{graphs.count()} {graph_type} graphs but "
                    f"{len(names[graph_type])} files in {relative}: two graphs of "
                    "the same name overwrite one file"
                )
            for name in names[graph_type]:
                if not SAFE_GRAPH_FILE.fullmatch(name):
                    raise CommandError(f"Unsafe graph file name: {name!r}")
                self.written.append(relative / name)
                document = json.loads((out / relative / name).read_text("utf-8"))
                for graph in document["graph"]:
                    for card in graph.get("cards", []):
                        help_text = card.get("helptext") or {}
                        if isinstance(help_text, dict) and any(help_text.values()):
                            help_cards += 1
        published = expected_published()
        missing = sorted(
            published
            - published_pairs()
            - {
                f"{graph.name}|{code}"
                for graph in exported_graphs().filter(publication__isnull=True)
                for code, _ in settings.LANGUAGES
            }
        )
        if missing:
            raise CommandError(
                f"Published graphs lack a language a fresh load would give them: {missing[:5]}"
            )
        self.inventory["graphs"] = {
            "resource_models": names["resource"],
            "branches": names["branch"],
            "cards_with_help": help_cards,
            "published": sorted(published),
        }
        self.inventory["widgets"], self.inventory["widget_rows"] = widget_usage()

    def export_lists(self, out, lists):
        stems = list_file_stems(lists)
        per_list, items_total, values_total = {}, 0, 0
        for controlled_list in lists:
            file_name = f"{stems[controlled_list.id]}.xml"
            self.write(
                out, LISTS_DIR / file_name, render_skos(list_graph(controlled_list))
            )
            rows = list(
                ListItem.objects.filter(list=controlled_list).values_list(
                    "id", "parent_id", "sortorder"
                )
            )
            self.assert_values_loadable(controlled_list)
            value_rows = list(
                ListItemValue.objects.filter(
                    list_item__list=controlled_list
                ).values_list("list_item_id", "valuetype_id", "language_id", "value")
            )
            values = len(value_rows)
            raw, ranked = list_digests(rows)
            per_list[str(controlled_list.id)] = {
                "name": controlled_list.name,
                "file": file_name,
                "searchable": controlled_list.searchable,
                "items": len(rows),
                "values": values,
                "digest_sortorder": raw,
                "digest_sibling_rank": ranked,
                "digest_items": items_digest(rows),
                "digest_values": values_digest(value_rows),
            }
            items_total += len(rows)
            values_total += values
        searchable = sorted(str(lst.id) for lst in lists if lst.searchable)
        statement = (
            f"UPDATE {List._meta.db_table} SET searchable = true WHERE id IN (\n"
            + ",\n".join(f"    '{list_id}'" for list_id in searchable)
            + "\n);"
            if searchable
            else "SELECT 1;"
        )
        self.write(
            out,
            SEARCHABLE_SQL,
            "-- Controlled lists that are searchable; SKOS does not carry the flag.\n"
            f"{statement}\n",
        )
        self.inventory["controlled_lists"] = {
            "lists": len(lists),
            "items": items_total,
            "values": values_total,
            "searchable": len(searchable),
            "per_list": per_list,
        }

    def export_system_settings(self, out):
        document = json.loads(CORE_SETTINGS_JSON.read_text(encoding="utf-8"))
        nodes = {
            alias: str(node_id)
            for alias, node_id in models.Node.objects.filter(
                graph_id=settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID,
                alias__in=["app_name", "search_items_per_page", "mapbox_api_key"],
            ).values_list("alias", "nodeid")
        }
        if len(nodes) != 3:
            raise CommandError("The System Settings graph lacks an expected node")
        self.settings_key_node_id = nodes["mapbox_api_key"]

        def text(value):
            return {"direction": "ltr", "value": value}

        replacements = {
            nodes["app_name"]: {"en": text(APP_NAME)},
            nodes["search_items_per_page"]: SEARCH_ITEMS_PER_PAGE,
            nodes["mapbox_api_key"]: {code: text("") for code, _ in settings.LANGUAGES},
        }
        seen = set()
        for resource in document["business_data"]["resources"]:
            for tile in resource["tiles"]:
                for node_id, value in replacements.items():
                    if node_id in tile["data"]:
                        tile["data"][node_id] = value
                        seen.add(node_id)
        if seen != set(replacements):
            raise CommandError("The core System Settings file lacks an expected tile")
        self.write(
            out,
            SETTINGS_FILE,
            json.dumps(document, indent=4, ensure_ascii=False) + "\n",
        )

    def export_package_config(self, out):
        PackagesCommand().export_package_configs(str(out))
        path = out / "package_config.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        relations = document["permitted_resource_relationships"]
        if len(relations) != models.Resource2ResourceConstraint.objects.count():
            raise CommandError("package_config.json lost resource constraints")
        document["permitted_resource_relationships"] = sorted(
            relations, key=lambda r: r["resource2resourceid"]
        )
        document["business_data_load_order"] = []
        path.unlink()
        self.write_json(out, Path("package_config.json"), document)
        self.inventory["resource_to_resource_constraints"] = len(relations)

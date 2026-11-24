"""The Analyses of a Document as the measurement-file workflow lists them.

An Analysis belongs to a Document when its ``component_observed`` is the
Document or one of its Components, and to a Project through
``analysis_by_project``. Nothing here writes. Reads go through the roles of
``utils/roles.py``, one query per role or set, and a reader sees only the
nodegroups and resources the permission framework lets them read.
"""

import hashlib
import os
from collections import defaultdict
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied

from arches.app.models.models import File, NodeGroup, ResourceInstance, TileModel
from arches.app.utils.permission_backend import (
    user_can_edit_resource,
    user_can_read_resource,
)

from manuspectrum.constants.xy_presets import TECHNIQUE_PRESETS
from manuspectrum.iiif import language as lang
from manuspectrum.iiif.facts import names_of
from manuspectrum.utils.file_pairs import pair
from manuspectrum.utils.public_visibility import readable_nodegroup_ids
from manuspectrum.utils.role_links import graph_id_of, node_links, role_node
from manuspectrum.utils.roles import ROLES
from manuspectrum.utils.spectrum_preview import is_raw_instrument

EDITABLE_DOCUMENTS_LIMIT = 50
_PREFERRED = ("en", lang.NONE)


@dataclass(frozen=True)
class StoredFile:
    file_id: str
    name: str
    extension: str
    is_raw: bool
    has_csv_twin: bool
    sha256: str | None


@dataclass(frozen=True)
class AnalysisCard:
    id: str
    name: str
    technique_ids: tuple[str, ...]
    technique_label: dict[str, str]
    technique_preset: str | None
    folio_sources: tuple[str, ...]
    files: tuple[StoredFile, ...]
    parent_tile_id: str | None
    projects: tuple[str, ...]
    editable: bool


def stored_sha256(file_id):
    """SHA-256 hex of a stored ``File``'s bytes, or None when the row or the bytes are missing."""
    row = File.objects.filter(pk=file_id).first()
    if row is None or not row.path:
        return None
    digest = hashlib.sha256()
    try:
        with row.path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _plain(language_map):
    """One display string of a language map: English, then no language, then the first."""
    for key in _PREFERRED:
        if language_map.get(key):
            return language_map[key][0]
    return next((texts[0] for texts in language_map.values() if texts), "")


def _links(key, targets, readable):
    """``node_links`` of role *key* (every link when *targets* is None); nothing when it is unresolved or not readable."""
    node = role_node(*ROLES[key])
    if node is None or node.nodegroup_id not in readable:
        return []
    if targets is not None and not targets:
        return []
    return node_links(node, targets)


def _readable_document(document_id, user):
    row = (
        ResourceInstance.objects.filter(pk=document_id)
        .select_related("resource_instance_lifecycle_state")
        .first()
    )
    if row is None or not user_can_read_resource(user, resource=row):
        raise PermissionDenied
    return row


def _technique(value):
    ids, labels = [], defaultdict(list)
    for item in lang.reference_items(value):
        found = [
            str(entry["list_item_id"])
            for entry in item["labels"]
            if isinstance(entry, dict) and entry.get("list_item_id")
        ]
        ids.append(found[0] if found else str(item.get("uri") or ""))
        for language, texts in lang.reference_item_labels(item).items():
            labels[language].extend(texts)
    return (
        tuple(i for i in ids if i),
        {language: ", ".join(texts) for language, texts in labels.items()},
    )


def _preset(technique_ids):
    presets = {TECHNIQUE_PRESETS.get(i) for i in technique_ids}
    return presets.pop() if len(presets) == 1 and None not in presets else None


def _stored_files(entries):
    entries = [e for e in entries if isinstance(e, dict) and e.get("file_id")]
    twins = pair(entries)
    result = []
    for entry in entries:
        name = str(entry.get("name") or "")
        file_id = str(entry["file_id"])
        sha = entry.get("msSourceSha256")
        result.append(
            StoredFile(
                file_id=file_id,
                name=name,
                extension=os.path.splitext(name)[1].lstrip(".").lower(),
                is_raw=is_raw_instrument(name),
                has_csv_twin=file_id in twins,
                sha256=sha if isinstance(sha, str) and sha else None,
            )
        )
    return tuple(result)


def _texts(value):
    return [text for texts in lang.string_map(value).values() for text in texts]


def document_analyses(document_id, user, project_id=None):
    """The ``AnalysisCard`` of every Analysis of a Document the *user* may read, by name.

    Raises ``PermissionDenied`` when the Document is missing or unreadable.
    With *project_id*, only the Analyses that Project holds. ``editable`` is
    ``user_can_edit_resource``: a Retired Analysis is not.
    """
    document = _readable_document(document_id, user)
    readable = readable_nodegroup_ids(user)
    document_id = str(document.pk)
    components = {
        c for c, _ in _links("item_visual_is_part_of_document", [document_id], readable)
    }
    observed = defaultdict(set)
    for analysis, target in _links(
        "component_observed", [document_id, *components], readable
    ):
        observed[analysis].add(target)
    in_project = (
        {a for a, _ in _links("analysis_by_project", [project_id], readable)}
        if project_id
        else None
    )
    ids = [a for a in observed if in_project is None or a in in_project]
    rows = {
        str(row.pk): row
        for row in ResourceInstance.objects.filter(pk__in=ids).select_related(
            "resource_instance_lifecycle_state"
        )
    }
    ids = [a for a in rows if user_can_read_resource(user, resource=rows[a])]
    if not ids:
        return []

    projects = defaultdict(list)
    for analysis, project in _links("analysis_by_project", None, readable):
        if analysis in rows:
            projects[analysis].append(project)

    files_node = role_node(*ROLES["files"])
    technique_node = role_node(*ROLES["technique"])
    text_nodes = {
        key: role_node(*ROLES[key])
        for key in ("an_location_note", "an_location_label", "an_filename")
    }
    parent_group = (
        NodeGroup.objects.filter(pk=files_node.nodegroup_id)
        .values_list("parentnodegroup_id", flat=True)
        .first()
        if files_node is not None
        else None
    )
    wanted = {
        str(n.nodegroup_id)
        for n in (files_node, technique_node, *text_nodes.values())
        if n is not None and n.nodegroup_id in readable
    }
    if parent_group and str(parent_group) in readable:
        wanted.add(str(parent_group))
    tiles = defaultdict(lambda: defaultdict(list))
    for tile in TileModel.objects.filter(
        resourceinstance_id__in=ids, nodegroup_id__in=wanted
    ).order_by("sortorder", "tileid"):
        tiles[str(tile.resourceinstance_id)][str(tile.nodegroup_id)].append(tile)

    names = names_of([*ids, *components], readable)
    cards = []
    for analysis in ids:

        def values(node, owner=analysis):
            if node is None:
                return []
            return [
                t.data.get(str(node.nodeid))
                for t in tiles[owner][str(node.nodegroup_id)]
                if (t.data or {}).get(str(node.nodeid)) not in (None, "", [])
            ]

        technique_ids, technique_label = (), {}
        for value in values(technique_node):
            technique_ids, technique_label = _technique(value)
        entries = [
            entry
            for value in values(files_node)
            for entry in (value if isinstance(value, list) else [])
        ]
        parent_tiles = tiles[analysis][str(parent_group)] if parent_group else []
        folio = [_plain(names.get(analysis, {}))]
        folio += [
            _plain(names.get(c, {})) for c in sorted(observed[analysis] & components)
        ]
        for key in ("an_location_note", "an_location_label", "an_filename"):
            folio += [text for v in values(text_nodes[key]) for text in _texts(v)]
        cards.append(
            AnalysisCard(
                id=analysis,
                name=_plain(names.get(analysis, {})),
                technique_ids=technique_ids,
                technique_label=technique_label,
                technique_preset=_preset(technique_ids),
                folio_sources=tuple(dict.fromkeys(t for t in folio if t)),
                files=_stored_files(entries),
                parent_tile_id=str(parent_tiles[0].tileid) if parent_tiles else None,
                projects=tuple(dict.fromkeys(projects[analysis])),
                editable=bool(user_can_edit_resource(user, resource=rows[analysis])),
            )
        )
    return sorted(cards, key=lambda card: (card.name.casefold(), card.id))


def document_status(document_id, user, project_id=None):
    """Counts of the Analyses of a Document, for the status card of step 1.

    ``complete`` has a raw file with its CSV, ``raw_without_csv`` a raw file
    and no CSV twin, ``without_file`` no file at all; ``csv_only`` has files
    but no raw one. ``by_technique`` groups by technique id. ``other_projects``
    lists the Projects studying the Document apart from *project_id*, with
    how many of its Analyses each holds, when the Document is studied by
    several.
    """
    cards = document_analyses(document_id, user, project_id)
    counts = {"complete": 0, "raw_without_csv": 0, "without_file": 0, "csv_only": 0}
    techniques = {}
    for card in cards:
        raws = [f for f in card.files if f.is_raw]
        if not card.files:
            counts["without_file"] += 1
        elif not raws:
            counts["csv_only"] += 1
        elif all(f.has_csv_twin for f in raws):
            counts["complete"] += 1
        else:
            counts["raw_without_csv"] += 1
        key = card.technique_ids
        entry = techniques.setdefault(
            key,
            {
                "technique_ids": list(key),
                "label": card.technique_label,
                "analyses": 0,
            },
        )
        entry["analyses"] += 1
    return {
        "analyses": len(cards),
        **counts,
        "by_technique": list(techniques.values()),
        "other_projects": _other_projects(document_id, user, project_id),
    }


def _other_projects(document_id, user, project_id):
    readable = readable_nodegroup_ids(user)
    document_id = str(document_id)
    studying = list(
        dict.fromkeys(p for p, _ in _links("project_studied", [document_id], readable))
    )
    if project_id is None and len(studying) < 2:
        return []
    others = [p for p in studying if p != str(project_id)]
    rows = {
        str(r.pk): r
        for r in ResourceInstance.objects.filter(pk__in=others).select_related(
            "resource_instance_lifecycle_state"
        )
    }
    others = [
        p
        for p in others
        if p in rows and user_can_read_resource(user, resource=rows[p])
    ]
    if not others:
        return []
    components = {
        c for c, _ in _links("item_visual_is_part_of_document", [document_id], readable)
    }
    held = defaultdict(set)
    for analysis, project in _links("analysis_by_project", others, readable):
        held[project].add(analysis)
    on_document = {
        a for a, _ in _links("component_observed", [document_id, *components], readable)
    }
    names = names_of(others, readable)
    return [
        {
            "project_id": project,
            "name": _plain(names.get(project, {})),
            "analyses": len(held[project] & on_document),
        }
        for project in sorted(
            others, key=lambda p: (_plain(names.get(p, {})).casefold(), p)
        )
    ]


def editable_documents(user, project_id=None, query=""):
    """``[{id, name}]`` of the Documents *user* reads that hold an Analysis they may edit.

    With *project_id*, the Documents that Project studies and its own
    Analyses only. *query* keeps names containing it (case and accents
    ignored only by ``casefold``). At most ``EDITABLE_DOCUMENTS_LIMIT``,
    ordered by name.
    """
    readable = readable_nodegroup_ids(user)
    observed = defaultdict(set)
    for analysis, target in _links("component_observed", None, readable):
        observed[target].add(analysis)
    components = defaultdict(set)
    for component, document in _links(
        "item_visual_is_part_of_document", None, readable
    ):
        components[document].add(component)
    if project_id:
        candidates = {
            d
            for _, d in _links("project_studied", None, readable)
            if _ == str(project_id)
        }
        in_project = {
            a for a, _ in _links("analysis_by_project", [project_id], readable)
        }
    else:
        candidates, in_project = set(components) | set(observed), None
    rows = {
        str(r.pk): r
        for r in ResourceInstance.objects.filter(
            pk__in=candidates, graph_id=graph_id_of("document")
        ).select_related("resource_instance_lifecycle_state")
    }
    analyses_of = {}
    for document in rows:
        found = set(observed.get(document, ()))
        for component in components.get(document, ()):
            found |= observed.get(component, set())
        if in_project is not None:
            found &= in_project
        if found:
            analyses_of[document] = found
    analysis_rows = {
        str(r.pk): r
        for r in ResourceInstance.objects.filter(
            pk__in=set().union(*analyses_of.values())
        ).select_related("resource_instance_lifecycle_state")
    }
    names = names_of(analyses_of, readable)
    needle = (query or "").casefold().strip()
    ordered = sorted(
        (
            (_plain(names.get(d, {})), d)
            for d in analyses_of
            if needle in _plain(names.get(d, {})).casefold()
        ),
        key=lambda pair_: (pair_[0].casefold(), pair_[1]),
    )
    result = []
    for name, document in ordered:
        if len(result) >= EDITABLE_DOCUMENTS_LIMIT:
            break
        if not user_can_read_resource(user, resource=rows[document]):
            continue
        if not any(
            user_can_edit_resource(user, resource=analysis_rows[a])
            for a in sorted(analyses_of[document])
            if a in analysis_rows
        ):
            continue
        result.append({"id": document, "name": name})
    return result

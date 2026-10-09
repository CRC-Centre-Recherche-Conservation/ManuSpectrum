"""The map's events (spec 2026-10-09 §2.1), computed once per corpus bundle.

An event is one (carrier, place). A carrier is a Document or Component production,
a Modification, an Alteration, an Analysis or a Sample of the visible set; its
dates, places and own geometry are read off its own nodegroups by role. Four-bound
dates widen the interval to the lowest and highest year present; a single bound
stands for both. A carrier with neither a bound, a visible linked place nor an own
geometry has no occurrence.

Place: the own geometry (a derived copy is not one), else each visible linked
Place with a geometry, else its nearest visible ancestor with one
(``placeSource`` ``parent``); a linked place left unmapped keeps the place with
``placeSource`` None. A hidden place is never a place and cuts the chain.

Material (PO rule): an identified material goes to the Modifications citing it
(``observed_by_characterisation``) and to the Alterations of an object it observes
that name its material (``occured_in_presence_of_material``); otherwise to the
production of each linked Component, else of that Component's Document, else of the
Document it observes.

An occurrence becomes events only with a supporting analysis among the rows: the
analysis itself, the analyses using a sample, the evidence of the materials a
modification or an alteration carries (and the analyses an alteration names),
otherwise every analysis on the carrier's Component, else its Document.
``histories`` hold every occurrence of each document, supporting analyses or not.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass

from manuspectrum.utils.public_visibility import readable_nodegroup_ids
from manuspectrum.views.explorer.places import (
    authorities_of,
    derived_only,
    geometry_summary,
)
from manuspectrum.views.explorer.service import (
    PLACE_DEPTH,
    Values,
    _bound_year,
    _links,
    _ordered_refs,
    bounds_meet,
    characterization_wanted,
    corpus_bundle,
    meets,
    names,
    period_facet,
    qualified_values,
    row_filter,
)
from manuspectrum.views.explorer.swatches import colour_rank
from manuspectrum.views.explorer.values import fold, reference_items, string_texts
from manuspectrum.views.summary_service import _date

EVENT_TYPES = ("production", "modification", "alteration", "analysis", "sampling")
MATERIAL_EVENTS = frozenset({"production", "modification", "alteration"})
PUBLIC_KEYS = (
    "id",
    "type",
    "carrier",
    "document",
    "component",
    "place",
    "placeSource",
    "date",
    "materials",
    "analyses",
)
OWN_PREFIX = "own:"
NO_YEAR = 10**6
DATE_ROLES = {
    "document": ("doc_start", "doc_end", None, None, "doc_approx"),
    "component": (
        "comp_start",
        "comp_end",
        "comp_end_begin",
        "comp_end_end",
        "comp_approx",
    ),
    "modification": (
        "mod_start",
        "mod_end",
        "mod_end_begin",
        "mod_end_end",
        "mod_approx",
    ),
    "alteration": (
        "alt_start",
        "alt_end",
        "alt_end_begin",
        "alt_end_end",
        "alt_approx",
    ),
    "analysis": ("start", "end", None, None, None),
    "sample": ("sample_start", "sample_end", None, None, None),
}
PLACE_ROLES = {
    "document": "doc_place",
    "component": "comp_place",
    "modification": "mod_place",
    "alteration": "alt_place",
    "analysis": "an_place",
    "sample": "sample_place",
}
GEOMETRY_ROLES = {
    "document": "doc_geometry",
    "component": "comp_geometry",
    "modification": "mod_geometry",
}
TYPE_OF = {
    "document": "production",
    "component": "production",
    "modification": "modification",
    "alteration": "alteration",
    "analysis": "analysis",
    "sample": "sampling",
}


@dataclass(frozen=True)
class Occurrence:
    type: str
    carrier: str
    model: str
    document: str
    component: str | None
    years: tuple | None
    approximate: bool
    stored: tuple
    linked: tuple
    own: object

    @property
    def key(self):
        return (self.model, self.carrier)


@dataclass(frozen=True)
class EventSet:
    events: tuple
    places: dict
    materials: dict
    material_terms: dict
    histories: dict


def parse_event_types(query):
    """The event types ``eventType`` names (repeated or comma-separated), in ``EVENT_TYPES`` order; others ignored.

    Without a known type, the ``MATERIAL_EVENTS``: ``analysis`` and ``sampling`` come only when asked.
    """
    asked = {
        v.strip()
        for raw in query.getlist("eventType")
        for v in raw.split(",")
        if v.strip()
    }
    wanted = asked & set(EVENT_TYPES) or MATERIAL_EVENTS
    return [t for t in EVENT_TYPES if t in wanted]


def _keys(model):
    return [
        k
        for k in (*DATE_ROLES[model], PLACE_ROLES[model], GEOMETRY_ROLES.get(model))
        if k
    ]


def dates_of(values, rid, model):
    """``(years, approximate, stored)`` of the first tile of *rid* holding a bound of its *model*'s date roles.

    *stored* is the stored text of the start bound and of the latest end bound
    (end, end of the end); without an end, the start alone.
    """
    start_key, end_key, begin_key, last_key, approx_key = DATE_ROLES[model]
    nodes = {
        k: values.node(k)
        for k in (start_key, end_key, begin_key, last_key)
        if k and values.node(k)
    }
    approx = values.node(approx_key) if approx_key else None
    for data in values.tiles(rid, start_key) or values.tiles(rid, end_key):
        dated = {k: data.get(n.nodeid) for k, n in nodes.items()}
        dated = {
            k: t
            for k, t in dated.items()
            if isinstance(t, str) and _bound_year(t) is not None
        }
        if not dated:
            continue
        years = [_bound_year(t) for t in dated.values()]
        ends = [dated[k] for k in (end_key, last_key) if k in dated]
        start_text = dated.get(start_key) or (
            None if ends else min(dated.values(), key=_bound_year)
        )
        return (
            (min(years), max(years)),
            bool(approx) and data.get(approx.nodeid) is True,
            (start_text, max(ends, key=_bound_year) if ends else None),
        )
    return None, False, (None, None)


def _occurrence(model, rid, values, document, component, places):
    years, approximate, stored = dates_of(values, rid, model)
    linked = tuple(
        p for p in _ordered_refs(values.get(rid, PLACE_ROLES[model])) if p in places
    )
    own = None
    if model in GEOMETRY_ROLES:
        for collection in values.get(rid, GEOMETRY_ROLES[model]):
            if isinstance(collection, dict) and not derived_only(collection):
                own = geometry_summary(collection)
                if own:
                    break
    if years is None and not linked and own is None:
        return None
    return Occurrence(
        TYPE_OF[model],
        rid,
        model,
        document,
        component,
        years,
        approximate,
        stored,
        linked,
        own,
    )


def _first(ids, wanted):
    shown = sorted(i for i in ids if i in wanted)
    return shown[0] if shown else None


def _object_chain(objects, visible, part_of):
    documents, components = set(), set()
    for o in objects:
        if o in visible.documents:
            documents.add(o)
        elif o in visible.components:
            components.add(o)
            documents |= {d for d in part_of.get(o, ()) if d in visible.documents}
    if not documents:
        return None
    return min(documents), (next(iter(components)) if len(components) == 1 else None)


def build_events(
    user,
    language,
    visible,
    chains,
    links,
    rows,
    order,
    label_of,
    characterization_values,
    material_components,
    swatches,
):
    """The ``EventSet`` of the visible corpus: events in document-name order, their places, materials and the documents' histories."""
    readable = readable_nodegroup_ids(user)
    by_id = {row["id"]: row for row in rows}
    rows_of = defaultdict(set)
    for row in rows:
        rows_of[row["document"]].add(row["id"])
        if row["component"]:
            rows_of[row["component"]].add(row["id"])
    part_of, places = links["part_of"], visible.places
    read = {
        model: Values(
            ids,
            _keys(model) + (["alt_material"] if model == "alteration" else []),
            user,
        )
        for model, ids in (
            ("document", visible.documents),
            ("component", visible.components),
            ("modification", visible.modifications),
            ("alteration", visible.alterations),
            ("analysis", list(by_id)),
            ("sample", visible.samples),
        )
    }
    mod_objects = _links("modification", "document_modified", readable)
    alt_objects = _links("alteration", "object_altered", readable)
    mod_cites = _links("modification", "observed_by_characterisation", readable)
    alt_analyses = _links(
        "alteration", "analysis_reference_observed_about_inference_making", readable
    )
    users_of = defaultdict(set)
    for analysis, samples in links["samples"].items():
        if analysis in by_id:
            for sample in samples:
                users_of[sample].add(analysis)

    occurrences = []
    for d in sorted(visible.documents):
        occurrences.append(
            _occurrence("document", d, read["document"], d, None, places)
        )
    for c in sorted(visible.components):
        document = _first(part_of.get(c, ()), visible.documents)
        if document:
            occurrences.append(
                _occurrence("component", c, read["component"], document, c, places)
            )
    for model, objects in (("modification", mod_objects), ("alteration", alt_objects)):
        for carrier in sorted(getattr(visible, f"{model}s")):
            chain = _object_chain(objects.get(carrier, ()), visible, part_of)
            if chain:
                occurrences.append(
                    _occurrence(model, carrier, read[model], *chain, places)
                )
    for a in sorted(by_id):
        occurrences.append(
            _occurrence(
                "analysis",
                a,
                read["analysis"],
                by_id[a]["document"],
                by_id[a]["component"],
                places,
            )
        )
    for s in sorted(visible.samples):
        if users_of[s]:
            first = by_id[min(users_of[s], key=order.__getitem__)]
            occurrences.append(
                _occurrence(
                    "sample",
                    s,
                    read["sample"],
                    first["document"],
                    first["component"],
                    places,
                )
            )
    occurrences = [o for o in occurrences if o and o.document in label_of]
    by_key = {o.key: o for o in occurrences}

    material_values = Values(
        visible.characterizations, ["material", "confidence"], user
    )
    qualified = qualified_values(material_values, visible.characterizations, language)
    entries, terms = {}, defaultdict(set)
    for c in visible.characterizations:
        entries[c] = [
            {
                "id": ref["uri"],
                "name": ref["label"],
                "reliability": q["id"] if q else None,
                "characterization": c,
            }
            for refs, _, q in qualified[c]["material"]
            for ref in refs
        ]
        for _, stored, _ in qualified[c]["material"]:
            for item in reference_items(stored):
                terms[item["uri"]] |= {
                    fold(e["value"])
                    for e in item.get("labels") or []
                    if isinstance(e, dict) and isinstance(e.get("value"), str)
                }
    named = {
        a: {
            item["uri"]
            for v in read["alteration"].get(a, "alt_material")
            for item in reference_items(v)
        }
        for a in visible.alterations
    }
    cited_by = defaultdict(list)
    for m in sorted(visible.modifications):
        for c in mod_cites.get(m, ()):
            cited_by[c].append(("modification", m))
    objects_of = links["objects"]
    attached = defaultdict(list)
    for c in sorted(visible.characterizations):
        reach = (
            set(objects_of.get(c, ())) & (visible.documents | visible.components)
        ) | set(material_components.get(c, ()))
        reach |= {
            d
            for k in material_components.get(c, ())
            for d in part_of.get(k, ())
            if d in visible.documents
        }
        uris = {e["id"] for e in entries[c]}
        homes = [k for k in cited_by[c] if k in by_key]
        homes += [
            ("alteration", a)
            for a in sorted(visible.alterations)
            if ("alteration", a) in by_key
            and uris & named[a]
            and set(alt_objects.get(a, ())) & reach
        ]
        if not homes:
            for k in material_components.get(c, ()):
                if ("component", k) in by_key:
                    homes.append(("component", k))
                else:
                    d = _first(part_of.get(k, ()), visible.documents)
                    if d and ("document", d) in by_key:
                        homes.append(("document", d))
            homes += [
                ("document", d)
                for d in sorted(set(objects_of.get(c, ())) & visible.documents)
                if ("document", d) in by_key
            ]
        for key in dict.fromkeys(homes):
            attached[key].append(c)

    def supporting(occ):
        if occ.type == "analysis":
            return [occ.carrier]
        if occ.type == "sampling":
            return sorted(users_of[occ.carrier], key=order.__getitem__)
        cited = {
            a
            for c in attached[occ.key]
            for a in visible.evidence.get(c, ())
            if a in by_id
        }
        if occ.type == "alteration":
            cited |= {a for a in alt_analyses.get(occ.carrier, ()) if a in by_id}
        if occ.type in ("modification", "alteration") and cited:
            return sorted(cited, key=order.__getitem__)
        return sorted(
            rows_of.get(occ.component or occ.document, ()), key=order.__getitem__
        )

    parent_links = _links("place", "part_of_places", readable)
    parent_of = {p: _first(parent_links.get(p, ()), places) for p in places}
    place_values = Values(places, ["place_geometry", "place_identifier"], user)
    geometry = {}
    for p in places:
        for value in place_values.get(p, "place_geometry"):
            found = geometry_summary(value) if isinstance(value, dict) else None
            if found:
                geometry[p] = found
                break

    def mapped_ancestor(place):
        seen, current = {place}, parent_of.get(place)
        for _ in range(PLACE_DEPTH):
            if current is None or current in seen:
                return None
            if current in geometry:
                return current
            seen.add(current)
            current = parent_of.get(current)
        return None

    own_places = {}

    def resolve(occ):
        if occ.own is not None:
            pid = f"{OWN_PREFIX}{occ.own.lng_lat[0]:.4f},{occ.own.lng_lat[1]:.4f}"
            own_places.setdefault(
                pid, (occ.own, occ.linked[0] if occ.linked else None, occ.carrier)
            )
            return [(pid, "own")]
        if not occ.linked:
            return [(None, None)]
        found = []
        for p in occ.linked:
            above = None if p in geometry else mapped_ancestor(p)
            found.append(
                (p, "place")
                if p in geometry
                else (above, "parent") if above else (p, None)
            )
        return list(dict.fromkeys(found))

    extra = {
        o.carrier
        for o in occurrences
        if o.model in ("modification", "alteration", "sample")
    }
    extra |= {
        o.component for o in occurrences if o.component and o.component not in label_of
    }
    carrier_names = names(extra, language, user)

    def name_of(rid):
        if rid in by_id:
            return by_id[rid]["name"]
        return (
            label_of.get(rid)
            or carrier_names.get(rid)
            or {"value": rid[:8], "lang": language}
        )

    events = []
    for occ in occurrences:
        analyses = supporting(occ)
        if not analyses:
            continue
        materials = (
            [e for c in attached[occ.key] for e in entries[c]]
            if occ.type in MATERIAL_EVENTS
            else []
        )
        for place, source in resolve(occ):
            events.append(
                {
                    "id": f"{occ.type}:{occ.carrier}:{place or '-'}",
                    "type": occ.type,
                    "carrier": {
                        "id": occ.carrier,
                        "model": occ.model,
                        "name": name_of(occ.carrier),
                    },
                    "document": {"id": occ.document, "name": name_of(occ.document)},
                    "component": (
                        {"id": occ.component, "name": name_of(occ.component)}
                        if occ.component
                        else None
                    ),
                    "place": place,
                    "placeSource": source,
                    "date": {
                        "start": occ.years[0] if occ.years else None,
                        "end": occ.years[1] if occ.years else None,
                        "approximate": occ.approximate,
                    },
                    "materials": materials,
                    "analyses": analyses,
                }
            )
    events.sort(
        key=lambda e: (
            fold(e["document"]["name"]["value"]),
            e["document"]["id"],
            EVENT_TYPES.index(e["type"]),
            e["date"]["start"] if e["date"]["start"] is not None else NO_YEAR,
            e["carrier"]["id"],
            e["place"] or "",
        )
    )

    wanted = {
        e["place"]
        for e in events
        if e["place"] and not e["place"].startswith(OWN_PREFIX)
    }
    wanted |= {linked for _, linked, _ in own_places.values() if linked}
    frontier = set(wanted)
    while frontier:
        frontier = {parent_of.get(p) for p in frontier if parent_of.get(p)} - wanted
        wanted |= frontier
    linked_all = {p for o in occurrences for p in o.linked}
    place_names = names(wanted | linked_all, language, user)
    places_out = {}
    for p in sorted(wanted):
        g = geometry.get(p)
        texts = [
            t
            for v in place_values.get(p, "place_identifier")
            for t in string_texts(v).values()
        ]
        places_out[p] = {
            "id": p,
            "name": place_names.get(p, {"value": p[:8], "lang": language}),
            "lngLat": list(g.lng_lat) if g else None,
            "geometryKind": g.kind if g else "point",
            "extentKm": g.extent_km if g else None,
            "parent": parent_of.get(p),
            "unpublished": p in visible.unpublished,
            "authorities": authorities_of(texts),
        }
    for pid, (g, linked, carrier) in sorted(own_places.items()):
        places_out[pid] = {
            "id": pid,
            "name": place_names[linked] if linked in place_names else name_of(carrier),
            "lngLat": list(g.lng_lat),
            "geometryKind": g.kind,
            "extentKm": g.extent_km,
            "parent": linked,
            "unpublished": False,
            "authorities": {},
        }

    labels, colours = {}, defaultdict(Counter)
    for e in events:
        for m in e["materials"]:
            labels.setdefault(m["id"], m["name"])
            for colour in characterization_values.get(m["characterization"], {}).get(
                "colour", ()
            ):
                colours[m["id"]][colour] += 1

    def colours_of(uri):
        return [
            colour
            for colour, _ in sorted(
                colours[uri].items(),
                key=lambda kv: (
                    -kv[1],
                    colour_rank(kv[0]) if colour_rank(kv[0]) is not None else 999,
                    kv[0],
                ),
            )
        ]

    def swatch_of(uri):
        for colour in colours_of(uri):
            if swatches.get(colour):
                return swatches[colour]
        return None

    materials_out = {
        uri: {
            "uri": uri,
            "label": labels[uri],
            "colours": colours_of(uri),
            "swatch": swatch_of(uri),
        }
        for uri in sorted(labels)
    }

    histories = defaultdict(list)
    for occ in occurrences:
        start, end = occ.stored
        line = {
            "type": occ.type,
            "carrier": {
                "id": occ.carrier,
                "model": occ.model,
                "name": name_of(occ.carrier),
            },
            "places": [
                {"id": p, "name": place_names[p]}
                for p in occ.linked
                if p in place_names
            ],
            "date": {
                "start": _date(start) if start else None,
                "end": _date(end) if end else None,
                "approximate": occ.approximate,
            },
        }
        rank = (
            0 if occ.model == "document" else 1,
            occ.years[0] if occ.years else NO_YEAR,
            EVENT_TYPES.index(occ.type),
            occ.carrier,
        )
        histories[occ.document].append((rank, line))
    return EventSet(
        events=tuple(events),
        places=places_out,
        materials=materials_out,
        material_terms={uri: frozenset(found) for uri, found in terms.items()},
        histories={
            d: tuple(line for _, line in sorted(lines, key=lambda item: item[0]))
            for d, lines in histories.items()
        },
    )


def kept_events(bundle, query):
    """``(events, keep, filters)``: the public ``MapEvent`` of the events *query* keeps, in bundle order.

    An event is kept when its type is among ``eventType`` (all without one), its own
    dates meet the period (``bounds_meet``; ``periodEvent`` does not apply), one of
    its supporting analyses is kept by the Corpus rule with the period left out, and,
    for a production, modification or alteration under characterization filters,
    one of its materials meets them. ``analyses`` keeps the kept ones.
    """
    keep, active, filters, *_ = row_filter(bundle.rows, query, universe=bundle.universe)
    kept_rows = {row["id"] for row in bundle.rows if keep(row, "period")}
    wanted = characterization_wanted(active)
    types = set(parse_event_types(query))
    found = []
    for event in bundle.events:
        if types and event["type"] not in types:
            continue
        date = event["date"]
        if not bounds_meet(
            None if date["start"] is None else (date["start"], date["end"]), filters
        ):
            continue
        analyses = [a for a in event["analyses"] if a in kept_rows]
        if not analyses:
            continue
        if (
            wanted
            and event["type"] in MATERIAL_EVENTS
            and not any(
                meets(bundle.characterization_values[m["characterization"]], wanted)
                for m in event["materials"]
            )
        ):
            continue
        found.append({**event, "analyses": analyses})
    return found, keep, filters


def place_subset(places, used):
    """The ``MapPlace`` of *used* and of their ancestors, by id."""
    wanted, frontier = set(), {p for p in used if p}
    while frontier:
        wanted |= frontier
        frontier = {
            places[p]["parent"] for p in frontier if p in places and places[p]["parent"]
        } - wanted
    return {p: places[p] for p in sorted(wanted) if p in places}


def events_payload(query, user, language, ticket=None):
    """``EventsResponse`` of the events *query* keeps (``kept_events``)."""
    bundle = corpus_bundle(user, language, ticket)
    events, keep, filters = kept_events(bundle, query)
    places = place_subset(bundle.event_places, {e["place"] for e in events})
    event = filters["periodEvent"]
    materials = {
        m["id"]: bundle.event_materials[m["id"]] for e in events for m in e["materials"]
    }
    return {
        "events": events,
        "places": places,
        "unplaced": sum(
            1 for e in events if not e["place"] or places[e["place"]]["lngLat"] is None
        ),
        "period": period_facet(bundle.rows, keep, event, bundle.period_bounds[event]),
        "materials": materials,
        "analysisNames": {
            a: bundle.by_id[a]["name"] for e in events for a in e["analyses"]
        },
        "colours": {
            colour: bundle.event_colours[colour]
            for m in materials.values()
            for colour in m["colours"]
        },
        "certaintyScale": bundle.certainty,
    }

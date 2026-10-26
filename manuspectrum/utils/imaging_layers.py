"""The imaging layer proposal rule: what a canvas label implies, and the tiles it plans and writes.

The one place the label → « Imaging layers » mapping is written. ``propose``
is pure; ``plan`` and ``write`` read and create the tiles of one imaging
manifest tile. Nodes are resolved by alias (``role_node``) and list items by
their English prefLabel in the list their node is configured with; a missing
or ambiguous item raises ``ImagingLayersConfigError`` and never yields a
partial tile.
"""

import re
import uuid
from dataclasses import dataclass, field

from arches.app.models.models import TileModel
from arches.app.models.tile import Tile
from arches_controlled_lists.datatypes.datatypes import ReferenceDataType
from arches_controlled_lists.models import ListItemValue

from manuspectrum.iiif.sources import canvas_label, manifest_json
from manuspectrum.utils.iiif_tools import CanvasIIIF
from manuspectrum.utils.role_links import role_node
from manuspectrum.utils.roles import ROLES
from manuspectrum.views.explorer.values import rewrite_legacy_url
from manuspectrum.views.summary_service import GraphIndex

SYMBOL = re.compile(r"^[A-Z][a-z]?$")
BAND = re.compile(r"^(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>nm|µm|um|cm-1|cm⁻¹|keV|eV)$")
VIDEO = re.compile(r"(?<![A-Za-z])video(?![A-Za-z])", re.I)
TRAILING = re.compile(r"[-_](?P<symbol>[A-Z][a-z]?)(?:-lim\d+)?$")
DECONV = "deconv"

ELEMENT_DISTRIBUTION = "Element distribution"
SPECTRAL_BAND = "Spectral band"
PHOTOGRAPHIC_REFERENCE = "Photographic reference"
DECONVOLUTION = "Deconvolution / fitting"

UNIT_ALIASES = {"um": "µm", "cm-1": "cm⁻¹"}
UNIT_ITEMS = {
    "nm": "Nanometre",
    "µm": "Micrometre",
    "cm⁻¹": "Reciprocal centimetre",
    "keV": "Kiloelectronvolt",
    "eV": "Electronvolt",
}

LAYER_ROLES = tuple(key for key in ROLES if key.startswith("layer_"))
MANIFEST_ROLE = "imaging"


class ImagingLayersError(Exception):
    """The proposal cannot be computed."""


class ImagingLayersConfigError(ImagingLayersError):
    """A node or a list item the rule names is missing or ambiguous in the model."""


class ManifestUnreadableError(ImagingLayersError):
    """The manifest of a tile cannot be read."""


@dataclass(frozen=True)
class Proposal:
    """What a label implies: the content kind (English prefLabel), the element symbols, the band and the processing."""

    content: str
    elements: tuple[str, ...]
    band: tuple[float, str] | None
    processing: str | None


def normalise_unit(unit):
    """The spelling of a unit the list is keyed on (``um`` → ``µm``, ``cm-1`` → ``cm⁻¹``)."""
    return UNIT_ALIASES.get(unit, unit)


def propose(label):
    """The ``Proposal`` of a canvas label, None when nothing can be read from it.

    Order: bare symbol, band, video frame, trailing symbol. A trailing symbol
    is deconvolved when the label says ``deconv`` anywhere, in any case.
    """
    label = (label or "").strip()
    if not label:
        return None
    if SYMBOL.match(label):
        return Proposal(ELEMENT_DISTRIBUTION, (label,), None, None)
    band = BAND.match(label)
    if band:
        value = float(band["value"].replace(",", "."))
        return Proposal(SPECTRAL_BAND, (), (value, normalise_unit(band["unit"])), None)
    if VIDEO.search(label):
        return Proposal(PHOTOGRAPHIC_REFERENCE, (), None, None)
    trailing = TRAILING.search(label)
    if trailing:
        processing = DECONVOLUTION if DECONV in label.lower() else None
        return Proposal(ELEMENT_DISTRIBUTION, (trailing["symbol"],), None, processing)
    return None


def layer_nodes():
    """``{role: NodeInfo}`` of the layer nodes; raises when the model lacks one."""
    nodes = {}
    for role in LAYER_ROLES:
        slug, alias = ROLES[role]
        node = role_node(slug, alias)
        if node is None:
            raise ImagingLayersConfigError(f"node {slug}.{alias} not found")
        nodes[role] = node
    return nodes


class ListResolver:
    """List items of the layer nodes by English label, each read once.

    The list of a node is the ``controlledList`` of its configuration.
    """

    def __init__(self):
        self._items = {}

    @staticmethod
    def _list_of(role):
        slug, alias = ROLES[role]
        index = GraphIndex.for_slug(slug)
        list_id = index.lists.get(alias) if index else None
        if not list_id:
            raise ImagingLayersConfigError(f"node {slug}.{alias} has no list")
        return list_id

    def _find(self, role, valuetype, text):
        key = (role, valuetype, text)
        if key not in self._items:
            found = set(
                ListItemValue.objects.filter(
                    list_item__list_id=self._list_of(role),
                    valuetype_id=valuetype,
                    language_id="en",
                    value=text,
                ).values_list("list_item_id", flat=True)
            )
            if len(found) > 1:
                raise ImagingLayersConfigError(
                    f"{text!r} is ambiguous in the list of {role}"
                )
            self._items[key] = str(found.pop()) if found else None
        return self._items[key]

    def item(self, role, label):
        """Id of the item whose English prefLabel is *label*; raises when absent or ambiguous."""
        found = self._find(role, "prefLabel", label)
        if found is None:
            raise ImagingLayersConfigError(f"{label!r} is not in the list of {role}")
        return found

    def element(self, symbol):
        """Id of the element whose English altLabel is *symbol*, None when the list has none."""
        return self._find("layer_elements", "altLabel", symbol)


def manifest_url(value):
    """The URL a manifest value stores (a string, a ``{"url"}`` dict or a list of one), None when empty."""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("url")
    return value if isinstance(value, str) and value else None


def canvases(manifest_value):
    """``[(canvas id as stored in the manifest, label)]`` of a manifest tile value.

    The manifest is fetched at ``rewrite_legacy_url`` of its stored URL; ids are
    raw: the tile stores them as the manifest writes them, and the Explorer
    rewrites legacy hosts when it reads.
    """
    url = manifest_url(manifest_value)
    manifest = manifest_json(rewrite_legacy_url(url)) if url else None
    if not isinstance(manifest, dict):
        raise ManifestUnreadableError(f"manifest {url!r} cannot be read")
    if CanvasIIIF.detect_version(manifest) == 3:
        raw = manifest.get("items") or []
    else:
        raw = ((manifest.get("sequences") or [{}])[0] or {}).get("canvases") or []
    return [
        (canvas.get("id") or canvas.get("@id"), canvas_label(canvas.get("label")))
        for canvas in raw
        if canvas.get("id") or canvas.get("@id")
    ]


@dataclass(frozen=True)
class PlannedLayer:
    """A tile to create: the canvas, its position, and the list item ids of its proposal."""

    position: int
    canvas: str
    label: str
    items: dict


@dataclass
class Plan:
    """The tiles of one manifest tile: to create, already there, unreadable, and tiles of a canvas no longer in the manifest."""

    resource_id: object
    manifest_tile_id: object
    proposed: list = field(default_factory=list)
    existing: int = 0
    skipped: list = field(default_factory=list)
    orphans: list = field(default_factory=list)


def _items_of(proposal, resolver):
    """List item ids of a proposal, None when an element symbol is not in the list."""
    elements = []
    for symbol in proposal.elements:
        item = resolver.element(symbol)
        if item is None:
            return None
        elements.append(item)
    items = {"content": resolver.item("layer_content", proposal.content)}
    if elements:
        items["elements"] = elements
    if proposal.band:
        value, unit = proposal.band
        items["band_value"] = value
        items["unit"] = resolver.item("layer_band_unit", UNIT_ITEMS[unit])
    if proposal.processing:
        items["method"] = resolver.item("layer_method", proposal.processing)
    return items


def plan(resource_id, manifest_tile, resolver=None):
    """The ``Plan`` of the layers of an imaging manifest tile.

    A canvas that has a layer tile under *manifest_tile* (matched on
    ``rewrite_legacy_url`` of both ids) is counted and never planned again; a
    tile whose canvas is not in the manifest is listed as an orphan and never
    deleted.
    """
    resolver = resolver or ListResolver()
    nodes = layer_nodes()
    manifest_node = role_node(*ROLES[MANIFEST_ROLE])
    if manifest_node is None:
        raise ImagingLayersConfigError("the imaging manifest node is not found")
    found = canvases(manifest_tile.data.get(str(manifest_node.nodeid)))
    stored = {}
    canvas_node = str(nodes["layer_canvas"].nodeid)
    for tile in TileModel.objects.filter(
        nodegroup_id=nodes["layer_canvas"].nodegroup_id,
        parenttile_id=manifest_tile.pk,
    ).order_by("sortorder", "tileid"):
        canvas = (tile.data or {}).get(canvas_node)
        stored.setdefault(rewrite_legacy_url(canvas or ""), tile.pk)
    result = Plan(resource_id, manifest_tile.pk)
    known = set()
    for position, (canvas, label) in enumerate(found):
        key = rewrite_legacy_url(canvas)
        known.add(key)
        if key in stored:
            result.existing += 1
            continue
        proposal = propose(label)
        items = _items_of(proposal, resolver) if proposal else None
        if items is None:
            result.skipped.append((position, canvas, label))
        else:
            result.proposed.append(PlannedLayer(position, canvas, label, items))
    result.orphans = [pk for key, pk in stored.items() if key not in known]
    return result


def _reference(*item_ids):
    return ReferenceDataType().transform_value_for_tile(list(item_ids))


def write(plan, resource=None):
    """Create the tiles of *plan* under its manifest tile, without a user, a request or an index.

    The tile holds every node of the layer group, empty but for the proposed
    values and the stored canvas and label. The caller indexes the resource.
    """
    nodes = layer_nodes()
    node = {role: str(info.nodeid) for role, info in nodes.items()}
    nodegroup_id = nodes["layer_canvas"].nodegroup_id
    for layer in plan.proposed:
        data = {nodeid: None for nodeid in node.values()}
        data[node["layer_canvas"]] = layer.canvas
        data[node["layer_label"]] = layer.label
        data[node["layer_content"]] = _reference(layer.items["content"])
        if "elements" in layer.items:
            data[node["layer_elements"]] = _reference(*layer.items["elements"])
        if "band_value" in layer.items:
            data[node["layer_band_value"]] = layer.items["band_value"]
            data[node["layer_band_unit"]] = _reference(layer.items["unit"])
        if "method" in layer.items:
            data[node["layer_method"]] = _reference(layer.items["method"])
        tile = Tile(
            tileid=uuid.uuid4(),
            resourceinstance_id=plan.resource_id,
            nodegroup_id=nodegroup_id,
            parenttile_id=plan.manifest_tile_id,
            data=data,
            sortorder=layer.position,
        )
        tile.save(user=None, request=None, index=False, resource=resource)

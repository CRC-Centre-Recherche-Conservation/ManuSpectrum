"""The OpenFreeMap basemap of the Arches maps.

The `streets` basemap row of Arches' `map_layers` carries the Positron style of
OpenFreeMap, drawn from the vector tiles of one `openfreemap` row of
`map_sources`. Positron is the only basemap: there is no satellite layer.

`openfreemap_positron_layers.json` (in `constants/`) is the `layers` array of
https://tiles.openfreemap.org/styles/positron as served on 2026-10-13, with the
layers' `source` renamed from `openmaptiles` to `openfreemap`. The style's other
source (`ne2_shaded`, a raster no layer uses) is not carried. The style is a fork
of openmaptiles/positron-gl-style (code BSD-3-Clause, design CC BY 4.0, derived
from CartoDB Basemaps, CC BY 3.0); the credit is in `NOTICE`, the attribution
shown on the map is `OPENFREEMAP_SOURCE["attribution"]`. A later change of the
style is a new data migration: the rows are written from this module.

`SPRITES_URL` and `GLYPHS_URL` are the style's own `sprite` and `glyphs`. The
sprite path is versioned by OpenFreeMap (`ofm_f384`); the System Settings tile
of each node wins over `settings.MAPBOX_SPRITES` / `MAPBOX_GLYPHS`.

`core_map_rows()` reads the map rows Arches installs, as left by its migrations
(`0010_4_1_0` deletes the `mapzen` rows `db_data.sql` still inserts). It serves
`export_pkg` and the checks; data migration 0013 carries its own frozen copy and
a test pins the two together.
"""

import json
import re
from pathlib import Path

import arches

CORE_DATA_SQL = Path(arches.__file__).parent / "db" / "dml" / "db_data.sql"
LAYERS_FILE = Path(__file__).parent / "constants" / "openfreemap_positron_layers.json"

SPRITES_NODE_ID = "0e900254-4148-11e7-9902-c4b301baab9f"
GLYPHS_NODE_ID = "0e90031e-4148-11e7-a176-c4b301baab9f"

OPENFREEMAP_SOURCE_NAME = "openfreemap"
STREETS_LAYER_NAME = "streets"
SATELLITE_LAYER_NAME = "satellite"
RETIRED_MAPZEN = "mapzen"

SPRITES_URL = "https://tiles.openfreemap.org/sprites/ofm_f384/ofm"
GLYPHS_URL = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf"
MAPBOX_SPRITES_URL = "mapbox://sprites/mapbox/basic-v9"
MAPBOX_GLYPHS_URL = "mapbox://fonts/mapbox/{fontstack}/{range}.pbf"

OPENFREEMAP_SOURCE = {
    "type": "vector",
    "url": "https://tiles.openfreemap.org/planet",
    "attribution": (
        '<a href="https://openfreemap.org" target="_blank">OpenFreeMap</a> '
        '<a href="https://www.openmaptiles.org/" target="_blank">&copy; OpenMapTiles</a> '
        'Data from <a href="https://www.openstreetmap.org/copyright" '
        'target="_blank">OpenStreetMap</a>'
    ),
}


def positron_layers():
    """A fresh copy of the vendored Positron layer definitions."""
    return json.loads(LAYERS_FILE.read_text(encoding="utf-8"))


def references_source(layerdefinitions, source_name):
    """Whether one of the layer definitions draws from the map source."""
    if not isinstance(layerdefinitions, list):
        return False
    return any(
        isinstance(layer, dict) and layer.get("source") == source_name
        for layer in layerdefinitions
    )


def needs_mapbox(source):
    """Whether a map source or setting value names a `mapbox://` URL, which needs a
    Mapbox token."""
    return "mapbox://" in json.dumps(source)


def core_map_rows():
    """({layer name: definitions}, {source name: source}) of Arches' own
    `db_data.sql`, minus the `mapzen` rows its migration `0010_4_1_0` deletes."""
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
        {n: json.loads(b) for n, b in layers if n != RETIRED_MAPZEN},
        {n: json.loads(b) for n, b in sources if n != RETIRED_MAPZEN},
    )

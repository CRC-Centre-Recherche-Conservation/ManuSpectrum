"""X-ray line and absorption-edge table for the XRF lens, built from XrayDB.

The table is generated once and versioned (``TABLE_PATH``); the app never
imports xraydb. A *source* is any object exposing:

- ``version``: the library version string;
- ``symbol(z)``: the element symbol of atomic number ``z``;
- ``lines(symbol)``: ``{name: (energy_eV, intensity, initial_level)}``;
- ``edges(symbol)``: ``{name: energy_eV}``.

Energies are stored in keV to 3 decimals, intensities to 3 significant
digits. Only elements Z 11-92 and lines at or above ``MIN_LINE_KEV`` are kept;
edges are limited to ``EDGE_NAMES`` at or above the same floor.
"""

import json
from pathlib import Path

Z_MIN = 11
Z_MAX = 92
MIN_LINE_KEV = 0.9
EDGE_NAMES = ("K", "L1", "L2", "L3", "M1", "M2", "M3", "M4", "M5")
LICENCE = "CC0 1.0"
CITATION = "Elam, Ravel & Sieber, Radiat. Phys. Chem. 63 (2002) 121"
PINNED_VERSION = "4.5.8"
INSTALL_HINT = (
    "pip install --target /tmp/xraydb-lib xraydb==%s, then run the command "
    "with PYTHONPATH=/tmp/xraydb-lib (xraydb pulls scipy and SQLAlchemy and "
    "is not a project dependency; keep it out of the shared venv)."
) % PINNED_VERSION

TABLE_PATH = (
    Path(__file__).resolve().parent.parent
    / "src/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/xray-lines.json"
)


def _kev(energy_ev):
    return round(energy_ev / 1000.0, 3)


def _significant(value):
    return float(f"{value:.3g}")


def build_table(source):
    """Return the line table as a plain dict, from an injected source."""
    elements = {}
    for z in range(Z_MIN, Z_MAX + 1):
        symbol = source.symbol(z)
        lines = {}
        for name, (energy_ev, intensity, initial) in source.lines(symbol).items():
            energy = _kev(energy_ev)
            if energy < MIN_LINE_KEV:
                continue
            lines[name] = [energy, _significant(intensity), initial]
        edges = {}
        source_edges = source.edges(symbol)
        for name in EDGE_NAMES:
            if name not in source_edges:
                continue
            energy = _kev(source_edges[name])
            if energy >= MIN_LINE_KEV:
                edges[name] = energy
        elements[symbol] = {"z": z, "lines": lines, "edges": edges}
    return {
        "source": f"XrayDB {source.version} ({LICENCE}) — {CITATION}",
        "version": source.version,
        "elements": elements,
    }


def dumps(table):
    """Serialise compactly with sorted keys: byte-stable for ``--check``."""
    return (
        json.dumps(table, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    )


class XrayDBSource:
    """Adapter over the xraydb module (imported by ``xraydb_source``)."""

    def __init__(self, module):
        self._db = module
        self.version = module.__version__

    def symbol(self, z):
        return self._db.atomic_symbol(z)

    def lines(self, symbol):
        return {
            name: (line.energy, line.intensity, line.initial_level)
            for name, line in self._db.xray_lines(symbol).items()
        }

    def edges(self, symbol):
        return {name: edge.energy for name, edge in self._db.xray_edges(symbol).items()}


def xraydb_source():
    """Import xraydb lazily; raises ImportError when it is not installed."""
    import xraydb

    return XrayDBSource(xraydb)

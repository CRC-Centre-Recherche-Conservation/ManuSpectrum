"""Oracle for the expected values of the measurement-file fixtures.

A documentation tool: tests and project code never import it. It reads a
fixture with an independent open library and writes the result, in our column
names and x-ascending order, into `expected.json` next to it, keyed by the
fixture path relative to this directory.

    pip install brukeropus==1.4.3 pyASDReader==1.2.3 spc-spectra==0.4.0 pyteomics numpy
    python oracle.py <format> <fixture path>      # format: spc

An entry holds `columns`, `rows`, `head` and `tail` (5 rows each), `sums` (per
column), `content_preset` and `oracle` (library and version). An entry may also
carry `"forbidden": [str]`, strings that must not occur in any fact value; the
tool keeps the list of an existing entry. Each library is imported inside its
format's function.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
EXPECTED = HERE / "expected.json"


def _entry(columns, rows, preset, oracle):
    return {
        "columns": columns,
        "rows": len(rows),
        "head": [list(r) for r in rows[:5]],
        "tail": [list(r) for r in rows[-5:]],
        "sums": [sum(r[i] for r in rows) for i in range(len(columns))],
        "content_preset": preset,
        "oracle": oracle,
    }


def spc(path):
    """Galactic SPC through spc-spectra: x by fxtype, y as stored."""
    import spc_spectra
    from importlib.metadata import version

    f = spc_spectra.File(str(path))
    x, y = [float(v) for v in f.x], [float(v) for v in f.sub[0].y]
    rows = list(zip(x, y))
    if rows[0][0] > rows[-1][0]:
        rows.reverse()
    names = {
        13: ("raman_shift_cm-1", "raman"),
        1: ("wavenumber_cm-1", None),
        3: ("wavelength_nm", None),
    }
    xname, preset = names.get(f.fxtype, ("x", None))
    return _entry(
        [xname, "intensity"], rows, preset, f"spc-spectra {version('spc-spectra')}"
    )


FORMATS = {"spc": spc}


def main(argv):
    if len(argv) != 3 or argv[1] not in FORMATS:
        sys.exit(f"usage: python oracle.py <{'|'.join(FORMATS)}> <fixture path>")
    path = Path(argv[2]).resolve()
    key = path.relative_to(HERE.resolve()).as_posix()
    store = json.loads(EXPECTED.read_text()) if EXPECTED.exists() else {}
    entry = FORMATS[argv[1]](path)
    if "forbidden" in store.get(key, {}):
        entry["forbidden"] = store[key]["forbidden"]
    store[key] = entry
    EXPECTED.write_text(json.dumps(store, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    main(sys.argv)

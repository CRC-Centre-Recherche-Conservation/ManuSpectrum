"""Oracle for the expected values of the measurement-file fixtures.

A documentation tool: tests and project code never import it. It reads a
fixture with an independent open library and writes the result, in our column
names and x-ascending order, into `expected.json` next to it, keyed by the
fixture path relative to this directory.

    pip install brukeropus==1.4.3 pyASDReader==1.2.3 spc-spectra==0.4.0 pyteomics lxml numpy
    python oracle.py <format> <fixture path>      # format: spc, opus, asd, mzxml

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


_OPUS_KEYS = {"AB": "a", "TR": "t", "RFL": "r", "RF": "r", "R": "r"}
_OPUS_COLUMNS = {
    "a": ("absorbance", "ftir"),
    "t": ("transmittance", None),
    "r": ("reflectance", "ftir_reflection"),
}


def opus(path):
    """Bruker OPUS through brukeropus: the result block named by `PLF`, x sorted.

    Prints the history text and the sample, form and path parameters, to be
    pinned by hand as `forbidden`.
    """
    from brukeropus import read_opus
    from importlib.metadata import version

    o = read_opus(str(path))
    plf = o.params.plf if "plf" in o.params.keys() else ""
    key = _OPUS_KEYS[plf]
    block = getattr(o, key)
    rows = sorted(zip((float(v) for v in block.x), (float(v) for v in block.y)))
    print("blocks:", o.data_keys, "PLF:", repr(plf))
    for code in ("snm", "sfm", "exp", "xpp"):
        if code in o.params.keys():
            print(code, repr(getattr(o.params, code)))
    print("history:", repr(getattr(o, "history", None)))
    name, preset = _OPUS_COLUMNS[key]
    return _entry(
        ["wavenumber_cm-1", name], rows, preset, f"brukeropus {version('brukeropus')}"
    )


def asd(path):
    """ASD FieldSpec through pyASDReader: target `digitalNumber`, white
    reference `referenceData.spectra`.

    Prints the comment and the reference description, to be pinned by hand as
    `forbidden`.
    """
    import logging
    import os
    import tempfile
    from importlib.metadata import version

    logging.disable(logging.CRITICAL)
    # pyASDReader writes an `asd_reader_*.log` file in the working directory
    os.chdir(tempfile.mkdtemp())
    from pyASDReader import ASDFile

    f = ASDFile(str(path))
    rows = [
        (float(w), float(t), float(r))
        for w, t, r in zip(f.wavelengths, f.digitalNumber, f.referenceData.spectra)
    ]
    print("comment:", repr(f.metadata.comments))
    print("reference description:", repr(f.referenceFileHeader.referenceDescription))
    return _entry(
        ["wavelength_nm", "target_dn", "white_reference_dn"],
        rows,
        "fors",
        f"pyASDReader {version('pyASDReader')}",
    )


def mzxml(path):
    """mzXML through pyteomics (the byte-offset index is not read): the scans'
    m/z and intensity arrays, intensities summed when every scan has the
    identical m/z array.

    Prints the `parentFile` names, the operator and contact names and the
    `dataProcessing` comments, to be pinned by hand as `forbidden`.
    """
    import xml.etree.ElementTree as ET
    from importlib.metadata import version

    from pyteomics import mzxml as reader

    with reader.MzXML(str(path), use_index=False) as source:
        scans = [(list(s["m/z array"]), list(s["intensity array"])) for s in source]
    grid = scans[0][0]
    if any(mz != grid for mz, _ in scans):
        sys.exit("the scans are on different m/z grids")
    rows = [
        (float(mz), float(sum(float(s[1][i]) for s in scans)))
        for i, mz in enumerate(grid)
    ]
    for node in ET.parse(path).getroot().iter():
        tag = node.tag.rpartition("}")[2]
        if tag in ("parentFile", "operator", "contact", "comment"):
            print(tag, node.attrib, (node.text or "").strip())
    return _entry(
        ["mz", "intensity"], rows, "mass_spec", f"pyteomics {version('pyteomics')}"
    )


FORMATS = {"spc": spc, "opus": opus, "asd": asd, "mzxml": mzxml}


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

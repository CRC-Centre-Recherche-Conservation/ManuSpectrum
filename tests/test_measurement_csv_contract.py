"""The bare CSV contract, pinned on both XY readers.

``tests/fixtures/measurement_files/contract/`` holds one synthetic CSV per
preset, written by ``write_csv``, and ``cases.json`` with the series
``read_series`` draws from each. ``media/js/utils/measurement-csv-contract.spec.js``
asserts that the browser reader draws the same curves. ``MS_WRITE_CONTRACT=1``
rewrites the committed files.
"""

import json
import math
import os

from arches.app.utils.file_validator import FileValidator
from django.test import SimpleTestCase

from manuspectrum.constants.xy_presets import XY_PRESETS
from manuspectrum.measurement_files.converters.base import Series
from manuspectrum.measurement_files.converters.csv_writer import check_csv, write_csv
from manuspectrum.utils.spectrum_preview import read_series

CONTRACT = os.path.join(
    os.path.dirname(__file__), "fixtures", "measurement_files", "contract"
)
ROWS = 64


def _grid(start, step):
    return [round(start + step * i, 6) for i in range(ROWS)]


def _peak(x, centre, width, height):
    return height * math.exp(-(((x - centre) / width) ** 2))


def _series(key):
    if key == "xrf":
        x = _grid(-1.2, 0.15)
        rows = [(v, round(40 + _peak(v, 6.4, 0.8, 900) + 5 * v, 6)) for v in x]
        columns = ("energy_keV", "counts")
    elif key == "xrf_channel":
        x = _grid(0, 16)
        rows = [(v, round(30 + _peak(v, 400, 90, 800), 6)) for v in x]
        columns = ("channel", "counts")
    elif key == "ftir":
        x = _grid(650, 60)
        rows = [(v, round(0.05 + _peak(v, 1700, 250, 0.8), 6)) for v in x]
        columns = ("wavenumber_cm-1", "absorbance")
    elif key == "ftir_reflection":
        x = _grid(650, 60)
        rows = [(v, round(0.9 - _peak(v, 1700, 250, 0.5), 6)) for v in x]
        columns = ("wavenumber_cm-1", "reflectance")
    elif key == "fors":
        x = _grid(380, 6)
        rows = [
            (
                v,
                round(800 + 3 * (v - 380) - _peak(v, 560, 40, 300), 6),
                round(3000 + 2 * (v - 380), 6),
            )
            for v in x
        ]
        columns = ("wavelength_nm", "target_dn", "white_reference_dn")
    elif key == "raman":
        x = _grid(100, 50)
        rows = [(v, round(200 + _peak(v, 1085, 40, 5000), 6)) for v in x]
        columns = ("raman_shift_cm-1", "intensity")
    elif key == "mass_spec":
        x = _grid(100.5, 2.25)
        rows = [
            (v, round(_peak(v, 150, 6, 1e5) + 50 * (1 + i % 3), 6))
            for i, v in enumerate(x)
        ]
        rows[0] = (rows[0][0], 1e-07)
        columns = ("mz", "intensity")
    else:
        raise KeyError(key)
    return Series(columns=columns, rows=tuple(rows))


KEYS = (
    "xrf",
    "xrf_channel",
    "ftir",
    "ftir_reflection",
    "fors",
    "raman",
    "mass_spec",
)


def _build():
    """Return ``{file name: bytes}`` for the CSVs and the case list."""
    files, cases = {}, []
    for key in KEYS:
        name = f"{key}.csv"
        files[name] = write_csv(_series(key))
        config = XY_PRESETS[key]["config"]
        path = os.path.join(CONTRACT, name)
        cases.append({"file": name, "presetKey": key, "config": config, "path": path})
    return files, cases


def _expected(cases, files):
    out = []
    for case in cases:
        path = case["path"]
        if os.environ.get("MS_WRITE_CONTRACT") == "1":
            os.makedirs(CONTRACT, exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(files[case["file"]])
        entry = {k: v for k, v in case.items() if k != "path"}
        entry["expected"] = read_series(path, case["config"])
        out.append(entry)
    return out


class ContractFilesTests(SimpleTestCase):
    def test_contract_files_are_current(self):
        files, cases = _build()
        cases = _expected(cases, files)
        rendered = json.dumps(cases, indent=2, ensure_ascii=False) + "\n"
        cases_path = os.path.join(CONTRACT, "cases.json")
        if os.environ.get("MS_WRITE_CONTRACT") == "1":
            with open(cases_path, "w", encoding="utf-8") as handle:
                handle.write(rendered)
        hint = "Run with MS_WRITE_CONTRACT=1 to regenerate the contract files."
        for name, data in files.items():
            with open(os.path.join(CONTRACT, name), "rb") as handle:
                self.assertEqual(handle.read(), data, f"{name} is stale. {hint}")
        with open(cases_path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), rendered, f"cases.json is stale. {hint}")

    def test_each_contract_file_passes_arches_and_the_checker(self):
        for key in KEYS:
            with self.subTest(preset=key):
                with open(os.path.join(CONTRACT, f"{key}.csv"), "rb") as handle:
                    data = handle.read()
                self.assertEqual(
                    FileValidator().test_unknown_filetypes(data, "csv"), []
                )
                self.assertEqual(check_csv(data), ())

    def test_the_series_carry_a_negative_x_and_an_exponent(self):
        files, _ = _build()
        self.assertTrue(files["xrf.csv"].split(b"\n")[1].startswith(b"-1.2,"))
        self.assertIn(b",1e-07\n", files["mass_spec.csv"])

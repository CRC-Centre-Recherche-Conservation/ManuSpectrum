import uuid

from django.test import SimpleTestCase

from manuspectrum.utils.file_pairs import pair
from manuspectrum.views.explorer.values import file_entries


def entry(file_id, name, **extra):
    return {"file_id": file_id, "name": name, **extra}


class PairTests(SimpleTestCase):
    def test_source_link_wins_over_names(self):
        entries = [
            entry("r", "scan.mca"),
            entry("c", "other.csv", msSourceFileId="r"),
            entry("d", "scan.csv"),
        ]
        self.assertEqual(pair(entries), {"r": "c"})

    def test_exact_converter_name_before_base_name(self):
        entries = [
            entry("a", "x.csv"),
            entry("b", "x.0.csv"),
            entry("r", "x.0"),
        ]
        self.assertEqual(pair(entries), {"r": "b"})

    def test_base_name_case_ignored(self):
        self.assertEqual(
            pair([entry("r", "Scan.MCA"), entry("c", "scan.csv")]), {"r": "c"}
        )

    def test_unpaired_and_invalid_entries(self):
        entries = [entry("r", "lonely.mca"), entry("c", "x.csv"), {"name": "y"}, "z"]
        self.assertEqual(pair(entries), {})
        self.assertEqual(pair(None), {})

    def test_source_to_missing_file_ignored(self):
        self.assertEqual(pair([entry("c", "x.csv", msSourceFileId="nope")]), {})

    def test_file_entries_follow_pairs(self):
        raw, csv = (str(uuid.uuid4()) for _ in range(2))
        entries = [
            entry(raw, "unrelated.mca"),
            entry(csv, "converted.csv", msSourceFileId=raw),
        ]
        items = {
            i["id"]: i
            for i in file_entries(
                entries, language="en", configs={}, kind="measurement"
            )
        }
        self.assertEqual(items[raw]["pairedWith"], csv)
        self.assertEqual(items[csv]["pairedWith"], raw)

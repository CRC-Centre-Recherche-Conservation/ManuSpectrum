import base64
import struct
import tracemalloc
import zlib
from pathlib import Path

from django.test import SimpleTestCase

from manuspectrum.measurement_files.converters import UnreadableFile, mzxml
from manuspectrum.measurement_files.converters.registry import convert, detect

from .measurement_fixtures import assert_matches

NAME = "indores_msm/MALDI_Latin2055f1v.mzxml"
FIXTURE = Path(__file__).parent / "fixtures" / "measurement_files" / NAME


def peaks(mz, intensity, *, precision=32, zlib_level=None, count=None):
    code = "f" if precision == 32 else "d"
    pairs = [v for pair in zip(mz, intensity) for v in pair]
    raw = struct.pack(f">{len(pairs)}{code}", *pairs)
    attrs = f'precision="{precision}" byteOrder="network" pairOrder="m/z-int"'
    if zlib_level is not None:
        raw = zlib.compress(raw, zlib_level)
        attrs += ' compressionType="zlib"'
    return (
        f'<scan num="1" msLevel="1" peaksCount="{len(mz) if count is None else count}">'
        f"<peaks {attrs}>{base64.b64encode(raw).decode()}</peaks></scan>"
    )


def document(
    *scans, header="", ns="http://sashimi.sourceforge.net/schema_revision/mzXML_3.2"
):
    return (
        f'<?xml version="1.0" encoding="ISO-8859-1"?><mzXML xmlns="{ns}">'
        f"<msRun>{header}{''.join(scans)}</msRun></mzXML>"
    ).encode()


MZ = [100.5, 101.25, 102.0, 103.75]
INTENSITY = [1.0, 2.5, 0.0, 4.0]


class MzxmlTests(SimpleTestCase):
    def test_reads_the_msm_maldi_file(self):
        data = FIXTURE.read_bytes()
        reading = mzxml.read(data)
        assert_matches(self, reading, NAME)
        self.assertEqual(reading.format, "mzxml")
        facts = {f.key: f for f in reading.facts}
        self.assertEqual(facts["channels"].value, "136825")
        self.assertIsNone(facts["channels"].unit)
        self.assertEqual(facts["spectral_range"].unit, "m/z")
        self.assertEqual(facts["spectral_range"].value, "699.8717651–4012.15332")
        self.assertEqual(detect(data), "mzxml")
        self.assertEqual(convert(data).format, "mzxml")

    def test_zlib_and_plain_peaks_agree(self):
        plain = mzxml.read(document(peaks(MZ, INTENSITY)))
        packed = mzxml.read(document(peaks(MZ, INTENSITY, zlib_level=9)))
        wide = mzxml.read(document(peaks(MZ, INTENSITY, precision=64, zlib_level=6)))
        self.assertEqual(plain.series, packed.series)
        self.assertEqual(plain.series, wide.series)
        self.assertEqual(plain.series.rows[1], (101.25, 2.5))
        self.assertEqual(plain.series.columns, ("mz", "intensity"))
        self.assertEqual(plain.content_preset, "mass_spec")

    def test_scans_on_one_grid_are_summed(self):
        nested = (
            peaks(MZ, [1, 1, 1, 1]).replace("</scan>", "")
            + peaks(MZ, [0.5, 0.5, 0.5, 0.5])
            + "</scan>"
        )
        reading = mzxml.read(document(peaks(MZ, INTENSITY), nested))
        self.assertEqual([r[1] for r in reading.series.rows], [2.5, 4.0, 1.5, 5.5])

    def test_different_grids_give_raw_only(self):
        other = [100.5, 101.25, 102.0, 104.0]
        reading = mzxml.read(document(peaks(MZ, INTENSITY), peaks(other, INTENSITY)))
        self.assertIsNone(reading.series)
        self.assertIsNone(reading.content_preset)
        self.assertEqual(reading.warnings, ("grids_differ",))

    def bomb(self, count, zeros):
        text = base64.b64encode(zlib.compress(bytes(zeros), 9)).decode()
        return document(
            f'<scan num="1" peaksCount="{count}"><peaks precision="32" '
            'byteOrder="network" pairOrder="m/z-int" compressionType="zlib">'
            f"{text}</peaks></scan>"
        )

    def test_zlib_bomb_is_malformed(self):
        with self.assertRaises(UnreadableFile) as caught:
            mzxml.read(self.bomb(2, 10 * 1024 * 1024))
        self.assertEqual(caught.exception.code, "malformed")

    def test_zlib_is_inflated_within_the_declared_size(self):
        data = self.bomb(1000, 6 * 1024 * 1024)
        tracemalloc.start()
        try:
            with self.assertRaises(UnreadableFile) as caught:
                mzxml.read(data)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual(caught.exception.code, "malformed")
        self.assertLess(peak, 1024 * 1024)

    def test_sizes_that_disagree_are_malformed(self):
        for scan in (
            peaks(MZ, INTENSITY, count=3),
            peaks(MZ, INTENSITY, count=5),
            peaks(MZ, INTENSITY, zlib_level=9, count=3),
            peaks(MZ, INTENSITY, zlib_level=9, count=5),
            peaks(MZ, INTENSITY, count=2_000_000),
            peaks(MZ, INTENSITY, count=0),
        ):
            with self.assertRaises(UnreadableFile) as caught:
                mzxml.read(document(scan))
            self.assertEqual(caught.exception.code, "malformed")

    def test_other_variants_are_refused(self):
        base = peaks(MZ, INTENSITY)
        for old, new in (
            ('byteOrder="network"', 'byteOrder="little"'),
            ('pairOrder="m/z-int"', 'pairOrder="int-m/z"'),
            ('precision="32"', 'precision="16"'),
        ):
            with self.assertRaises(UnreadableFile) as caught:
                mzxml.read(document(base.replace(old, new)))
            self.assertEqual(caught.exception.code, "unsupported_variant")

    def test_parent_file_path_is_never_copied(self):
        header = (
            '<parentFile fileName="file:///home/someone/raw/sample.raw" '
            'fileType="RAWData" fileSha1="0000"/>'
            '<msInstrument><msManufacturer category="msManufacturer" value="Acme"/>'
            '<msModel category="msModel" value="Flyer 2"/>'
            '<msIonisation category="msIonisation" value="MALDI"/>'
            '<msMassAnalyzer category="msMassAnalyzer" value="TOF"/>'
            '<msDetector category="msDetector" value="MCP"/>'
            '<software type="acquisition" name="Acquire" version="3.1"/>'
            '<operator first="Jane" last="Doe" email="jane@example.test"/>'
            "</msInstrument>"
            '<dataProcessing><software type="processing" name="Tool" version="1"/>'
            "<comment>private note</comment></dataProcessing>"
        )
        reading = mzxml.read(document(peaks(MZ, INTENSITY), header=header))
        facts = {f.key: f.value for f in reading.facts}
        self.assertEqual(facts["instrument"], "Acme Flyer 2")
        self.assertEqual(facts["ionisation"], "MALDI")
        self.assertEqual(facts["mass_analyzer"], "TOF")
        self.assertEqual(facts["detector"], "MCP")
        self.assertEqual(facts["acquisition_software"], "Acquire 3.1")
        for secret in ("someone", "sample.raw", "Jane", "Doe", "example.test", "note"):
            for value in facts.values():
                self.assertNotIn(secret, value)

    def test_entity_expansion_is_refused(self):
        bomb = (
            '<?xml version="1.0"?><!DOCTYPE mzXML ['
            '<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">'
            '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;">]><mzXML>&c;</mzXML>'
        ).encode()
        with self.assertRaises(UnreadableFile) as caught:
            mzxml.read(bomb)
        self.assertEqual(caught.exception.code, "malformed")

    def test_no_scan_is_malformed(self):
        with self.assertRaises(UnreadableFile) as caught:
            mzxml.read(document())
        self.assertEqual(caught.exception.code, "malformed")

    def test_repeated_mz_is_refused(self):
        with self.assertRaises(UnreadableFile) as caught:
            convert(document(peaks([1.0, 1.0], [1.0, 2.0])))
        self.assertEqual(caught.exception.code, "duplicate_x")


class MzxmlBoundsTests(SimpleTestCase):
    def test_the_sum_of_every_peaks_count_is_bounded_before_decoding(self):
        from unittest import mock

        from manuspectrum.measurement_files.converters.base import MAX_CHANNELS

        half = MAX_CHANNELS // 2 + 1
        scans = [
            f'<scan peaksCount="{half}"><peaks precision="32">AAAA</peaks></scan>'
        ] * 2
        with mock.patch.object(mzxml, "_decode", side_effect=AssertionError):
            with self.assertRaises(UnreadableFile) as caught:
                mzxml.read(document(*scans))
        self.assertEqual(caught.exception.code, "malformed")

    def test_the_grids_are_compared_as_each_scan_is_decoded(self):
        broken = '<scan peaksCount="2"><peaks precision="32">!!</peaks></scan>'
        reading = mzxml.read(
            document(
                peaks([1.0, 2.0], [1.0, 1.0]),
                peaks([1.0, 3.0], [1.0, 1.0]),
                broken,
            )
        )
        self.assertIsNone(reading.series)
        self.assertEqual(reading.warnings, ("grids_differ",))

    def test_scans_on_one_grid_are_summed(self):
        reading = mzxml.read(
            document(
                peaks([1.0, 2.0], [1.0, 2.0]),
                peaks([1.0, 2.0], [10.0, 20.0]),
            )
        )
        self.assertEqual(reading.series.rows, ((1.0, 11.0), (2.0, 22.0)))

    def test_an_empty_scan_is_skipped(self):
        empty = '<scan peaksCount="0"><peaks precision="32"></peaks></scan>'
        reading = mzxml.read(document(empty, peaks(MZ, INTENSITY)))
        self.assertEqual(len(reading.series.rows), 4)

    def test_a_file_of_empty_scans_alone_is_malformed(self):
        empty = '<scan peaksCount="0"><peaks precision="32"></peaks></scan>'
        with self.assertRaises(UnreadableFile) as caught:
            mzxml.read(document(empty))
        self.assertEqual(caught.exception.code, "malformed")

    def test_another_content_type_is_an_unsupported_variant(self):
        scan = peaks(MZ, INTENSITY).replace(
            'pairOrder="m/z-int"', 'contentType="m/z ruler"'
        )
        with self.assertRaises(UnreadableFile) as caught:
            mzxml.read(document(scan))
        self.assertEqual(caught.exception.code, "unsupported_variant")
        ok = peaks(MZ, INTENSITY).replace(
            'pairOrder="m/z-int"', 'contentType="m/z-int"'
        )
        self.assertEqual(len(mzxml.read(document(ok)).series.rows), 4)


class MzxmlRefusalTests(SimpleTestCase):
    def refused(self, data):
        with self.assertRaises(UnreadableFile) as caught:
            mzxml.read(data)
        return caught.exception.code

    def test_an_unknown_compression_is_an_unsupported_variant(self):
        scan = peaks(MZ, INTENSITY).replace(
            'byteOrder="network"', 'byteOrder="network" compressionType="lzma"'
        )
        self.assertEqual(self.refused(document(scan)), "unsupported_variant")

    def test_a_corrupt_zlib_stream_is_malformed(self):
        scan = peaks(MZ, INTENSITY, zlib_level=9)
        garbage = base64.b64encode(b"\x78\x9c" + b"\xff" * 30).decode()
        start = scan.index("</peaks>")
        text_start = scan.index(">", scan.index("<peaks")) + 1
        scan = scan[:text_start] + garbage + scan[start:]
        self.assertEqual(self.refused(document(scan)), "malformed")

    def test_another_root_element_is_malformed(self):
        self.assertEqual(self.refused(b'<?xml version="1.0"?><other/>'), "malformed")

    def test_a_scan_without_peaks_is_skipped(self):
        bare = '<scan num="9" msLevel="1"></scan>'
        reading = mzxml.read(document(bare, peaks(MZ, INTENSITY)))
        self.assertEqual(len(reading.series.rows), 4)
        self.assertEqual(self.refused(document(bare)), "malformed")

    def test_a_peaks_count_that_is_not_a_non_negative_integer_is_malformed(self):
        for count in ("many", "", "-2"):
            with self.subTest(count):
                scan = peaks(MZ, INTENSITY).replace(
                    'peaksCount="4"', f'peaksCount="{count}"'
                )
                self.assertEqual(self.refused(document(scan)), "malformed")

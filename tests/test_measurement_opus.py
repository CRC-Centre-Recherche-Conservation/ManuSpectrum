import struct

from django.test import SimpleTestCase

from manuspectrum.measurement_files.converters import UnreadableFile, opus, registry
from tests.measurement_fixtures import FIXTURES, assert_matches, expected

FTIR = "indores_albi/IR1_parchment.0"
SERS = "indores_albi/SERS_Ms29f57v_s1_785_01.spc.0"


def params(**values):
    out = b""
    for code, value in values.items():
        if isinstance(value, str):
            raw = value.encode("latin-1") + b"\x00"
            raw += b"\x00" * (-len(raw) % 4)
            out += code.encode() + b"\x00" + struct.pack("<hh", 2, len(raw) // 2) + raw
        elif isinstance(value, float):
            out += code.encode() + b"\x00" + struct.pack("<hhd", 1, 4, value)
        else:
            out += code.encode() + b"\x00" + struct.pack("<hhi", 0, 2, value)
    return out + b"END\x00" + struct.pack("<hh", 0, 0) + b"\x00" * 4


def type_word(a=0, b=0, c=0, d=0, e=0, f=0):
    return a | b << 2 | c << 4 | d << 10 | e << 17 | f << 19


def opus_file(blocks):
    """An OPUS file of invented values from (type fields, bytes) pairs."""
    start, entries, body = 24, b"", b""
    offset = start + 12 * len(blocks)
    for fields, raw in blocks:
        raw += b"\x00" * (-len(raw) % 4)
        entries += struct.pack("<3i", type_word(*fields), len(raw) // 4, offset)
        body += raw
        offset += len(raw)
    head = b"\x0a\x0a\xfe\xfe" + struct.pack("<diii", 920622.0, start, 40, len(blocks))
    return head + entries + body


def result(kind, ys, *, first=4000.0, last=400.0, **status):
    """A result data block and its data status block."""
    header = dict(DPF=1, NPT=len(ys), FXV=first, LXV=last, CSF=1.0, DXU="WN")
    header.update(DAT="01/02/2031", TIM="09:41:07.000 (GMT+1)")
    header.update(status)
    return [
        ((3, 3, 0, kind), struct.pack(f"<{len(ys)}f", *ys)),
        ((3, 3, 1, kind), params(**header)),
    ]


def synthetic(*results, plf="AB", **acquisition):
    blocks = [((0, 0, 3), params(PLF=plf, NSS=8, **acquisition))]
    for one in results:
        blocks += one
    return opus_file(blocks)


class OpusTests(SimpleTestCase):
    def test_reads_the_albi_ftir_spectrum(self):
        reading = registry.convert((FIXTURES / FTIR).read_bytes())
        self.assertEqual(reading.format, "opus")
        self.assertEqual(reading.content_preset, "ftir_reflection")
        assert_matches(self, reading, FTIR)
        facts = {f.key: f for f in reading.facts}
        self.assertEqual(facts["result_spectrum"].value, "RFL")
        self.assertEqual(facts["instrument"].value, "Alpha")
        self.assertEqual(facts["serial_number"].value, "1 04204")
        self.assertEqual(facts["resolution"].value, "4")
        self.assertEqual(facts["resolution"].unit, "cm-1")
        self.assertEqual(facts["sample_scans"].value, "128")
        self.assertEqual(facts["background_scans"].value, "128")
        self.assertEqual(facts["beam_splitter"].value, "KBr")
        self.assertEqual(facts["apodization"].value, "B3")
        self.assertEqual(facts["zero_filling"].value, "2")
        self.assertEqual(facts["source"].value, "MIR")
        self.assertEqual(facts["acquired_at"].value, "01/07/2016 10:14:13.690 (GMT+2)")
        self.assertEqual(facts["spectral_range"].value, "373.5542082–6996.957669")
        self.assertIn("h2o_compensation_not_applied", reading.warnings)
        self.assertIn("date_order_unknown", reading.warnings)

    def test_spc_0_sers_file_is_opus(self):
        data = (FIXTURES / SERS).read_bytes()
        self.assertEqual(registry.detect(data), "opus")
        with self.assertRaises(UnreadableFile) as caught:
            registry.convert(data)
        self.assertEqual(caught.exception.code, "unsupported_variant")

    def test_history_and_sample_name_are_never_copied(self):
        reading = registry.convert((FIXTURES / FTIR).read_bytes())
        forbidden = expected(FTIR)["forbidden"]
        self.assertIn("zone 1 parchemin", forbidden)
        self.assertGreater(len(forbidden), 3)
        for fact in reading.facts:
            for bad in forbidden:
                self.assertNotIn(bad, fact.value)
        data = (FIXTURES / FTIR).read_bytes()
        self.assertNotIn(
            b"zone 1 parchemin", b"".join(f.value.encode() for f in reading.facts)
        )
        self.assertIn(b"zone 1 parchemin", data)

    def test_ambiguous_result_without_plf(self):
        data = (FIXTURES / FTIR).read_bytes()
        self.assertEqual(data.count(b"RFL\x00"), 2)
        start = data.index(b"PLF\x00")
        blank = bytearray(data)
        blank[start + 8 : start + 12] = b"\x00\x00\x00\x00"
        with self.assertRaises(UnreadableFile) as caught:
            registry.convert(bytes(blank))
        self.assertEqual(caught.exception.code, "ambiguous_result")

    def test_plf_picks_the_result_among_several(self):
        data = synthetic(
            result(4, [0.1, 0.2, 0.3]), result(5, [0.9, 0.8, 0.7]), plf="TR"
        )
        reading = registry.convert(data)
        self.assertEqual(reading.series.columns, ("wavenumber_cm-1", "transmittance"))
        self.assertIsNone(reading.content_preset)
        self.assertEqual(reading.series.rows[0][0], 400.0)
        self.assertAlmostEqual(reading.series.rows[0][1], 0.7, places=6)

    def test_absorbance_and_single_result_without_plf(self):
        data = synthetic(result(4, [0.1, 0.2, 0.3]), plf="")
        reading = registry.convert(data)
        self.assertEqual(reading.series.columns, ("wavenumber_cm-1", "absorbance"))
        self.assertEqual(reading.content_preset, "ftir")
        self.assertEqual([r[0] for r in reading.series.rows], [400.0, 2200.0, 4000.0])

    def test_unlisted_result_type_is_unsupported(self):
        for data in (
            synthetic(result(6, [1.0, 2.0, 3.0]), plf=""),
            synthetic(result(4, [1.0, 2.0, 3.0]), plf="KM"),
            synthetic(result(4, [1.0, 2.0, 3.0], DXU="MIC")),
        ):
            with self.assertRaises(UnreadableFile) as caught:
                opus.read(data)
            self.assertEqual(caught.exception.code, "unsupported_variant")

    def test_scale_factor_and_water_compensation(self):
        data = synthetic(
            result(4, [1.0, 2.0, 3.0], CSF=2.0), TCL="H2Ocomp ([a], [b], {H2O=3});"
        )
        reading = opus.read(data)
        self.assertEqual([r[1] for r in reading.series.rows], [6.0, 4.0, 2.0])
        self.assertIn("h2o_compensation_not_applied", reading.warnings)
        plain = opus.read(synthetic(result(4, [1.0, 2.0, 3.0])))
        self.assertNotIn("h2o_compensation_not_applied", plain.warnings)

    def test_never_read_parameters_stay_out_of_facts(self):
        data = opus_file(
            [
                ((0, 0, 3), params(PLF="AB")),
                ((0, 0, 10), params(SNM="secret name", EXP="a.XPM")),
            ]
            + result(4, [1.0, 2.0, 3.0])
        )
        reading = opus.read(data)
        text = " ".join(f.value for f in reading.facts)
        self.assertNotIn("secret", text)
        self.assertNotIn("XPM", text)

    def test_truncated_and_broken_files(self):
        data = (FIXTURES / FTIR).read_bytes()
        for cut, code in ((10, "truncated"), (2000, "truncated"), (5000, "truncated")):
            with self.assertRaises(UnreadableFile) as caught:
                opus.read(data[:cut])
            self.assertEqual(caught.exception.code, code)
        for ys, kwargs, code in (
            ([1.0], {}, "too_few_points"),
            ([1.0, 2.0], {"first": 5.0, "last": 5.0}, "duplicate_x"),
            ([1.0, float("nan")], {}, "non_finite"),
        ):
            with self.assertRaises(UnreadableFile) as caught:
                opus.read(synthetic(result(4, ys, **kwargs)))
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(UnreadableFile) as caught:
            opus.read(synthetic(result(4, [1.0, 2.0], NPT=500000)))
        self.assertEqual(caught.exception.code, "truncated")
        with self.assertRaises(UnreadableFile) as caught:
            opus.read(synthetic(result(4, [1.0, 2.0], NPT=2000000)))
        self.assertEqual(caught.exception.code, "malformed")


class OpusOverlapTests(SimpleTestCase):
    def test_overlapping_blocks_are_refused_without_walking_them(self):
        from unittest import mock

        count = 4096
        start, region = 24, 24 + 12 * count
        entries = b"".join(
            struct.pack("<3i", type_word(0, 0, 3), 1024, region) for _ in range(count)
        )
        head = b"\x0a\x0a\xfe\xfe" + struct.pack("<diii", 920622.0, start, count, count)
        data = head + entries + bytes(4096)
        with mock.patch.object(opus, "_params", wraps=opus._params) as spy:
            with self.assertRaises(UnreadableFile) as caught:
                opus.read(data)
        self.assertEqual(caught.exception.code, "malformed")
        spy.assert_not_called()

    def test_two_adjacent_blocks_are_not_overlapping(self):
        reading = opus.read(synthetic(result(4, [1.0, 2.0, 3.0])))
        self.assertEqual(len(reading.series.rows), 3)


class OpusRefusalTests(SimpleTestCase):
    def refused(self, data):
        with self.assertRaises(UnreadableFile) as caught:
            registry.convert(data)
        self.assertEqual(caught.exception.format, "opus")
        return caught.exception.code

    def test_a_directory_that_cannot_be_right_is_malformed(self):
        good = synthetic(result(4, [1.0, 2.0, 3.0]))
        low_start = bytearray(good)
        struct.pack_into("<i", low_start, 12, 10)
        many = bytearray(good)
        struct.pack_into("<i", many, 20, 5000)
        negative = bytearray(good)
        struct.pack_into("<i", negative, 20, -1)
        for name, data in {
            "start inside the header": low_start,
            "too many blocks": many,
            "negative count": negative,
        }.items():
            with self.subTest(name):
                self.assertEqual(self.refused(bytes(data)), "malformed")

    def test_a_directory_longer_than_the_file_is_truncated(self):
        data = bytearray(synthetic(result(4, [1.0, 2.0, 3.0])))
        struct.pack_into("<i", data, 20, 4000)
        self.assertEqual(self.refused(bytes(data)), "truncated")

    def test_a_directory_entry_without_an_offset_ends_the_directory(self):
        data = bytearray(synthetic(result(4, [1.0, 2.0, 3.0])))
        status_entry = 24 + 12 * 2
        struct.pack_into("<i", data, status_entry + 8, 0)
        self.assertEqual(self.refused(bytes(data)), "malformed")

    def test_a_parameter_longer_than_its_block_is_malformed(self):
        broken = b"PLF\x00" + struct.pack("<hh", 2, 1000) + b"\x00" * 8
        data = opus_file([((0, 0, 3), broken)] + result(4, [1.0, 2.0, 3.0]))
        self.assertEqual(self.refused(data), "malformed")

    def test_a_number_parameter_too_short_for_its_type_is_malformed(self):
        for kind in (0, 1):
            with self.subTest(kind):
                short = b"NSS\x00" + struct.pack("<hh", kind, 1) + b"\x00" * 4
                data = opus_file([((0, 0, 3), short)] + result(4, [1.0, 2.0, 3.0]))
                self.assertEqual(self.refused(data), "malformed")

    def test_an_unknown_plf_is_an_unsupported_variant(self):
        data = synthetic(result(4, [1.0, 2.0, 3.0]), plf="XX")
        self.assertEqual(self.refused(data), "unsupported_variant")

    def test_a_plf_without_its_result_block_is_malformed(self):
        data = synthetic(result(4, [1.0, 2.0, 3.0]), plf="TR")
        self.assertEqual(self.refused(data), "malformed")

    def test_a_file_without_a_result_block_is_malformed(self):
        self.assertEqual(self.refused(synthetic(plf="")), "malformed")

    def test_a_result_without_its_status_block_is_malformed(self):
        data = opus_file(
            [((0, 0, 3), params(PLF="AB"))] + result(4, [1.0, 2.0, 3.0])[:1]
        )
        self.assertEqual(self.refused(data), "malformed")

    def test_a_status_block_missing_a_required_value_is_malformed(self):
        data = opus_file(
            [
                ((0, 0, 3), params(PLF="AB")),
                ((3, 3, 0, 4), struct.pack("<3f", 1.0, 2.0, 3.0)),
                ((3, 3, 1, 4), params(DPF=1, FXV=4000.0, LXV=400.0, DXU="WN")),
            ]
        )
        self.assertEqual(self.refused(data), "malformed")

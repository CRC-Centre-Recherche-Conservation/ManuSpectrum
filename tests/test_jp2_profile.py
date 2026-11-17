import io
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from PIL import Image

from manuspectrum.utils import jp2_profile


def encode(size=(400, 300), **options):
    buffer = io.BytesIO()
    Image.new("RGB", size, (120, 60, 30)).save(buffer, format="JPEG2000", **options)
    return buffer.getvalue()


def tiled(size=(400, 300), levels=6):
    return encode(size, tile_size=(256, 256), num_resolutions=levels)


class ReadProfileTests(SimpleTestCase):
    def test_reads_size_tiles_and_levels_from_the_headers(self):
        profile = jp2_profile.read_profile(io.BytesIO(tiled()))
        self.assertEqual((profile.width, profile.height), (400, 300))
        self.assertEqual((profile.tile_width, profile.tile_height), (256, 256))
        self.assertEqual(profile.resolution_levels, 6)
        self.assertEqual(profile.decomposition_levels, 5)
        self.assertEqual(profile.tile_pixels, 256 * 256)

    def test_a_file_without_tiles_is_one_tile(self):
        profile = jp2_profile.read_profile(io.BytesIO(encode(num_resolutions=3)))
        self.assertEqual(profile.tile_pixels, 400 * 300)
        self.assertEqual(profile.resolution_levels, 3)

    def test_reads_only_the_start_of_the_file(self):
        class Counting(io.BytesIO):
            total = 0

            def read(self, size=-1):
                data = super().read(size)
                self.total += len(data)
                return data

        stream = Counting(tiled((1200, 900)))
        jp2_profile.read_profile(stream)
        self.assertLess(stream.total, 1024)
        self.assertGreater(len(stream.getvalue()), 4 * stream.total)

    def test_refuses_what_is_not_a_jp2(self):
        for label, data in (
            ("text", b"hello" * 100),
            ("empty", b""),
            ("png", self.png()),
            ("raw codestream", tiled()[jp2_profile_start(tiled()) :]),
        ):
            with self.subTest(label):
                with self.assertRaises(jp2_profile.InvalidJp2):
                    jp2_profile.read_profile(io.BytesIO(data))

    def png(self):
        buffer = io.BytesIO()
        Image.new("RGB", (4, 4)).save(buffer, format="PNG")
        return buffer.getvalue()

    def test_refuses_a_truncated_file_wherever_it_stops(self):
        data = tiled()
        for cut in (5, 12, 20, 40, 80, jp2_profile_start(data) + 10):
            with self.subTest(cut=cut):
                with self.assertRaises(jp2_profile.InvalidJp2):
                    jp2_profile.read_profile(io.BytesIO(data[:cut]))

    def test_a_damaged_box_length_is_refused_not_raised(self):
        data = bytearray(tiled())
        data[12:16] = b"\xff\xff\xff\xff"
        with self.assertRaises(jp2_profile.InvalidJp2):
            jp2_profile.read_profile(io.BytesIO(bytes(data)))


class HeaderGuardTests(SimpleTestCase):
    def test_a_siz_shorter_than_its_fixed_part_is_refused_without_reading_on(self):
        data = bytearray(tiled())
        siz = data.index(b"\xff\x51")
        data[siz + 2 : siz + 4] = (4).to_bytes(2, "big")

        class Spy(io.BytesIO):
            total = 0

            def read(self, size=-1):
                chunk = super().read(size)
                self.total += len(chunk)
                return chunk

        stream = Spy(bytes(data) + b"\0" * 100_000)
        with self.assertRaises(jp2_profile.InvalidJp2):
            jp2_profile.read_profile(stream)
        self.assertLess(stream.total, 1024)

    def test_a_codestream_without_a_jp2_header_box_is_refused(self):
        data = tiled()
        start = data.index(b"jp2h") - 4
        length = int.from_bytes(data[start : start + 4], "big")
        without = data[:start] + data[start + length :]
        with self.assertRaises(jp2_profile.InvalidJp2):
            jp2_profile.read_profile(io.BytesIO(without))

    def test_a_jp2_header_box_after_the_codestream_does_not_count(self):
        data = tiled()
        start = data.index(b"jp2h") - 4
        length = int.from_bytes(data[start : start + 4], "big")
        moved = data[:start] + data[start + length :] + data[start : start + length]
        with self.assertRaises(jp2_profile.InvalidJp2):
            jp2_profile.read_profile(io.BytesIO(moved))


def jp2_profile_start(data):
    return data.index(b"jp2c") + 4


@override_settings(JP2_MIN_RESOLUTION_LEVELS=5, JP2_MAX_TILE_PIXELS=100_000)
class CheckUploadTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.object(jp2_profile, "LEVELS_CHECK_ABOVE_PIXELS", 10_000)
        patcher.start()
        self.addCleanup(patcher.stop)

    def check(self, data, name="plate.jp2"):
        refusal = jp2_profile.check_upload(name, io.BytesIO(data))
        return refusal and refusal.message

    def deposit(self, *files):
        return jp2_profile.check_deposit(
            [SimpleUploadedFile(name, data) for name, data in files]
        )

    def test_a_tiled_file_with_enough_levels_passes(self):
        self.assertIsNone(self.check(tiled()))

    def test_a_file_with_too_few_levels_is_refused(self):
        message = self.check(tiled(levels=2))
        self.assertIn('"plate.jp2"', message)
        self.assertIn("2 resolution levels, at least 5", message)

    def test_one_level_reads_in_the_singular(self):
        self.assertIn("1 resolution level, at least", self.check(tiled(levels=1)))

    def test_the_level_rule_spares_small_images(self):
        with mock.patch.object(jp2_profile, "LEVELS_CHECK_ABOVE_PIXELS", 1_000_000):
            self.assertIsNone(self.check(tiled(levels=2)))

    def test_a_file_of_one_huge_tile_is_refused(self):
        message = self.check(encode((500, 400), num_resolutions=6))
        self.assertIn("tiles of 0.2 MP (at most 0.1 MP)", message)
        self.assertIn("1024 × 1024 tiles", message)

    def test_a_grid_of_oversized_tiles_is_refused(self):
        with override_settings(JP2_MAX_TILE_PIXELS=20_000):
            data = encode((512, 256), tile_size=(256, 256), num_resolutions=6)
            self.assertIn("tiles of 0.1 MP", self.check(data))

    def test_a_grid_of_small_tiles_passes_however_large_the_image(self):
        with override_settings(JP2_MAX_TILE_PIXELS=70_000):
            data = encode((600, 600), tile_size=(256, 256), num_resolutions=6)
            self.assertIsNone(self.check(data))

    def test_a_tile_larger_than_the_image_counts_as_the_image(self):
        with override_settings(JP2_MAX_TILE_PIXELS=100_000):
            data = encode((200, 100), tile_size=(4096, 4096), num_resolutions=5)
            self.assertIsNone(self.check(data))

    def test_the_megapixels_round_up_so_a_refusal_never_reads_as_the_limit(self):
        self.assertEqual(jp2_profile._megapixels(20_400_000), "20.4")
        self.assertEqual(jp2_profile._megapixels(20_000_001), "20.1")
        self.assertEqual(jp2_profile._megapixels(20_000_000), "20.0")

    def test_the_thresholds_are_settings(self):
        with override_settings(JP2_MAX_TILE_PIXELS=1_000_000):
            self.assertIsNone(self.check(encode((500, 400), num_resolutions=6)))
        with override_settings(JP2_MIN_RESOLUTION_LEVELS=7):
            self.assertIn("at least 7", self.check(tiled(levels=6)))

    def test_a_fake_or_truncated_file_gets_a_message_not_an_exception(self):
        for data in (b"not a jp2" * 50, tiled()[:60]):
            with self.subTest(size=len(data)):
                self.assertIn(
                    "is not a valid JPEG 2000 file",
                    self.check(data, name="fake.jp2"),
                )

    def test_reads_an_uploaded_file_and_rewinds_it(self):
        upload = SimpleUploadedFile("plate.jp2", tiled(levels=2))
        self.assertIsNotNone(jp2_profile.check_upload(upload.name, upload))
        self.assertEqual(upload.tell(), 0)

    def test_the_name_is_escaped_in_every_message(self):
        name = "<img src=x onerror=1>.jp2"
        for label, data in (
            ("fake", b"nope" * 30),
            ("levels", tiled(levels=2)),
            ("tiles", encode((500, 400), num_resolutions=6)),
        ):
            with self.subTest(label):
                message = self.check(data, name=name)
                self.assertNotIn("<img", message)
                self.assertIn("&lt;img src=x onerror=1&gt;.jp2", message)

    def test_the_recommended_command_closes_the_deposit_message_once(self):
        message = self.deposit(("a.jp2", tiled(levels=2)), ("b.jp2", tiled(levels=1)))
        self.assertIn('"a.jp2"', message)
        self.assertIn('"b.jp2"', message)
        self.assertEqual(message.count(jp2_profile.RECOMMENDED_COMMAND), 1)
        self.assertTrue(message.endswith(jp2_profile.RECOMMENDED_COMMAND))

    def test_a_damaged_file_alone_gets_no_command(self):
        message = self.deposit(("fake.jp2", b"nope" * 30))
        self.assertNotIn(jp2_profile.RECOMMENDED_COMMAND, message)

    def test_a_good_deposit_has_no_message(self):
        self.assertIsNone(self.deposit(("a.jp2", tiled()), ("p.txt", b"hello")))

    def test_a_jp2_under_another_extension_is_refused(self):
        for name in ("plate.png", "plate.tif", "plate", "plate.j2k"):
            with self.subTest(name):
                message = self.deposit((name, tiled()))
                self.assertIn(f'"{name}" is a JPEG 2000 file', message)
                self.assertIn("rename it with the .jp2 extension", message)

    def test_other_files_are_not_read_further_than_the_signature(self):
        upload = SimpleUploadedFile("plate.png", b"\x89PNG" + b"0" * 100)
        self.assertIsNone(jp2_profile.check_deposit([upload]))
        self.assertEqual(upload.tell(), 0)

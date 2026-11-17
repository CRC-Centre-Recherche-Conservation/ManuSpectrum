import re
import unittest
from pathlib import Path

TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "manuspectrum/templates/views/components/widgets/manifest-widget.htm"
)


class ManifestWidgetTemplateTests(unittest.TestCase):
    def test_the_url_select_starts_with_a_blank_option(self):
        select = re.search(
            r"<select[^>]*select2Query[^>]*>(.*?)</select>", TEMPLATE.read_text(), re.S
        )
        self.assertIsNotNone(select)
        self.assertRegex(select[1].strip(), r"^<option>\s*</option>")


class ManifestWidgetJpeg2000Tests(unittest.TestCase):
    SCRIPT = (
        TEMPLATE.parents[4] / "media/js/views/components/widgets/manifest-widget.js"
    )

    def test_both_panels_list_jpeg_2000_among_the_accepted_formats(self):
        lines = re.findall(r"Accepted formats:\" %\}([^\n]*)", TEMPLATE.read_text())
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertEqual(line.strip(), "JPEG, PNG, TIFF, JPEG 2000")

    def test_the_dropzone_accepts_jp2_by_extension_only(self):
        accepted = re.search(r"acceptedFiles: \[([^\]]*)\]", self.SCRIPT.read_text())
        self.assertIsNotNone(accepted)
        self.assertIn('".jp2"', accepted[1])
        self.assertNotIn("image/jp2", accepted[1])

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

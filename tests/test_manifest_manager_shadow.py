"""The Image Service Manager page shadow is the installed Arches file plus one line.

Usage:
    python manage.py test tests.test_manifest_manager_shadow --settings="tests.test_settings"
"""

import unittest
from pathlib import Path

import arches

RELATIVE = Path("media/js/views/components/plugins/manifest-manager.js")
CORE = Path(arches.__file__).resolve().parent / "app" / RELATIVE
SHADOW = Path(__file__).resolve().parents[1] / "manuspectrum" / RELATIVE

CORE_LINE = """acceptedFiles: ["image/jpeg", "image/png", "image/tiff"].join(','),"""
SHADOW_LINE = (
    """acceptedFiles: ["image/jpeg", "image/png", "image/tiff", ".jp2"].join(','),"""
)
HEADER_END = "\n */\n"

RECOPY = (
    "manuspectrum/media/js/views/components/plugins/manifest-manager.js must be the "
    "installed Arches file ({core}) below its header comment, with the single line "
    "`{shadow}` in place of `{core_line}`: copy the core file again below the header "
    "and re-apply that line."
)


class ManifestManagerShadowTests(unittest.TestCase):
    def shadow_body(self):
        text = SHADOW.read_text()
        self.assertTrue(
            text.startswith("/**\n * Shadow of"),
            "the shadow starts with its header",
        )
        return text[text.index(HEADER_END) + len(HEADER_END) :]

    def test_the_shadow_is_the_installed_core_file_with_one_line_changed(self):
        core = CORE.read_text()
        self.assertEqual(core.count(CORE_LINE), 1, "the core line moved: " + str(CORE))

        self.assertEqual(
            self.shadow_body(),
            core.replace(CORE_LINE, SHADOW_LINE),
            RECOPY.format(core=CORE, shadow=SHADOW_LINE, core_line=CORE_LINE),
        )

    def test_the_create_picker_accepts_jp2_by_extension_only(self):
        self.assertIn('"image/tiff", ".jp2"', self.shadow_body())
        self.assertNotIn("image/jp2", self.shadow_body())

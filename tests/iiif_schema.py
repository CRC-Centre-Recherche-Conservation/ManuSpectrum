"""Validation of a IIIF Presentation 3 manifest against the pinned schema.

``tests/fixtures/iiif/iiif_3_0.json`` is the JSON Schema (Draft 7) the IIIF
presentation validator applies to Presentation 3 documents, vendored for tests
only:

- source: https://github.com/IIIF/presentation-validator, ``schema/iiif_3_0.json``
- commit: fb5bd9039494701dc7472cdcaffe83fb5a212463
- sha256: 14dd7ee8aee25d959be4b12feddb4179c726909fc85b925f6707f4ab3bfe2ad6
- licence: the repository declares none (no LICENSE file, nothing in its
  ``pyproject.toml`` or README); licence requested upstream in
  https://github.com/IIIF/presentation-validator/issues/222

The schema holds no remote ``$ref``: validation never touches the network.
"""

import json
from pathlib import Path

from jsonschema import Draft7Validator
from jsonschema.exceptions import best_match

SCHEMA_PATH = Path(__file__).parent / "fixtures" / "iiif" / "iiif_3_0.json"

with SCHEMA_PATH.open(encoding="utf-8") as handle:
    VALIDATOR = Draft7Validator(json.load(handle))


def assert_valid_manifest(testcase, manifest):
    """Fail ``testcase`` with the best-matching error's path and message."""
    error = best_match(VALIDATOR.iter_errors(manifest))
    if error is not None:
        path = "/".join(map(str, error.absolute_path))
        testcase.fail(f"{path}: {error.message}")

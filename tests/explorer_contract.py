"""Python mirror of the Explorer's ``api/types.ts`` contract (spec §5).

Each shape lists its required keys and, for nested objects, the shape of the
value. ``assert_shape`` fails on a missing key and on an unexpected key, so a
payload and the TypeScript types cannot drift silently.
"""

LABEL = {"value": str, "lang": str}
REF = {"id": str, "model": str, "name": "Label"}
VALUE_REF = {"id": str, "uri": str, "label": "Label"}
RANKED_VALUE = {"id": str, "uri": str, "label": "Label", "rank": int}
IMAGE_REF = {
    "service": (str, type(None)),
    "url": (str, type(None)),
    "width": int,
    "height": int,
}

SHAPES = {
    "Label": LABEL,
    "Ref": REF,
    "ValueRef": VALUE_REF,
    "RankedValue": RANKED_VALUE,
    "ImageRef": IMAGE_REF,
    "Facet": {"key": str, "values": list},
    "SearchResponse": {
        "total": int,
        "page": dict,
        "results": list,
        "facets": list,
        "unpublishedCount": int,
    },
    "DocumentHit": {
        "type": str,
        "id": str,
        "name": "Label",
        "holding": ("Label", None),
        "analysisCount": int,
        "thumbnail": (str, type(None)),
        "unpublished": bool,
    },
    "AnalysisHit": {
        "type": str,
        "id": str,
        "name": "Label",
        "technique": ("ValueRef", None),
        "document": "Ref",
        "component": ("Ref", None),
        "canvas": (str, type(None)),
        "date": (str, type(None)),
        "dataKinds": list,
        "materials": list,
        "unpublished": bool,
    },
    "DocumentPayload": {
        "id": str,
        "name": "Label",
        "holding": ("Label", None),
        "manifest": (str, type(None)),
        "canvases": list,
        "annotations": list,
        "characterizations": list,
        "history": list,
        "unpublishedCount": int,
        "unpublished": bool,
        "certaintyScale": dict,
        "unlocated": list,
        "samples": list,
    },
    "Annotation": {
        "key": str,
        "analysis": str,
        "canvas": str,
        "shape": dict,
        "technique": ("ValueRef", None),
        "dataKind": str,
        "unpublished": bool,
        "match": bool,
        "name": "Label",
    },
    "SampleSummary": {
        "id": str,
        "name": "Label",
        "zone": (dict, type(None)),
        "analyses": list,
        "unpublished": bool,
    },
    "UnlocatedAnalysis": {
        "analysis": str,
        "name": "Label",
        "technique": ("ValueRef", None),
        "dataKind": str,
        "unpublished": bool,
        "match": bool,
    },
    "CharacterizationSummary": {
        "id": str,
        "name": "Label",
        "objects": list,
        "materials": list,
        "colours": list,
        "layers": list,
        "elements": list,
        "zone": (dict, type(None)),
        "evidence": list,
        "note": (dict, type(None)),
        "sources": list,
        "authors": list,
        "date": dict,
        "unpublished": bool,
    },
    "AnalysisPayload": {
        "id": str,
        "name": "Label",
        "technique": ("ValueRef", None),
        "instrument": ("Ref", None),
        "operators": list,
        "projects": list,
        "date": dict,
        "document": "Ref",
        "component": ("Ref", None),
        "sample": ("Ref", None),
        "files": list,
        "conditions": list,
        "evidenceOf": list,
        "dataset": (dict, type(None)),
        "bibliography": list,
        "citation": (dict, type(None)),
        "permalink": str,
        "certaintyScale": dict,
        "unpublished": bool,
    },
    "FileEntry": {
        "id": str,
        "name": str,
        "size": (int, type(None)),
        "format": str,
        "role": str,
        "pairedWith": (str, type(None)),
        "dataKind": str,
        "viewer": dict,
        "layers": list,
        "license": dict,
        "downloadUrl": str,
        "previewUrl": (str, type(None)),
        "zone": (dict, type(None)),
    },
    "ItemsResponse": {"items": list, "missing": list},
}


def _matches(value, expected):
    if isinstance(expected, str):
        return isinstance(value, dict)
    if isinstance(expected, tuple):
        return any(
            _matches(value, e) if e is not None else value is None for e in expected
        )
    return isinstance(value, expected) and not (
        expected is int and isinstance(value, bool)
    )


def assert_shape(testcase, payload, shape_name):
    """Fail when *payload* misses a key of *shape_name*, carries an extra one, or a value has the wrong type."""
    shape = SHAPES[shape_name]
    testcase.assertIsInstance(payload, dict, shape_name)
    testcase.assertEqual(sorted(payload), sorted(shape), f"{shape_name} keys")
    for key, expected in shape.items():
        value = payload[key]
        testcase.assertTrue(
            _matches(value, expected), f"{shape_name}.{key} = {value!r}"
        )
        nested = (
            expected
            if isinstance(expected, str)
            else (
                next((e for e in expected if isinstance(e, str)), None)
                if isinstance(expected, tuple)
                else None
            )
        )
        if nested and isinstance(value, dict):
            assert_shape(testcase, value, nested)

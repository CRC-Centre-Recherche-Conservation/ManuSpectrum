"""Python mirror of the Explorer's ``api/types.ts`` contract (spec §5).

Each shape lists its required keys and, for nested objects, the shape of the
value. ``assert_shape`` fails on a missing key and on an unexpected key, so a
payload and the TypeScript types cannot drift silently.
"""

LABEL = {"value": str, "lang": str}
REF = {"id": str, "model": str, "name": "Label"}
VALUE_REF = {"id": str, "uri": str, "label": "Label"}
TECHNIQUE = {
    "id": str,
    "uri": str,
    "label": "Label",
    "code": str,
    "colour": (int, type(None)),
    "family": str,
}
TECHNIQUE_MARK = {"code": str, "colour": (int, type(None)), "family": str}
RANKED_VALUE = {"id": str, "uri": str, "label": "Label", "rank": int}
NAMED_REF = {"id": str, "name": "Label"}
CITATION = {"text": str, "bibtex": str}
IMAGE_REF = {
    "service": (str, type(None)),
    "url": (str, type(None)),
    "width": int,
    "height": int,
}

LAYER_ELEMENT = {"value": "ValueRef", "symbol": (str, type(None))}
LAYER_BAND = {
    "value": (int, float, type(None)),
    "lower": (int, float, type(None)),
    "upper": (int, float, type(None)),
    "unit": ("ValueRef", None),
}
LAYER_PROCESSING = {
    "method": ("ValueRef", None),
    "index": (int, float, type(None)),
    "inputs": (str, type(None)),
}
FILE_LAYER = {
    "index": int,
    "id": str,
    "label": str,
    "image": "ImageRef",
    "content": ("ValueRef", None),
    "elements": list,
    "emissionLine": ("ValueRef", None),
    "band": ("LayerBand", None),
    "processing": ("LayerProcessing", None),
    "note": (str, type(None)),
}

SHAPES = {
    "Label": LABEL,
    "Ref": REF,
    "ValueRef": VALUE_REF,
    "RankedValue": RANKED_VALUE,
    "ImageRef": IMAGE_REF,
    "FileLayer": FILE_LAYER,
    "LayerElement": LAYER_ELEMENT,
    "LayerBand": LAYER_BAND,
    "LayerProcessing": LAYER_PROCESSING,
    "NamedRef": NAMED_REF,
    "Citation": CITATION,
    "Technique": TECHNIQUE,
    "TechniqueMark": TECHNIQUE_MARK,
    "Facet": {"key": str, "group": str, "values": list, "total": int},
    "FacetValue": {
        "id": str,
        "label": "Label",
        "count": int,
        "mark": ("TechniqueMark", None),
        "swatch": (str, type(None)),
    },
    "SearchResponse": {
        "total": int,
        "page": dict,
        "results": list,
        "facets": (list, type(None)),
        "unpublishedCount": int,
        "withoutAnalyses": int,
    },
    "HomeResponse": {
        "documentCount": int,
        "techniques": list,
        "projects": list,
        "featured": ("DocumentHit", None),
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
        "shelfmark": ("Label", None),
        "dates": (dict, type(None)),
        "description": ("Label", None),
        "documentType": ("Label", None),
    },
    "AnalysisHit": {
        "type": str,
        "id": str,
        "name": "Label",
        "technique": ("Technique", None),
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
        "techniques": dict,
        "analyses": list,
        "components": list,
        "characterizations": list,
        "history": list,
        "unpublishedCount": int,
        "unpublished": bool,
        "certaintyScale": dict,
        "samples": list,
    },
    "DocumentAnalysis": {
        "id": str,
        "name": "Label",
        "technique": (str, type(None)),
        "dataKind": str,
        "unpublished": bool,
        "zones": list,
    },
    "AnalysisZone": {"canvas": int, "shape": dict, "feature": str},
    "DocumentComponent": {"id": str, "name": "Label", "zones": list},
    "ContentStateLink": {"feature": str, "url": str},
    "DocumentMatch": {"facets": list, "kept": "MatchKept", "total": int},
    "MatchKept": {"analyses": (list, type(None)), "characterizations": list},
    "SampleSummary": {
        "id": str,
        "name": "Label",
        "zone": (dict, type(None)),
        "analyses": list,
        "unpublished": bool,
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
        "technique": ("Technique", None),
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
        "citation": "Citation",
        "availability": str,
        "manifest": (str, type(None)),
        "contentStates": list,
        "permalink": str,
        "reportUrl": str,
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
        "viewer": "FileViewer",
        "layers": list,
        "license": dict,
        "downloadUrl": str,
        "previewUrl": (str, type(None)),
        "zone": (dict, type(None)),
    },
    "FileViewer": {
        "rendererConfigId": (str, type(None)),
        "presetKey": (str, type(None)),
        "configName": (str, type(None)),
        "xLabel": (str, type(None)),
        "yLabel": (str, type(None)),
        "axisKey": (str, type(None)),
        "points": (int, type(None)),
        "decimated": bool,
    },
    "AnalysisItem": {"key": str, "kind": str, "analysis": "AnalysisHit", "files": list},
    "ItemsResponse": {"items": list, "missing": list},
    "SharePayload": {
        "scope": "ShareScope",
        "citations": list,
        "availability": str,
        "export": "ShareExport",
        "links": "ShareLinks",
    },
    "ShareScope": {
        "kind": str,
        "key": str,
        "analyses": int,
        "characterizations": int,
        "spectra": int,
        "drafts": int,
        "missing": list,
    },
    "ShareExport": {"files": int, "bytes": int, "overLimit": bool, "documents": list},
    "SynthesisResponse": {
        "coverage": list,
        "canvases": list,
        "techniques": list,
        "pairs": list,
        "elements": list,
        "materials": list,
        "unpublishedCount": int,
    },
    "SynthesisCoverage": {
        "canvas": str,
        "label": str,
        "document": str,
        "counts": dict,
        "components": list,
    },
    "SynthesisCoverageComponent": {"component": ("Ref", None), "counts": dict},
    "SynthesisCanvas": {
        "canvas": str,
        "document": str,
        "label": str,
        "selected": bool,
        "analyses": list,
        "materials": list,
    },
    "SynthesisPair": {
        "colour": ("ValueRef", None),
        "material": "ValueRef",
        "elements": list,
        "count": int,
        "materials": list,
    },
    "SynthesisElementRef": {
        "id": str,
        "uri": str,
        "label": "Label",
        "symbol": (str, type(None)),
    },
    "SynthesisElement": {
        "symbol": str,
        "level": ("RankedValue", None),
        "count": int,
        "materials": list,
    },
    "SynthesisMaterial": {
        "id": str,
        "evidence": list,
        "canvases": list,
        "objects": list,
        "summary": "CharacterizationSummary",
        "selected": bool,
    },
    "ShareDocument": {"id": str, "name": "Label", "url": str, "path": str},
    "ProductLink": {"url": str, "path": str},
    "ShareLinks": {
        "manifest": ("ProductLink", type(None)),
        "seriesCsv": ("ProductLink", type(None)),
        "manifestTooLarge": bool,
        "export": "ProductLink",
    },
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

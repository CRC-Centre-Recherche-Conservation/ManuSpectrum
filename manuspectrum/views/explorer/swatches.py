"""Display colours of the colour list, the same rule for the rail and the Materials table.

The concepts of the colour list (« AGORHA - Color », INHA thesaurus) are
coloured by URI, the same in every language: a CSS colour, or a gradient for
the metallic ones. A concept the table does not hold falls back to the first
colour word among its labels.
"""

import re

from manuspectrum.views.explorer.values import (
    FALLBACK_LANGUAGE,
    fold,
    reference_items,
    value_refs,
)

INHA = "https://thesaurus.inha.fr/thesaurus/resource/ark:/54721/"

_BY_ID = {
    "d549884f-ed29-4a28-87c8-07311d9a14ad": ("blue", "#2f55a4"),
    "8fea5a73-2d20-4fcf-a1a5-84c886c25152": ("red", "#b8322a"),
    "65911707-7503-4511-a7f8-50d7950e8178": ("orange", "#d9772b"),
    "23d3e025-d192-44a3-b402-8e7549cad396": ("yellow", "#e3b53b"),
    "28b1b584-6607-49cf-acff-67e7f16dae68": ("green", "#3f7d4e"),
    "0e604a6e-3c95-4608-a7b8-5f99fcd506e5": ("violet", "#6d4a8f"),
    "0bfbc388-6da7-4209-995d-33c72c08fb9f": ("pink", "#e3a1a8"),
    "c3c194f1-5237-4e1c-ad3d-38cb2351b8eb": ("brown", "#7a4e2d"),
    "b4028a43-aafc-4d54-bdf7-8c901c693d14": ("black", "#26232b"),
    "2259f089-935b-46ec-af76-cdb5156ee311": ("white", "#f5f0e4"),
    "aa134bc0-36d8-4156-a1f6-8f3241f70a93": ("grey", "#8f8c86"),
    "71aa53c3-0322-4111-bf82-98fa14f62393": ("beige", "#d9c8a4"),
    "163d790d-859f-4a9d-92ae-2f759a1d8b6b": (
        "silver",
        "linear-gradient(135deg, #e9ebee, #a9adb4 55%, #dfe2e6)",
    ),
    "c1e1850f-9eb1-48f4-b8b8-6154a3a1623c": (
        "gold",
        "linear-gradient(135deg, #f3dc8a, #b8891f 55%, #ecd07a)",
    ),
    "3219663b-bd8b-4e14-8dc8-02eaf6e1f793": (
        "copper",
        "linear-gradient(135deg, #e0a27a, #a8562c 55%, #d98d62)",
    ),
}

SWATCH_BY_URI = {INHA + item: swatch for item, (_, swatch) in _BY_ID.items()}

_NAME_TO_URI = {name: INHA + item for item, (name, _) in _BY_ID.items()}

# Chromatic order, identical in every language.
SWATCH_ORDER = tuple(
    _NAME_TO_URI[name]
    for name in (
        "white",
        "beige",
        "yellow",
        "orange",
        "red",
        "pink",
        "violet",
        "blue",
        "green",
        "brown",
        "grey",
        "black",
        "gold",
        "silver",
        "copper",
    )
)

_RANK = {uri: rank for rank, uri in enumerate(SWATCH_ORDER)}

SWATCH_WORDS = {
    "blue": "royalblue",
    "bleu": "royalblue",
    "azur": "royalblue",
    "red": "firebrick",
    "rouge": "firebrick",
    "vermillon": "orangered",
    "vermilion": "orangered",
    "green": "forestgreen",
    "vert": "forestgreen",
    "gold": "goldenrod",
    "golden": "goldenrod",
    "or": "goldenrod",
    "dore": "goldenrod",
    "silver": "silver",
    "argent": "silver",
    "argente": "silver",
    "white": "white",
    "blanc": "white",
    "black": "black",
    "noir": "black",
    "yellow": "gold",
    "jaune": "gold",
    "brown": "saddlebrown",
    "brun": "saddlebrown",
    "marron": "saddlebrown",
    "beige": "beige",
    "ochre": "peru",
    "ocre": "peru",
    "grey": "grey",
    "gray": "grey",
    "gris": "grey",
    "purple": "purple",
    "violet": "purple",
    "pourpre": "purple",
    "pink": "hotpink",
    "rose": "hotpink",
    "orange": "darkorange",
}


def colour_rank(uri):
    """Rank of the colour concept *uri* in ``SWATCH_ORDER``; None for a concept the list does not hold."""
    return _RANK.get(uri)


def colour_swatch(value):
    """Display colour of a stored colour reference *value*; None when neither its URI nor a label names one.

    The URI of each item is tried first (``SWATCH_BY_URI``). Else labels are
    tried in a fixed order whatever the request language: English preferred
    label, other preferred labels by language, then alternative labels by
    language; the first colour word found (``SWATCH_WORDS``) wins.
    """
    items = [
        item
        for item in (value if isinstance(value, list) else [value])
        if isinstance(item, dict)
    ]
    for item in items:
        if item.get("uri") in SWATCH_BY_URI:
            return SWATCH_BY_URI[item["uri"]]
    entries = [
        entry
        for item in items
        for entry in item.get("labels") or []
        if isinstance(entry, dict) and isinstance(entry.get("value"), str)
    ]
    entries.sort(
        key=lambda e: (
            e.get("valuetype_id") != "prefLabel",
            e.get("language_id") != FALLBACK_LANGUAGE,
            e.get("language_id") or "",
            e["value"],
        )
    )
    for entry in entries:
        for word in re.split(r"[^a-z]+", fold(entry["value"])):
            if word in SWATCH_WORDS:
                return SWATCH_WORDS[word]
    return None


def colour_refs(value, language):
    """``ColourRef`` list of a stored colour reference *value*: its ``value_refs``, each with the swatch of its own item."""
    return [
        {**ref, "swatch": colour_swatch(item)}
        for item, ref in zip(reference_items(value), value_refs(value, language))
    ]

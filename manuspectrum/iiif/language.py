"""IIIF language maps: every language of a value in one document (Presentation 3 §4.4).

A language map is ``{language: [text, …]}``. Keys are the BCP 47 codes the
value was stored under; a value stored without a language goes under
``none``; a language is never guessed. Interface strings are rendered in every
language of ``settings.LANGUAGES``. The v2 form (Presentation 2.1 §4.3) is a
list of ``{"@value", "@language"}`` objects.
"""

from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext

LanguageMap = dict[str, list[str]]
NONE = "none"
_RANK = {"prefLabel": 0, "altLabel": 1}


def languages():
    """The codes of ``settings.LANGUAGES``, in order."""
    return [code for code, _ in settings.LANGUAGES]


def _clean(text):
    return text.strip() if isinstance(text, str) else ""


def from_texts(texts):
    """``{lang: [text]}`` of ``{lang: text}``; empty texts are dropped."""
    return {
        lang: [_clean(text)]
        for lang, text in (texts or {}).items()
        if lang and _clean(text)
    }


def none(*values):
    """``{"none": [...]}`` of the non-empty *values*; ``{}`` when there is none."""
    kept = [_clean(v) for v in values if _clean(v)]
    return {NONE: kept} if kept else {}


def string_map(value):
    """Language map of a localized string tile value; a plain string has no language."""
    if isinstance(value, str):
        return none(value)
    if not isinstance(value, dict):
        return {}
    return from_texts(
        {
            lang: entry.get("value") if isinstance(entry, dict) else entry
            for lang, entry in value.items()
        }
    )


def text_in(value, language, sep=", "):
    """One string of *value* for *language*: its own texts, else ``none``, else its first language; "" when empty."""
    if isinstance(value, str):
        return value
    if not value:
        return ""
    for key in (language, NONE):
        if value.get(key):
            return sep.join(value[key])
    return sep.join(next(iter(value.values())))


def first_text(value, sep=", "):
    """One string of *value*: the first configured language holding one, else ``none``, else any."""
    for lang in (*languages(), NONE):
        if value.get(lang):
            return sep.join(value[lang])
    return text_in(value, NONE, sep)


def gettext_map(msgid, **params):
    """*msgid* rendered in every configured language, ``%(name)s`` filled per language.

    A parameter is a string, the same in every language, or a language map,
    read in each language by ``text_in``.
    """
    rendered = {}
    for lang in languages():
        with translation.override(lang):
            text = gettext(msgid)
        if params:
            text = text % {key: text_in(value, lang) for key, value in params.items()}
        rendered[lang] = [text]
    return rendered


def joined(maps, sep=", "):
    """One string per language joining *maps* in order (multi-valued metadata).

    The languages are those any map carries, configured ones first. In each
    language a map gives its own texts, else its ``none`` texts, else those of
    its first language. Maps carrying ``none`` only give ``{"none": [...]}``.
    """
    maps = [m for m in maps if m]
    if not maps:
        return {}
    order = [*languages()]
    tagged = []
    for value in maps:
        for lang in value:
            if lang != NONE and lang not in tagged:
                tagged.append(lang)
    tagged.sort(key=lambda lang: order.index(lang) if lang in order else len(order))
    if not tagged:
        return {NONE: [sep.join(sep.join(m[NONE]) for m in maps)]}
    return {lang: [sep.join(text_in(m, lang, sep) for m in maps)] for lang in tagged}


def descriptor_names(descriptors):
    """Name per language of ``resource_instances.descriptors``; languages without a name are left out."""
    return from_texts(
        {
            lang: entry.get("name")
            for lang, entry in (descriptors or {}).items()
            if isinstance(entry, dict)
        }
    )


def reference_item_labels(item):
    """Labels of one controlled-list reference item: per language its prefLabel, else its altLabel."""
    best = {}
    for entry in (item or {}).get("labels") or []:
        if not isinstance(entry, dict) or not _clean(entry.get("value")):
            continue
        lang = entry.get("language_id") or NONE
        rank = _RANK.get(entry.get("valuetype_id"), len(_RANK))
        if lang not in best or rank < best[lang][0]:
            best[lang] = (rank, _clean(entry["value"]))
    return {lang: [text] for lang, (_, text) in best.items()}


def reference_items(value):
    """The items of a reference value that carry labels."""
    items = value if isinstance(value, list) else [value]
    return [
        i for i in items if isinstance(i, dict) and isinstance(i.get("labels"), list)
    ]


def reference_labels(value):
    """Labels of every item of a reference value, one string per language."""
    return joined(reference_item_labels(item) for item in reference_items(value))


def to_v2(value):
    """``[{"@value", "@language"}]`` of a language map; a ``none`` text has no ``@language``."""
    found = []
    for lang, texts in (value or {}).items():
        for text in texts:
            found.append(
                {"@value": text}
                if lang == NONE
                else {"@value": text, "@language": lang}
            )
    return found

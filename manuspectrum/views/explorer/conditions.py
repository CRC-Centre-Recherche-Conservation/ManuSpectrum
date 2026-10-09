"""Conditions de mesure of an Analysis, read from its typed statements (spec §3.5, D40).

``content_of_statement`` is rich text entered in the Arches editor; it is
reduced to a short allow-list by ``nh3`` before it leaves the server, so the
client can render it as HTML.
"""

import re

import nh3

from manuspectrum.views.explorer.values import label, string_texts, value_refs

ALLOWED_TAGS = frozenset({"p", "br", "em", "strong", "ul", "ol", "li", "sub", "sup"})
_EMPTY = re.compile(r"^(\s|&nbsp;|<br\s*/?>|<p>\s*</p>)*$", re.IGNORECASE)


def clean_html(html):
    """*html* reduced to ``ALLOWED_TAGS`` without any attribute; script and style content removed."""
    return nh3.clean(
        html or "", tags=set(ALLOWED_TAGS), attributes={}, link_rel=None
    ).strip()


def conditions_of(tiles, type_node_id, content_node_id, language):
    """``[{"type", "html", "lang"}]`` of the statements carrying content.

    Typed statements come first, ordered by their type label; untyped ones
    follow. The text is taken in *language*, else English, else the first
    language present, with that language in ``lang``.
    """
    typed, untyped = [], []
    for data in tiles:
        text = label(string_texts((data or {}).get(content_node_id)), language)
        if not text:
            continue
        html = clean_html(text["value"])
        if _EMPTY.match(html):
            continue
        refs = value_refs((data or {}).get(type_node_id), language)
        entry = {"type": refs[0] if refs else None, "html": html, "lang": text["lang"]}
        (typed if refs else untyped).append(entry)
    typed.sort(key=lambda c: c["type"]["label"]["value"].casefold())
    return typed + untyped

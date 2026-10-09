"""The family of an identified material in the map's Materials control: one table, one rule.

The AGORHA materials list repeats a term under several parents (vermilion is a red
pigment and a colouring material of synthetic origin). ``FAMILY_TABLE`` names, in
priority order, the list items (by INHA uri) whose descendants form a family: a
material takes the family of the first entry found on the ancestry of any of its
occurrences, its own uri included, else ``other``. Explicit metals and inks come
first, then the colour branches of « Coloring material », then « lake pigment »
(red), metals and binders.
"""

from collections import defaultdict

from arches_controlled_lists.models import ListItem

from manuspectrum.views.explorer.service import parent_chains

INHA = "https://thesaurus.inha.fr/thesaurus/resource/ark:/54721/"
FAMILIES = (
    "blue",
    "red",
    "yellow",
    "green",
    "white",
    "black",
    "metals",
    "binders",
    "other",
)
FAMILY_TABLE = tuple(
    (INHA + item, family)
    for item, family in (
        ("983dc56b-54f0-4b4a-80cf-9c45fd67cbf4", "metals"),  # gold
        ("ba2163cf-5fa3-4f43-a078-01b09536946e", "metals"),  # silver
        ("5ee2516b-b17a-492c-abaa-fc7cae9bb9ab", "metals"),  # tin
        ("d5a41ddb-35d5-462b-8ff0-bc6da3d2117b", "metals"),  # copper
        ("1eb39f7b-bd9d-457e-adf0-0ef91174a01b", "black"),  # ink
        ("d3bed0de-60fe-48b4-95f5-74c1e6f266f2", "blue"),  # blue pigment
        ("8367b7f3-c32d-46d8-8f10-2a10bc7950ea", "blue"),  # blue colorant
        ("b7238344-724a-44ec-8820-b2944fe2a908", "red"),  # red pigment
        ("f4a041b0-ad6e-47a4-9fce-e6fd68e62284", "red"),  # red colorant
        ("22ee3aee-3893-40e2-9202-9bcfe22fdb7e", "red"),  # orange pigment
        ("0adeac49-e51d-4417-8a00-632ecce81b49", "red"),  # orange colorant
        ("b10c0d6a-5312-4e5b-8ebb-9eefd51ec832", "red"),  # pink colorant
        ("f647c688-1f6e-4160-af75-83a4db27ef24", "yellow"),  # yellow pigment
        ("c73fae4d-e6e7-4ee8-8c16-04a21cbbb8ac", "yellow"),  # yellow colorant
        ("34caadcb-6fc1-47ec-8bd8-83810c1ebba9", "green"),  # green pigment
        ("b98c1636-ab99-4a24-b272-2cc1474760e2", "green"),  # green colorant
        ("ba9fb1da-15d4-4e6d-bcc2-2c87f42897a3", "white"),  # white pigment
        ("682e458c-7852-44cb-96b0-522ab8a1595b", "white"),  # white colorant
        ("1473b92b-b205-4694-9306-a326cb5d9aeb", "black"),  # black pigment
        ("29609071-877a-4f19-ba12-06d53e38d2cc", "black"),  # black colorant
        ("ab5c36eb-f323-4441-9f74-e6d9d7fa7e3a", "red"),  # lake pigment
        ("37ed014e-c8ba-4475-aa14-e6bf9c77a585", "metals"),  # metal
        ("037fd4fe-a32c-4dde-a500-819cb250b5ca", "metals"),  # alloy
        ("d1713997-db6c-4249-b17e-22fc1d1fdb74", "binders"),  # egg
        ("cb16308b-fb95-46ad-8a1c-0d664b77ef7b", "binders"),  # glue (animal)
        ("b14d3385-f00d-48ba-8b17-af19ca6b9365", "binders"),  # vegetable gum
        ("b32c5200-1cc5-4167-8558-381a205fd778", "binders"),  # gum arabic
        ("a9e7145c-70b2-41b8-ab08-007efe614fde", "binders"),  # gum resin
        ("9067c3e0-7ba1-49d2-8c28-5c71afe9d1f6", "binders"),  # drying oil
        ("6bbec8fd-1f8a-490d-afc6-33fb9a1a63e9", "binders"),  # vegetable oil
        ("bd350016-73e6-416d-95e5-52b626658774", "binders"),  # beeswax
        ("25698502-b753-4747-b84e-dc23e4d9e1f9", "binders"),  # plant resin
    )
)
_RANK = {uri: (index, family) for index, (uri, family) in enumerate(FAMILY_TABLE)}


def family_from_chains(chains):
    """The family of a material whose occurrences have the uri *chains* (its own uri, then its ancestors'); ``other`` when none is listed."""
    best = None
    for chain in chains:
        for uri in chain:
            found = _RANK.get(uri)
            if found and (best is None or found[0] < best[0]):
                best = found
    return best[1] if best else "other"


def families_of(uris):
    """``{uri: family}`` of the material uris *uris* (empty ones left out), read off every list item carrying each uri and their ancestors."""
    wanted = sorted({uri for uri in uris if uri})
    if not wanted:
        return {}
    items = [
        (str(i), uri)
        for i, uri in ListItem.objects.filter(uri__in=wanted).values_list("id", "uri")
    ]
    ancestry = parent_chains([i for i, _ in items])
    above = {a for chain in ancestry.values() for a in chain}
    uri_of = (
        {
            str(i): uri
            for i, uri in ListItem.objects.filter(pk__in=list(above)).values_list(
                "id", "uri"
            )
        }
        if above
        else {}
    )
    chains = defaultdict(list)
    for item, uri in items:
        chains[uri].append([uri, *(uri_of.get(a, "") for a in ancestry.get(item, []))])
    return {uri: family_from_chains(chains.get(uri, [[uri]])) for uri in wanted}

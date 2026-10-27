"""Rules over stored manifest values, shared by the thumbnail fetcher and the Explorer."""


def first_manifest_url(values):
    """The first of a Document's facsimile *values* naming a IIIF manifest, or None.

    The one rule for a Document's thumbnail source: ``DocumentThumbnailFetcher``
    fetches it, and a search hit advertises the thumbnail route only when it
    exists.
    """
    return next(
        (v for v in values if isinstance(v, str) and "manifest" in v.lower()), None
    )

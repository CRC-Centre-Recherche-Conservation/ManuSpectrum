"""IIIF context URIs, media types and selector vocabularies."""

PRESENTATION_3 = "http://iiif.io/api/presentation/3/context.json"
PRESENTATION_2 = "http://iiif.io/api/presentation/2/context.json"
MEDIA_FRAGMENTS = "http://www.w3.org/TR/media-frags/"
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
OCTET_STREAM = "application/octet-stream"
IIIF_MEDIA_TYPE = f'application/ld+json;profile="{PRESENTATION_3}"'
IIIF_V2_MEDIA_TYPE = f'application/ld+json;profile="{PRESENTATION_2}"'

# The media type a raw file is served with, by its lower-case extension; the
# raw instrument formats (settings.RAW_INSTRUMENT_EXTENSIONS) are octet-stream.
MEDIA_TYPE_BY_EXTENSION = {
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".tsv": "text/tab-separated-values",
}

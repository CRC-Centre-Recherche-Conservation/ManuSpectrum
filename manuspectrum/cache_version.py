"""Code version of the cached payloads, read once per process.

Imported by ``settings.py`` before Django is configured: no Django import here.
"""

import hashlib
import os
from pathlib import Path

# Modules whose code decides the shape of a cached payload. Editing one of
# them changes the cache key prefix, so a process running the new code never
# reads an entry built by the old one. Modules that only parse upstream data
# (Biblissima proxy) are not listed: their entries expire by TTL.
CACHE_SHAPE_MODULES = (
    "views/model_graph.py",
    "views/model_graph_service.py",
    "views/iiif_annotation.py",
    "views/serializers/iiif_annotation.py",
    "views/summary.py",
    "views/summary_service.py",
    # The summary payload reads its localized texts through graph_nodes.
    "views/graph_nodes.py",
)

ENV_OVERRIDE = "MANUSPECTRUM_CACHE_VERSION"


def cache_code_version(app_root, modules=CACHE_SHAPE_MODULES, environ=os.environ):
    """A 12-hex digest of the listed module sources under `app_root`.

    ``MANUSPECTRUM_CACHE_VERSION`` in the environment replaces the digest
    verbatim, which is how a deployment forces every key to start cold.
    """
    override = environ.get(ENV_OVERRIDE, "").strip()
    if override:
        return override
    digest = hashlib.sha1(usedforsecurity=False)
    for relative in modules:
        digest.update(relative.encode("utf-8"))
        digest.update(Path(app_root, relative).read_bytes())
    return digest.hexdigest()[:12]

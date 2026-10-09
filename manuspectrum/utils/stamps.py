"""Stamps of files a cached payload renders from: size and mtime, never contents."""

import functools
import hashlib
import os
from importlib import metadata

from django.conf import settings

# Distributions whose message catalogues a IIIF document renders.
CATALOGUE_DISTRIBUTIONS = ("arches", "django")


def files_stamp(root, directories, seed=""):
    """12 hex chars over *seed* and the size and mtime of every file under *directories* of *root*.

    A file that vanishes between its listing and its ``stat`` is left out.
    """
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(seed.encode())
    for directory in directories:
        top = os.path.join(root, directory)
        for folder, subfolders, files in os.walk(top):
            subfolders.sort()
            for filename in sorted(files):
                path = os.path.join(folder, filename)
                try:
                    stat = os.stat(path)
                except FileNotFoundError:
                    continue
                relative = os.path.relpath(path, root)
                digest.update(
                    f"{relative}:{stat.st_size}:{stat.st_mtime_ns}\n".encode()
                )
    return digest.hexdigest()[:12]


def locale_stamp():
    """The stamp of the translations: ``CATALOGUE_DISTRIBUTIONS`` versions and the project's ``locale`` files.

    Read on every call under ``DEBUG`` (the development server reloads
    catalogues without restarting), once per process otherwise.
    """
    if settings.DEBUG:
        return _read_locale_stamp()
    return _process_locale_stamp()


@functools.cache
def _process_locale_stamp():
    return _read_locale_stamp()


def _read_locale_stamp():
    versions = "".join(
        f"{name}={metadata.version(name)}\n" for name in CATALOGUE_DISTRIBUTIONS
    )
    return files_stamp(settings.APP_ROOT, ("locale",), versions)

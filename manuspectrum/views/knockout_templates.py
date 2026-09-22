"""Knockout component templates, rendered once per language and kept.

Arches' ``templates`` route (``arches.app.views.main.templates``, Arches
8.1.5) renders any template name through the full request context and answers
without a validator, and ``template-loader.js`` asks
``/<language>/templates/<name>`` for every component a page mounts, on every
page load. This view answers the same URLs.

A name under ``SHARED_PREFIXES`` is rendered once per language and
``template_stamp()`` into the default cache, and served with an ETag and
``public, max-age=KNOCKOUT_TEMPLATE_MAX_AGE``: those subtrees print no
per-reader value, load only the tag libraries ``i18n``, ``static``,
``template_tags`` and ``webpack_loader``, and include or extend string
literals only (``tests/test_knockout_templates.py`` scans them). Any other
name is left to the core view, uncached: a page template such as ``login.htm``
carries the reader's CSRF token. A name no loader can read is a bodyless 404,
as the browser loader inserts whatever it receives into the page.
"""

import functools
import hashlib
import logging
import os
import posixpath
from importlib import metadata

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseNotFound, HttpResponseNotModified
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.utils import translation

from arches.app.views import main

from manuspectrum.utils.cache import etag_already_held, stable_cache_key

logger = logging.getLogger(__name__)

# The subtrees template-loader.js fetches from.
SHARED_PREFIXES = (
    "views/components/",
    "views/report-templates/",
    "views/resource/permissions/",
    "views/resource/related-resources/",
)

# Distributions whose templates and catalogues a shared template renders.
STAMPED_DISTRIBUTIONS = ("arches", "arches-controlled-lists", "arches-vue-components")

HTML = "text/html; charset=utf-8"

# What a name that reaches no template file raises between the loaders and
# the filesystem: Django turns FileNotFoundError alone into
# TemplateDoesNotExist, a directory or a path through a file raise their own.
NOT_A_TEMPLATE = (TemplateDoesNotExist, IsADirectoryError, NotADirectoryError)


def knockout_template(request, template):
    """The ``templates`` route: shared names from the cache, others from core.

    The name is the captured path, or ``?template=`` when the path is empty,
    as in the core view. A name holding a NUL byte, which only ``?template=``
    can carry, is a 404 before any loader sees it.
    """
    name = template or request.GET.get("template") or ""
    if not name or "\x00" in name:
        return HttpResponseNotFound()
    if request.method in ("GET", "HEAD") and is_shared(name):
        return _shared(request, name)
    if _load(name) is None:
        return HttpResponseNotFound()
    return main.templates(request, template)


def is_shared(name):
    """Whether *name* is a canonical ``.htm`` path under a shared prefix.

    Canonical means ``posixpath.normpath`` leaves it unchanged: no ``..``, no
    ``.`` segment, no doubled slash. A traversal would pass the prefix test and
    reach a page template, and each spelling of one file would fill its own
    cache entry.
    """
    return (
        name.endswith(".htm")
        and name.startswith(SHARED_PREFIXES)
        and posixpath.normpath(name) == name
    )


def template_stamp():
    """What a shared template's bytes depend on besides its name and language.

    The versions of ``STAMPED_DISTRIBUTIONS`` and the size and mtime of every
    file under the project's ``templates`` and ``locale`` directories. The
    versions are read once per process; the files once per process too, or on
    every call under ``DEBUG``, where the development server reloads templates
    without restarting. A file that vanishes between its listing and its
    ``stat`` is left out. Settings a template prints (``STATIC_URL``, the
    export thresholds) are not in it: those entries expire after
    ``KNOCKOUT_TEMPLATE_CACHE_TTL``, or at once with
    ``MANUSPECTRUM_CACHE_VERSION``.
    """
    if settings.DEBUG:
        return _read_stamp()
    return _process_stamp()


@functools.cache
def _process_stamp():
    return _read_stamp()


@functools.cache
def _distribution_versions():
    return "".join(
        f"{distribution}={metadata.version(distribution)}\n"
        for distribution in STAMPED_DISTRIBUTIONS
    )


def _read_stamp():
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(_distribution_versions().encode())
    for directory in ("templates", "locale"):
        top = os.path.join(settings.APP_ROOT, directory)
        for folder, subfolders, files in os.walk(top):
            subfolders.sort()
            for filename in sorted(files):
                path = os.path.join(folder, filename)
                try:
                    stat = os.stat(path)
                except FileNotFoundError:
                    continue
                relative = os.path.relpath(path, settings.APP_ROOT)
                digest.update(
                    f"{relative}:{stat.st_size}:{stat.st_mtime_ns}\n".encode()
                )
    return digest.hexdigest()[:12]


def _load(name):
    """The template *name* resolves to, or ``None`` when no loader can read it.

    Besides an unknown name: a directory, a path through a file.
    """
    try:
        return get_template(name)
    except NOT_A_TEMPLATE:
        return None


def _renews_csrf_cookie(request):
    return bool(request.META.get("CSRF_COOKIE_NEEDS_UPDATE"))


def _shared(request, name):
    """Serve a shared template from the cache, rendering it on a miss.

    While ``CSRF_COOKIE_NEEDS_UPDATE`` is set, ``CsrfViewMiddleware`` adds a
    ``Set-Cookie`` to the response, which is then ``private, no-store``; a
    cached body is still served, with its ETag. The middleware sets that flag
    before the view for a malformed ``csrftoken`` cookie, and a render that
    reads the token sets it too. The two cannot be told apart, so nothing
    rendered while the flag is set is kept. The WARNING names a template only
    when the flag went from unset to set during its render.
    """
    language = translation.get_language() or settings.LANGUAGE_CODE
    key = stable_cache_key("ko-template", name, language, template_stamp())
    entry = cache.get(key)
    if entry is None:
        template = _load(name)
        if template is None:
            return HttpResponseNotFound()
        renewed_before = _renews_csrf_cookie(request)
        body = template.render(request=request).encode("utf-8")
        if _renews_csrf_cookie(request):
            if not renewed_before:
                logger.warning("%s reads the CSRF token; served uncached", name)
            response = HttpResponse(body, content_type=HTML)
            response["Cache-Control"] = "private, no-store"
            return response
        etag = '"%s"' % hashlib.md5(body, usedforsecurity=False).hexdigest()
        entry = {"body": body, "etag": etag}
        cache.set(key, entry, settings.KNOCKOUT_TEMPLATE_CACHE_TTL)
    if etag_already_held(request, entry["etag"]):
        response = HttpResponseNotModified()
    else:
        response = HttpResponse(entry["body"], content_type=HTML)
    response["ETag"] = entry["etag"]
    response["Cache-Control"] = (
        "private, no-store"
        if _renews_csrf_cookie(request)
        else f"public, max-age={settings.KNOCKOUT_TEMPLATE_MAX_AGE}"
    )
    return response

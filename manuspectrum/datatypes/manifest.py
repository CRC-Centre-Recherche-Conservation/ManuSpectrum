import uuid
import re
from urllib.parse import urlparse

from django.conf import settings as django_settings
from django.core.validators import URLValidator, ValidationError
from arches.app.datatypes.base import BaseDataType
from arches.app.models.models import IIIFManifest, Widget
from django.utils.translation import gettext_lazy as _

from manuspectrum.utils import manifest_registry
from manuspectrum.utils.manifest_registry import (  # noqa: F401
    FailParsingManifestIIIF,
    InvalidManifestURL,
)

text: Widget = Widget.objects.get(name="manifest-widget")

details: dict[str, str | Widget | bool | None] = {
    "datatype": "manifest",
    "iconclass": "fa fa-file-image-o",
    "modulename": "manifest.py",
    "classname": "ManifestDataType",
    "defaultwidget": text,
    "defaultconfig": None,
    "configcomponent": None,
    "configname": None,
    "isgeometric": False,
    "issearchable": False,
}


# Local IIIF manifest reference: /manifest/{uuid4}, optionally absolute and
# optionally language-prefixed. Tiles store the bare path, but every Arches
# route lives under a language prefix, so /en/manifest/{uuid} is the URL a
# curator copies out of the address bar and pastes back in.
_LANGUAGE_PREFIX_RE = "|".join(
    re.escape(code) for code, _label in django_settings.LANGUAGES
)
_LOCAL_MANIFEST_RE = re.compile(
    r"^(?:https?://[^/]+)?"
    r"(?:/(?:" + _LANGUAGE_PREFIX_RE + r"))?"
    r"/manifest/"
    r"(?P<uuid>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)

# Cheap, network-free URL FORMAT gate. The host / private-IP / SSRF policy lives
# in manuspectrum.utils.http.assert_url_is_safe (DNS-based, opened only by
# SSRF_ALLOW_PRIVATE), NOT here — so there is no dev/prod regex split.
_validate_url_format = URLValidator(schemes=["http", "https"])


def get_local_hosts():
    """Hostnames that identify THIS server, for local-manifest detection.

    Seeded from ``settings.PUBLIC_SERVER_ADDRESS`` (the canonical public URL)
    plus ``ALLOWED_HOSTS`` defensively. ``ALLOWED_HOSTS`` may legitimately be
    empty on a given host, so ``PUBLIC_SERVER_ADDRESS`` MUST be set per
    environment for absolute self-URLs to be recognised. Returns bare
    lowercased hostnames.
    """
    hosts = set()
    public = urlparse(getattr(django_settings, "PUBLIC_SERVER_ADDRESS", "") or "")
    if public.hostname:
        hosts.add(public.hostname.lower())
    for host in getattr(django_settings, "ALLOWED_HOSTS", []) or []:
        if host and host != "*":
            hosts.add(host.lower())
    return hosts


def _match_local_manifest(url):
    """Return the local manifest UUID iff ``url`` points at THIS server.

    Accepts a relative ``/manifest/{uuid}`` path or an absolute URL whose host
    is in ``get_local_hosts()``. Returns ``None`` for any other host (e.g.
    ``http://evil.com/manifest/{uuid}``) so it is handled as an external URL.
    The authority is ``urlparse(url).hostname`` (NOT the regex host group), so
    userinfo tricks like ``http://localhost@evil.com/...`` cannot bypass it.

    Does NO network I/O — a false-positive "local" is only origin confusion
    (still gated by the UUID-existence check), never SSRF. Never add a fetch
    into this path.
    """
    match = _LOCAL_MANIFEST_RE.match(url or "")
    if not match:
        return None
    hostname = urlparse(url).hostname
    if hostname and hostname.lower() not in get_local_hosts():
        return None
    return match.group("uuid")


class ManifestDataType(BaseDataType):
    @staticmethod
    def _normalize_url(url):
        """Strip the fragment and the trailing slash (``manifest_registry.normalize_url``)."""
        return manifest_registry.normalize_url(url)

    @staticmethod
    def _to_relative_path(url):
        """Extract the path of an absolute URL that targets THIS server.

        Local manifests are stored as relative paths (e.g. /manifest/{uuid}).
        An absolute URL is collapsed to its path ONLY when its host is one of
        ``get_local_hosts()``; a foreign host is returned unchanged so it is
        treated as external rather than silently mapped to a local path.
        """
        if not url:
            return url
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            if (parsed.hostname or "").lower() in get_local_hosts():
                return parsed.path.rstrip("/")
            return url
        return url

    @staticmethod
    def is_iiif_manifest(manifest_json):
        return manifest_registry.is_iiif_manifest(manifest_json)

    def validate(self, value, **kwargs):
        """Validate the manifest value without creating any DB records.

        Only checks format, URL reachability, and IIIF compliance.
        Creation is handled exclusively in pre_tile_save().
        """
        errors = []

        if value:
            manifest_id = None
            manifest_url = None

            if isinstance(value, dict):
                manifest_id = value.get("manifest_id")
                manifest_url = value.get("manifest_url")
                if not manifest_id and not manifest_url:
                    errors.append(
                        {
                            "type": "ERROR",
                            "message": _("Manifest must have a URL or ID"),
                        }
                    )
                    return errors

            elif isinstance(value, str):
                try:
                    uuid.UUID(value)
                    manifest_id = value
                except ValueError:
                    manifest_url = value

            if manifest_id:
                try:
                    IIIFManifest.objects.get(globalid=manifest_id)
                except IIIFManifest.DoesNotExist:
                    errors.append(
                        {"type": "ERROR", "message": _("Manifest ID does not exist")}
                    )

            elif manifest_url:
                manifest_url = self._normalize_url(manifest_url)

                # Case 1: local manifest reference (/manifest/{uuid} on our host)
                local_uuid = _match_local_manifest(manifest_url)
                if local_uuid is not None:
                    if not IIIFManifest.objects.filter(globalid=local_uuid).exists():
                        errors.append(
                            {
                                "type": "ERROR",
                                "message": _("Manifest not found"),
                            }
                        )
                    return errors

                # Case 2: external URL — cheap FORMAT gate only, NO network.
                # validate() must stay pure (it is also skipped on user-less
                # server saves), so reachability + IIIF compliance are checked
                # in pre_tile_save(), the side-effecting lifecycle hook.
                try:
                    _validate_url_format(manifest_url)
                except ValidationError:
                    errors.append({"type": "ERROR", "message": _("Invalid URL format")})

        return errors

    def pre_tile_save(self, tile, nodeid):
        """Ensure the IIIFManifest DB record exists and store local path.

        Always normalizes tile.data to a local relative path
        (/manifest/{globalid}) so all tiles point to the local server,
        regardless of whether the manifest was created locally or imported.
        """
        value = tile.data.get(str(nodeid))
        if not value or not isinstance(value, str):
            return

        # Skip UUIDs (legacy manifest_id references)
        try:
            uuid.UUID(value)
            return
        except ValueError:
            pass

        manifest_url = self._normalize_url(value)

        # 1. Already-known local manifest (relative path, or our own host).
        relative_path = self._to_relative_path(manifest_url)
        manifest = IIIFManifest.objects.filter(url=relative_path).first()
        if manifest:
            tile.data[str(nodeid)] = (
                manifest.url
                if manifest.url.startswith("/")
                else f"/manifest/{manifest.globalid}"
            )
            return

        # 2. External manifest already imported (stored by absolute URL).
        manifest = IIIFManifest.objects.filter(url=manifest_url).first()
        if manifest:
            tile.data[str(nodeid)] = f"/manifest/{manifest.globalid}"
            return

        # 3. New external manifest: every failure RAISES so the enclosing
        #    transaction.atomic() rolls back instead of committing a tile that
        #    points at an un-imported manifest.
        manifest, _created = manifest_registry.import_manifest(manifest_url)
        tile.data[str(nodeid)] = f"/manifest/{manifest.globalid}"

    def transform_value_for_tile(self, value, **kwargs):
        """Transform input value for tile storage. Returns a URL string."""
        if not value:
            return None

        if isinstance(value, dict):
            if "manifest_url" in value:
                return self._normalize_url(value["manifest_url"])
            return None

        if isinstance(value, str):
            return self._normalize_url(value)

    def transform_export_values(self, value, *args, **kwargs):
        return value

    def get_display_value(self, tile, node, **kwargs):
        # Search export passes tiles as plain dicts (ES _source), not Tile
        # instances — get_tile_data() handles both shapes.
        data = self.get_tile_data(tile)
        if data and str(node.nodeid) in data:
            value = data[str(node.nodeid)]
            if not value:
                return None
            try:
                db_url = self._to_relative_path(value)
                manifest = IIIFManifest.objects.get(url=db_url)
                result = f"{manifest.label}"
                if manifest.url:
                    result += f" ({manifest.url})"
                return result
            except (IIIFManifest.DoesNotExist, ValueError):
                return str(value)
        return None

    def clean(self, tile, nodeid):
        value = tile.data.get(str(nodeid))
        if value in ["", None]:
            tile.data[str(nodeid)] = None

    def _extract_manifest_label(self, manifest_json):
        return manifest_registry.extract_label(manifest_json)

    def _extract_manifest_description(self, manifest_json):
        return manifest_registry.extract_description(manifest_json)

    @classmethod
    def get_pref_label(cls):
        return "IIIF Manifest"

    def get_config_form_class(self):
        return None

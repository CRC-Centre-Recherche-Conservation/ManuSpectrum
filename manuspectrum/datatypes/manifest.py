import uuid
from urllib.parse import urlparse

from django.conf import settings as django_settings
from django.core.validators import ValidationError
from arches.app.datatypes.base import BaseDataType
from arches.app.models.models import IIIFManifest, Widget
from django.utils.translation import gettext_lazy as _

from manuspectrum.utils import manifest_registry
from manuspectrum.utils.manifest_registry import FailParsingManifestIIIF

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

                # Case 1: local manifest reference, by the rule pre_tile_save
                # applies (manifest_registry.local_row): /manifest/{uuid},
                # a language-prefixed copy or /iiif/manifest/{uuid}, relative
                # or on our host.
                lookup = self._to_relative_path(manifest_url) or manifest_url
                is_local, row = manifest_registry.local_row(lookup)
                if is_local:
                    if row is None:
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
                    manifest_registry.check_url_format(manifest_url)
                except ValidationError:
                    errors.append({"type": "ERROR", "message": _("Invalid URL format")})

        return errors

    def pre_tile_save(self, tile, nodeid):
        """Ensure the IIIFManifest DB record exists and store its local path.

        Always normalizes tile.data to a local relative path
        (/manifest/{globalid}) so all tiles point to the local server,
        regardless of whether the manifest was created locally or imported.
        The value is resolved in this order: a local reference by globalid,
        then a row already registered for the URL (as given, normalized or
        with a trailing slash; ``manifest_registry.find_registered``), then an
        import. A local reference whose globalid has no row is not fetched
        and fails. Every failure RAISES so the enclosing transaction.atomic()
        rolls back instead of committing a tile that points at an un-imported
        manifest.
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
        lookup = self._to_relative_path(manifest_url) or manifest_url
        manifest, outcome = manifest_registry.find_registered(lookup)
        if manifest is None and outcome is None and lookup != manifest_url:
            manifest, outcome = manifest_registry.find_registered(manifest_url)
        if manifest is None:
            if outcome == manifest_registry.LOCAL:
                raise FailParsingManifestIIIF(f"Manifest not found: {value}")
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

    @classmethod
    def get_pref_label(cls):
        return "IIIF Manifest"

    def get_config_form_class(self):
        return None

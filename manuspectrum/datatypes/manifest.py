import logging
import uuid
import re
import requests
from functools import lru_cache
from urllib.parse import urlparse, urlunparse

from django.conf import settings as django_settings
from arches.app.datatypes.base import BaseDataType
from arches.app.models.models import IIIFManifest, Widget
from django.utils.translation import gettext_lazy as _

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


logger = logging.getLogger(__name__)


class FailRegexURLMatch(Exception):
    pass


class FailParsingManifestIIIF(Exception):
    pass


class ManifestDataType(BaseDataType):
    @staticmethod
    @lru_cache(maxsize=1)
    def _get_request_headers():
        import arches

        app_name = getattr(django_settings, "APP_NAME", "Arches")
        app_version = getattr(django_settings, "APP_VERSION", "")
        arches_version = getattr(arches, "__version__", "")
        parts = [f"{app_name}/{app_version}" if app_version else app_name]
        if arches_version:
            parts.append(f"Arches/{arches_version}")
        return {
            "User-Agent": " ".join(parts),
            "Accept": "application/ld+json, application/json",
        }

    _LOCAL_MANIFEST_RE = re.compile(
        r"^(?:https?://[^/]+)?/manifest/"
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
        re.IGNORECASE,
    )

    _URL_REGEX_STRICT = re.compile(
        r"https?://"
        r"(www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}"
        r"\b([-a-zA-Z0-9()@:%_+.~#?&/=]*)"
    )
    _URL_REGEX_DEV = re.compile(
        r"https?://"
        r"("
        r"(www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}"
        r"|localhost"
        r"|(\d{1,3}\.){3}\d{1,3}"
        r")"
        r"(:\d{1,5})?"
        r"(/[-a-zA-Z0-9()@:%_+.~#?&/=]*)?"
    )

    @classmethod
    def _get_url_regex(cls):
        if django_settings.DEBUG:
            return cls._URL_REGEX_DEV
        return cls._URL_REGEX_STRICT

    @staticmethod
    def _normalize_url(url):
        """Normalize a URL to prevent duplicates from cosmetic differences.

        - Strips trailing slashes
        - Removes fragments (#...)
        - Returns the cleaned URL string
        """
        if not url:
            return url
        parsed = urlparse(url)
        # Remove fragment, strip trailing slash from path
        path = parsed.path.rstrip("/")
        normalized = urlunparse(
            (parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, "")
        )
        return normalized

    @staticmethod
    def _to_relative_path(url):
        """Extract the path portion of a URL for DB lookups.

        The manifest_manager stores URLs as relative paths (e.g. /manifest/{uuid}).
        The widget may send full URLs (e.g. http://host/manifest/{uuid}).
        """
        if not url:
            return url
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            return parsed.path.rstrip("/")
        return url

    @staticmethod
    def is_iiif_manifest(manifest_json):
        if not isinstance(manifest_json, dict):
            raise FailParsingManifestIIIF("Manifest JSON is not a dict")

        context = manifest_json.get("@context")

        if context and "iiif.io/api/presentation/2/context.json" in context:
            if manifest_json.get("@type") == "sc:Manifest":
                return True
            raise FailParsingManifestIIIF(
                "Missing or invalid @type for IIIF v2 manifest"
            )

        if context and "iiif.io/api/presentation/3/context.json" in context:
            if manifest_json.get("type") == "Manifest":
                return True
            raise FailParsingManifestIIIF(
                "Missing or invalid type for IIIF v3 manifest"
            )

        raise FailParsingManifestIIIF(
            "Not a recognized IIIF manifest (no valid @context)"
        )

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

                # Case 1: local manifest path (/manifest/{uuid})
                local_match = self._LOCAL_MANIFEST_RE.match(manifest_url)
                if local_match:
                    if not IIIFManifest.objects.filter(
                        globalid=local_match.group(1)
                    ).exists():
                        errors.append(
                            {
                                "type": "ERROR",
                                "message": _("Manifest not found"),
                            }
                        )
                    return errors

                # Case 2: external URL — validate format, fetch, check IIIF
                try:
                    if not self._get_url_regex().match(manifest_url):
                        raise FailRegexURLMatch()

                    resp = requests.get(
                        manifest_url,
                        timeout=5,
                        headers=self._get_request_headers(),
                    )
                    resp.raise_for_status()
                    manifest_json = resp.json()
                    self.is_iiif_manifest(manifest_json)
                except FailRegexURLMatch:
                    errors.append({"type": "ERROR", "message": _("Invalid URL format")})
                except requests.Timeout:
                    errors.append(
                        {
                            "type": "ERROR",
                            "message": _("Timeout while fetching manifest"),
                        }
                    )
                except FailParsingManifestIIIF as e:
                    errors.append(
                        {
                            "type": "ERROR",
                            "message": _(f"Invalid IIIF manifest: {str(e)}"),
                        }
                    )
                except Exception as e:
                    errors.append(
                        {"type": "ERROR", "message": _(f"Unexpected error: {str(e)}")}
                    )

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
        try:
            # 1. Try relative path lookup (local manifests from manifest_manager)
            relative_path = self._to_relative_path(manifest_url)
            manifest = IIIFManifest.objects.filter(url=relative_path).first()
            if manifest:
                tile.data[str(nodeid)] = manifest.url
                return

            # 2. Try full URL lookup (external manifests already imported)
            manifest = IIIFManifest.objects.filter(url=manifest_url).first()
            if manifest:
                tile.data[str(nodeid)] = f"/manifest/{manifest.globalid}"
                return

            # 3. Fetch and import new external manifest as local
            resp = requests.get(
                manifest_url, timeout=5, headers=self._get_request_headers()
            )
            resp.raise_for_status()
            manifest_json = resp.json()
            self.is_iiif_manifest(manifest_json)

            label = self._extract_manifest_label(manifest_json)
            desc = self._extract_manifest_description(manifest_json)

            new_globalid = uuid.uuid4()
            manifest = IIIFManifest.objects.create(
                globalid=new_globalid,
                url=f"/manifest/{new_globalid}",
                label=label or "IIIF Manifest",
                description=desc or "",
                manifest=manifest_json,
            )
            tile.data[str(nodeid)] = manifest.url
        except Exception as e:
            logger.warning("pre_tile_save manifest import failed: %s", e)

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
        if tile.data and str(node.nodeid) in tile.data:
            value = tile.data[str(node.nodeid)]
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
        if not manifest_json:
            return None
        label = manifest_json.get("label")
        if isinstance(label, dict):
            val = (
                label.get("en") or label.get("none") or next(iter(label.values()), None)
            )
            return val[0] if isinstance(val, list) and val else val
        if isinstance(label, list) and label:
            return label[0].get("@value") if isinstance(label[0], dict) else label[0]
        return str(label) if label else None

    def _extract_manifest_description(self, manifest_json):
        if not manifest_json:
            return None
        desc = manifest_json.get("description") or manifest_json.get("summary")
        if isinstance(desc, dict):
            val = desc.get("en") or desc.get("none") or next(iter(desc.values()), None)
            return val[0] if isinstance(val, list) and val else val
        if isinstance(desc, list) and desc:
            return desc[0].get("@value") if isinstance(desc[0], dict) else desc[0]
        return str(desc) if desc else None

    @classmethod
    def get_pref_label(cls):
        return "IIIF Manifest"

    def get_config_form_class(self):
        return None

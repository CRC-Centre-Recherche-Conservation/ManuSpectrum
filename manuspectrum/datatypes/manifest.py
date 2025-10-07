import uuid
import re
import requests

from arches.app.datatypes.base import BaseDataType
from arches.app.models.models import IIIFManifest, Widget
from django.utils.translation import gettext_lazy as _

text: Widget = Widget.objects.get(name="manifest-widget")

details: dict[str, str | Widget | bool | None] = {
    'datatype': 'manifest',
    'iconclass': 'fa fa-file-image-o',
    'modulename': 'manifest.py',
    'classname': 'ManifestDataType',
    'defaultwidget': text,
    'defaultconfig': None,
    'configcomponent': None,
    'configname': None,
    'isgeometric': False,
    'issearchable': False
}


class FailRegexURLMatch(Exception):
    pass


class FailParsingManifestIIIF(Exception):
    pass


class ManifestDataType(BaseDataType):
    URL_REGEX = re.compile(
        r"https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)"
    )

    @staticmethod
    def is_iiif_manifest(manifest_json):
        if not isinstance(manifest_json, dict):
            raise FailParsingManifestIIIF("Manifest JSON is not a dict")

        context = manifest_json.get("@context")

        if context and "iiif.io/api/presentation/2/context.json" in context:
            if manifest_json.get("@type") == "sc:Manifest":
                return True
            raise FailParsingManifestIIIF("Missing or invalid @type for IIIF v2 manifest")

        if context and "iiif.io/api/presentation/3/context.json" in context:
            if manifest_json.get("type") == "Manifest":
                return True
            raise FailParsingManifestIIIF("Missing or invalid type for IIIF v3 manifest")

        raise FailParsingManifestIIIF("Not a recognized IIIF manifest (no valid @context)")

    def validate(self, value, **kwargs):
        errors = []

        if value:
            manifest_id = None
            manifest_url = None

            if isinstance(value, dict):
                manifest_id = value.get('manifest_id')
                manifest_url = value.get('manifest_url')
                if not manifest_id and not manifest_url:
                    errors.append({'type': 'ERROR', 'message': _('Manifest must have a URL or ID')})
                    return errors

            elif isinstance(value, str):
                try:
                    uuid.UUID(value)
                    manifest_id = value
                except ValueError:
                    manifest_url = value

            if manifest_id:
                try:
                    IIIFManifest.objects.get(id=manifest_id)
                except IIIFManifest.DoesNotExist:
                    errors.append({'type': 'ERROR', 'message': _('Manifest ID does not exist')})

            elif manifest_url:
                try:
                    if not self.URL_REGEX.match(manifest_url):
                        raise FailRegexURLMatch()
                    resp = requests.get(manifest_url, timeout=5)
                    resp.raise_for_status()
                    manifest_json = resp.json()
                    self.is_iiif_manifest(manifest_json)

                    label = self._extract_manifest_label(manifest_json)
                    desc = self._extract_manifest_description(manifest_json)

                    IIIFManifest.objects.get_or_create(
                        url=manifest_url,
                        defaults={
                            'label': label or 'IIIF Manifest',
                            'description': desc or '',
                            'manifest': manifest_json
                        }
                    )
                except FailRegexURLMatch:
                    errors.append({'type': 'ERROR', 'message': _('Invalid URL format')})
                except requests.Timeout:
                    errors.append({'type': 'ERROR', 'message': _('Timeout while fetching manifest')})
                except FailParsingManifestIIIF as e:
                    errors.append({'type': 'ERROR', 'message': _(f'Invalid IIIF manifest: {str(e)}')})
                except Exception as e:
                    errors.append({'type': 'ERROR', 'message': _(f'Unexpected error: {str(e)}')})

        return errors

    def transform_value_for_tile(self, value, **kwargs):
        if not value:
            return None

        if isinstance(value, dict):
            if 'manifest_id' in value:
                return str(value['manifest_id'])
            elif 'manifest_url' in value:
                try:
                    manifest = IIIFManifest.objects.get(url=value['manifest_url'])
                    return str(manifest.id)
                except IIIFManifest.DoesNotExist:
                    return None

        elif isinstance(value, str):
            try:
                uuid.UUID(value)
                return value
            except ValueError:
                try:
                    manifest = IIIFManifest.objects.get(url=value)
                    return str(manifest.id)
                except IIIFManifest.DoesNotExist:
                    return None

    def transform_export_values(self, value, *args, **kwargs):
        return value

    def get_display_value(self, tile, node, **kwargs):
        if tile.data and str(node.nodeid) in tile.data:
            value = tile.data[str(node.nodeid)]
            try:
                manifest = IIIFManifest.objects.get(id=value)
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
        label = manifest_json.get('label')
        if isinstance(label, dict):
            val = label.get('en') or label.get('none') or next(iter(label.values()), None)
            return val[0] if isinstance(val, list) and val else val
        if isinstance(label, list) and label:
            return label[0].get('@value') if isinstance(label[0], dict) else label[0]
        return str(label) if label else None

    def _extract_manifest_description(self, manifest_json):
        if not manifest_json:
            return None
        desc = manifest_json.get('description') or manifest_json.get('summary')
        if isinstance(desc, dict):
            val = desc.get('en') or desc.get('none') or next(iter(desc.values()), None)
            return val[0] if isinstance(val, list) and val else val
        if isinstance(desc, list) and desc:
            return desc[0].get('@value') if isinstance(desc[0], dict) else desc[0]
        return str(desc) if desc else None

    @classmethod
    def get_pref_label(cls):
        return 'IIIF Manifest'

    def get_config_form_class(self):
        return None

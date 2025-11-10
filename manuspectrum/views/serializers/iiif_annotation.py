import logging
from arches.app.models.resource import Resource
from arches.app.models.tile import Tile
from arches.app.models.models import Value, IIIFManifest
from django.conf import settings

logger = logging.getLogger(__name__)


class IIIFAnnotationSerializer:
    """
    Builds a IIIF Presentation API v3 Annotation
    from internal Arches resource data.

    This serializer is used to represent analytical resources
    (datasets, manifests, instruments, etc.) as IIIF Annotations
    with multilingual metadata and links to related resources.
    """

    base_url = settings.PUBLIC_SERVER_ADDRESS
    base_url_iiif = base_url + "iiif"

    DATATYPE_NODES = {
        'manifest': '9764a2c7-fc1b-46dd-8b4a-8b86588a0294',
        'file_list': '8fe5161a-7bf2-11ef-b1e5-dd514ecd97bc',
        'technique': '3bcb6798-7b55-11ef-ba46-5b6797b92ed6',
        'instrument': '8fc653e6-7b53-11ef-ba46-5b6797b92ed6',
        'acquisition_date': '7da25ec4-a8be-11ef-8106-d32727aece17',
        'researchers': '482cf800-7b53-11ef-ba46-5b6797b92ed6',
        'component_observed': '9c807052-7b4f-11ef-ba46-5b6797b92ed6',
        'metadata_fields': 'b382167d-7b4c-11ef-ba46-5b6797b92ed6',
        'project': '80a46fd8-7b4e-11ef-ba46-5b6797b92ed6',
        'name': '020b3a16-7b4e-11ef-ba46-5b6797b92ed6',
        'mime_type': '2edf2f2a-e887-11ef-9bfc-0debd0685137',
        'dataset_uri': 'eae46252-7bf0-11ef-b1e5-dd514ecd97bc'
    }

    # ----------------------------------------------------------------------
    # Data extraction helpers
    # ----------------------------------------------------------------------

    @classmethod
    def _get_resource_tiles(cls, resource_id: str) -> dict:
        """Retrieve all tiles for a given resource instance and extract data."""
        tiles = Tile.objects.filter(resourceinstance_id=resource_id)
        data = {}

        for tile in tiles:
            if tile.data:
                for node_id, value in tile.data.items():
                    if value is not None:
                        data[node_id] = value
        return data

    @classmethod
    def _extract_resource_id(cls, value) -> str:
        """Extract the UUID from a resource-instance type value."""
        if isinstance(value, dict):
            return value.get('resourceId', '')
        elif isinstance(value, str):
            return value
        return ''

    # ----------------------------------------------------------------------
    # Concept and resource resolution
    # ----------------------------------------------------------------------

    @classmethod
    def _resolve_concept_multilingual(cls, concept_valueid: str) -> dict:
        """
        Resolve a concept value to multilingual labels with URI.
        Returns: {"uri": "...", "labels": {"en": "label", "fr": "étiquette"}}
        """
        try:
            values = Value.objects.filter(valueid=concept_valueid)
            labels, uri = {}, None

            for v in values:
                if v.value:
                    lang = getattr(v, 'language_id', 'en')
                    labels[lang] = v.value
                if getattr(v, 'concept', None):
                    uri = f"{cls.base_url}rdm/concepts/{v.concept.conceptid}"

            return {
                "uri": uri or f"{cls.base_url}rdm/concepts/values/{concept_valueid}",
                "labels": labels or {"en": str(concept_valueid)}
            }
        except Exception as e:
            logger.warning(f"Concept resolution failed for {concept_valueid}: {e}")
            return {
                "uri": f"{cls.base_url}rdm/concepts/values/{concept_valueid}",
                "labels": {"en": str(concept_valueid)}
            }

    @classmethod
    def _resolve_resource_multilingual(cls, resource_id: str) -> dict:
        """
        Resolve a resource instance to multilingual labels with URI.
        Returns: {"uri": "...", "labels": {"en": "label", "fr": "étiquette"}}
        """
        try:
            resource = Resource.objects.get(resourceinstanceid=resource_id)
            uri = f"{cls.base_url}resources/{resource_id}"
            displayname = resource.displayname() if callable(resource.displayname) else resource.displayname

            if isinstance(displayname, dict):
                labels = {
                    lang: info["value"]
                    for lang, info in displayname.items()
                    if isinstance(info, dict) and info.get("value")
                }
                return {"uri": uri, "labels": labels}

            return {"uri": uri, "labels": {"en": str(displayname)}}

        except Resource.DoesNotExist:
            logger.info(f"Referenced resource not found: {resource_id}")
            return {"uri": f"{cls.base_url}resources/{resource_id}", "labels": {"en": str(resource_id)}}
        except Exception as e:
            logger.warning(f"Resource resolution failed for {resource_id}: {e}")
            return {"uri": f"{cls.base_url}resources/{resource_id}", "labels": {"en": str(resource_id)}}

    # ----------------------------------------------------------------------
    # Value formatting helpers
    # ----------------------------------------------------------------------

    @classmethod
    def _get_localized_string(cls, data: dict) -> dict:
        """Extract localized strings from a multilingual value."""
        if isinstance(data, dict):
            return {
                lang: [info["value"]]
                for lang, info in data.items()
                if isinstance(info, dict) and info.get("value", "").strip()
            }
        return {"en": [str(data)]}

    # ----------------------------------------------------------------------
    # IIIF Body, Metadata, and SeeAlso builders
    # ----------------------------------------------------------------------

    @classmethod
    def _build_body(cls, tiles_data: dict | str) -> dict:
        """Builds the IIIF `body` based on the available datatype nodes."""
        manifest_node = cls.DATATYPE_NODES.get('manifest')
        if manifest_node and manifest_node in tiles_data:
            manifest_url = tiles_data[manifest_node]
            try:
                manifest_resource = IIIFManifest.objects.get(url=manifest_url)
                return {
                    "id": manifest_url,
                    "type": "Manifest",
                    "format": "application/ld+json",
                    "label": {"en": manifest_resource.label},
                }
            except IIIFManifest.DoesNotExist:
                logger.info(f"Manifest not found for URL: {manifest_url}")

        filelist_node = cls.DATATYPE_NODES.get('file_list')
        if filelist_node and filelist_node in tiles_data:
            file_data = tiles_data[filelist_node]
            if isinstance(file_data, list) and file_data:
                first_file = file_data[0]
                mime_type = tiles_data.get(cls.DATATYPE_NODES.get('mime_type'), 'application/octet-stream')
                name_node = cls.DATATYPE_NODES.get('name')
                label = cls._get_localized_string(tiles_data.get(name_node, {"en": {"value": "Dataset file"}}))
                return {
                    "id": settings.PUBLIC_SERVER_ADDRESS + first_file.get('url', '').lstrip('/'),
                    "type": "Dataset",
                    "format": mime_type,
                    "label": label,
                }

        # Default textual body
        name_node = cls.DATATYPE_NODES.get('name')
        value = "No data available"
        if name_node and name_node in tiles_data:
            name_data = tiles_data[name_node]
            if isinstance(name_data, dict):
                for lang_info in name_data.values():
                    if isinstance(lang_info, dict) and lang_info.get("value"):
                        value = lang_info["value"]
                        break

        return {"type": "TextualBody", "value": value, "format": "text/plain", "language": "fr"}

    @classmethod
    def _format_metadata_value(cls, raw_value, field_key: str) -> dict:
        """Format a metadata field according to its data type."""
        # Concept lists
        if field_key == 'technique':
            if isinstance(raw_value, list):
                all_labels = {}
                for concept_id in raw_value:
                    concept_data = cls._resolve_concept_multilingual(concept_id)
                    for lang, label in concept_data['labels'].items():
                        all_labels.setdefault(lang, []).append(f"{label} ({concept_data['uri']})")
                return all_labels or {"en": [str(raw_value)]}

        # Resource-instance fields
        if field_key in ['instrument', 'component_observed', 'project']:
            all_labels = {}
            items = raw_value if isinstance(raw_value, list) else [raw_value]
            for item in items:
                resource_id = cls._extract_resource_id(item)
                if resource_id:
                    res_data = cls._resolve_resource_multilingual(resource_id)
                    for lang, label in res_data['labels'].items():
                        all_labels.setdefault(lang, []).append(f"{label} ({res_data['uri']})")
            return all_labels or {"en": [str(raw_value)]}

        # Researchers (join names)
        if field_key == 'researchers':
            all_names = {}
            items = raw_value if isinstance(raw_value, list) else [raw_value]
            for item in items:
                resource_id = cls._extract_resource_id(item)
                if resource_id:
                    res_data = cls._resolve_resource_multilingual(resource_id)
                    for lang, label in res_data['labels'].items():
                        all_names.setdefault(lang, []).append(label)
            return {lang: ["; ".join(names)] for lang, names in all_names.items()} or {"en": [str(raw_value)]}

        # Date fields
        if field_key == 'acquisition_date':
            return {"en": [str(raw_value)]}

        # Localized strings
        if isinstance(raw_value, dict):
            return {
                lang: [info["value"]]
                for lang, info in raw_value.items()
                if isinstance(info, dict) and info.get("value")
            } or {"en": [str(raw_value)]}

        return {"en": [str(raw_value)]}

    @classmethod
    def _build_metadata(cls, tiles_data: dict) -> list:
        """Builds the IIIF `metadata` section."""
        metadata = []
        fields = {
            'technique': 'Technique',
            'instrument': 'Instrument',
            'project': 'Project',
            'acquisition_date': 'Acquisition date',
            'researchers': 'Researchers',
            'component_observed': 'Component observed',
        }

        for field, label in fields.items():
            node = cls.DATATYPE_NODES.get(field)
            if node and node in tiles_data and tiles_data[node]:
                try:
                    formatted_value = cls._format_metadata_value(tiles_data[node], field)
                    metadata.append({"label": {"en": [label]}, "value": formatted_value})
                except Exception as e:
                    logger.warning(f"Failed to format metadata field '{field}': {e}")

        # Instrumental metadata
        meta_node = cls.DATATYPE_NODES.get('metadata_fields')
        if meta_node and meta_node in tiles_data:
            instr_data = tiles_data[meta_node]
            if isinstance(instr_data, dict):
                value_dict = {
                    lang: [info["value"]]
                    for lang, info in instr_data.items()
                    if isinstance(info, dict) and info.get("value")
                }
                metadata.append({"label": {"en": ["Instrumental metadata"]}, "value": value_dict})
            else:
                metadata.append({"label": {"en": ["Instrumental metadata"]}, "value": {"en": [str(instr_data)]}})

        return metadata

    @classmethod
    def _build_see_also(cls, tiles_data: dict, analysis_id: str) -> list:
        """Builds the IIIF `seeAlso` section with related links."""
        see_also = [{
            "id": f"{cls.base_url}report/{analysis_id}",
            "type": "Text",
            "format": "text/html",
            "label": {"en": ["Detailed analysis report"]},
        }]

        doi_node = cls.DATATYPE_NODES.get('dataset_uri')
        if doi_node and doi_node in tiles_data and tiles_data[doi_node]:
            uri = tiles_data[doi_node]
            see_also.append({
                "id": uri,
                "type": "Dataset",
                "format": "text/html",
                "label": {"en": ["Published dataset"]},
            })

        return see_also

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------

    @classmethod
    def to_representation(cls, target: str, resource_id: str) -> dict:
        """
        Build a full IIIF Annotation representation for a given Arches resource.

        Args:
            target (str): The IIIF target (e.g., Canvas URL).
            resource_id (str): The Arches resource UUID.

        Returns:
            dict: A IIIF Presentation API v3 compliant annotation.
        """
        annotation = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "id": f"{cls.base_url_iiif}/annotation/{resource_id}",
            "type": "Annotation",
            "motivation": "supplementing",
            "target": target,
        }

        if not resource_id:
            annotation["body"] = {"type": "TextualBody",
                                  "value": "No data available",
                                  "format": "text/plain",
                                  "language": "fr"}
            return annotation

        tiles_data = cls._get_resource_tiles(resource_id)

        label_node = cls.DATATYPE_NODES.get('name')
        if label_node and label_node in tiles_data:
            annotation["label"] = cls._get_localized_string(tiles_data[label_node])

        annotation["body"] = cls._build_body(tiles_data)

        metadata = cls._build_metadata(tiles_data)
        if metadata:
            annotation["metadata"] = metadata

        see_also = cls._build_see_also(tiles_data, resource_id)
        if see_also:
            annotation["seeAlso"] = see_also

        return annotation

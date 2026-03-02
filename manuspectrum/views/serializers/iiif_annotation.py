import logging
from typing import Dict, List

from django.conf import settings
from arches.app.models.resource import Resource
from arches.app.models.tile import Tile
from arches.app.models.models import Value, IIIFManifest

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

    @classmethod
    def _to_full_manifest_url(cls, url: str) -> str:
        """Convert a relative manifest path to a full URL.

        Tiles from Manifest Datatype store relative paths like /manifest/{uuid}.
        """
        if not url:
            return url
        if url.startswith("/"):
            return cls.base_url.rstrip("/") + url
        return url

    DATATYPE_NODES = {
        "manifest": "9764a2c7-fc1b-46dd-8b4a-8b86588a0294",
        "file_list": "8fe5161a-7bf2-11ef-b1e5-dd514ecd97bc",
        "technique": "3bcb6798-7b55-11ef-ba46-5b6797b92ed6",
        "instrument": "8fc653e6-7b53-11ef-ba46-5b6797b92ed6",
        "acquisition_date": "7da25ec4-a8be-11ef-8106-d32727aece17",
        "researchers": "482cf800-7b53-11ef-ba46-5b6797b92ed6",
        "component_observed": "9c807052-7b4f-11ef-ba46-5b6797b92ed6",
        "metadata_fields": "b382167d-7b4c-11ef-ba46-5b6797b92ed6",
        "project": "80a46fd8-7b4e-11ef-ba46-5b6797b92ed6",
        "name": "020b3a16-7b4e-11ef-ba46-5b6797b92ed6",
        "mime_type": "2edf2f2a-e887-11ef-9bfc-0debd0685137",
        "dataset_uri": "eae46252-7bf0-11ef-b1e5-dd514ecd97bc",
    }

    # caches batch
    _batch_mode: bool = False
    _concept_cache: Dict[str, dict] = {}
    _resource_cache: Dict[str, dict] = {}
    _manifest_cache: Dict[str, dict] = {}  # url -> {"label": ...}
    _tiles_cache: Dict[str, dict] = {}

    # ----------------------------------------------------------------------
    # Data extraction helpers
    # ----------------------------------------------------------------------

    @classmethod
    def _get_resource_tiles(cls, resource_id: str) -> dict:
        """
        Returns the tiles of a resource:
        - In batch mode: data comes from _tiles_cache (0 queries)
        - Outside batch mode: a single targeted query.
        """
        if resource_id in cls._tiles_cache:
            return cls._tiles_cache[resource_id]

        tiles_qs = Tile.objects.filter(resourceinstance_id=resource_id).values(
            "resourceinstance_id", "data"
        )

        data: dict = {}
        for row in tiles_qs:
            tile_data = row.get("data") or {}
            for node_id, value in tile_data.items():
                if value is not None:
                    data[node_id] = value

        cls._tiles_cache[resource_id] = data
        return data

    @classmethod
    def _extract_resource_id(cls, value) -> str:
        """Extract the UUID from a resource-instance type value."""
        if isinstance(value, dict):
            return value.get("resourceId", "")
        if isinstance(value, str):
            return value
        return ""

    # ----------------------------------------------------------------------
    # Concept and resource resolution
    # ----------------------------------------------------------------------

    @classmethod
    def _resolve_concept_multilingual(cls, concept_valueid: str) -> dict:
        """
        Resolve a concept value to multilingual labels with URI.
        Returns: {"uri": "...", "labels": {"en": "label", "fr": "étiquette"}}
        """
        if concept_valueid in cls._concept_cache:
            return cls._concept_cache[concept_valueid]

        if cls._batch_mode:
            result = {
                "uri": f"{cls.base_url}rdm/concepts/values/{concept_valueid}",
                "labels": {"en": str(concept_valueid)},
            }
            cls._concept_cache[concept_valueid] = result
            return result

        # Single mode (annotation only)
        try:
            values = (
                Value.objects.filter(valueid=concept_valueid)
                .select_related("concept")
                .values("valueid", "language_id", "value", "concept__conceptid")
            )

            labels: dict = {}
            uri = None

            for v in values:
                val = v.get("value")
                if val:
                    lang = v.get("language_id") or "en"
                    labels[lang] = val
                concept_id = v.get("concept__conceptid")
                if concept_id and not uri:
                    uri = f"{cls.base_url}rdm/concepts/{concept_id}"

            result = {
                "uri": uri or f"{cls.base_url}rdm/concepts/values/{concept_valueid}",
                "labels": labels or {"en": str(concept_valueid)},
            }
            cls._concept_cache[concept_valueid] = result
            return result

        except Exception as e:
            logger.warning(f"Concept resolution failed for {concept_valueid}: {e}")
            result = {
                "uri": f"{cls.base_url}rdm/concepts/values/{concept_valueid}",
                "labels": {"en": str(concept_valueid)},
            }
            cls._concept_cache[concept_valueid] = result
            return result

    @classmethod
    def _resolve_resource_multilingual(cls, resource_id: str) -> dict:
        """
        Resolve a resource instance to multilingual labels with URI.
        Returns: {"uri": "...", "labels": {"en": "label", "fr": "étiquette"}}
        """
        if resource_id in cls._resource_cache:
            return cls._resource_cache[resource_id]

        if cls._batch_mode:
            result = {
                "uri": f"{cls.base_url}resources/{resource_id}",
                "labels": {"en": str(resource_id)},
            }
            cls._resource_cache[resource_id] = result
            return result

        # "single" mode
        try:
            resource = Resource.objects.get(resourceinstanceid=resource_id)
            uri = f"{cls.base_url}resources/{resource_id}"

            displayname = (
                resource.displayname()
                if callable(resource.displayname)
                else resource.displayname
            )
            if isinstance(displayname, dict):
                labels = {
                    lang: info["value"]
                    for lang, info in displayname.items()
                    if isinstance(info, dict) and info.get("value")
                }
            else:
                labels = {"en": str(displayname)}

            result = {"uri": uri, "labels": labels}
            cls._resource_cache[resource_id] = result
            return result

        except Resource.DoesNotExist:
            logger.info(f"Referenced resource not found: {resource_id}")
        except Exception as e:  # pragma: no cover
            logger.warning(f"Resource resolution failed for {resource_id}: {e}")

        result = {
            "uri": f"{cls.base_url}resources/{resource_id}",
            "labels": {"en": str(resource_id)},
        }
        cls._resource_cache[resource_id] = result
        return result

    # ----------------------------------------------------------------------
    # Batch processing methods
    # ----------------------------------------------------------------------

    @classmethod
    def batch_to_representation(cls, annotations_data: List[Dict]) -> List[Dict]:
        """
        Process multiple annotations in batch to optimize queries.

        Args:
            annotations_data: List of dicts with 'target', 'resource_id',
                              and optionally 'canvas_uri' and 'manifest_url'

        Returns:
            List of IIIF annotation representations
        """
        resource_ids = [
            a["resource_id"] for a in annotations_data if a.get("resource_id")
        ]

        cls._batch_mode = True
        try:
            cls._prefetch_all_data(resource_ids)

            results: List[dict] = []
            for anno_data in annotations_data:
                results.append(
                    cls.to_representation(
                        anno_data["target"],
                        anno_data["resource_id"],
                        canvas_uri=anno_data.get("canvas_uri"),
                        manifest_url=anno_data.get("manifest_url"),
                    )
                )
        finally:
            # clean for future request
            cls._batch_mode = False
            cls._clear_caches()

        return results

    @classmethod
    def _prefetch_all_data(cls, resource_ids: List[str]):
        """Prefetch all needed data in minimal queries."""
        if not resource_ids:
            return

        # 1. TILES : only on request
        tiles_qs = Tile.objects.filter(resourceinstance_id__in=resource_ids).values(
            "resourceinstance_id", "data"
        )

        tiles_by_resource: Dict[str, dict] = {}
        for row in tiles_qs:
            rid = str(row["resourceinstance_id"])
            tile_data = row.get("data") or {}
            if rid not in tiles_by_resource:
                tiles_by_resource[rid] = {}
            for node_id, value in tile_data.items():
                if value is not None:
                    tiles_by_resource[rid][node_id] = value

        cls._tiles_cache = tiles_by_resource

        # 2. Collect IDs of concepts, resources, manifests
        all_concept_ids: set[str] = set()
        all_referenced_resource_ids: set[str] = set()
        all_manifest_urls: set[str] = set()

        technique_node = cls.DATATYPE_NODES["technique"]
        manifest_node = cls.DATATYPE_NODES["manifest"]

        for rid, tile_data in tiles_by_resource.items():
            # Technics(concepts)
            if technique_node in tile_data:
                tech_values = tile_data[technique_node]
                if isinstance(tech_values, list):
                    all_concept_ids.update(str(v) for v in tech_values if v)

            # Resources
            for field in ["instrument", "component_observed", "project", "researchers"]:
                node = cls.DATATYPE_NODES.get(field)
                if not node or node not in tile_data or not tile_data[node]:
                    continue
                values = tile_data[node]
                if not isinstance(values, list):
                    values = [values]
                for v in values:
                    res_id = cls._extract_resource_id(v)
                    if res_id:
                        all_referenced_resource_ids.add(res_id)

            # Manifest
            if manifest_node in tile_data and tile_data[manifest_node]:
                all_manifest_urls.add(tile_data[manifest_node])

        # 3. Batch load of concepts
        if all_concept_ids:
            cls._batch_load_concepts(list(all_concept_ids))

        # 4. Batch load of resources
        if all_referenced_resource_ids:
            cls._batch_load_resources(list(all_referenced_resource_ids))

        # 5. Batch load of manifests
        if all_manifest_urls:
            cls._batch_load_manifests(list(all_manifest_urls))

    @classmethod
    def _batch_load_concepts(cls, concept_ids: List[str]):
        """Load all concepts and their translations in one query."""
        values = (
            Value.objects.filter(valueid__in=concept_ids)
            .select_related("concept")
            .values("valueid", "language_id", "value", "concept__conceptid")
        )

        concepts_data: Dict[str, dict] = {}
        for v in values:
            vid = str(v["valueid"])
            concepts_data.setdefault(vid, {"labels": {}, "uri": None})

            val = v.get("value")
            if val:
                lang = v.get("language_id") or "en"
                concepts_data[vid]["labels"][lang] = val

            concept_id = v.get("concept__conceptid")
            if concept_id and not concepts_data[vid]["uri"]:
                concepts_data[vid]["uri"] = f"{cls.base_url}rdm/concepts/{concept_id}"

        for cid in concept_ids:
            if cid not in concepts_data:
                concepts_data[cid] = {
                    "uri": f"{cls.base_url}rdm/concepts/values/{cid}",
                    "labels": {"en": str(cid)},
                }
            elif not concepts_data[cid]["uri"]:
                concepts_data[cid]["uri"] = f"{cls.base_url}rdm/concepts/values/{cid}"

        cls._concept_cache = concepts_data

    @classmethod
    def _batch_load_resources(cls, resource_ids: List[str]):
        """Load all resources in one query."""
        resources = Resource.objects.filter(resourceinstanceid__in=resource_ids)

        cache_data: Dict[str, dict] = {}
        for resource in resources:
            rid = str(resource.resourceinstanceid)
            uri = f"{cls.base_url}resources/{rid}"

            displayname = (
                resource.displayname()
                if callable(resource.displayname)
                else resource.displayname
            )
            if isinstance(displayname, dict):
                labels = {
                    lang: info["value"]
                    for lang, info in displayname.items()
                    if isinstance(info, dict) and info.get("value")
                }
            else:
                labels = {"en": str(displayname)}

            cache_data[rid] = {
                "uri": uri,
                "labels": labels,
            }

        for rid in resource_ids:
            if rid not in cache_data:
                cache_data[rid] = {
                    "uri": f"{cls.base_url}resources/{rid}",
                    "labels": {"en": str(rid)},
                }

        cls._resource_cache = cache_data

    @classmethod
    def _batch_load_manifests(cls, manifest_urls: List[str]):
        """Load all manifests in one query, handling both full URLs and relative paths."""
        from urllib.parse import urlparse

        # Build list of all URL variants to search (full URLs + relative paths)
        all_variants = set(manifest_urls)
        url_to_relative = {}
        for url in manifest_urls:
            if url.startswith(("http://", "https://")):
                relative_path = urlparse(url).path
                if relative_path:
                    all_variants.add(relative_path)
                    url_to_relative[url] = relative_path

        manifests = IIIFManifest.objects.filter(url__in=list(all_variants)).values(
            "url", "label"
        )
        cache = {m["url"]: {"label": m["label"]} for m in manifests}

        # Map original full URLs to their data (found via relative path)
        for full_url, relative_path in url_to_relative.items():
            if full_url not in cache and relative_path in cache:
                cache[full_url] = cache[relative_path]

        cls._manifest_cache = cache

    @classmethod
    def _clear_caches(cls):
        """Clear all batch caches."""
        cls._concept_cache.clear()
        cls._resource_cache.clear()
        cls._manifest_cache.clear()
        cls._tiles_cache.clear()

    # ----------------------------------------------------------------------
    # Value & label helpers
    # ----------------------------------------------------------------------

    @classmethod
    def _get_localized_string(cls, data: dict) -> dict:
        """Extract localized strings from a multilingual value."""
        if isinstance(data, dict):
            out = {
                lang: [info["value"]]
                for lang, info in data.items()
                if isinstance(info, dict) and info.get("value", "").strip()
            }
            if out:
                return out
        return {"en": [str(data)]}

    # ----------------------------------------------------------------------
    # IIIF Body, Metadata, and SeeAlso builders
    # ----------------------------------------------------------------------

    @classmethod
    def _build_body(cls, tiles_data: dict) -> dict | list:
        """
        Builds the IIIF `body` based on the available datatype nodes.

        Returns a single body dict if only one, or a list if multiple.
        Per IIIF spec, body can be either a single resource or an array.
        """
        bodies: List[dict] = []

        # 1) Manifest(s)
        manifest_body = cls._build_manifest_body(tiles_data)
        if manifest_body:
            bodies.append(manifest_body)

        # 2) Dataset files (can be multiple)
        file_bodies = cls._build_file_bodies(tiles_data)
        bodies.extend(file_bodies)

        # 3) Fallback: TextualBody if no other body found
        if not bodies:
            name_node = cls.DATATYPE_NODES.get("name")
            value = "No data available"
            if name_node and name_node in tiles_data:
                name_data = tiles_data[name_node]
                if isinstance(name_data, dict):
                    for lang_info in name_data.values():
                        if isinstance(lang_info, dict) and lang_info.get("value"):
                            value = lang_info["value"]
                            break

            bodies.append(
                {
                    "type": "TextualBody",
                    "value": value,
                    "format": "text/plain",
                    "language": "fr",
                }
            )

        # Return single object if only one, list if multiple (cleaner JSON output)
        return bodies[0] if len(bodies) == 1 else bodies

    @classmethod
    def _build_manifest_body(cls, tiles_data: dict) -> dict | None:
        """Build a Manifest body if present in tiles data."""
        manifest_node = cls.DATATYPE_NODES.get("manifest")
        if not manifest_node or manifest_node not in tiles_data:
            return None

        manifest_url = tiles_data[manifest_node]
        if not manifest_url:
            return None

        full_url = cls._to_full_manifest_url(manifest_url)

        # Check cache first
        if manifest_url in cls._manifest_cache:
            manifest_resource = cls._manifest_cache[manifest_url]
            label = manifest_resource["label"]
            return {
                "id": full_url,
                "type": "Manifest",
                "format": "application/ld+json",
                "label": {"en": [label] if label else ["Manifest"]},
            }

        # Outside batch, fallback: try exact URL then relative path
        if not cls._batch_mode:
            from urllib.parse import urlparse

            urls_to_try = [manifest_url]
            if manifest_url.startswith(("http://", "https://")):
                relative_path = urlparse(manifest_url).path
                if relative_path:
                    urls_to_try.append(relative_path)

            for url_variant in urls_to_try:
                try:
                    m = IIIFManifest.objects.get(url=url_variant)
                    return {
                        "id": full_url,
                        "type": "Manifest",
                        "format": "application/ld+json",
                        "label": {"en": [m.label] if m.label else ["Manifest"]},
                    }
                except IIIFManifest.DoesNotExist:
                    continue

            logger.info(f"Manifest not found for URL: {manifest_url}")

        return None

    @classmethod
    def _build_file_bodies(cls, tiles_data: dict) -> List[dict]:
        """Build Dataset bodies for all files in file_list."""
        bodies: List[dict] = []

        filelist_node = cls.DATATYPE_NODES.get("file_list")
        if not filelist_node or filelist_node not in tiles_data:
            return bodies

        file_data = tiles_data[filelist_node]
        if not isinstance(file_data, list) or not file_data:
            return bodies

        mime_type = tiles_data.get(
            cls.DATATYPE_NODES.get("mime_type"),
            "application/octet-stream",
        )
        name_node = cls.DATATYPE_NODES.get("name")
        base_label = cls._get_localized_string(
            tiles_data.get(name_node, {"en": {"value": "Dataset file"}})
        )

        for idx, file_item in enumerate(file_data):
            file_url = file_item.get("url", "")
            if not file_url:
                continue

            # Add index to label if multiple files
            if len(file_data) > 1:
                label = {
                    lang: [f"{vals[0]} ({idx + 1}/{len(file_data)})"]
                    for lang, vals in base_label.items()
                }
            else:
                label = base_label

            bodies.append(
                {
                    "id": settings.PUBLIC_SERVER_ADDRESS + file_url.lstrip("/"),
                    "type": "Dataset",
                    "format": mime_type,
                    "label": label,
                }
            )

        return bodies

    # ----------------------------------------------------------------------
    # Metadata helpers
    # ----------------------------------------------------------------------

    @classmethod
    def _format_metadata_value(cls, raw_value, field_key: str) -> dict:
        """Format a metadata field according to its data type."""
        # Concept lists
        if field_key == "technique":
            if isinstance(raw_value, list):
                all_labels: Dict[str, List[str]] = {}
                for concept_id in raw_value:
                    concept_data = cls._resolve_concept_multilingual(str(concept_id))
                    for lang, label in concept_data["labels"].items():
                        all_labels.setdefault(lang, []).append(
                            f"{label} ({concept_data['uri']})"
                        )
                return all_labels or {"en": [str(raw_value)]}

        # Resource-instance fields
        if field_key in ["instrument", "component_observed", "project"]:
            all_labels: Dict[str, List[str]] = {}
            items = raw_value if isinstance(raw_value, list) else [raw_value]
            for item in items:
                resource_id = cls._extract_resource_id(item)
                if resource_id:
                    res_data = cls._resolve_resource_multilingual(resource_id)
                    for lang, label in res_data["labels"].items():
                        all_labels.setdefault(lang, []).append(
                            f"{label} ({res_data['uri']})"
                        )
            return all_labels or {"en": [str(raw_value)]}

        # Researchers
        if field_key == "researchers":
            all_names: Dict[str, List[str]] = {}
            items = raw_value if isinstance(raw_value, list) else [raw_value]
            for item in items:
                resource_id = cls._extract_resource_id(item)
                if resource_id:
                    res_data = cls._resolve_resource_multilingual(resource_id)
                    for lang, label in res_data["labels"].items():
                        all_names.setdefault(lang, []).append(label)
            if all_names:
                return {lang: ["; ".join(names)] for lang, names in all_names.items()}
            return {"en": [str(raw_value)]}

        # Date
        if field_key == "acquisition_date":
            return {"en": [str(raw_value)]}

        # Localized strings
        if isinstance(raw_value, dict):
            out = {
                lang: [info["value"]]
                for lang, info in raw_value.items()
                if isinstance(info, dict) and info.get("value")
            }
            if out:
                return out

        return {"en": [str(raw_value)]}

    @classmethod
    def _build_metadata(cls, tiles_data: dict) -> list:
        """Builds the IIIF `metadata` section."""
        metadata: List[dict] = []

        fields = {
            "technique": "Technique",
            "instrument": "Instrument",
            "project": "Project",
            "acquisition_date": "Acquisition date",
            "researchers": "Researchers",
            "component_observed": "Component observed",
        }

        for field, label in fields.items():
            node = cls.DATATYPE_NODES.get(field)
            if node and node in tiles_data and tiles_data[node]:
                try:
                    formatted_value = cls._format_metadata_value(
                        tiles_data[node], field
                    )
                    metadata.append(
                        {
                            "label": {"en": [label]},
                            "value": formatted_value,
                        }
                    )
                except Exception as e:  # pragma: no cover
                    logger.warning(f"Failed to format metadata field '{field}': {e}")

        # Instrumental metadata
        meta_node = cls.DATATYPE_NODES.get("metadata_fields")
        if meta_node and meta_node in tiles_data:
            instr_data = tiles_data[meta_node]
            if isinstance(instr_data, dict):
                value_dict = {
                    lang: [info["value"]]
                    for lang, info in instr_data.items()
                    if isinstance(info, dict) and info.get("value")
                }
                metadata.append(
                    {
                        "label": {"en": ["Instrumental metadata"]},
                        "value": value_dict,
                    }
                )
            else:
                metadata.append(
                    {
                        "label": {"en": ["Instrumental metadata"]},
                        "value": {"en": [str(instr_data)]},
                    }
                )

        return metadata

    @classmethod
    def _build_see_also(cls, tiles_data: dict, analysis_id: str) -> list:
        """Builds the IIIF `seeAlso` section with related links."""
        see_also = [
            {
                "id": f"{cls.base_url}report/{analysis_id}",
                "type": "Text",
                "format": "text/html",
                "label": {"en": ["Detailed analysis report"]},
            }
        ]

        doi_node = cls.DATATYPE_NODES.get("dataset_uri")
        if doi_node and doi_node in tiles_data and tiles_data[doi_node]:
            uri = tiles_data[doi_node]
            see_also.append(
                {
                    "id": uri,
                    "type": "Dataset",
                    "format": "text/html",
                    "label": {"en": ["Published dataset"]},
                }
            )

        return see_also

    # ----------------------------------------------------------------------
    # Target builder
    # ----------------------------------------------------------------------

    @classmethod
    def _build_target(
        cls,
        target_string: str,
        canvas_uri: str | None = None,
        manifest_url: str | None = None,
    ) -> dict | str:
        """
        Build a IIIF SpecificResource target from a target string.

        Args:
            target_string: The target URL, possibly with #xywh fragment
            canvas_uri: The canvas URI (without fragment)
            manifest_url: The manifest URL

        Returns:
            dict: A IIIF SpecificResource target, or str if no fragment
        """
        if not target_string:
            return target_string

        # Parse the target string to extract canvas and fragment
        fragment = None
        base_canvas = canvas_uri

        if "#" in target_string:
            parts = target_string.split("#", 1)
            if not base_canvas:
                base_canvas = parts[0]
            fragment = parts[1] if len(parts) > 1 else None
        elif not base_canvas:
            base_canvas = target_string

        # If no fragment, return simple target (just the canvas URI)
        if not fragment:
            return base_canvas or target_string

        # Build the SpecificResource target
        source: dict = {
            "id": base_canvas,
            "type": "Canvas",
        }

        # Add partOf with manifest reference if available
        if manifest_url:
            source["partOf"] = [
                {
                    "id": manifest_url,
                    "type": "Manifest",
                }
            ]

        target: dict = {
            "type": "SpecificResource",
            "source": source,
            "selector": {
                "type": "FragmentSelector",
                "conformsTo": "http://www.w3.org/TR/media-frags/",
                "value": fragment,
            },
        }

        return target

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------

    @classmethod
    def to_representation(
        cls,
        target: str,
        resource_id: str,
        canvas_uri: str | None = None,
        manifest_url: str | None = None,
    ) -> dict:
        """
        Build a full IIIF Annotation representation for a given Arches resource.

        Args:
            target (str): The IIIF target (e.g., Canvas URL + #xywh).
            resource_id (str): The Arches resource UUID.
            canvas_uri (str, optional): The canvas URI (without fragment).
            manifest_url (str, optional): The manifest URL for partOf reference.

        Returns:
            dict: A IIIF Presentation API v3 compliant annotation.
        """
        # Build structured target
        structured_target = cls._build_target(target, canvas_uri, manifest_url)

        annotation: dict = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "id": f"{cls.base_url_iiif}/v3/annotation/{resource_id}",
            "type": "Annotation",
            "motivation": "supplementing",
            "target": structured_target,
        }

        if not resource_id:
            annotation["body"] = {
                "type": "TextualBody",
                "value": "No data available",
                "format": "text/plain",
                "language": "fr",
            }
            return annotation

        tiles_data = cls._get_resource_tiles(resource_id)

        label_node = cls.DATATYPE_NODES.get("name")
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


class IIIFAnnotationSerializerV2(IIIFAnnotationSerializer):
    """
    Builds a IIIF Presentation API v2 Annotation (Open Annotation model)
    from internal Arches resource data.

    This serializer converts the v3 structures to v2 format:
    - body → resource
    - target → on
    - id → @id
    - type → @type
    - label dict → label string
    """

    V2_CONTEXT = "http://iiif.io/api/presentation/2/context.json"

    # Mapping of v3 types to v2 types
    TYPE_MAPPING = {
        "Annotation": "oa:Annotation",
        "Canvas": "sc:Canvas",
        "Manifest": "sc:Manifest",
        "SpecificResource": "oa:SpecificResource",
        "FragmentSelector": "oa:FragmentSelector",
        "Dataset": "dctypes:Dataset",
        "Text": "dctypes:Text",
        "TextualBody": "cnt:ContentAsText",
    }

    # ----------------------------------------------------------------------
    # V2 conversion helpers
    # ----------------------------------------------------------------------

    @classmethod
    def _convert_label_to_v2(cls, label_v3: dict | str | None) -> str | None:
        """
        Convert v3 label format to v2 simple string.
        v3: {"en": ["text"], "fr": ["texte"]} → v2: "text"
        Takes the first value from the first language found.
        """
        if label_v3 is None:
            return None
        if isinstance(label_v3, str):
            return label_v3
        if isinstance(label_v3, dict):
            # Try common languages first
            for lang in ["en", "fr", "de", "es", "it"]:
                if lang in label_v3:
                    values = label_v3[lang]
                    if isinstance(values, list) and values:
                        return values[0]
                    elif isinstance(values, str):
                        return values
            # Fallback: take first available
            for values in label_v3.values():
                if isinstance(values, list) and values:
                    return values[0]
                elif isinstance(values, str):
                    return values
        return str(label_v3)

    @classmethod
    def _convert_type_to_v2(cls, type_v3: str) -> str:
        """Convert v3 type to v2 prefixed type."""
        return cls.TYPE_MAPPING.get(type_v3, type_v3)

    @classmethod
    def _convert_metadata_to_v2(cls, metadata_v3: list) -> list:
        """
        Convert v3 metadata format to v2 format.
        v3: [{"label": {"en": ["Label"]}, "value": {"en": ["Value"]}}]
        v2: [{"label": "Label", "value": "Value"}]
        """
        metadata_v2 = []
        for entry in metadata_v3:
            label = cls._convert_label_to_v2(entry.get("label"))
            value = cls._convert_label_to_v2(entry.get("value"))
            if label and value:
                metadata_v2.append({"label": label, "value": value})
        return metadata_v2

    # ----------------------------------------------------------------------
    # V2 Body builder (resource)
    # ----------------------------------------------------------------------

    @classmethod
    def _build_body_v2(cls, tiles_data: dict) -> dict | list:
        """
        Builds the IIIF v2 `resource` based on the available datatype nodes.
        Converts v3 body structure to v2 resource structure.
        """
        bodies: List[dict] = []

        # 1) Manifest(s)
        manifest_body = cls._build_manifest_body_v2(tiles_data)
        if manifest_body:
            bodies.append(manifest_body)

        # 2) Dataset files (can be multiple)
        file_bodies = cls._build_file_bodies_v2(tiles_data)
        bodies.extend(file_bodies)

        # 3) Fallback: TextualBody if no other body found
        if not bodies:
            name_node = cls.DATATYPE_NODES.get("name")
            value = "No data available"
            if name_node and name_node in tiles_data:
                name_data = tiles_data[name_node]
                if isinstance(name_data, dict):
                    for lang_info in name_data.values():
                        if isinstance(lang_info, dict) and lang_info.get("value"):
                            value = lang_info["value"]
                            break

            bodies.append(
                {
                    "@type": "cnt:ContentAsText",
                    "chars": value,
                    "format": "text/plain",
                }
            )

        return bodies[0] if len(bodies) == 1 else bodies

    @classmethod
    def _build_manifest_body_v2(cls, tiles_data: dict) -> dict | None:
        """Build a Manifest resource body in v2 format."""
        manifest_node = cls.DATATYPE_NODES.get("manifest")
        if not manifest_node or manifest_node not in tiles_data:
            return None

        manifest_url = tiles_data[manifest_node]
        if not manifest_url:
            return None

        full_url = cls._to_full_manifest_url(manifest_url)

        # Check cache first
        if manifest_url in cls._manifest_cache:
            manifest_resource = cls._manifest_cache[manifest_url]
            label = manifest_resource["label"]
            return {
                "@id": full_url,
                "@type": "sc:Manifest",
                "format": "application/ld+json",
                "label": label if label else "Manifest",
            }

        # Outside batch, fallback: try exact URL then relative path
        if not cls._batch_mode:
            from urllib.parse import urlparse

            urls_to_try = [manifest_url]
            if manifest_url.startswith(("http://", "https://")):
                relative_path = urlparse(manifest_url).path
                if relative_path:
                    urls_to_try.append(relative_path)

            for url_variant in urls_to_try:
                try:
                    m = IIIFManifest.objects.get(url=url_variant)
                    return {
                        "@id": full_url,
                        "@type": "sc:Manifest",
                        "format": "application/ld+json",
                        "label": m.label if m.label else "Manifest",
                    }
                except IIIFManifest.DoesNotExist:
                    continue

            logger.info(f"Manifest not found for URL: {manifest_url}")

        return None

    @classmethod
    def _build_file_bodies_v2(cls, tiles_data: dict) -> List[dict]:
        """Build Dataset resource bodies for all files in file_list (v2 format)."""
        bodies: List[dict] = []

        filelist_node = cls.DATATYPE_NODES.get("file_list")
        if not filelist_node or filelist_node not in tiles_data:
            return bodies

        file_data = tiles_data[filelist_node]
        if not isinstance(file_data, list) or not file_data:
            return bodies

        mime_type = tiles_data.get(
            cls.DATATYPE_NODES.get("mime_type"),
            "application/octet-stream",
        )
        name_node = cls.DATATYPE_NODES.get("name")
        base_label = cls._convert_label_to_v2(
            cls._get_localized_string(
                tiles_data.get(name_node, {"en": {"value": "Dataset file"}})
            )
        )

        for idx, file_item in enumerate(file_data):
            file_url = file_item.get("url", "")
            if not file_url:
                continue

            # Add index to label if multiple files
            if len(file_data) > 1:
                label = f"{base_label} ({idx + 1}/{len(file_data)})"
            else:
                label = base_label

            bodies.append(
                {
                    "@id": settings.PUBLIC_SERVER_ADDRESS + file_url.lstrip("/"),
                    "@type": "dctypes:Dataset",
                    "format": mime_type,
                    "label": label,
                }
            )

        return bodies

    # ----------------------------------------------------------------------
    # V2 Target builder (on)
    # ----------------------------------------------------------------------

    @classmethod
    def _build_target_v2(
        cls,
        target_string: str,
        canvas_uri: str | None = None,
        manifest_url: str | None = None,
    ) -> str | dict:
        """
        Build a IIIF v2 target (on) from a target string.

        In v2, the target is typically a simple URI with fragment:
        "https://example.com/canvas/1#xywh=100,100,200,200"

        For more complex selectors, return an oa:SpecificResource structure.
        """
        if not target_string:
            return canvas_uri or ""

        # If target already has fragment, return as-is (simple form)
        if "#" in target_string:
            return target_string

        # If no fragment, return the canvas URI
        return canvas_uri or target_string

    # ----------------------------------------------------------------------
    # V2 See Also builder
    # ----------------------------------------------------------------------

    @classmethod
    def _build_see_also_v2(cls, tiles_data: dict, analysis_id: str) -> list:
        """Builds the IIIF v2 `seeAlso` section with related links."""
        see_also = [
            {
                "@id": f"{cls.base_url}report/{analysis_id}",
                "@type": "dctypes:Text",
                "format": "text/html",
                "label": "Detailed analysis report",
            }
        ]

        doi_node = cls.DATATYPE_NODES.get("dataset_uri")
        if doi_node and doi_node in tiles_data and tiles_data[doi_node]:
            uri = tiles_data[doi_node]
            see_also.append(
                {
                    "@id": uri,
                    "@type": "dctypes:Dataset",
                    "format": "text/html",
                    "label": "Published dataset",
                }
            )

        return see_also

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------

    @classmethod
    def to_representation(
        cls,
        target: str,
        resource_id: str,
        canvas_uri: str | None = None,
        manifest_url: str | None = None,
    ) -> dict:
        """
        Build a full IIIF v2 Annotation representation for a given Arches resource.

        Args:
            target (str): The IIIF target (e.g., Canvas URL + #xywh).
            resource_id (str): The Arches resource UUID.
            canvas_uri (str, optional): The canvas URI (without fragment).
            manifest_url (str, optional): The manifest URL for partOf reference.

        Returns:
            dict: A IIIF Presentation API v2 compliant annotation (Open Annotation).
        """
        # Build v2 target (on)
        on_target = cls._build_target_v2(target, canvas_uri, manifest_url)

        annotation: dict = {
            "@context": cls.V2_CONTEXT,
            "@id": f"{cls.base_url_iiif}/v2/annotation/{resource_id}",
            "@type": "oa:Annotation",
            "motivation": "oa:commenting",
            "on": on_target,
        }

        if not resource_id:
            annotation["resource"] = {
                "@type": "cnt:ContentAsText",
                "chars": "No data available",
                "format": "text/plain",
            }
            return annotation

        tiles_data = cls._get_resource_tiles(resource_id)

        label_node = cls.DATATYPE_NODES.get("name")
        if label_node and label_node in tiles_data:
            label_v3 = cls._get_localized_string(tiles_data[label_node])
            annotation["label"] = cls._convert_label_to_v2(label_v3)

        annotation["resource"] = cls._build_body_v2(tiles_data)

        metadata_v3 = cls._build_metadata(tiles_data)
        if metadata_v3:
            annotation["metadata"] = cls._convert_metadata_to_v2(metadata_v3)

        see_also = cls._build_see_also_v2(tiles_data, resource_id)
        if see_also:
            annotation["seeAlso"] = see_also

        return annotation

    @classmethod
    def batch_to_representation(cls, annotations_data: List[Dict]) -> List[Dict]:
        """
        Process multiple annotations in batch to optimize queries (v2 format).

        Args:
            annotations_data: List of dicts with 'target', 'resource_id',
                              and optionally 'canvas_uri' and 'manifest_url'

        Returns:
            List of IIIF v2 annotation representations
        """
        resource_ids = [
            a["resource_id"] for a in annotations_data if a.get("resource_id")
        ]

        cls._batch_mode = True
        try:
            cls._prefetch_all_data(resource_ids)

            results: List[dict] = []
            for anno_data in annotations_data:
                results.append(
                    cls.to_representation(
                        anno_data["target"],
                        anno_data["resource_id"],
                        canvas_uri=anno_data.get("canvas_uri"),
                        manifest_url=anno_data.get("manifest_url"),
                    )
                )
        finally:
            cls._batch_mode = False
            cls._clear_caches()

        return results

"""
API IIIF Annotation Collection - Version refactorisée
Utilise les classes existantes : CanvasIIIF et BBoxCalculator
"""
from django.conf import settings
from django.http import JsonResponse
from django.views import View
from arches.app.models.models import ResourceInstance, TileModel, VwAnnotation, ResourceXResource
from arches.app.models.resource import Resource
import json
import logging

logger = logging.getLogger(__name__)


class IIIFAnnotationCollectionView(View):
    """
    Vue pour générer une AnnotationCollection IIIF pour un Document ou Composant donné.
    URL: /iiif/annotation-collection/<uuid:resource_id>
    """

    # GraphIDs
    ANALYSIS_GRAPH_ID = "60c85aba-f079-45bc-997f-21cdd4f77b6d"
    DOCUMENT_GRAPH_ID = "0c8226c1-11a9-4c48-9601-a7a0c6f2df6b"
    COMPONENT_GRAPH_ID = "d47595b4-f8a6-419c-8f33-b388206280c4"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Cache pour les manifestes déjà récupérés
        self._manifest_cache = {}
        self._canvas_dimensions_cache = {}
        self.base_url = settings.PUBLIC_SERVER_ADDRESS + 'iiif'

    def get(self, request, resource_id):
        """
        Retourne une AnnotationCollection IIIF pour le Document/Composant donné
        """
        try:
            # Vérifier que la ressource existe
            resource = ResourceInstance.objects.get(resourceinstanceid=resource_id)

            # Récupérer toutes les Analysis liées
            analyses = self._get_related_analyses(resource)  # ✓ Passer l'objet resource

            if not analyses:
                return JsonResponse({
                    "error": "No analyses found for this resource"
                }, status=404)

            # Générer les AnnotationPages groupées par Canvas
            annotation_pages_by_canvas = self._group_annotations_by_canvas(analyses)

            # Construire l'AnnotationCollection
            collection = self._build_annotation_collection(
                resource_id,
                annotation_pages_by_canvas,
                resource
            )

            return JsonResponse(collection, safe=False)

        except ResourceInstance.DoesNotExist:
            return JsonResponse({
                "error": "Resource not found"
            }, status=404)
        except Exception as e:
            logger.error(f"Error generating annotation collection: {e}")
            return JsonResponse({
                "error": str(e)
            }, status=500)

    def _get_related_analyses(self, resource: ResourceInstance):
        """
        Récupère toutes les ressources Analysis liées à un Component ou à un Document.
        Gère automatiquement :
          - Analysis → Component
          - Analysis → Component → Document
          - Analysis → Document
        """

        analyses = set()  # ✅ éviter les doublons
        rid = resource.resourceinstanceid
        graph_id = str(resource.graph_id)

        # -------------------------------------------------------------------------
        # 🧩 Si la ressource est un Component
        # -------------------------------------------------------------------------
        if graph_id == self.COMPONENT_GRAPH_ID:
            analysis_relations = ResourceXResource.objects.filter(
                to_resource_id=rid,
                from_resource_graph_id=self.ANALYSIS_GRAPH_ID
            )
            for rel in analysis_relations:
                try:
                    analysis = Resource.objects.get(resourceinstanceid=rel.from_resource_id)
                    analyses.add(analysis)
                except Resource.DoesNotExist:
                    continue

        # -------------------------------------------------------------------------
        # 📄 Si la ressource est un Document
        # -------------------------------------------------------------------------
        elif graph_id == self.DOCUMENT_GRAPH_ID:
            # (1) Analyses directement liées au Document
            direct_relations = ResourceXResource.objects.filter(
                to_resource_id=rid,
                from_resource_graph_id=self.ANALYSIS_GRAPH_ID
            )
            for rel in direct_relations:
                try:
                    analysis = Resource.objects.get(resourceinstanceid=rel.from_resource_id)
                    analyses.add(analysis)
                except Resource.DoesNotExist:
                    continue

            # (2) Components liés au Document
            component_relations = ResourceXResource.objects.filter(
                to_resource_id=rid,
                from_resource_graph_id=self.COMPONENT_GRAPH_ID
            )
            component_ids = [rel.from_resource_id for rel in component_relations]

            # (3) Analyses liées à ces Components
            if component_ids:
                component_analysis_relations = ResourceXResource.objects.filter(
                    to_resource_id__in=component_ids,
                    from_resource_graph_id=self.ANALYSIS_GRAPH_ID,
                    to_resource_graph_id=self.COMPONENT_GRAPH_ID
                )
                for rel in component_analysis_relations:
                    try:
                        analysis = Resource.objects.get(resourceinstanceid=rel.from_resource_id)
                        analyses.add(analysis)
                    except Resource.DoesNotExist:
                        continue

        return list(analyses)

    def _get_annotations_from_analysis(self, analysis):
        """
        Récupère les annotations (VwAnnotation) d'une ressource Analysis
        """
        annotations = []
        seen_feature_ids = set()

        # Récupérer les VwAnnotation pour cette Analysis
        vw_annotations = VwAnnotation.objects.filter(
            resourceinstance_id=analysis.resourceinstanceid
        )

        for vw_anno in vw_annotations:
            try:
                # VwAnnotation.feature contient directement la feature GeoJSON
                feature = vw_anno.feature or {}

                # Extraire les informations nécessaires
                if feature:
                    feature_id = feature.get('id')
                    if feature_id and feature_id in seen_feature_ids:
                        continue
                    properties = feature.get('properties', {})
                    geometry = feature.get('geometry', {})

                    annotations.append({
                        'id': vw_anno.resourceinstance_id,
                        'geometry': geometry,
                        'properties': properties,
                        'canvas': properties.get('canvas'),
                        'manifest': properties.get('manifest'),
                        'analysis_id': str(analysis.resourceinstanceid),
                        'analysis_label': self._get_display_name(analysis),
                        'vw_annotation': vw_anno
                    })
                    if feature_id:
                        seen_feature_ids.add(feature_id)
            except Exception as e:
                logger.error(f"Error parsing annotation: {e}")
                continue

        return annotations

    def _get_canvas_dimensions(self, canvas_uri, manifest_url):
        """
        Récupère les dimensions d'un Canvas ou d'un Image Service IIIF
        """
        # Vérifier le cache
        if canvas_uri in self._canvas_dimensions_cache:
            return self._canvas_dimensions_cache[canvas_uri]

        from manuspectrum.utils.iiif_tools import CanvasIIIF

        # ✅ Essayer d'abord via l'Image Service (plus direct et fiable)
        dimensions = CanvasIIIF.get_image_service_dimensions(canvas_uri)

        # Cache le résultat
        self._canvas_dimensions_cache[canvas_uri] = dimensions
        return dimensions

    def _convert_geojson_to_iiif_target(self, annotation, zoom=5):
        """
        Convertit les coordonnées GeoJSON en format IIIF target
        Utilise BBoxCalculator pour les calculs
        """
        geometry = annotation.get('geometry')
        canvas_uri = annotation.get('canvas')
        manifest_url = annotation.get('manifest')

        if not geometry or not canvas_uri:
            return canvas_uri

        # Récupérer les dimensions du canvas
        canvas_width, canvas_height = self._get_canvas_dimensions(canvas_uri, manifest_url)

        # Utiliser BBoxCalculator pour générer le fragment xywh
        from manuspectrum.utils.iiif_tools import BBoxCalculator
        xywh_fragment = BBoxCalculator.geometry_to_xywh(
            geometry,
            canvas_width,
            canvas_height,
            zoom=zoom,
            margin=0, # Pas de marge pour les annotations IIIF
            radius=0 # Pas de marge pour les annotations IIIF
        )

        if xywh_fragment:
            return f"{canvas_uri}#{xywh_fragment}"

        return canvas_uri

    def _group_annotations_by_canvas(self, analyses):
        """
        Groupe les annotations par Canvas
        """
        canvas_groups = {}

        for analysis in analyses:
            annotations = self._get_annotations_from_analysis(analysis)

            for anno in annotations:
                canvas_uri = anno.get('canvas')
                if not canvas_uri:
                    continue

                if canvas_uri not in canvas_groups:
                    canvas_groups[canvas_uri] = []

                canvas_groups[canvas_uri].append(anno)

        return canvas_groups

    def _build_annotation_collection(self, resource_id, annotation_pages_by_canvas, resource):
        """
        Construit l'AnnotationCollection IIIF selon le standard
        """
        collection_id = f"{self.base_url}/annotation-collection/{resource_id}"

        # Créer les AnnotationPages
        annotation_pages = []
        canvas_uris = list(annotation_pages_by_canvas.keys())
        total_annotations = 0

        for idx, canvas_uri in enumerate(canvas_uris):
            page_id = f"{collection_id}/page-{idx}"
            annotations = annotation_pages_by_canvas[canvas_uri]
            total_annotations += len(annotations)

            # Construire les Annotations IIIF
            iiif_annotations = []
            for anno in annotations:
                target = self._convert_geojson_to_iiif_target(anno)

                iiif_annotation = {
                    "id": f"{self.base_url}/annotation/{anno['id']}",
                    "type": "Annotation",
                    "motivation": "supplementing",
                    "body": {
                        "type": "TextualBody",
                        "value": anno['analysis_label'],
                        "format": "text/plain",
                        "language": "fr"
                    },
                    "target": target
                }
                iiif_annotations.append(iiif_annotation)

            # Construire l'AnnotationPage
            annotation_page = {
                "id": page_id,
                "type": "AnnotationPage",
                "items": iiif_annotations,
                "partOf": collection_id
            }

            # Ajouter les références next/prev
            if idx < len(canvas_uris) - 1:
                annotation_page["next"] = f"{collection_id}/page-{idx + 1}"

            if idx > 0:
                annotation_page["prev"] = f"{collection_id}/page-{idx - 1}"

            annotation_pages.append(annotation_page)

        # Construire l'AnnotationCollection
        collection = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "id": collection_id,
            "type": "AnnotationCollection",
            "label": {
                "fr": [f"Analyses pour {self._get_display_name(resource)}"]
            },
            "total": total_annotations
        }

        if annotation_pages:
            collection["first"] = annotation_pages[0]["id"]
            collection["last"] = annotation_pages[-1]["id"]
            collection["items"] = annotation_pages

        return collection

    def _get_display_name(self, resource):
        """
        Récupère le displayname d'une ressource (gère méthode ou propriété)
        """
        if hasattr(resource, 'displayname'):
            displayname = resource.displayname
            # Si c'est une méthode, l'appeler
            if callable(displayname):
                return displayname()
            # Sinon c'est une propriété
            return displayname
        # Fallback sur l'UUID
        return str(resource.resourceinstanceid)


class IIIFAnnotationPageView(View):
    """
    Vue pour retourner une AnnotationPage individuelle
    URL: /iiif/annotation-collection/<uuid:resource_id>/page-<int:page_num>
    """
    base_url = settings.PUBLIC_SERVER_ADDRESS + 'iiif'

    def get(self, request, resource_id, page_num):
        """
        Retourne une AnnotationPage spécifique
        """
        try:
            # Récupérer la collection complète (on pourrait optimiser en ne récupérant que la page demandée)
            collection_view = IIIFAnnotationCollectionView()
            collection_view.request = request

            resource = ResourceInstance.objects.get(resourceinstanceid=resource_id)
            analyses = collection_view._get_related_analyses(resource)  # ✓ Passer l'objet resource
            annotation_pages_by_canvas = collection_view._group_annotations_by_canvas(analyses)

            canvas_uris = list(annotation_pages_by_canvas.keys())

            if page_num >= len(canvas_uris):
                return JsonResponse({
                    "error": "Page not found"
                }, status=404)

            collection_id = f"{self.base_url}/annotation-collection/{resource_id}"
            page_id = f"{collection_id}/page-{page_num}"

            canvas_uri = canvas_uris[page_num]
            annotations = annotation_pages_by_canvas[canvas_uri]

            # Construire les Annotations IIIF
            iiif_annotations = []
            for anno in annotations:
                target = collection_view._convert_geojson_to_iiif_target(anno)

                iiif_annotation = {
                    "id": f"{self.base_url}annotation/{anno['id']}",
                    "type": "Annotation",
                    "motivation": "tagging",
                    "body": {
                        "type": "TextualBody",
                        "value": anno['analysis_label'],
                        "format": "text/plain",
                        "language": "fr"
                    },
                    "target": target
                }
                iiif_annotations.append(iiif_annotation)

            # Construire l'AnnotationPage
            annotation_page = {
                "@context": "http://iiif.io/api/presentation/3/context.json",
                "id": page_id,
                "type": "AnnotationPage",
                "items": iiif_annotations,
                "partOf": {
                    "id": collection_id,
                    "type": "AnnotationCollection",
                    "label": {
                        "fr": [f"Analyses pour {collection_view._get_display_name(resource)}"]
                    }
                }
            }

            if page_num < len(canvas_uris) - 1:
                annotation_page["next"] = f"{collection_id}/page-{page_num + 1}"

            if page_num > 0:
                annotation_page["prev"] = f"{collection_id}/page-{page_num - 1}"

            return JsonResponse(annotation_page, safe=False)

        except ResourceInstance.DoesNotExist:
            return JsonResponse({
                "error": "Resource not found"
            }, status=404)
        except Exception as e:
            logger.error(f"Error generating annotation page: {e}")
            return JsonResponse({
                "error": str(e)
            }, status=500)


class IIIFAnnotationView(View):
    """
    Vue pour retourner une Annotation IIIF individuelle
    URL: /iiif/annotation/<uuid:resource_id> -> resource_id correspond à la ressource Analysis
    """

    ANALYSIS_GRAPH_ID = "60c85aba-f079-45bc-997f-21cdd4f77b6d"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._canvas_dimensions_cache = {}
        self.base_url = settings.PUBLIC_SERVER_ADDRESS + 'iiif'

    def get(self, request, resource_id):
        """
        Retourne une Annotation IIIF pour l'Analysis donnée
        """
        try:
            # Vérifier que la ressource Analysis existe
            analysis = Resource.objects.get(resourceinstanceid=resource_id)

            # Vérifier que c'est bien une Analysis
            if str(analysis.graph_id) != self.ANALYSIS_GRAPH_ID:
                return JsonResponse({
                    "error": "Resource is not an Analysis"
                }, status=400)

            # Récupérer les annotations de cette Analysis
            annotations = self._get_annotations_from_analysis(analysis)

            if not annotations:
                return JsonResponse({
                    "error": "No annotation data found for this Analysis"
                }, status=404)

            # Prendre la première annotation (une Analysis = une annotation)
            anno_data = annotations[0]

            # Construire l'Annotation IIIF
            iiif_annotation = self._build_iiif_annotation(resource_id, anno_data)

            return JsonResponse(iiif_annotation, safe=False)

        except Resource.DoesNotExist:
            return JsonResponse({
                "error": "Annotation not found"
            }, status=404)
        except Exception as e:
            logger.error(f"Error generating annotation: {e}")
            return JsonResponse({
                "error": str(e)
            }, status=500)

    def _get_annotations_from_analysis(self, analysis):
        """
        Récupère les annotations (VwAnnotation) d'une ressource Analysis
        """
        annotations = []

        # Récupérer les VwAnnotation pour cette Analysis
        vw_annotations = VwAnnotation.objects.filter(
            resourceinstance_id=analysis.resourceinstanceid
        )

        for vw_anno in vw_annotations:
            try:
                feature = vw_anno.feature or {}

                if feature:
                    properties = feature.get('properties', {})
                    geometry = feature.get('geometry', {})

                    annotations.append({
                        'id': vw_anno.resourceinstance_id,
                        'geometry': geometry,
                        'properties': properties,
                        'canvas': properties.get('canvas'),
                        'manifest': properties.get('manifest'),
                        'analysis_id': str(analysis.resourceinstanceid),
                        'analysis_label': self._get_display_name(analysis),
                        'vw_annotation': vw_anno
                    })
            except Exception as e:
                logger.error(f"Error parsing annotation: {e}")
                continue

        return annotations

    def _build_iiif_annotation(self, annotation_id, anno_data):
        """
        Construit une Annotation IIIF selon le standard
        """
        annotation_uri = f"{self.base_url}annotation/{annotation_id}"

        # Convertir le target GeoJSON en IIIF
        target = self._convert_geojson_to_iiif_target(anno_data)

        # Construire l'annotation
        iiif_annotation = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "id": annotation_uri,
            "type": "Annotation",
            "motivation": "supplementing",
            "body": {
                "type": "TextualBody",
                "value": anno_data['analysis_label'],
                "format": "text/plain",
                "language": "fr"
            },
            "target": target
        }

        return iiif_annotation

    def _convert_geojson_to_iiif_target(self, annotation, zoom=5):
        """
        Convertit les coordonnées GeoJSON en format IIIF target
        """
        geometry = annotation.get('geometry')
        canvas_uri = annotation.get('canvas')
        manifest_url = annotation.get('manifest')

        if not geometry or not canvas_uri:
            return canvas_uri or ""

        # Récupérer les dimensions du canvas
        canvas_width, canvas_height = self._get_canvas_dimensions(canvas_uri, manifest_url)

        # Utiliser BBoxCalculator pour générer le fragment xywh
        from manuspectrum.utils.iiif_tools import BBoxCalculator
        xywh_fragment = BBoxCalculator.geometry_to_xywh(
            geometry,
            canvas_width,
            canvas_height,
            zoom=zoom,
            margin=0,
            radius=0
        )

        if xywh_fragment:
            return f"{canvas_uri}#{xywh_fragment}"

        return canvas_uri

    def _get_canvas_dimensions(self, canvas_uri, manifest_url):
        """
        Récupère les dimensions d'un Canvas ou d'un Image Service IIIF
        """
        if canvas_uri in self._canvas_dimensions_cache:
            return self._canvas_dimensions_cache[canvas_uri]

        from manuspectrum.utils.iiif_tools import CanvasIIIF

        dimensions = CanvasIIIF.get_image_service_dimensions(canvas_uri)
        self._canvas_dimensions_cache[canvas_uri] = dimensions
        return dimensions

    def _get_display_name(self, resource):
        """
        Récupère le displayname d'une ressource
        """
        if hasattr(resource, 'displayname'):
            displayname = resource.displayname
            if callable(displayname):
                return displayname()
            return displayname
        return str(resource.resourceinstanceid)
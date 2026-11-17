"""Image Service Manager writes, limited to Resource Editor and Resource Reviewer, with JPEG 2000.

Subclass of ``arches.app.views.manifest_manager.ManifestManagerView``
(Arches 8.1.6). ``post`` and ``delete`` pass ``group_required`` first, as
Arches' ``TileData`` guards its own writes; ``get`` and ``delete`` are the
core view's. The page itself may be open more widely (its ``view_plugin``
grants, deploy/ADMIN.md); tests/test_manifest_manager_view.py pins the write
groups.

``post`` is the core method copied whole, because ``acceptable_types`` is a
local of ``post`` and the core view has no extension point. Two differences,
both marked in the body:

- ``.jp2`` is an acceptable type;
- the deposit goes through ``utils.jp2_profile.check_deposit`` before anything
  is written (every ``.jp2``, and any file with a JPEG 2000 signature under
  another name), and one refusal answers 400 with a translated title and
  message for the whole deposit (the core view skips an unacceptable file
  silently).

The differences are the lines marked ``# ManuSpectrum:``, the ``".jp2"`` entry
and the block between ``# ManuSpectrum: begin`` and ``# ManuSpectrum: end``.
``CorePostCanaryTests`` in the test module pins a digest of the core ``post``
and checks that, without those lines, the copy is the core text: it fails when
an Arches upgrade changes ``post``, then re-copy the new body and apply the two
differences. Remove the copy once Arches accepts JPEG 2000 itself.
Remove this module, its entry in ``urls.py`` and the routing tests once the
installed Arches guards these writes itself: ``CoreGuardCanaryTests`` fails at
that release.
"""

import json
import logging
import os
import uuid

from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _

from arches.app.models import models
from arches.app.utils.decorators import group_required
from arches.app.utils.response import JSONResponse
from arches.app.views.manifest_manager import (
    ManifestManagerView as CoreManifestManagerView,
    ManifestValidationError,
)

from manuspectrum.utils.jp2_profile import check_deposit

logger = logging.getLogger(__name__)


@method_decorator(
    group_required("Resource Editor", "Resource Reviewer", raise_exception=True),
    name="post",
)
@method_decorator(
    group_required("Resource Editor", "Resource Reviewer", raise_exception=True),
    name="delete",
)
class ManifestManagerView(CoreManifestManagerView):
    """``ManifestManagerView`` whose writes require Resource Editor or Resource Reviewer, and which accepts JPEG 2000."""

    def post(self, request):
        def create_manifest(
            name="", desc="", file_url="file_url", attribution="", logo="", canvases=[]
        ):
            metadata = []  # {"label": "TBD", "value": ["Unknown", ...]}
            sequence_id = f"{self.cantaloupe_uri}/manifest/sequence/TBD.json"

            return {
                "@context": "http://iiif.io/api/presentation/2/context.json",
                "@type": "sc:Manifest",
                "description": desc,
                "label": name,
                "attribution": attribution,
                "logo": logo,
                "metadata": metadata,
                "thumbnail": {
                    "@id": file_url + "/full/!300,300/0/default.jpg",
                    "@type": "dctypes:Image",
                    "format": "image/jpeg",
                    "label": "Main View (.45v)",
                },
                "sequences": [
                    {
                        "@id": sequence_id,
                        "@type": "sc:Sequence",
                        "canvases": canvases,
                        "label": "Object",
                        "startCanvas": "",
                    }
                ],
            }

        def create_canvas(image_json, file_url, file_name, image_id):
            canvas_id = f"{self.cantaloupe_uri}/manifest/canvas/{image_id}.json"
            image_id = f"{self.cantaloupe_uri}/manifest/annotation/{image_id}.json"
            thumbnail_width = 300 if image_json["width"] >= 300 else image_json["width"]
            thumbnail_height = (
                300 if image_json["height"] >= 300 else image_json["height"]
            )
            thumbnail_id = (
                f"{file_url}/full/!{thumbnail_width},{thumbnail_height}/0/default.jpg"
            )

            return {
                "@id": canvas_id,
                "@type": "sc:Canvas",
                "height": image_json["height"],
                "width": image_json["width"],
                "images": [
                    {
                        "@id": image_id,
                        "@type": "oa.Annotation",
                        "motivation": "unknown",
                        "on": canvas_id,
                        "resource": {
                            "@id": file_url + "/full/full/0/default.jpg",
                            "@type": "dctypes:Image",
                            "format": "image/jpeg",
                            "height": image_json["height"],
                            "width": image_json["width"],
                            "service": {
                                "@context": "http://iiif.io/api/image/2/context.json",
                                "@id": file_url,
                                "profile": "http://iiif.io/api/image/2/level2.json",
                            },
                        },
                    }
                ],
                "label": f"{file_name}",
                "license": "TBD",
                "thumbnail": {
                    "@id": thumbnail_id,
                    "@type": "dctypes:Image",
                    "format": "image/jpeg",
                    "service": {
                        "@context": "http://iiif.io/api/image/2/context.json",
                        "@id": file_url,
                        "profile": "http://iiif.io/api/image/2/level2.json",
                    },
                },
            }

        def add_canvases(manifest, canvases):
            manifest.manifest["sequences"][0]["canvases"] += canvases

        def check_canvas_in_use(canvas_id):
            return models.VwAnnotation.objects.filter(canvas=canvas_id).exists()

        def delete_canvases(manifest, canvases_to_remove):
            canvas_ids_remove = [
                canvas["images"][0]["resource"]["service"]["@id"]
                for canvas in canvases_to_remove
            ]
            canvases_in_use = []
            for canvas_id in canvas_ids_remove:
                if check_canvas_in_use(canvas_id):
                    canvases_in_use.append(canvas_id)
            canvases = manifest.manifest["sequences"][0]["canvases"]
            if len(canvases_in_use) > 0:
                canvas_labels_in_use = [
                    item["label"]
                    for item in canvases
                    if item["images"][0]["resource"]["service"]["@id"]
                    in canvases_in_use
                ]
                raise ManifestValidationError(
                    "The following canvases cannot be deleted because they have resource annotations: {}".format(
                        ", ".join(canvas_labels_in_use)
                    )
                )
            manifest.manifest["sequences"][0]["canvases"] = [
                canvas
                for canvas in canvases
                if canvas["images"][0]["resource"]["service"]["@id"]
                not in canvas_ids_remove
            ]

        def create_image(file):
            new_image_id = uuid.uuid4()
            new_image_file = models.File.objects.create(fileid=new_image_id, path=file)
            new_image_file.save()

            file_name = os.path.basename(new_image_file.path.name)
            file_url = (
                f"{request.scheme}://{request.get_host()}/iiifserver/iiif/2/{file_name}"
            )
            file_json_url = f"{self.cantaloupe_uri}/2/{file_name}/info.json"
            image_json = self.fetch(file_json_url)

            return image_json, new_image_id, file_url

        def change_manifest_info(manifest, name, desc, attribution, logo):
            if name is not None and name != "":
                manifest.label = name
                manifest.manifest["label"] = name
            if desc is not None and desc != "":
                manifest.description = desc
                manifest.manifest["description"] = desc
            if attribution and attribution != "":
                manifest.manifest["attribution"] = attribution
            if logo and logo != "":
                manifest.manifest["logo"] = logo

        def change_manifest_metadata(manifest):  # To be fixed
            manifest.manifest["metadata"] = metadata

        def change_canvas_label(manifest, canvas_id, label):
            # canvas_id = canvas['images'][0]['resource']['service']['@id']
            canvases = manifest.manifest["sequences"][0]["canvases"]
            for canvas in canvases:
                if canvas["images"][0]["resource"]["service"]["@id"] == canvas_id:
                    canvas["label"] = label

        acceptable_types = [
            ".jpg",
            ".jpeg",
            ".tiff",
            ".tif",
            ".png",
            # ManuSpectrum: JPEG 2000 is an acceptable type.
            ".jp2",
        ]

        files = request.FILES.getlist("files")
        # ManuSpectrum: begin, refuse the whole deposit before anything is written.
        refusal = check_deposit(files)
        if refusal:
            return JSONResponse(
                {"title": _("JPEG 2000 file refused"), "message": refusal},
                status=400,
            )
        # ManuSpectrum: end
        name = request.POST.get("manifest_title")
        if name == "null" or name == "undefined":
            try:
                name = os.path.splitext(files[0].name)[0]
            except:
                pass

        attribution = request.POST.get("manifest_attribution", "")
        logo = request.POST.get("manifest_logo", "")
        desc = request.POST.get("manifest_description", "")
        operation = request.POST.get("operation")
        manifest_url = request.POST.get("manifest")
        canvas_label = request.POST.get("canvas_label")
        canvas_id = request.POST.get("canvas_id")
        metadata = request.POST.get("metadata")
        transaction_id = request.POST.get("transaction_id", uuid.uuid4())
        selected_canvases = request.POST.get("selected_canvases")
        try:
            metadata = json.loads(request.POST.get("metadata"))
        except TypeError:
            metadata = []

        if operation == "create":
            canvases = []
            for f in files:
                if os.path.splitext(f.name)[1].lower() in acceptable_types:
                    image_json, image_id, file_url = create_image(f)

                    canvas = create_canvas(
                        image_json, file_url, os.path.splitext(f.name)[0], image_id
                    )
                    canvases.append(canvas)
                else:
                    logger.warning("filetype unacceptable: " + f.name)

            pres_dict = create_manifest(
                name=name,
                canvases=canvases,
                file_url=canvases[0]["thumbnail"]["service"]["@id"],
            )
            manifest_global_id = str(uuid.uuid4())
            json_url = f"/manifest/{manifest_global_id}"
            pres_dict["@id"] = f"{request.scheme}://{request.get_host()}{json_url}"

            manifest = models.IIIFManifest.objects.create(
                label=name,
                description=desc,
                manifest=pres_dict,
                url=json_url,
                globalid=manifest_global_id,
                transactionid=transaction_id,
            )

            return JSONResponse(manifest)
        else:
            manifest = models.IIIFManifest.objects.get(url=manifest_url)

        change_manifest_info(manifest, name, desc, attribution, logo)

        if canvas_label is not None:
            change_canvas_label(manifest, canvas_id, canvas_label)

        if selected_canvases is not None:
            selected_canvases_json = json.loads(selected_canvases)
            try:
                delete_canvases(manifest, selected_canvases_json)
            except ManifestValidationError as e:
                return JSONResponse({"message": e.message}, status=500)

        if len(files) > 0:
            try:
                canvases = []
                for f in files:
                    if os.path.splitext(f.name)[1].lower() in acceptable_types:
                        image_json, image_id, file_url = create_image(f)
                        canvas = create_canvas(
                            image_json, file_url, os.path.splitext(f.name)[0], image_id
                        )
                        canvases.append(canvas)
                    else:
                        logger.warning("filetype unacceptable: " + f.name)
                add_canvases(manifest, canvases)
            except:
                logger.warning("You have to select a manifest to add images")
                raise

        change_manifest_metadata(manifest)

        manifest.save()
        return JSONResponse(manifest)

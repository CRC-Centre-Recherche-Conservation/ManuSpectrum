"""The spectrum preview of a file whose row is deleted after it was memoised.

Unlike the rest of the preview tests (``tests.test_spectrum_preview``, database
free), this module needs the migrated test database, for the ``files`` row, its
tile and the ``post_delete`` receiver, and pays the runner's Elasticsearch
index setup for it. The Analysis graph and the file-list nodegroup come from
the trigger tests' case.

Usage:
    python manage.py test tests.test_spectrum_preview_deletion --settings="tests.test_settings"
"""

from django.core.cache import cache
from django.urls import reverse

from arches.app.models.models import File

from manuspectrum.views.spectrum_preview import file_record, file_record_key
from tests.test_xy_config_trigger import XYTriggerTestCase

FILE_ID = "5c0d7e21-9b4a-4f36-a8e2-1d3f6b9c0a47"


class DeletedFilePreviewTests(XYTriggerTestCase):
    def test_a_deleted_file_is_not_served_from_the_memo(self):
        resource = self.analysis()
        tile = self.write_files(resource, {"file_id": FILE_ID, "name": "a.csv"})
        File.objects.create(
            fileid=FILE_ID, path="uploadedfiles/preview-delete.csv", tile=tile
        )
        cache.clear()
        self.addCleanup(cache.clear)
        self.assertIsNotNone(file_record(FILE_ID))
        self.assertIsNotNone(cache.get(file_record_key(FILE_ID)))

        with self.captureOnCommitCallbacks(execute=True):
            File.objects.filter(pk=FILE_ID).delete()

        self.assertIsNone(cache.get(file_record_key(FILE_ID)))
        response = self.client.get(reverse("api-spectrum-preview", args=[FILE_ID]))
        self.assertEqual(response.status_code, 404)

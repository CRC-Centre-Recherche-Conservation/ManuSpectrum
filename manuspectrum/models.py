import uuid
from django.db import models
from django.db.models import JSONField


class RendererConfig(models.Model):
    """
    Arches for Science
    GPL-3.0 license
    https://github.com/archesproject/arches-for-science
    """
    configid = models.UUIDField(primary_key=True, unique=True)
    rendererid = models.UUIDField()
    name = models.TextField(blank=False, null=False)
    description = models.TextField(blank=True, null=True)
    config = JSONField(default=dict)

    class Meta:
        managed = True
        db_table = "renderer_config"

    def __init__(self, *args, **kwargs):
        super(RendererConfig, self).__init__(*args, **kwargs)
        if not self.configid:
            self.configid = uuid.uuid4()


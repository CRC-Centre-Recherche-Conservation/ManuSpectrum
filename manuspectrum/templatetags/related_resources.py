from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def related_resources_export_limit():
    """Relations Arches loads at once (``paginate=false``), read by ``models/report.js``."""
    return int(settings.RELATED_RESOURCES_EXPORT_LIMIT)


@register.simple_tag
def related_resources_per_page():
    """Relations of one page of Arches' related resources route."""
    return int(settings.RELATED_RESOURCES_PER_PAGE)

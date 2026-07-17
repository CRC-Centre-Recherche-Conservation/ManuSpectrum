from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def biblissima_portal_url():
    return settings.BIBLISSIMA_PORTAL_URL


@register.simple_tag
def biblissima_entity_uri_base():
    return settings.BIBLISSIMA_ENTITY_URI_BASE

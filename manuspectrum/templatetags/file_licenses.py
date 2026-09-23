from django import template

from manuspectrum.constants.licenses import catalogue_json

register = template.Library()


@register.simple_tag
def license_catalogue_json():
    """The licence catalogue as JSON, labels in the active language.

    Returned unmarked, so autoescaping makes it safe inside an HTML attribute.
    """
    return catalogue_json()

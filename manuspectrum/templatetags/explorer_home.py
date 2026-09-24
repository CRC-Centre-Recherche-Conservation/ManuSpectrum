from django import template
from django.utils.translation import get_language

from manuspectrum.views.explorer_home import homepage_techniques

register = template.Library()


@register.simple_tag(name="homepage_techniques")
def homepage_techniques_tag():
    """The homepage technique chips for the current language."""
    return homepage_techniques(get_language())

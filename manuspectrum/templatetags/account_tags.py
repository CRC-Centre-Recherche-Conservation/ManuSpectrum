from datetime import timedelta

from django import template

register = template.Library()


@register.filter
def group_key(value, size=4):
    """Show a secret in groups of *size* characters separated by a space."""
    text = str(value or "")
    size = int(size)
    return " ".join(text[i : i + size] for i in range(0, len(text), size))


@register.filter
def whole_minutes(value):
    """The length of the timedelta *value* in minutes, at least 1; None for anything else."""
    if not isinstance(value, timedelta):
        return None
    return max(1, round(value.total_seconds() / 60))


@register.simple_tag
def described_field(field, suffixes):
    """Render *field* with ``aria-describedby`` naming ``<field id>-<suffix>`` elements.

    *suffixes* is a space-separated string; an ``aria-describedby`` already set
    on the widget is kept first.
    """
    base = field.id_for_label
    ids = [f"{base}-{suffix}" for suffix in str(suffixes).split()]
    existing = field.field.widget.attrs.get("aria-describedby")
    if existing:
        ids.insert(0, existing)
    return field.as_widget(attrs={"aria-describedby": " ".join(ids)})

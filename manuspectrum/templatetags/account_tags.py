from django import template

register = template.Library()


@register.filter
def group_key(value, size=4):
    """Show a secret in groups of *size* characters separated by a space."""
    text = str(value or "")
    size = int(size)
    return " ".join(text[i : i + size] for i in range(0, len(text), size))

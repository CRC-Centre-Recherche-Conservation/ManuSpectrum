"""The password rules the activation page shows, read from the configured validators.

The server stays the only judge: this module only reports which of the
checkable character rules `AUTH_PASSWORD_VALIDATORS` enforces, so the page can
tick them live. Common-password and similarity checks are not reported.
"""

from django.conf import settings
from django.utils.module_loading import import_string

DEFAULT_MIN_LENGTH = 8


def _classes(validators):
    """Resolve each configured validator to (class, options)."""
    for entry in validators:
        try:
            yield import_string(entry["NAME"]), entry.get("OPTIONS", {})
        except ImportError:
            continue


def password_rules():
    """Return the rules of `settings.AUTH_PASSWORD_VALIDATORS` the page can check.

    Keys: `min_length` (int, 0 when no length validator), `upper`, `lower`,
    `digit` (bool), `symbols` (the accepted symbol characters, "" when no
    symbol rule).
    """
    from arches.app.utils import password_validation as arches_rules
    from django.contrib.auth import password_validation as django_rules

    rules = {
        "min_length": 0,
        "upper": False,
        "lower": False,
        "digit": False,
        "symbols": "",
    }
    for cls, options in _classes(settings.AUTH_PASSWORD_VALIDATORS):
        if issubclass(
            cls, (arches_rules.MinLengthValidator, django_rules.MinimumLengthValidator)
        ):
            rules["min_length"] = max(
                rules["min_length"], int(options.get("min_length", DEFAULT_MIN_LENGTH))
            )
        elif issubclass(cls, arches_rules.HasUpperAndLowerCaseValidator):
            rules["upper"] = True
        elif cls.__name__ == "HasLowerCaseValidator":
            rules["lower"] = True
        elif issubclass(cls, arches_rules.HasNumericCharacterValidator):
            rules["digit"] = True
        elif issubclass(cls, arches_rules.SpecialCharacterValidator):
            rules["symbols"] = "".join(
                options.get("special_characters", ("!", "@", "#"))
            )
    return rules

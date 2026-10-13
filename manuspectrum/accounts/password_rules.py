"""The password rules the activation page shows, read from the configured validators.

The server stays the only judge: this module only reports which of the
checkable character rules `AUTH_PASSWORD_VALIDATORS` enforces, so the page can
tick them live. `password_rule_list` words every configured rule once for the
info panel, the common-password and similarity checks included.
"""

from django.conf import settings
from django.utils.module_loading import import_string
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

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
    symbol rule), `letter` (bool, a numeric-only refusal), `common` and
    `similarity` (bool, the validators that cannot be ticked live).
    """
    from arches.app.utils import password_validation as arches_rules
    from django.contrib.auth import password_validation as django_rules

    rules = {
        "min_length": 0,
        "upper": False,
        "lower": False,
        "digit": False,
        "symbols": "",
        "letter": False,
        "common": False,
        "similarity": False,
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
        elif issubclass(cls, django_rules.NumericPasswordValidator):
            rules["letter"] = True
        elif issubclass(cls, django_rules.CommonPasswordValidator):
            rules["common"] = True
        elif issubclass(cls, django_rules.UserAttributeSimilarityValidator):
            rules["similarity"] = True
    return rules


def password_rule_list(rules):
    """Word each enforced rule once, in the active language.

    The numeric-only rule is implied by an upper- or lower-case rule and is
    listed only when neither is configured.
    """
    words = []
    if rules["min_length"]:
        n = rules["min_length"]
        words.append(
            ngettext("At least %(n)s character", "At least %(n)s characters", n)
            % {"n": n}
        )
    if rules["upper"]:
        words.append(_("One upper-case letter"))
    if rules["lower"]:
        words.append(_("One lower-case letter"))
    if rules["letter"] and not (rules["upper"] or rules["lower"]):
        words.append(_("One letter"))
    if rules["digit"]:
        words.append(_("One digit"))
    if rules["symbols"]:
        words.append(_("One symbol"))
    if rules["common"]:
        words.append(_("Not a commonly used password"))
    if rules["similarity"]:
        words.append(_("Not too close to your name, username or e-mail address"))
    return words

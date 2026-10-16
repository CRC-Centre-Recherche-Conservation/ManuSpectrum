"""Password validators that complete Arches' own (``arches.app.utils.password_validation``).

Arches' ``MinLengthValidator`` builds its help text with
``_("... {0} ...".format(n))``, which formats before the lookup, so no catalogue
can translate it; ``MinLengthValidator`` here words it with ``ngettext``.

Arches' ``HasUpperAndLowerCaseValidator`` only fails when a password has no
upper-case letter or nothing but upper-case letters, so a password without any
lower-case letter passes it.
"""

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from arches.app.utils.password_validation import (
    MinLengthValidator as ArchesMinLengthValidator,
)


class MinLengthValidator(ArchesMinLengthValidator):
    """Arches' length rule with a translatable help text."""

    def get_help_text(self):
        return ngettext(
            "At least %(n)s character", "At least %(n)s characters", self.min_length
        ) % {"n": self.min_length}


class HasLowerCaseValidator:
    """Refuse a password with no lower-case letter."""

    def validate(self, password, user=None):
        if not any(char.islower() for char in password):
            raise ValidationError(
                _("Your password must contain at least one lower case letter"),
                code="missing_lowercase",
            )

    def get_help_text(self):
        return _("Have at least 1 lower case character")

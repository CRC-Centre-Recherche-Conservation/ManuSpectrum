"""Password validators that complete Arches' own (``arches.app.utils.password_validation``).

Arches' ``HasUpperAndLowerCaseValidator`` only fails when a password has no
upper-case letter or nothing but upper-case letters, so a password without any
lower-case letter passes it.
"""

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


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

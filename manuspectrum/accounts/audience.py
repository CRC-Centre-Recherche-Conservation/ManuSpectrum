"""Who a message to the users may reach.

The platform sends nothing to its users by itself: an administrator copies the
addresses and writes from the shared project mailbox, in blind copy.
"""

from dataclasses import dataclass, field

from manuspectrum.accounts.retention import former_username
from manuspectrum.models import AccountRetention
from manuspectrum.utils.public_visibility import ANONYMOUS_USERNAME


@dataclass
class Audience:
    addresses: list = field(default_factory=list)
    inactive: int = 0
    no_address: int = 0
    anonymised: int = 0
    duplicates: int = 0

    @property
    def left_out(self):
        return self.inactive + self.no_address + self.anonymised


def audience(users):
    """The addresses of *users* a message may go to, and why the others are left out.

    A user is left out when anonymised (ledger row or ``former-user-<id>`` name),
    inactive, or without an address. The `anonymous` account is not counted. The
    addresses are deduplicated ignoring case and sorted.
    """
    users = [u for u in users if u.username != ANONYMOUS_USERNAME]
    done = set(
        AccountRetention.objects.filter(
            user_id__in=[u.pk for u in users], anonymised_on__isnull=False
        ).values_list("user_id", flat=True)
    )
    result = Audience()
    seen = {}
    for user in users:
        if user.pk in done or user.username == former_username(user.pk):
            result.anonymised += 1
        elif not user.is_active:
            result.inactive += 1
        elif not (user.email or "").strip():
            result.no_address += 1
        else:
            address = user.email.strip()
            if address.lower() in seen:
                result.duplicates += 1
            else:
                seen[address.lower()] = address
    result.addresses = [seen[key] for key in sorted(seen)]
    return result

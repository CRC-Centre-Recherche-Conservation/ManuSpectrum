"""Plan, shorten or withdraw the maintenance announcement of a site update.

Run by the update tooling on the host (``make -C deploy site-notice``), which
keeps the printed id. Every write goes through the ORM, so the
``SiteNotice`` receivers refresh the memo and the nginx snapshot.

``plan`` prints ``id=<n>``; ``end`` and ``withdraw`` print ``absent`` for an
unknown id and exit 0, so a repeated call is harmless. A validation error is
reported on stderr with exit status 1. Datetimes are naive Paris wall-clock
times (``YYYY-MM-DDTHH:MM``), as the model stores them.
"""

import re
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from manuspectrum.models import SiteNotice, site_now

# Stored announcement data, one literal per language field, not UI strings.
TEXT_EN = "Scheduled update of the site: brief interruption of service."
TEXT_FR = "Mise à jour du site : brève interruption de service."

ISO_MINUTE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
RELATIVE = re.compile(r"^\+(\d{1,4})([dhm])$")
UNITS = {"d": "days", "h": "hours", "m": "minutes"}


def parse_moment(text):
    if not ISO_MINUTE.match(text):
        raise CommandError(f"{text!r} is not a time: write YYYY-MM-DDTHH:MM.")
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M")
    except ValueError as error:
        raise CommandError(f"{text!r} is not a valid time: {error}.")


def parse_at(text):
    if text == "now":
        return site_now().replace(second=0, microsecond=0)
    match = RELATIVE.match(text)
    if match:
        delta = timedelta(**{UNITS[match[2]]: int(match[1])})
        return site_now().replace(second=0, microsecond=0) + delta
    return parse_moment(text)


def notice_id(text):
    if not re.fullmatch(r"\d{1,9}", text):
        raise CommandError(f"{text!r} is not an announcement id.")
    return int(text)


class Command(BaseCommand):
    help = "Plan, end or withdraw the announcement of a site update."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)
        plan = sub.add_parser("plan", help="Create the announcement, print id=<n>.")
        plan.add_argument("--start", required=True, help="YYYY-MM-DDTHH:MM, Paris")
        plan.add_argument("--end", required=True, help="YYYY-MM-DDTHH:MM, Paris")
        plan.add_argument("--reminders", help='for example "1d 1h 10m"')
        end = sub.add_parser("end", help="Set the end, or withdraw if not after start.")
        end.add_argument("id")
        end.add_argument("--at", default="now", help="now, +24h, +30m, +1d or ISO")
        withdraw = sub.add_parser("withdraw", help="Delete the announcement.")
        withdraw.add_argument("id")

    def handle(self, *args, **options):
        getattr(self, f"do_{options['action']}")(options)

    def do_plan(self, options):
        fields = {}
        if options["reminders"] is not None:
            fields["reminders"] = options["reminders"]
        notice = SiteNotice(
            kind=SiteNotice.MAINTENANCE,
            display=SiteNotice.EVENT,
            text_en=TEXT_EN,
            text_fr=TEXT_FR,
            starts_at=parse_moment(options["start"]),
            ends_at=parse_moment(options["end"]),
            **fields,
        )
        try:
            notice.full_clean()
        except ValidationError as error:
            raise CommandError("; ".join(error.messages))
        notice.save()
        self.stdout.write(f"id={notice.pk}")

    def do_end(self, options):
        pk, at = notice_id(options["id"]), parse_at(options["at"])
        notice = SiteNotice.objects.filter(pk=pk).first()
        if notice is None:
            self.stdout.write("absent")
            return
        if at <= notice.starts_at:
            notice.delete()
            return
        notice.ends_at = at
        notice.save()

    def do_withdraw(self, options):
        deleted, _ = SiteNotice.objects.filter(pk=notice_id(options["id"])).delete()
        if not deleted:
            self.stdout.write("absent")

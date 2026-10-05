"""Set a user's password from a file, so the secret never appears on a command line.

``setup_db`` creates the superuser ``admin`` with a publicly known password; the
container entrypoint (``init``) runs this command right after it with the
``admin_password`` Compose secret. The same command rotates the password later.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

MIN_LENGTH = 16
DEFAULT_PASSWORD = "admin"
EXIT_DEFAULT_PASSWORD = 3


class Command(BaseCommand):
    help = (
        "Set the password of a user from a file (default: admin, ADMIN_PASSWORD_FILE)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument(
            "--check-default",
            action="store_true",
            help="Change nothing: exit %d when the user still accepts Arches' "
            "default password, 0 otherwise (also when the user is absent)."
            % EXIT_DEFAULT_PASSWORD,
        )
        parser.add_argument(
            "--password-file", default=os.environ.get("ADMIN_PASSWORD_FILE")
        )

    def handle(self, *args, username, password_file, check_default, **options):
        if check_default:
            user = get_user_model().objects.filter(username=username).first()
            if user is not None and user.check_password(DEFAULT_PASSWORD):
                self.stderr.write(
                    f"user {username!r} still has Arches' default password"
                )
                raise SystemExit(EXIT_DEFAULT_PASSWORD)
            return
        if not password_file:
            raise CommandError(
                "no password file: pass --password-file or set ADMIN_PASSWORD_FILE"
            )
        try:
            with open(password_file, encoding="utf-8") as handle:
                password = handle.read().strip()
        except OSError as error:
            raise CommandError(
                f"cannot read the password file {password_file}: {error.strerror}"
            ) from None
        if not password:
            raise CommandError(f"the password file {password_file} is empty")
        if len(password) < MIN_LENGTH:
            raise CommandError(
                f"the password in {password_file} is shorter than {MIN_LENGTH} characters"
            )
        user = get_user_model().objects.filter(username=username).first()
        if user is None:
            raise CommandError(f"user {username!r} does not exist")
        user.set_password(password)
        user.save(update_fields=["password"])
        self.stdout.write(f"Password of {username!r} set from {password_file}.")

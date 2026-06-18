from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from pykeg.core import models


class Command(BaseCommand):
    help = "Renames user from <from> to <to>."

    def add_arguments(self, parser):
        parser.add_argument("from_username", help="Existing username to rename.")
        parser.add_argument("to_username", help="New username.")

    def handle(self, *args, **options):
        from_username = options["from_username"]
        to_username = options["to_username"]

        if from_username == "guest":
            raise CommandError("Cannot rename the guest user.")

        with transaction.atomic():
            try:
                user = models.User.objects.get(username=from_username)
            except models.User.DoesNotExist:
                raise CommandError('User named "{}" does not exist'.format(from_username))

            user.username = to_username
            user.save()

        print('"{}" has been renamed "{}"'.format(from_username, to_username))

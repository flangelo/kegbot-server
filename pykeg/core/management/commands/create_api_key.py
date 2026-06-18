from django.core.management.base import BaseCommand, CommandError

from pykeg.core import models


class Command(BaseCommand):
    help = "Creates an API key with the given description."

    def add_arguments(self, parser):
        parser.add_argument("description", help="Description for the new API key.")

    def handle(self, *args, **options):
        description = options.get("description")
        if not description:
            raise CommandError("Must specify description")

        key = models.ApiKey.objects.create(description=description)
        print(key.key)

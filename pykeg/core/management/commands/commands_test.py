"""Tests for assorted management commands (create_api_key, rename_user, regen_stats)."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from pykeg.core import defaults, models
from pykeg.test import factories


@pytest.mark.django_db
def test_create_api_key_creates_key():
    before = models.ApiKey.objects.count()
    call_command("create_api_key", "my integration")
    assert models.ApiKey.objects.count() == before + 1
    assert models.ApiKey.objects.filter(description="my integration").exists()


@pytest.mark.django_db
def test_rename_user_changes_username():
    defaults.set_defaults(set_is_setup=True, create_controller=True)
    models.User.create_new_user("oldname", "old@example.com")

    call_command("rename_user", "oldname", "newname")

    assert models.User.objects.filter(username="newname").exists()
    assert not models.User.objects.filter(username="oldname").exists()


@pytest.mark.django_db
def test_rename_user_refuses_guest():
    defaults.set_defaults(set_is_setup=True, create_controller=True)
    with pytest.raises(CommandError):
        call_command("rename_user", "guest", "somethingelse")


@pytest.mark.django_db
def test_regen_stats_runs_after_a_pour():
    defaults.set_defaults(set_is_setup=True, create_controller=True)
    factories.start_keg("kegboard.flow0")
    factories.pour("kegboard.flow0", ticks=500)

    # Should rebuild stats without raising. RQ runs synchronously under test.
    call_command("regen_stats")

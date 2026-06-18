"""Tests for pykeg.web.util."""

import pytest
from django.conf import settings

from pykeg.web import util


def test_get_base_url_uses_configured_base_url():
    # Under pytest, KEGBOT_BASE_URL defaults to http://test.example.com.
    assert util.get_base_url() == settings.KEGBOT["KEGBOT_BASE_URL"].rstrip("/")


def test_get_base_url_strips_trailing_slash(monkeypatch):
    monkeypatch.setitem(settings.KEGBOT, "KEGBOT_BASE_URL", "http://example.org/")
    assert util.get_base_url() == "http://example.org"


def test_get_base_url_raises_without_base_url_or_request(monkeypatch):
    # No configured base URL and no active request → cannot resolve.
    monkeypatch.setitem(settings.KEGBOT, "KEGBOT_BASE_URL", "")
    monkeypatch.setattr(util, "get_current_request", lambda: None)
    with pytest.raises(util.UnknownBaseUrlException):
        util.get_base_url()


def test_get_base_url_falls_back_to_request(monkeypatch):
    monkeypatch.setitem(settings.KEGBOT, "KEGBOT_BASE_URL", "")

    class _FakeRequest:
        def build_absolute_uri(self, path):
            return "http://reqhost/" + path.lstrip("/")

    monkeypatch.setattr(util, "get_current_request", lambda: _FakeRequest())
    assert util.get_base_url() == "http://reqhost"

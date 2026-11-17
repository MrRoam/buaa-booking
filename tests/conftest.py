from __future__ import annotations

import json
from datetime import date, datetime

import pytest
import requests

from buaa_booking.config import CHINA, load_config


@pytest.fixture(autouse=True)
def no_live_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must not send live network requests")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"enabled": True, "venue_site_id": 38, "dates": ["2026-10-18"],
        "weekdays": [], "release_lead_days": 2, "preferences": [{"start": "19:00", "end": "21:00"}],
        "notifications": {"desktop": False}}), encoding="utf-8")
    return path


@pytest.fixture
def config(config_file):
    return load_config(config_file)


@pytest.fixture
def target():
    return date(2026, 10, 18)

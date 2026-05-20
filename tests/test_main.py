import pytest
import requests

from datetime import date

import main


class DummyResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def test_format_pace():
    assert main.format_pace(360.0) == "6:00/mi"
    assert main.format_pace(367.5) == "6:08/mi"
    assert main.format_pace(59.9) == "0:60/mi"


def test_miles():
    assert main.miles(1609.344) == pytest.approx(1.0)
    assert main.miles(804.672) == pytest.approx(0.5)


def test_parse_strava_local_date():
    activity = {"start_date_local": "2026-05-20T12:34:56Z"}
    assert main.parse_strava_local_date(activity) == date(2026, 5, 20)


def test_is_outdoor_activity():
    assert main.is_outdoor_activity({"trainer": False}) is True
    assert main.is_outdoor_activity({"trainer": None}) is True
    assert main.is_outdoor_activity({"trainer": True}) is False


def test_get_activity_temp_stats_returns_stats(monkeypatch):
    dummy_stream = {
        "temp": {
            "data": [10.0, 15.0, 20.0],
        }
    }

    def fake_get(*args, **kwargs):
        return DummyResponse(dummy_stream)

    monkeypatch.setattr(main.requests, "get", fake_get)

    result = main.get_activity_temp_stats(activity_id=123, access_token="fake-token")

    assert result == {
        "low_f": 50.0,
        "high_f": 68.0,
        "average_f": 59.0,
    }


def test_get_activity_temp_stats_returns_none_for_empty_data(monkeypatch):
    dummy_stream = {"temp": {"data": []}}

    def fake_get(*args, **kwargs):
        return DummyResponse(dummy_stream)

    monkeypatch.setattr(main.requests, "get", fake_get)

    assert main.get_activity_temp_stats(activity_id=123, access_token="fake-token") is None


def test_get_weather_for_activity_returns_weather(monkeypatch):
    activity = {
        "id": 987,
        "name": "Morning Run",
        "type": "Run",
        "sport_type": "Run",
        "start_latlng": [37.7749, -122.4194],
        "start_date_local": "2026-05-20T08:00:00Z",
    }

    api_payload = {
        "hourly": {
            "time": ["2026-05-20T08:00"],
            "temperature_2m": [55.3],
        }
    }

    def fake_get(*args, **kwargs):
        return DummyResponse(api_payload)

    monkeypatch.setattr(main.requests, "get", fake_get)

    result = main.get_weather_for_activity(activity)

    assert result == {
        "activity_id": 987,
        "name": "Morning Run",
        "type": "Run",
        "sport_type": "Run",
        "date": "2026-05-20T08:00:00Z",
        "weather_hour": "2026-05-20T08:00",
        "temperature_f": 55.3,
    }


def test_get_weather_for_activity_returns_none_when_latlng_missing():
    activity = {
        "id": 123,
        "name": "Trail Run",
        "type": "Run",
        "sport_type": "Run",
        "start_date_local": "2026-05-20T09:00:00Z",
    }

    assert main.get_weather_for_activity(activity) is None


def test_fetch_activities_since_paginates(monkeypatch):
    pages = [
        [{"id": 1}],
        [{"id": 2}],
        [],
    ]

    def fake_get(*args, **kwargs):
        page = kwargs["params"]["page"]
        return DummyResponse(pages[page - 1])

    monkeypatch.setattr(main.requests, "get", fake_get)

    result = main.fetch_activities_since("fake-token", date(2026, 5, 18))

    assert result == [{"id": 1}, {"id": 2}]

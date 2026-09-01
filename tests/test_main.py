import pytest
import requests
import logging
import threading

from datetime import date

import main


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "CACHE_PATH", tmp_path / "strava_cache.json")


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


def test_run_streak_respects_historical_end_date(monkeypatch):
    monkeypatch.setitem(main.tokens, "access_token", "fake-token")
    requested_ranges = []

    def fake_fetch(token, start_date, end_date):
        requested_ranges.append((start_date, end_date))
        return [{
            "type": "Run",
            "distance": 1609.344,
            "start_date_local": "2026-08-15T07:00:00Z",
        }]

    monkeypatch.setattr(main, "fetch_cached_activities", fake_fetch)

    result = main.run_streak(start="2026-08-01", end="2026-08-31")

    assert requested_ranges == [(date(2026, 8, 1), date(2026, 8, 31))]
    assert result["period"] == {"start": "2026-08-01", "end": "2026-08-31"}
    assert result["total_days"] == 31
    assert result["total_miles"] == 1.0


def test_run_streak_rejects_reversed_range(monkeypatch):
    monkeypatch.setitem(main.tokens, "access_token", "fake-token")

    response = main.run_streak(start="2026-08-31", end="2026-08-01")

    assert response.status_code == 400


def test_run_streak_can_read_without_refreshing(monkeypatch):
    monkeypatch.setitem(main.tokens, "access_token", "fake-token")
    cached_activity = {
        "type": "Run",
        "distance": 1609.344,
        "start_date_local": "2026-08-15T07:00:00Z",
    }
    monkeypatch.setattr(
        main,
        "read_cached_activities",
        lambda start_date, end_date: [cached_activity],
    )

    def unexpected_refresh(*args, **kwargs):
        raise AssertionError("cache-only requests must not refresh Strava data")

    monkeypatch.setattr(main, "fetch_cached_activities", unexpected_refresh)

    result = main.run_streak(
        start="2026-08-01", end="2026-08-31", refresh=False
    )

    assert result["total_miles"] == 1.0


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


def test_get_activity_pace_data_includes_summary_and_stream_samples(monkeypatch):
    stream = {
        "time": {"data": [0, 10, 20]},
        "distance": {"data": [0.0, 40.0, 85.0]},
        "velocity_smooth": {"data": [0.0, 4.0, 4.5]},
    }
    monkeypatch.setattr(main.requests, "get", lambda *args, **kwargs: DummyResponse(stream))

    result = main.get_activity_pace_data({
        "id": 123,
        "distance": 1609.344,
        "moving_time": 480,
        "average_speed": 3.353,
        "max_speed": 4.5,
    }, "fake-token")

    assert result["average_seconds_per_mile"] == 480.0
    assert result["average_pace"] == "8:00/mi"
    assert result["sample_count"] == 2
    assert result["samples"][0] == {
        "elapsed_seconds": 10,
        "distance_meters": 40.0,
        "meters_per_second": 4.0,
        "seconds_per_mile": 402.3,
        "pace": "6:42/mi",
    }


def test_add_pace_data_enriches_only_new_runs(monkeypatch):
    activities = [
        {"id": 1, "type": "Run"},
        {"id": 2, "type": "Ride"},
        {"id": 3, "type": "Run", "pace_data": {"sample_count": 1}},
    ]
    calls = []
    monkeypatch.setattr(
        main,
        "get_activity_pace_data",
        lambda activity, token: calls.append((activity["id"], token)) or {"sample_count": 2},
    )

    main.add_pace_data_to_new_runs(activities, "fake-token")

    assert calls == [(1, "fake-token")]
    assert activities[0]["pace_data"] == {"sample_count": 2}
    assert "pace_data" not in activities[1]
    assert activities[2]["pace_data"] == {"sample_count": 1}


def test_day_details_includes_cached_pace_data(monkeypatch):
    pace_data = {"average_pace": "8:00/mi", "sample_count": 2, "samples": []}
    monkeypatch.setitem(main.tokens, "access_token", "fake-token")
    monkeypatch.setattr(main, "fetch_cached_activities", lambda *args: [{
        "id": 42,
        "name": "Morning Run",
        "type": "Run",
        "start_date_local": "2026-05-20T08:00:00Z",
        "distance": 1609.344,
        "moving_time": 480,
        "trainer": False,
        "pace_data": pace_data,
    }])
    monkeypatch.setattr(main, "get_weather_for_activity", lambda activity: None)

    result = main.day_details("2026-05-20")

    assert result["activities"][0]["pace_data"] == pace_data


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


def test_should_refresh_only_last_five_calendar_days():
    today = date(2026, 7, 31)

    assert main.should_refresh_date(date(2026, 7, 27), today) is True
    assert main.should_refresh_date(date(2026, 7, 26), today) is False


def test_fetch_cached_activities_reuses_old_dates(monkeypatch):
    cached_activity = {
        "id": 10,
        "start_date_local": "2026-07-20T08:00:00Z",
    }
    main.save_data_cache({
        "version": 1,
        "activities": {"2026-07-20": [cached_activity]},
        "weather": {},
    })

    def unexpected_fetch(*args, **kwargs):
        raise AssertionError("an old cached date should not be fetched")

    monkeypatch.setattr(main, "fetch_activities_since", unexpected_fetch)

    assert main.fetch_cached_activities(
        "fake-token", date(2026, 7, 20), date(2026, 7, 20)
    ) == [cached_activity]


def test_fetch_cached_activities_refreshes_recent_and_records_empty_days(monkeypatch):
    calls = []

    def fake_fetch(access_token, start_date):
        calls.append(start_date)
        return [{"id": 20, "start_date_local": "2026-07-30T08:00:00Z"}]

    monkeypatch.setattr(main, "fetch_activities_since", fake_fetch)

    result = main.fetch_cached_activities(
        "fake-token", date(2026, 7, 29), date(2026, 7, 30)
    )

    assert [activity["id"] for activity in result] == [20]
    assert calls == [date(2026, 7, 29)]
    cache = main.load_data_cache()
    assert cache["activities"]["2026-07-29"] == []
    assert cache["activities"]["2026-07-30"][0]["id"] == 20


def test_get_weather_for_activity_reuses_old_cached_result(monkeypatch):
    weather = {"activity_id": 99, "temperature_f": 61.2}
    main.save_data_cache({
        "version": 1,
        "activities": {},
        "weather": {"2026-07-20": {"99": weather}},
    })
    activity = {
        "id": 99,
        "start_latlng": [40.0, -75.0],
        "start_date_local": "2026-07-20T07:00:00Z",
    }

    def unexpected_get(*args, **kwargs):
        raise AssertionError("old weather should come from the cache")

    monkeypatch.setattr(main.requests, "get", unexpected_get)

    assert main.get_weather_for_activity(activity) == weather


def test_fetch_cached_activities_populates_weather_on_initial_scan(monkeypatch):
    activity = {
        "id": 30,
        "start_date_local": "2026-07-20T07:00:00Z",
        "start_latlng": [40.0, -75.0],
        "trainer": False,
    }
    weather_calls = []

    monkeypatch.setattr(
        main, "fetch_activities_since", lambda access_token, start_date: [activity]
    )
    monkeypatch.setattr(
        main,
        "get_weather_for_activity",
        lambda item: weather_calls.append(item["id"]),
    )

    main.fetch_cached_activities(
        "fake-token", date(2026, 7, 20), date(2026, 7, 20)
    )

    assert weather_calls == [30]


def test_initial_scan_skips_weather_for_treadmill_activities(monkeypatch):
    activity = {
        "id": 31,
        "start_date_local": "2026-07-20T07:00:00Z",
        "start_latlng": [40.0, -75.0],
        "trainer": True,
    }

    monkeypatch.setattr(
        main, "fetch_activities_since", lambda access_token, start_date: [activity]
    )

    def unexpected_weather(*args, **kwargs):
        raise AssertionError("treadmill activities should not request weather")

    monkeypatch.setattr(main, "get_weather_for_activity", unexpected_weather)

    main.fetch_cached_activities(
        "fake-token", date(2026, 7, 20), date(2026, 7, 20)
    )


def test_fetch_cached_activities_logs_cached_and_pull_days(monkeypatch, caplog):
    main.save_data_cache({
        "version": 1,
        "activities": {"2026-07-20": []},
        "weather": {},
    })
    monkeypatch.setattr(main, "fetch_activities_since", lambda *args: [])

    with caplog.at_level(logging.INFO, logger="strava_api"):
        main.fetch_cached_activities(
            "fake-token", date(2026, 7, 20), date(2026, 7, 21)
        )

    message = caplog.messages[-1]
    assert "cached=['2026-07-20']" in message
    assert "pull=['2026-07-21']" in message
    assert "missing=['2026-07-21']" in message


def test_cache_writes_are_serialized_across_threads(monkeypatch):
    active_writers = 0
    maximum_writers = 0
    writer_guard = threading.Lock()
    original_fetch = main.fetch_activities_since

    def observed_fetch(*args, **kwargs):
        nonlocal active_writers, maximum_writers
        with writer_guard:
            active_writers += 1
            maximum_writers = max(maximum_writers, active_writers)
        try:
            return []
        finally:
            with writer_guard:
                active_writers -= 1

    monkeypatch.setattr(main, "fetch_activities_since", observed_fetch)
    threads = [
        threading.Thread(
            target=main.fetch_cached_activities,
            args=("fake-token", date(2026, 7, 20), date(2026, 7, 20)),
        )
        for _ in range(3)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert maximum_writers == 1
    monkeypatch.setattr(main, "fetch_activities_since", original_fetch)

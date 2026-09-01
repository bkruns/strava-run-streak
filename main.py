import os
import json
import logging
import requests
import threading
from functools import wraps
from pathlib import Path
from dotenv import load_dotenv

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

load_dotenv()

app = FastAPI()


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "Unhandled error while serving %s %s", request.method, request.url.path
    )
    return JSONResponse(
        {"error": "Internal server error. Check the server logs for details."},
        status_code=500,
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
REDIRECT_URI = os.getenv("STRAVA_REDIRECT_URI")

AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
METERS_PER_MILE = 1609.344

tokens = {}

CACHE_PATH = Path(os.getenv("STRAVA_CACHE_PATH", "strava_cache.json"))
CACHE_REFRESH_DAYS = 5
CACHE_LOCK = threading.RLock()


def synchronized_cache(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        with CACHE_LOCK:
            return function(*args, **kwargs)

    return wrapper

# configure basic logging
logger = logging.getLogger("strava_api")
logging.basicConfig(level=logging.INFO)

# Warn if required environment variables are missing (do not log secret values)
missing_env = [
    name
    for name in ("STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REDIRECT_URI")
    if not os.getenv(name)
]

if missing_env:
    logger.warning("Missing required environment variables: %s", ", ".join(missing_env))
else:
    logger.info("Required STRAVA environment variables appear to be set.")


@app.get("/")
def home():
    return {"message": "RunLens Strava API starter"}


@app.get("/login")
def login():
    scope = "read,activity:read_all"

    url = (
        f"{AUTH_URL}"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&approval_prompt=auto"
        f"&scope={scope}"
    )

    return RedirectResponse(url)


@app.get("/callback")
def callback(request: Request):
    code = request.query_params.get("code")
    error = request.query_params.get("error")

    if error:
        return JSONResponse({"error": error}, status_code=400)

    if not code:
        return JSONResponse({"error": "Missing authorization code"}, status_code=400)

    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )

    response.raise_for_status()
    token_data = response.json()

    tokens["access_token"] = token_data["access_token"]
    tokens["refresh_token"] = token_data["refresh_token"]
    tokens["expires_at"] = token_data["expires_at"]

    return HTMLResponse("""
    <html>
    <body style="font-family: Arial; text-align: center; padding-top: 40px;">
        <h2>✅ Strava Login Successful</h2>
        <p>You can close this window.</p>

        <script>
        window.close();
        </script>
    </body>
    </html>
    """)


@app.get("/activities")
def activities():
    access_token = tokens.get("access_token")

    if not access_token:
        return JSONResponse(
            {"error": "Not authenticated. Visit /login first."},
            status_code=401,
        )

    response = requests.get(
        ACTIVITIES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={"per_page": 10, "page": 1},
        timeout=15,
    )

    response.raise_for_status()

    return response.json()

def get_activity_temp_stats(activity_id: int, access_token: str):
    response = requests.get(
        f"https://www.strava.com/api/v3/activities/{activity_id}/streams",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "keys": "temp",
            "key_by_type": "true",
        },
        timeout=15,
    )

    response.raise_for_status()
    streams = response.json()

    temp_stream = streams.get("temp", {})
    temps_c = temp_stream.get("data", [])

    if not temps_c:
        return None

    temps_f = [(temp * 9 / 5) + 32 for temp in temps_c]

    return {
        "low_f": round(min(temps_f), 1),
        "high_f": round(max(temps_f), 1),
        "average_f": round(sum(temps_f) / len(temps_f), 1),
    }


def get_activity_pace_data(activity: dict, access_token: str):
    """Download and format the pace stream for a newly fetched run."""
    activity_id = activity.get("id")
    if activity_id is None:
        return None

    response = requests.get(
        f"https://www.strava.com/api/v3/activities/{activity_id}/streams",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "keys": "time,distance,velocity_smooth",
            "key_by_type": "true",
        },
        timeout=15,
    )
    response.raise_for_status()
    streams = response.json()

    times = streams.get("time", {}).get("data", [])
    distances = streams.get("distance", {}).get("data", [])
    velocities = streams.get("velocity_smooth", {}).get("data", [])
    sample_count = min(len(times), len(distances), len(velocities))

    samples = []
    for index in range(sample_count):
        velocity = velocities[index]
        if not isinstance(velocity, (int, float)) or velocity <= 0:
            continue

        seconds_per_mile = METERS_PER_MILE / velocity
        samples.append({
            "elapsed_seconds": times[index],
            "distance_meters": round(distances[index], 1),
            "meters_per_second": round(velocity, 3),
            "seconds_per_mile": round(seconds_per_mile, 1),
            "pace": format_pace(seconds_per_mile),
        })

    distance_meters = activity.get("distance") or 0
    moving_seconds = activity.get("moving_time") or 0
    average_seconds_per_mile = (
        moving_seconds / miles(distance_meters)
        if distance_meters > 0 and moving_seconds > 0
        else None
    )

    return {
        "average_seconds_per_mile": (
            round(average_seconds_per_mile, 1)
            if average_seconds_per_mile is not None
            else None
        ),
        "average_pace": (
            format_pace(average_seconds_per_mile)
            if average_seconds_per_mile is not None
            else None
        ),
        "average_speed_meters_per_second": activity.get("average_speed"),
        "max_speed_meters_per_second": activity.get("max_speed"),
        "sample_count": len(samples),
        "samples": samples,
    }


@app.get("/last-week-stats")
def weekly_stats():
    access_token = tokens.get("access_token")

    if not access_token:
        return JSONResponse(
            {"error": "Not authenticated. Visit /login first."},
            status_code=401,
        )

    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)

    activities = fetch_cached_activities(
        access_token, week_start.date(), now.date()
    )

    runs = [
        activity
        for activity in activities
        if activity.get("type") == "Run"
    ]

    total_meters = sum(
        run.get("distance", 0)
        for run in runs
    )

    total_miles = total_meters / 1609.344

    total_moving_seconds = sum(
        run.get("moving_time", 0)
        for run in runs
    )

    avg_pace_seconds_per_mile = (
        total_moving_seconds / total_miles
        if total_miles > 0
        else 0
    )

    total_elevation_meters = sum(
        run.get("total_elevation_gain", 0)
        for run in runs
    )

    longest_run = max(
        runs,
        key=lambda run: run.get("distance", 0),
        default=None,
    )

    outdoor_runs = [
        run
        for run in runs
        if is_outdoor_activity(run)
    ]

    weather_results = [
        get_weather_for_activity(run)
        for run in outdoor_runs
    ]

    weather_results = [
        weather
        for weather in weather_results
        if weather is not None
        and weather.get("temperature_f") is not None
    ]

    temps = [
        weather["temperature_f"]
        for weather in weather_results
    ]

    return {
        "period": {
            "start": week_start.isoformat(),
            "end": now.isoformat(),
        },

        "run_count": len(runs),

        "total_miles": round(total_miles, 2),

        "average_pace": (
            format_pace(avg_pace_seconds_per_mile)
            if total_miles > 0
            else None
        ),

        "total_elevation_feet": round(
            total_elevation_meters * 3.28084
        ),

        "temperature": {
            "outdoor_runs_with_weather": len(weather_results),
            "average_temp_f": (
                round(sum(temps) / len(temps), 1)
                if temps
                else None
            ),
            "low_temp_f": (
                round(min(temps), 1)
                if temps
                else None
            ),
            "high_temp_f": (
                round(max(temps), 1)
                if temps
                else None
            ),
        },

        "longest_run": {
            "name": longest_run.get("name"),
            "date": longest_run.get("start_date_local"),
            "miles": round(
                longest_run.get("distance", 0) / 1609.344,
                2,
            ),
            "moving_time_minutes": round(
                longest_run.get("moving_time", 0) / 60,
                1,
            ),
        }
        if longest_run
        else None,
    }

@app.get("/activity/{activity_id}")
def activity_details(activity_id: int):
    access_token = tokens.get("access_token")

    if not access_token:
        return JSONResponse(
            {"error": "Not authenticated. Visit /login first."},
            status_code=401,
        )

    response = requests.get(
        f"https://www.strava.com/api/v3/activities/{activity_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "include_all_efforts": "true",
        },
        timeout=15,
    )

    response.raise_for_status()
    return response.json()

def is_outdoor_activity(activity: dict) -> bool:
    return activity.get("trainer") is not True


@synchronized_cache
def get_weather_for_activity(activity: dict):
    latlng = activity.get("start_latlng")

    if not latlng or len(latlng) != 2:
        return None

    lat, lon = latlng

    start_date_local = activity.get("start_date_local")
    if not start_date_local:
        return None

    activity_time = datetime.fromisoformat(
        start_date_local.replace("Z", "+00:00")
    )

    activity_hour = activity_time.strftime("%Y-%m-%dT%H:00")

    activity_date = activity_time.date().isoformat()
    activity_id = str(activity.get("id"))
    cache = load_data_cache()
    cached_day = cache["weather"].get(activity_date, {})

    if not should_refresh_date(activity_time.date()) and activity_id in cached_day:
        return cached_day[activity_id]

    response = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": activity_date,
            "end_date": activity_date,
            "hourly": "temperature_2m",
            "temperature_unit": "fahrenheit",
            "timezone": "auto",
        },
        timeout=15,
    )

    response.raise_for_status()
    data = response.json()

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])

    result = None
    if activity_hour in times:
        index = times.index(activity_hour)
        result = {
            "activity_id": activity.get("id"),
            "name": activity.get("name"),
            "type": activity.get("type"),
            "sport_type": activity.get("sport_type"),
            "date": start_date_local,
            "weather_hour": activity_hour,
            "temperature_f": temps[index],
        }

    cache = load_data_cache()
    cache["weather"].setdefault(activity_date, {})[activity_id] = result
    save_data_cache(cache)
    return result


@app.get("/weekly-outdoor-temp")
def weekly_outdoor_temp():
    access_token = tokens.get("access_token")

    if not access_token:
        return JSONResponse(
            {"error": "Not authenticated. Visit /login first."},
            status_code=401,
        )

    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)

    activities = fetch_cached_activities(
        access_token, week_start.date(), now.date()
    )

    outdoor_activities = [
        activity
        for activity in activities
        if is_outdoor_activity(activity)
    ]

    weather_results = [
        get_weather_for_activity(activity)
        for activity in outdoor_activities
    ]

    weather_results = [
        weather
        for weather in weather_results
        if weather is not None
        and weather.get("temperature_f") is not None
    ]

    temps = [
        weather["temperature_f"]
        for weather in weather_results
    ]

    return {
        "period": {
            "start": week_start.isoformat(),
            "end": now.isoformat(),
        },
        "activity_count": len(activities),
        "outdoor_activity_count": len(outdoor_activities),
        "activities_with_weather": len(weather_results),
        "average_temp_f": round(sum(temps) / len(temps), 1) if temps else None,
        "low_temp_f": round(min(temps), 1) if temps else None,
        "high_temp_f": round(max(temps), 1) if temps else None,
        "activities": weather_results,
    }

@app.get("/weekly-stats")
def weekly_stats(weeks: int = 1):
    access_token = tokens.get("access_token")

    if not access_token:
        return JSONResponse(
            {"error": "Not authenticated. Visit /login first."},
            status_code=401,
        )

    weeks = max(1, min(weeks, 26))

    now = datetime.now(timezone.utc)
    start = now - timedelta(weeks=weeks)

    activities = fetch_cached_activities(access_token, start.date(), now.date())

    runs = [
        activity
        for activity in activities
        if activity.get("type") == "Run"
    ]

    weekly_results = []

    for week_offset in range(weeks):
        week_end = now - timedelta(weeks=week_offset)
        week_start = week_end - timedelta(days=7)

        week_runs = [
            run for run in runs
            if week_start <= datetime.fromisoformat(
                run["start_date"].replace("Z", "+00:00")
            ) < week_end
        ]

        total_meters = sum(run.get("distance", 0) for run in week_runs)
        total_miles = total_meters / 1609.344

        total_seconds = sum(run.get("moving_time", 0) for run in week_runs)

        avg_pace_seconds = (
            total_seconds / total_miles
            if total_miles > 0
            else 0
        )

        elevation_meters = sum(
            run.get("total_elevation_gain", 0)
            for run in week_runs
        )

        outdoor_runs = [
            run for run in week_runs
            if is_outdoor_activity(run)
        ]

        weather_results = [
            get_weather_for_activity(run)
            for run in outdoor_runs
        ]

        weather_results = [
            weather for weather in weather_results
            if weather is not None
            and weather.get("temperature_f") is not None
        ]

        temps = [
            weather["temperature_f"]
            for weather in weather_results
        ]

        longest_run = max(
            week_runs,
            key=lambda run: run.get("distance", 0),
            default=None,
        )

        weekly_results.append({
            "week_start": week_start.date().isoformat(),
            "week_end": week_end.date().isoformat(),
            "run_count": len(week_runs),
            "total_miles": round(total_miles, 2),
            "average_pace": (
                format_pace(avg_pace_seconds)
                if total_miles > 0
                else None
            ),
            "total_elevation_feet": round(elevation_meters * 3.28084),
            "temperature": {
                "outdoor_runs_with_weather": len(weather_results),
                "average_temp_f": round(sum(temps) / len(temps), 1) if temps else None,
                "low_temp_f": round(min(temps), 1) if temps else None,
                "high_temp_f": round(max(temps), 1) if temps else None,
            },
            "longest_run": {
                "name": longest_run.get("name"),
                "date": longest_run.get("start_date_local"),
                "miles": round(longest_run.get("distance", 0) / 1609.344, 2),
            } if longest_run else None,
        })

    return {
        "weeks": weeks,
        "generated_at": now.isoformat(),
        "weekly_stats": list(reversed(weekly_results)),
    }

def format_pace(seconds_per_mile: float) -> str:
    minutes = int(seconds_per_mile // 60)
    seconds = int(round(seconds_per_mile % 60))
    return f"{minutes}:{seconds:02d}/mi"

def miles(meters: float) -> float:
    return meters / METERS_PER_MILE


def parse_strava_local_date(activity: dict) -> date:
    return datetime.fromisoformat(
        activity["start_date_local"].replace("Z", "+00:00")
    ).date()


def fetch_activities_since(access_token: str, start_date: date):
    after_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)

    all_activities = []
    page = 1

    while True:
        response = requests.get(
            ACTIVITIES_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "after": int(after_dt.timestamp()),
                "per_page": 200,
                "page": page,
            },
            timeout=15,
        )

        response.raise_for_status()
        activities = response.json()

        if not activities:
            break

        all_activities.extend(activities)
        page += 1

    return all_activities


def empty_data_cache():
    return {"version": 1, "activities": {}, "weather": {}}


def load_data_cache():
    if not CACHE_PATH.exists():
        return empty_data_cache()

    try:
        with CACHE_PATH.open("r", encoding="utf-8") as cache_file:
            cache = json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        logger.warning("Unable to read %s; starting with an empty cache", CACHE_PATH)
        return empty_data_cache()

    cache.setdefault("version", 1)
    cache.setdefault("activities", {})
    cache.setdefault("weather", {})
    return cache


def save_data_cache(cache):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = CACHE_PATH.with_suffix(CACHE_PATH.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as cache_file:
        json.dump(cache, cache_file, indent=2, sort_keys=True)
        cache_file.write("\n")
    temporary_path.replace(CACHE_PATH)


def should_refresh_date(day: date, today: date = None):
    today = today or datetime.now().date()
    return day >= today - timedelta(days=CACHE_REFRESH_DAYS - 1)


def cache_weather_for_activities(activities):
    for activity in activities:
        if not is_outdoor_activity(activity) or not activity.get("start_latlng"):
            continue

        try:
            get_weather_for_activity(activity)
        except requests.RequestException:
            logger.exception(
                "Unable to fetch weather for activity %s", activity.get("id")
            )


def add_pace_data_to_new_runs(activities, access_token: str):
    """Enrich new run summaries before they are persisted in the JSON cache."""
    for activity in activities:
        if activity.get("type") != "Run" or "pace_data" in activity:
            continue

        try:
            activity["pace_data"] = get_activity_pace_data(activity, access_token)
        except requests.RequestException:
            logger.exception(
                "Unable to fetch pace data for activity %s", activity.get("id")
            )


@synchronized_cache
def fetch_cached_activities(access_token: str, start_date: date, end_date: date = None):
    """Return activities by local date, refreshing today and the prior four days.

    Empty days are persisted too, so historical dates without activities do not
    cause another Strava request on every read.
    """
    today = datetime.now().date()
    end_date = min(end_date or today, today)
    if start_date > end_date:
        return []

    cache = load_data_cache()
    cached_dates = cache["activities"]
    requested_days = [
        start_date + timedelta(days=offset)
        for offset in range((end_date - start_date).days + 1)
    ]
    cached_requested_days = [
        day for day in requested_days if day.isoformat() in cached_dates
    ]
    missing_days = [
        day for day in requested_days if day.isoformat() not in cached_dates
    ]
    refresh_days = [
        day for day in requested_days
        if should_refresh_date(day, today) and day not in missing_days
    ]
    dates_to_fetch = [
        day for day in requested_days
        if should_refresh_date(day, today) or day.isoformat() not in cached_dates
    ]

    logger.info(
        "Activity cache plan range=%s..%s cached=%s pull=%s missing=%s refresh=%s",
        start_date.isoformat(),
        end_date.isoformat(),
        [day.isoformat() for day in cached_requested_days],
        [day.isoformat() for day in dates_to_fetch],
        [day.isoformat() for day in missing_days],
        [day.isoformat() for day in refresh_days],
    )

    if dates_to_fetch:
        fetch_start = min(dates_to_fetch)
        fetched = fetch_activities_since(access_token, fetch_start)
        add_pace_data_to_new_runs(fetched, access_token)
        fetched_by_date = defaultdict(list)
        for activity in fetched:
            try:
                activity_date = parse_strava_local_date(activity)
            except (KeyError, ValueError):
                continue
            if fetch_start <= activity_date <= end_date:
                fetched_by_date[activity_date.isoformat()].append(activity)

        # A broad Strava request may span cached history. Only replace dates that
        # are missing or inside the rolling refresh window.
        for day in dates_to_fetch:
            cached_dates[day.isoformat()] = fetched_by_date[day.isoformat()]
        save_data_cache(cache)

    activities = [
        activity
        for day in requested_days
        for activity in cached_dates.get(day.isoformat(), [])
    ]
    cache_weather_for_activities(activities)
    return activities


@synchronized_cache
def read_cached_activities(start_date: date, end_date: date):
    """Return a date range exactly as stored, without any external requests."""
    cached_dates = load_data_cache()["activities"]
    return [
        activity
        for offset in range((end_date - start_date).days + 1)
        for activity in cached_dates.get(
            (start_date + timedelta(days=offset)).isoformat(), []
        )
    ]


@app.get("/run-streak")
def run_streak(start: str = None, end: str = None, refresh: bool = True):
    access_token = tokens.get("access_token")

    if not access_token:
        return JSONResponse(
            {"error": "Not authenticated. Visit /login first."},
            status_code=401,
        )

    # Default to month-to-date, while allowing historical ranges for exports.
    today = datetime.now().date()
    try:
        start_date = date.fromisoformat(start) if start else today.replace(day=1)
        end_date = date.fromisoformat(end) if end else today
    except ValueError:
        return JSONResponse(
            {"error": "Dates must use YYYY-MM-DD format."},
            status_code=400,
        )

    if end_date > today:
        end_date = today
    if start_date > end_date:
        return JSONResponse(
            {"error": "Start date must be on or before end date."},
            status_code=400,
        )

    activities = (
        fetch_cached_activities(access_token, start_date, end_date)
        if refresh
        else read_cached_activities(start_date, end_date)
    )

    runs = [
        activity
        for activity in activities
        if activity.get("type") == "Run"
    ]

    daily_miles = defaultdict(float)
    daily_run_counts = defaultdict(int)

    for run in runs:
        run_date = parse_strava_local_date(run)
        daily_miles[run_date] += miles(run.get("distance", 0))
        daily_run_counts[run_date] += 1

    all_days = [
        start_date + timedelta(days=offset)
        for offset in range((end_date - start_date).days + 1)
    ]

    missed_days = [
        day.isoformat()
        for day in all_days
        if daily_run_counts[day] == 0
    ]

    run_days = [
        day
        for day in all_days
        if daily_run_counts[day] > 0
    ]

    monthly_miles = defaultdict(float)

    for day, distance in daily_miles.items():
        month_key = day.strftime("%Y-%m")
        monthly_miles[month_key] += distance

    daily_totals = [
        {
            "date": day.isoformat(),
            "run_count": daily_run_counts[day],
            "total_miles": round(daily_miles[day], 2),
        }
        for day in all_days
    ]

    days_with_runs = [
        day for day in daily_totals
        if day["run_count"] > 0
    ]

    longest_day = max(
        days_with_runs,
        key=lambda day: day["total_miles"],
        default=None,
    )

    shortest_day = min(
        days_with_runs,
        key=lambda day: day["total_miles"],
        default=None,
    )

    average_miles_per_run_day = (
        sum(day["total_miles"] for day in days_with_runs) / len(days_with_runs)
        if days_with_runs
        else 0
    )

    total_miles = sum(daily_miles.values())

    return {
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        },
        "streak_active": len(missed_days) == 0,
        "total_days": len(all_days),
        "run_days": len(run_days),
        "missed_day_count": len(missed_days),
        "missed_days": missed_days,
        "total_runs": sum(daily_run_counts.values()),
        "total_miles": round(total_miles, 2),
        "average_miles_per_run_day": round(average_miles_per_run_day, 2),
        "longest_total_run_day": longest_day,
        "shortest_total_run_day": shortest_day,
        "monthly_totals": [
            {
                "month": month,
                "total_miles": round(distance, 2),
            }
            for month, distance in sorted(monthly_miles.items())
        ],
        "daily_totals": daily_totals,
    }


@app.get("/day-details")
def day_details(date: str):
    """Return full activity details for a specific local date (YYYY-MM-DD),
    including weather information when available.
    """
    access_token = tokens.get("access_token")

    if not access_token:
        return JSONResponse(
            {"error": "Not authenticated. Visit /login first."},
            status_code=401,
        )

    try:
        # parse the provided YYYY-MM-DD string into a `date` object without
        # shadowing the imported `date` name
        target_date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    except Exception:
        return JSONResponse({"error": "Invalid date format, expected YYYY-MM-DD"}, status_code=400)

    activities = fetch_cached_activities(
        access_token, target_date_obj, target_date_obj
    )

    runs = [a for a in activities if a.get("type") == "Run"]

    activity_items = []
    for a in runs:
        weather = get_weather_for_activity(a)
        miles_val = round(a.get("distance", 0) / 1609.344, 2)
        moving_minutes = round(a.get("moving_time", 0) / 60, 1)
        avg_miles_per_min = None
        if moving_minutes and miles_val:
            try:
                avg_miles_per_min = round(miles_val / moving_minutes, 4)
            except Exception:
                avg_miles_per_min = None

        activity_items.append({
            "id": a.get("id"),
            "name": a.get("name"),
            "type": a.get("type"),
            "start_date_local": a.get("start_date_local"),
            "miles": miles_val,
            "moving_time_minutes": moving_minutes,
            "treadmill": a.get("trainer") is True,
            "avg_miles_per_minute": avg_miles_per_min,
            "pace_data": a.get("pace_data"),
            "weather": weather,
        })

    total_miles = round(sum(item["miles"] for item in activity_items), 2)

    return {
        "date": target_date_obj.isoformat(),
        "run_count": len(activity_items),
        "total_miles": total_miles,
        "activities": activity_items,
    }


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

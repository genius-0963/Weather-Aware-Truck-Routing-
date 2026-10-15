from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache

from .risk import RISK_SCORE, RiskAssessment, assess_weather

MILES_PER_METER = 1 / 1609.344
KMH_TO_MPH = 0.6213711922
CM_TO_INCH = 0.3937007874
MAX_WAYPOINTS_PER_REQUEST = 40
FORECAST_HOURS = 48
_geocode_lock = threading.Lock()
_last_geocode_request = 0.0


class RoutingServiceError(Exception):
    """An external routing, geocoding, or forecast dependency failed."""


def _get_json(url: str, *, user_agent: str = "WeatherAwareTruckRouting/1.0") -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": user_agent,
        },
    )
    try:
        with urlopen(request, timeout=settings.EXTERNAL_API_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise RoutingServiceError(
                    f"An external service returned HTTP {response.status}."
                )
            return json.loads(response.read())
    except HTTPError as exc:
        raise RoutingServiceError(
            f"An external service returned HTTP {exc.code}."
        ) from exc
    except (TimeoutError, URLError, json.JSONDecodeError, OSError) as exc:
        raise RoutingServiceError(
            "An external route or weather service could not be reached."
        ) from exc


@lru_cache(maxsize=256)
def _geocode_cached(normalized_query: str) -> tuple[float, float, str]:
    global _last_geocode_request
    with _geocode_lock:
        wait_seconds = 1.05 - (time.monotonic() - _last_geocode_request)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        _last_geocode_request = time.monotonic()
        query = urlencode({"q": normalized_query, "format": "jsonv2", "limit": 1})
        results = _get_json(
            f"{settings.GEOCODING_BASE_URL}/search?{query}",
            user_agent="WeatherAwareTruckRouting/1.0 (route planning)",
        )

    if not isinstance(results, list) or not results:
        raise RoutingServiceError(
            f"Could not find a map location for “{normalized_query}”."
        )
    result = results[0]
    try:
        return (
            float(result["lat"]),
            float(result["lon"]),
            str(result.get("display_name", normalized_query)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RoutingServiceError(
            f"The map service returned an invalid location for “{normalized_query}”."
        ) from exc


def geocode(query: str) -> tuple[float, float, str]:
    return _geocode_cached(" ".join(query.strip().split()).casefold())


def _fetch_routes(
    origin: tuple[float, float], destination: tuple[float, float]
) -> list[dict[str, Any]]:
    coordinates = f"{origin[1]},{origin[0]};{destination[1]},{destination[0]}"
    query = urlencode(
        {
            "overview": "full",
            "geometries": "geojson",
            "steps": "false",
            "alternatives": "3",
        }
    )
    payload = _get_json(
        f"{settings.ROUTING_BASE_URL}/route/v1/driving/{coordinates}?{query}"
    )
    routes = payload.get("routes") if isinstance(payload, dict) else None
    if not routes:
        message = payload.get("message") if isinstance(payload, dict) else None
        raise RoutingServiceError(
            message or "The routing service did not return a usable route."
        )
    return routes[:3]


def _haversine_miles(
    point_a: tuple[float, float], point_b: tuple[float, float]
) -> float:
    lon1, lat1 = map(math.radians, point_a)
    lon2, lat2 = map(math.radians, point_b)
    delta_lon, delta_lat = lon2 - lon1, lat2 - lat1
    arc = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 3958.7613 * 2 * math.asin(min(1, math.sqrt(arc)))


def _route_points(
    route: dict[str, Any], interval_miles: int
) -> tuple[float, list[dict[str, float]], list[tuple[float, float]]]:
    try:
        raw_coordinates = route["geometry"]["coordinates"]
        coordinates = [
            (float(point[0]), float(point[1]))
            for point in raw_coordinates
            if len(point) >= 2
        ]
        route_miles = float(route["distance"]) * MILES_PER_METER
    except (KeyError, TypeError, ValueError) as exc:
        raise RoutingServiceError("The routing service returned invalid geometry.") from exc

    if len(coordinates) < 2 or route_miles <= 0:
        raise RoutingServiceError("The routing service returned an empty route.")

    cumulative = [0.0]
    for previous, current in zip(coordinates, coordinates[1:]):
        cumulative.append(cumulative[-1] + _haversine_miles(previous, current))
    geometry_miles = cumulative[-1]
    if geometry_miles <= 0:
        raise RoutingServiceError("The route geometry has no measurable distance.")

    distances = [float(value) for value in range(0, int(route_miles), interval_miles)]
    if not distances or distances[0] != 0:
        distances.insert(0, 0.0)
    if not math.isclose(distances[-1], route_miles, abs_tol=0.01):
        distances.append(route_miles)

    checkpoints: list[dict[str, float]] = []
    for distance in distances:
        target = min(geometry_miles, geometry_miles * distance / route_miles)
        index = next(
            (i for i, value in enumerate(cumulative) if value >= target),
            len(cumulative) - 1,
        )
        if index == 0:
            lon, lat = coordinates[0]
        else:
            before, after = cumulative[index - 1], cumulative[index]
            fraction = 0 if after == before else (target - before) / (after - before)
            lon = coordinates[index - 1][0] + (
                coordinates[index][0] - coordinates[index - 1][0]
            ) * fraction
            lat = coordinates[index - 1][1] + (
                coordinates[index][1] - coordinates[index - 1][1]
            ) * fraction
        checkpoints.append(
            {
                "distance_miles": round(distance, 2),
                "latitude": lat,
                "longitude": lon,
            }
        )
    return route_miles, checkpoints, coordinates


def _forecast_batch(
    locations: list[tuple[float, float]], departure: datetime
) -> list[dict[str, Any]]:
    rounded = [(round(lat, 4), round(lon, 4)) for lat, lon in locations]
    cache_material = json.dumps(
        {"locations": rounded, "date": departure.date().isoformat()},
        separators=(",", ":"),
    )
    cache_key = "weather-route:" + hashlib.sha256(
        cache_material.encode("utf-8")
    ).hexdigest()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    query = urlencode(
        {
            "latitude": ",".join(f"{lat:.4f}" for lat, _ in rounded),
            "longitude": ",".join(f"{lon:.4f}" for _, lon in rounded),
            "hourly": "wind_speed_10m,rain,snowfall,temperature_2m",
            "wind_speed_unit": "mph",
            "temperature_unit": "fahrenheit",
            "precipitation_unit": "inch",
            "timezone": "UTC",
            "forecast_days": 16,
        }
    )
    payload = _get_json(f"{settings.WEATHER_BASE_URL}?{query}")
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or len(payload) != len(locations):
        raise RoutingServiceError(
            "The weather service returned an incomplete checkpoint forecast."
        )

    normalized: list[dict[str, Any]] = []
    for location in payload:
        hourly = location.get("hourly") if isinstance(location, dict) else None
        if not isinstance(hourly, dict):
            raise RoutingServiceError(
                "The weather service omitted hourly checkpoint data."
            )
        times = hourly.get("time", [])
        values = {
            "wind": hourly.get("wind_speed_10m", []),
            "rain": hourly.get("rain", []),
            "snow": hourly.get("snowfall", []),
            "temperature": hourly.get("temperature_2m", []),
        }
        if any(len(series) != len(times) for series in values.values()):
            raise RoutingServiceError(
                "The weather service returned mismatched hourly values."
            )
        normalized.append(
            {
                timestamp: {
                    "wind_mph": float(values["wind"][index]),
                    "rain_in_per_hour": float(values["rain"][index]),
                    "snow_in_per_hour": float(values["snow"][index]) * CM_TO_INCH,
                    "temperature_f": (
                        float(values["temperature"][index])
                        if values["temperature"][index] is not None
                        else None
                    ),
                }
                for index, timestamp in enumerate(times)
                if all(
                    values[name][index] is not None
                    for name in ("wind", "rain", "snow")
                )
            }
        )

    cache.set(cache_key, normalized, timeout=600)
    return normalized


def _fetch_weather(
    locations: list[tuple[float, float]], departure: datetime
) -> list[dict[str, Any]]:
    unique: list[tuple[float, float]] = []
    index_by_location: dict[tuple[float, float], int] = {}
    for lat, lon in locations:
        key = (round(lat, 4), round(lon, 4))
        if key not in index_by_location:
            index_by_location[key] = len(unique)
            unique.append((lat, lon))

    chunks = [
        unique[start : start + MAX_WAYPOINTS_PER_REQUEST]
        for start in range(0, len(unique), MAX_WAYPOINTS_PER_REQUEST)
    ]
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(chunks)))) as executor:
        batches = list(
            executor.map(lambda chunk: _forecast_batch(chunk, departure), chunks)
        )

    weather_by_location: dict[tuple[float, float], dict[str, Any]] = {}
    for chunk, forecast_batch in zip(chunks, batches):
        for coordinate, forecast in zip(chunk, forecast_batch):
            key = (round(coordinate[0], 4), round(coordinate[1], 4))
            weather_by_location[key] = forecast

    try:
        return [
            weather_by_location[(round(lat, 4), round(lon, 4))]
            for lat, lon in locations
        ]
    except KeyError as exc:
        raise RoutingServiceError(
            "A checkpoint forecast could not be matched to its route location."
        ) from exc


def _nearest_hour(forecast: dict[str, Any], target: datetime) -> dict[str, Any]:
    target_hour = target.astimezone(timezone.utc).replace(
        minute=0, second=0, microsecond=0
    )
    if target.minute >= 30:
        target_hour += timedelta(hours=1)
    key = target_hour.strftime("%Y-%m-%dT%H:00")
    sample = forecast.get(key)
    if sample is None:
        raise RoutingServiceError(
            "The requested trip time is outside the available weather forecast."
        )
    return sample


def _assess_weather_sample(
    weather: dict[str, Any], load_weight_lb: int
) -> RiskAssessment:
    return assess_weather(
        wind_mph=weather["wind_mph"],
        rain_in_per_hour=weather["rain_in_per_hour"],
        snow_in_per_hour=weather["snow_in_per_hour"],
        load_weight_lb=load_weight_lb,
    )


def _format_checkpoint(
    index: int,
    checkpoint: dict[str, float],
    previous_distance: float,
    arrival: datetime,
    forecast: dict[str, Any],
    departure: datetime,
    load_weight_lb: int,
) -> dict[str, Any]:
    actual_weather = _nearest_hour(forecast, arrival)
    actual_risk = _assess_weather_sample(actual_weather, load_weight_lb)
    forecast_points = []
    for offset in range(FORECAST_HOURS + 1):
        weather = _nearest_hour(forecast, departure + timedelta(hours=offset))
        risk = _assess_weather_sample(weather, load_weight_lb)
        forecast_points.append(
            {
                **weather,
                "forecast_offset_hours": offset,
                "risk_level": risk.level,
            }
        )
    return {
        "index": index,
        "distance_miles": checkpoint["distance_miles"],
        "segment_miles": round(
            checkpoint["distance_miles"] - previous_distance, 2
        ),
        "latitude": round(checkpoint["latitude"], 6),
        "longitude": round(checkpoint["longitude"], 6),
        "estimated_arrival": arrival.isoformat().replace("+00:00", "Z"),
        "weather": actual_weather,
        "risk_level": actual_risk.level,
        "risk_reasons": list(actual_risk.reasons),
        "forecast": forecast_points,
    }


def _score_route(route: dict[str, Any]) -> tuple[float, float, float, float, int]:
    checkpoints = route["checkpoints"]
    no_travel_miles = sum(
        point["segment_miles"]
        for point in checkpoints
        if point["risk_level"] == "no_travel"
    )
    severe_miles = sum(
        point["segment_miles"]
        for point in checkpoints
        if point["risk_level"] == "severe"
    )
    high_miles = sum(
        point["segment_miles"]
        for point in checkpoints
        if point["risk_level"] == "high"
    )
    total = sum(point["segment_miles"] for point in checkpoints)
    average = (
        sum(
            point["segment_miles"] * RISK_SCORE[point["risk_level"]]
            for point in checkpoints
        )
        / total
        if total > 0
        else 0.0
    )
    route["no_travel_miles"] = round(no_travel_miles, 1)
    route["severe_miles"] = round(severe_miles, 1)
    route["high_miles"] = round(high_miles, 1)
    route["average_risk_score"] = round(average, 2)
    return (
        route["no_travel_miles"],
        route["severe_miles"],
        route["high_miles"],
        route["average_risk_score"],
        route["duration_seconds"],
    )


def create_route_plan(
    *,
    origin_text: str,
    destination_text: str,
    departure: datetime,
    load_weight_lb: int,
    interval_miles: int,
) -> dict[str, Any]:
    origin_lat, origin_lon, origin_name = geocode(origin_text)
    destination_lat, destination_lon, destination_name = geocode(destination_text)
    raw_routes = _fetch_routes(
        (origin_lat, origin_lon), (destination_lat, destination_lon)
    )

    route_checkpoints: list[list[dict[str, float]]] = []
    route_coordinates: list[list[tuple[float, float]]] = []
    route_distances: list[float] = []
    for route in raw_routes:
        distance, checkpoints, coordinates = _route_points(route, interval_miles)
        route_distances.append(distance)
        route_checkpoints.append(checkpoints)
        route_coordinates.append(coordinates)

    all_locations = [
        (point["latitude"], point["longitude"])
        for checkpoints in route_checkpoints
        for point in checkpoints
    ]
    all_forecasts = _fetch_weather(all_locations, departure)
    forecast_cursor = 0
    options: list[dict[str, Any]] = []

    for route_index, route in enumerate(raw_routes):
        distance = route_distances[route_index]
        estimated_duration = max(
            int(float(route.get("duration", 0))),
            int(distance / 55 * 3600),
        )
        estimated_arrival = departure + timedelta(seconds=estimated_duration)
        checkpoints = []
        previous_distance = 0.0
        for point_index, point in enumerate(route_checkpoints[route_index]):
            checkpoint_forecast = all_forecasts[forecast_cursor]
            forecast_cursor += 1
            elapsed = estimated_duration * point["distance_miles"] / distance
            arrival = departure + timedelta(seconds=elapsed)
            checkpoints.append(
                _format_checkpoint(
                    point_index,
                    point,
                    previous_distance,
                    arrival,
                    checkpoint_forecast,
                    departure,
                    load_weight_lb,
                )
            )
            previous_distance = point["distance_miles"]

        options.append(
            {
                "route_id": f"route-{route_index + 1}",
                "label": f"Option {route_index + 1}",
                "distance_miles": round(distance, 1),
                "duration_seconds": estimated_duration,
                "estimated_arrival": estimated_arrival.isoformat().replace(
                    "+00:00", "Z"
                ),
                "severe_miles": 0,
                "high_miles": 0,
                "no_travel_miles": 0,
                "average_risk_score": 0.0,
                "summary": (
                    f"{round(distance):,} mi · "
                    f"{estimated_duration // 3600}h "
                    f"{(estimated_duration % 3600) // 60:02d}m estimated"
                ),
                "coordinates": [
                    {"latitude": round(lat, 6), "longitude": round(lon, 6)}
                    for lon, lat in route_coordinates[route_index]
                ],
                "checkpoints": checkpoints,
            }
        )
        _score_route(options[-1])

    ranked = sorted(options, key=_score_route)
    best_route_id = ranked[0]["route_id"]
    return {
        "origin": origin_name,
        "destination": destination_name,
        "departure_at": departure.isoformat().replace("+00:00", "Z"),
        "load_weight_lb": load_weight_lb,
        "sample_interval_miles": interval_miles,
        "best_route_id": best_route_id,
        "routes": options,
        "forecast_hours_available": FORECAST_HOURS,
        "data_sources": [
            "OpenStreetMap Nominatim geocoding",
            "OSRM public routing service",
            "Open-Meteo hourly forecast",
        ],
    }

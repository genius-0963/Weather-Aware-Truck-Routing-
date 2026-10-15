from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from django.core.cache import cache
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .services import RoutingServiceError, create_route_plan as build_route_plan

MAX_PLAN_REQUESTS_PER_MINUTE = 8
ALLOWED_INTERVALS = {10, 25, 50}


def _error(message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


def _client_rate_limit(request: HttpRequest) -> bool:
    client_address = request.META.get("REMOTE_ADDR", "unknown")
    key = f"route-plan-rate:{client_address}"
    current = cache.get(key)
    if current is None:
        cache.add(key, 1, timeout=60)
        current = cache.get(key, 1)
    else:
        current = cache.incr(key)
    return int(current) > MAX_PLAN_REQUESTS_PER_MINUTE


@require_GET
def health(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@csrf_exempt
@require_POST
def create_route_plan(request: HttpRequest) -> JsonResponse:
    if len(request.body) > 64 * 1024:
        return _error("Request body must be 64 KB or smaller.", 413)
    if _client_rate_limit(request):
        response = _error(
            "Too many route requests. Wait a minute before trying again.", 429
        )
        response["Retry-After"] = "60"
        return response

    try:
        payload: Any = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error("Request body must be valid JSON.", 400)
    if not isinstance(payload, dict):
        return _error("Request body must be a JSON object.", 400)

    allowed_fields = {
        "origin",
        "destination",
        "departure_at",
        "load_weight_lb",
        "sample_interval_miles",
    }
    unknown_fields = set(payload) - allowed_fields
    if unknown_fields:
        return _error(
            f"Unexpected request fields: {', '.join(sorted(unknown_fields))}.", 400
        )

    origin = payload.get("origin")
    destination = payload.get("destination")
    if not isinstance(origin, str) or not 2 <= len(origin.strip()) <= 180:
        return _error("Enter an origin between 2 and 180 characters.", 400)
    if not isinstance(destination, str) or not 2 <= len(destination.strip()) <= 180:
        return _error("Enter a destination between 2 and 180 characters.", 400)

    raw_departure = payload.get("departure_at")
    if not isinstance(raw_departure, str):
        return _error("Departure time must include a date and time zone.", 400)
    try:
        departure = datetime.fromisoformat(raw_departure.replace("Z", "+00:00"))
    except ValueError:
        return _error("Departure time must be a valid ISO 8601 date-time.", 400)
    if departure.tzinfo is None:
        return _error("Departure time must include a time zone.", 400)
    departure = departure.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    if departure < now - timedelta(minutes=5):
        return _error("Departure time must be in the future.", 400)
    if departure > now + timedelta(days=14):
        return _error(
            "Departure must be within the next 14 days for forecast coverage.", 400
        )

    load_weight_lb = payload.get("load_weight_lb")
    if (
        isinstance(load_weight_lb, bool)
        or not isinstance(load_weight_lb, int)
        or not 0 <= load_weight_lb <= 200_000
    ):
        return _error("Load weight must be a whole number from 0 to 200,000 lb.", 400)

    interval_miles = payload.get("sample_interval_miles")
    if interval_miles not in ALLOWED_INTERVALS:
        return _error("Sample spacing must be 10, 25, or 50 miles.", 400)

    try:
        result = build_route_plan(
            origin_text=origin.strip(),
            destination_text=destination.strip(),
            departure=departure,
            load_weight_lb=load_weight_lb,
            interval_miles=interval_miles,
        )
    except RoutingServiceError as exc:
        return _error(str(exc), 422)

    return JsonResponse(result)

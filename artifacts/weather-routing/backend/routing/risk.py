from __future__ import annotations

from dataclasses import dataclass


RISK_SCORE = {
    "low": 0,
    "moderate": 1,
    "high": 2,
    "severe": 3,
    "no_travel": 4,
}


@dataclass(frozen=True)
class RiskAssessment:
    level: str
    score: int
    reasons: tuple[str, ...]


def _wind_level(mph: float) -> str:
    if mph >= 55:
        return "no_travel"
    if mph >= 45:
        return "severe"
    if mph >= 35:
        return "high"
    if mph >= 25:
        return "moderate"
    return "low"


def _rain_level(inches_per_hour: float) -> str:
    if inches_per_hour > 1:
        return "no_travel"
    if inches_per_hour >= 0.5:
        return "severe"
    if inches_per_hour >= 0.25:
        return "high"
    if inches_per_hour >= 0.1:
        return "moderate"
    return "low"


def _snow_level(inches_per_hour: float) -> str:
    if inches_per_hour > 3:
        return "no_travel"
    if inches_per_hour >= 2:
        return "severe"
    if inches_per_hour >= 1:
        return "high"
    if inches_per_hour >= 0.5:
        return "moderate"
    return "low"


def assess_weather(
    *,
    wind_mph: float,
    rain_in_per_hour: float,
    snow_in_per_hour: float,
    load_weight_lb: int,
) -> RiskAssessment:
    """Apply the assessment's weather thresholds and payload overrides."""
    categories = [
        _wind_level(wind_mph),
        _rain_level(rain_in_per_hour),
        _snow_level(snow_in_per_hour),
    ]
    reasons: list[str] = []

    if wind_mph >= 55:
        reasons.append(f"Wind at {wind_mph:.1f} mph exceeds the no-travel limit.")
    elif wind_mph >= 45 and load_weight_lb > 30_000:
        categories.append("no_travel")
        reasons.append(
            f"Wind at {wind_mph:.1f} mph is no-travel for loads over 30,000 lb."
        )
    elif wind_mph >= 35 and load_weight_lb > 40_000:
        categories.append("severe")
        reasons.append(
            f"Wind at {wind_mph:.1f} mph is severe for loads over 40,000 lb."
        )

    if _wind_level(wind_mph) != "low":
        reasons.append(f"Wind: {wind_mph:.1f} mph.")
    if _rain_level(rain_in_per_hour) != "low":
        reasons.append(f"Rain: {rain_in_per_hour:.2f} in/hr.")
    if _snow_level(snow_in_per_hour) != "low":
        reasons.append(f"Snow: {snow_in_per_hour:.2f} in/hr.")

    level = max(categories, key=RISK_SCORE.__getitem__)
    if not reasons:
        reasons.append("Weather remains below the listed risk thresholds.")

    return RiskAssessment(level=level, score=RISK_SCORE[level], reasons=tuple(reasons))

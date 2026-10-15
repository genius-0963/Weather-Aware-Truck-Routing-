from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import Client, SimpleTestCase

from .risk import assess_weather
from .services import _assess_weather_sample


class WeatherRiskThresholdTests(SimpleTestCase):
    def test_forecast_temperature_does_not_break_risk_assessment(self) -> None:
        risk = _assess_weather_sample(
            {
                "wind_mph": 24.0,
                "rain_in_per_hour": 0.0,
                "snow_in_per_hour": 0.0,
                "temperature_f": 62.0,
            },
            load_weight_lb=38_000,
        )

        self.assertEqual(risk.level, "low")

    def test_wind_boundaries(self) -> None:
        self.assertEqual(
            assess_weather(
                wind_mph=24.9,
                rain_in_per_hour=0,
                snow_in_per_hour=0,
                load_weight_lb=0,
            ).level,
            "low",
        )
        self.assertEqual(
            assess_weather(
                wind_mph=25,
                rain_in_per_hour=0,
                snow_in_per_hour=0,
                load_weight_lb=0,
            ).level,
            "moderate",
        )
        self.assertEqual(
            assess_weather(
                wind_mph=55,
                rain_in_per_hour=0,
                snow_in_per_hour=0,
                load_weight_lb=0,
            ).level,
            "no_travel",
        )

    def test_load_overrides_are_strictly_greater_than_the_limit(self) -> None:
        def level(wind: float, load: int) -> str:
            return assess_weather(
                wind_mph=wind,
                rain_in_per_hour=0,
                snow_in_per_hour=0,
                load_weight_lb=load,
            ).level

        self.assertEqual(level(45, 30_000), "severe")
        self.assertEqual(level(45, 30_001), "no_travel")
        self.assertEqual(level(35, 40_000), "high")
        self.assertEqual(level(35, 40_001), "severe")

    def test_rain_and_snow_no_travel_thresholds(self) -> None:
        self.assertEqual(
            assess_weather(
                wind_mph=0,
                rain_in_per_hour=1.0,
                snow_in_per_hour=0,
                load_weight_lb=0,
            ).level,
            "severe",
        )
        self.assertEqual(
            assess_weather(
                wind_mph=0,
                rain_in_per_hour=1.01,
                snow_in_per_hour=0,
                load_weight_lb=0,
            ).level,
            "no_travel",
        )
        self.assertEqual(
            assess_weather(
                wind_mph=0,
                rain_in_per_hour=0,
                snow_in_per_hour=3.01,
                load_weight_lb=0,
            ).level,
            "no_travel",
        )


class RoutePlanViewTests(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()
        self.client = Client()

    @patch("routing.views.build_route_plan", return_value={"routes": []})
    def test_valid_request_reaches_planning_service(self, build_plan: MagicMock) -> None:
        departure = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        response = self.client.post(
            "/api/v1/route-plans",
            {
                "origin": "San Francisco, CA",
                "destination": "Los Angeles, CA",
                "departure_at": departure,
                "load_weight_lb": 38_000,
                "sample_interval_miles": 25,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"routes": []})
        build_plan.assert_called_once()

    def test_invalid_checkpoint_spacing_returns_a_client_error(self) -> None:
        departure = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        response = self.client.post(
            "/api/v1/route-plans",
            {
                "origin": "San Francisco, CA",
                "destination": "Los Angeles, CA",
                "departure_at": departure,
                "load_weight_lb": 38_000,
                "sample_interval_miles": 20,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Sample spacing", response.json()["error"])

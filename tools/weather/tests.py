import asyncio

from backend.testing import run_async
import os
from unittest.mock import MagicMock, patch

from django.test import TestCase


def _run(coro):
    return run_async(coro)


class WeatherToolTimeoutTests(TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"OPENWEATHER_API_KEY": "test-key"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    @patch("tools.weather.api.requests.get")
    def test_current_weather_uses_timeout(self, mock_get):
        from tools.weather.api import _REQUEST_TIMEOUT_SECONDS, _weather

        response = MagicMock()
        response.json.return_value = {"weather": [{"description": "clear"}]}
        mock_get.return_value = response

        result = _run(_weather.get_current_weather("Calgary"))

        self.assertEqual(result, {"weather": [{"description": "clear"}]})
        mock_get.assert_called_once()
        self.assertEqual(mock_get.call_args.kwargs["timeout"], _REQUEST_TIMEOUT_SECONDS)

    @patch("tools.weather.api.requests.get")
    def test_forecast_uses_timeout_and_groups_daily_response(self, mock_get):
        from tools.weather.api import _REQUEST_TIMEOUT_SECONDS, _weather

        response = MagicMock()
        response.json.return_value = {
            "city": {"name": "Calgary"},
            "list": [
                {
                    "dt_txt": "2026-06-22 09:00:00",
                    "main": {"temp": 12.0},
                    "weather": [{"description": "cloudy"}],
                },
                {
                    "dt_txt": "2026-06-22 12:00:00",
                    "main": {"temp": 18.0},
                    "weather": [{"description": "cloudy"}],
                },
            ],
        }
        mock_get.return_value = response

        result = _run(_weather.get_weather_forecast("Calgary", days=1))

        self.assertEqual(result["city"], "Calgary")
        self.assertEqual(result["forecast"][0]["temp_min"], 12.0)
        self.assertEqual(result["forecast"][0]["temp_max"], 18.0)
        mock_get.assert_called_once()
        self.assertEqual(mock_get.call_args.kwargs["timeout"], _REQUEST_TIMEOUT_SECONDS)

    @patch("tools.weather.api.requests.get")
    def test_coordinates_weather_uses_timeout(self, mock_get):
        from tools.weather.api import _REQUEST_TIMEOUT_SECONDS, _weather

        response = MagicMock()
        response.json.return_value = {"name": "Calgary"}
        mock_get.return_value = response

        result = _run(_weather.get_weather_by_coordinates(51.05, -114.07))

        self.assertEqual(result, {"name": "Calgary"})
        mock_get.assert_called_once()
        self.assertEqual(mock_get.call_args.kwargs["timeout"], _REQUEST_TIMEOUT_SECONDS)


class WeatherToolRegistrationTests(TestCase):
    def test_weather_tools_are_registered_under_top_level_tools_package(self):
        import tools.weather.api  # noqa: F401
        from tools.registry import get

        self.assertEqual(get("weather.get_current_weather").plugin_id, None)
        self.assertEqual(get("weather.get_weather_forecast").plugin_id, None)
        self.assertEqual(get("weather.get_weather_by_coordinates").plugin_id, None)

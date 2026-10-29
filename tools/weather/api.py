"""
Direct OpenWeatherMap API calls. No MCP, subprocess, or sub-agent.
"""

import asyncio
import logging
import os

import requests

from tools.registry import ToolDef, register

logger = logging.getLogger(__name__)
_REQUEST_TIMEOUT_SECONDS = 15


class _WeatherAPI:
    BASE_URL = "https://api.openweathermap.org/data/2.5"

    @property
    def _api_key(self) -> str:
        """Read the OpenWeather API key.

        Returns:
            Configured OpenWeather API key.
        """
        key = os.getenv("OPENWEATHER_API_KEY")
        if not key:
            raise RuntimeError("OPENWEATHER_API_KEY environment variable is not set")
        return key

    async def get_current_weather(self, city: str) -> dict:
        """Fetch current weather for a city.

        Args:
            city: City name or city plus country code.

        Returns:
            OpenWeather current weather response.
        """
        url = f"{self.BASE_URL}/weather"
        params = {"q": city, "appid": self._api_key, "units": "metric"}
        resp = await asyncio.to_thread(
            lambda: requests.get(url, params=params, timeout=_REQUEST_TIMEOUT_SECONDS)
        )
        resp.raise_for_status()
        return resp.json()

    async def get_weather_forecast(self, city: str, days: int = 5) -> dict:
        """Fetch a daily weather forecast for a city.

        Args:
            city: City name or city plus country code.
            days: Number of days to include.

        Returns:
            Condensed forecast response.
        """
        # /forecast/daily requires a paid OWM subscription. Use the free-tier
        # /forecast endpoint (3-hour intervals, 5-day window) instead, then
        # collapse into one summary entry per calendar day.
        url = f"{self.BASE_URL}/forecast"
        cnt = min(days * 8, 40)  # 8 slots per day, OWM cap is 40
        params = {"q": city, "cnt": cnt, "appid": self._api_key, "units": "metric"}
        resp = await asyncio.to_thread(
            lambda: requests.get(url, params=params, timeout=_REQUEST_TIMEOUT_SECONDS)
        )
        resp.raise_for_status()
        raw = resp.json()

        from collections import defaultdict
        by_day: dict = defaultdict(list)
        for slot in raw.get("list", []):
            date = slot["dt_txt"].split(" ")[0]
            by_day[date].append(slot)

        daily = []
        for date in sorted(by_day.keys())[:days]:
            slots = by_day[date]
            temps = [s["main"]["temp"] for s in slots]
            descriptions = [s["weather"][0]["description"] for s in slots]
            daily.append({
                "date": date,
                "temp_min": round(min(temps), 1),
                "temp_max": round(max(temps), 1),
                "description": max(set(descriptions), key=descriptions.count),
            })

        return {"city": raw.get("city", {}).get("name", city), "forecast": daily}

    async def get_weather_by_coordinates(self, lat: float, lon: float) -> dict:
        """Fetch current weather by coordinates.

        Args:
            lat: Latitude.
            lon: Longitude.

        Returns:
            OpenWeather current weather response.
        """
        url = f"{self.BASE_URL}/weather"
        params = {"lat": lat, "lon": lon, "appid": self._api_key, "units": "metric"}
        resp = await asyncio.to_thread(
            lambda: requests.get(url, params=params, timeout=_REQUEST_TIMEOUT_SECONDS)
        )
        resp.raise_for_status()
        return resp.json()


_weather = _WeatherAPI()

# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

register(ToolDef(
    name="weather.get_current_weather",
    display_name="Get Current Weather",
    description="Fetch current weather conditions for a city.",
    params_schema={
        "city": {
            "type": "string",
            "description": "City name, optionally with country code, e.g. 'London,uk' or 'Tokyo'.",
            "required": True,
        },
    },
    fn=_weather.get_current_weather,
))

register(ToolDef(
    name="weather.get_weather_forecast",
    display_name="Get Weather Forecast",
    description="Fetch a daily weather forecast for up to 5 days for a city.",
    params_schema={
        "city": {
            "type": "string",
            "description": "City name, optionally with country code.",
            "required": True,
        },
        "days": {
            "type": "integer",
            "default": 5,
            "description": "Number of days to forecast (1-5).",
            "required": False,
        },
    },
    fn=_weather.get_weather_forecast,
))

register(ToolDef(
    name="weather.get_weather_by_coordinates",
    display_name="Get Weather by Coordinates",
    description="Fetch current weather conditions by geographic coordinates.",
    params_schema={
        "lat": {"type": "number", "description": "Latitude.", "required": True},
        "lon": {"type": "number", "description": "Longitude.", "required": True},
    },
    fn=_weather.get_weather_by_coordinates,
))

"""M2-7: Open-Meteo 无 Key 天气 + WMO 映射。"""
import sys

import pytest

sys.path.insert(0, ".")

from packages.agent.tools import query_weather as qw


def test_wmo_text_and_wind_helpers():
    assert qw._wmo_text(0) == "晴"
    assert qw._wmo_text(61) == "小雨"
    assert qw._wmo_text(999) == "未知天气"
    assert qw._wind_dir(0) == "北"
    assert qw._wind_dir(180) == "南"
    assert qw._beaufort(4.3) == "1"
    assert qw._beaufort(45) == "6"


def test_weather_available_without_any_key(monkeypatch):
    monkeypatch.delenv("QWEATHER_API_KEY", raising=False)
    monkeypatch.delenv("WEATHER_PROVIDER", raising=False)
    monkeypatch.setattr(qw, "QWEATHER_KEY", "")

    assert qw._weather_provider() == "open-meteo"
    assert qw._weather_available() is True


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class _Client:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None):
        if "geocoding" in url:
            return _Resp({"results": [{
                "name": "杭州", "latitude": 30.29, "longitude": 120.16,
                "timezone": "Asia/Shanghai",
            }]})
        if "air-quality" in url:
            return _Resp({"current": {"pm10": 20, "pm2_5": 10, "european_aqi": 25}})
        return _Resp({
            "current": {
                "temperature_2m": 14.3,
                "apparent_temperature": 14.1,
                "relative_humidity_2m": 83,
                "precipitation": 0.0,
                "weather_code": 3,
                "wind_speed_10m": 4.3,
                "wind_direction_10m": 180,
            },
            "daily": {
                "time": ["2026-11-05", "2026-11-06"],
                "weather_code": [3, 61],
                "temperature_2m_max": [20.9, 19.7],
                "temperature_2m_min": [14.3, 13.5],
                "precipitation_probability_max": [11, 98],
                "wind_speed_10m_max": [4.3, 12.0],
                "wind_direction_10m_dominant": [180, 90],
            },
        })


@pytest.mark.asyncio
async def test_open_meteo_now_without_key(monkeypatch):
    monkeypatch.setattr(qw.httpx, "AsyncClient", _Client)

    data = await qw._query_open_meteo("杭州", "now")

    assert data["temp"] == "14"
    assert data["text"] == "阴"
    assert data["wind_dir"] == "南"
    assert data["provider"] == "open-meteo"


@pytest.mark.asyncio
async def test_open_meteo_forecast_without_key(monkeypatch):
    monkeypatch.setattr(qw.httpx, "AsyncClient", _Client)

    data = await qw._query_open_meteo("杭州", "forecast")

    assert data["provider"] == "open-meteo"
    assert len(data["forecast"]) == 2
    assert data["forecast"][1]["text_day"] == "小雨"

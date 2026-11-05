"""
query_weather — 天气查询工具

默认无需 Key：Open-Meteo 地理编码 + 实时/3日预报。
有 QWEATHER_API_KEY 时优先和风；两者都失败再用搜索兜底。
支持：实时天气 / 3日预报 / 空气质量；生活指数仅和风/搜索。
"""
import os
import httpx
from loguru import logger

from ..tool_registry import register_tool, ToolPermission
from ..tool_result import ToolResult

QWEATHER_KEY = os.getenv("QWEATHER_API_KEY", "")
QWEATHER_HOST = "https://nm57rmgdmv.re.qweatherapi.com"
GEO_URL = f"{QWEATHER_HOST}/geo/v2/city/lookup"
NOW_URL = f"{QWEATHER_HOST}/v7/weather/now"
FORECAST_URL = f"{QWEATHER_HOST}/v7/weather/3d"
AIR_URL = f"{QWEATHER_HOST}/v7/air/now"
INDICES_URL = f"{QWEATHER_HOST}/v7/indices/1d"

# Open-Meteo：无需 API Key，非商业使用免费（CC-BY 4.0，需署名）
OPEN_METEO_GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"


def _qweather_key() -> str:
    return os.getenv("QWEATHER_API_KEY", "") or QWEATHER_KEY


def _weather_provider() -> str:
    """auto: 有和风 Key 用和风，否则 Open-Meteo；也可显式 search。"""
    explicit = (os.getenv("WEATHER_PROVIDER") or "").strip().lower()
    if explicit in ("qweather", "open-meteo", "search"):
        return explicit
    return "qweather" if _qweather_key() else "open-meteo"


def _search_available() -> bool:
    from .search_web import _available
    return _available()


def _weather_available() -> bool:
    if _weather_provider() == "search":
        return _search_available()
    return True


# WMO weather codes → 中文描述
_WMO_TEXT = {
    0: "晴", 1: "大部晴朗", 2: "多云", 3: "阴",
    45: "有雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "小阵雨", 81: "阵雨", 82: "强阵雨",
    85: "小阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷阵雨伴冰雹",
}


def _wmo_text(code: int | str | None) -> str:
    try:
        return _WMO_TEXT.get(int(code), "未知天气")
    except (TypeError, ValueError):
        return "未知天气"


def _wind_dir(degrees: float | str | None) -> str:
    try:
        deg = float(degrees) % 360
    except (TypeError, ValueError):
        return ""
    names = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
    return names[int((deg + 22.5) // 45) % 8]


def _beaufort(kmh: float | str | None) -> str:
    try:
        speed = float(kmh)
    except (TypeError, ValueError):
        return ""
    bounds = [1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118]
    for scale, limit in enumerate(bounds):
        if speed < limit:
            return str(scale)
    return "12"



@register_tool(
    name="query_weather",
    description="查询指定城市的天气信息。当伙伴问天气、温度、下雨、穿什么衣服、空气质量时使用。",
    schema={
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "城市名称，如'北京'、'上海'、'东京'",
            },
            "type": {
                "type": "string",
                "description": "查询类型: 'now'(实时), 'forecast'(预报), 'air'(空气质量), 'life'(生活指数), 默认'now'",
            },
        },
        "required": ["city"],
    },
    permission=ToolPermission.READ_ONLY,
    category="external",
    max_frequency=6,
    check_available=_weather_available,
)
async def query_weather(city: str, type: str = "now", ctx=None) -> ToolResult:
    """查询城市天气。

    顺序：和风（有 Key）→ Open-Meteo（无需 Key）→ 网页搜索兜底。
    可用 WEATHER_PROVIDER=qweather|open-meteo|search 显式指定。
    """
    provider = _weather_provider()

    if provider != "search" and _qweather_key():
        try:
            data = await _query_qweather(city, type)
            if data:
                data["city"] = city
                return ToolResult.ok(data, trigger_portrait_update=True)
        except Exception as e:
            logger.warning("weather.qweather_failed", error=str(e))

    if provider != "search":
        try:
            data = await _query_open_meteo(city, type)
            if data:
                data["city"] = city
                return ToolResult.ok(data, trigger_portrait_update=True)
        except Exception as e:
            logger.warning("weather.open_meteo_failed", error=str(e))

    return await _search_fallback(city, type)


async def _query_qweather(city: str, type: str) -> dict | None:
    location_id = await _lookup_city(city)
    if not location_id:
        return None
    if type == "forecast":
        return await _get_forecast(location_id)
    if type == "air":
        return await _get_air(location_id)
    if type == "life":
        return await _get_indices(location_id)
    return await _get_now(location_id)


async def _query_open_meteo(city: str, type: str) -> dict | None:
    location = await _open_meteo_geocode(city)
    if not location:
        return None

    if type == "life":
        # Open-Meteo 没有生活指数，交给搜索/和风
        return None

    if type == "air":
        return await _open_meteo_air(location)

    if type == "forecast":
        return await _open_meteo_forecast(location)

    return await _open_meteo_now(location)


async def _open_meteo_geocode(city: str) -> dict | None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(OPEN_METEO_GEO_URL, params={
            "name": city,
            "count": 1,
            "language": "zh",
            "format": "json",
        })
    if resp.status_code != 200:
        return None
    results = (resp.json() or {}).get("results") or []
    if not results:
        return None
    item = results[0]
    return {
        "name": item.get("name") or city,
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "timezone": item.get("timezone") or "auto",
    }


async def _open_meteo_now(location: dict) -> dict | None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(OPEN_METEO_FORECAST_URL, params={
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "current": (
                "temperature_2m,relative_humidity_2m,apparent_temperature,"
                "precipitation,weather_code,wind_speed_10m,wind_direction_10m"
            ),
            "timezone": location.get("timezone") or "auto",
            "forecast_days": 1,
        })
    if resp.status_code != 200:
        return None
    current = (resp.json() or {}).get("current") or {}
    if current.get("temperature_2m") is None:
        return None
    return {
        "temp": str(round(float(current["temperature_2m"]))),
        "feels_like": str(round(float(current.get("apparent_temperature") or current["temperature_2m"]))),
        "text": _wmo_text(current.get("weather_code")),
        "wind_dir": _wind_dir(current.get("wind_direction_10m")),
        "wind_scale": _beaufort(current.get("wind_speed_10m")),
        "humidity": str(current.get("relative_humidity_2m", "")),
        "precip": str(current.get("precipitation", "0.0")),
        "provider": "open-meteo",
    }


async def _open_meteo_forecast(location: dict) -> dict | None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(OPEN_METEO_FORECAST_URL, params={
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,wind_speed_10m_max,wind_direction_10m_dominant"
            ),
            "timezone": location.get("timezone") or "auto",
            "forecast_days": 3,
        })
    if resp.status_code != 200:
        return None
    daily = (resp.json() or {}).get("daily") or {}
    dates = daily.get("time") or []
    if not dates:
        return None
    days = []
    for index, date in enumerate(dates[:3]):
        days.append({
            "date": date,
            "text_day": _wmo_text((daily.get("weather_code") or [None])[index]),
            "text_night": _wmo_text((daily.get("weather_code") or [None])[index]),
            "temp_max": str((daily.get("temperature_2m_max") or [""])[index]),
            "temp_min": str((daily.get("temperature_2m_min") or [""])[index]),
            "wind_dir": _wind_dir((daily.get("wind_direction_10m_dominant") or [""])[index]),
            "wind_scale": _beaufort((daily.get("wind_speed_10m_max") or [""])[index]),
            "precip": str((daily.get("precipitation_probability_max") or [""])[index]),
            "humidity": "",
        })
    return {"forecast": days, "provider": "open-meteo"}


async def _open_meteo_air(location: dict) -> dict | None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(OPEN_METEO_AIR_URL, params={
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "current": "pm10,pm2_5,european_aqi",
            "timezone": location.get("timezone") or "auto",
        })
    if resp.status_code != 200:
        return None
    current = (resp.json() or {}).get("current") or {}
    aqi = current.get("european_aqi")
    if aqi is None:
        return None
    aqi = round(float(aqi))
    if aqi <= 20:
        category = "优"
    elif aqi <= 40:
        category = "良"
    elif aqi <= 60:
        category = "中等"
    elif aqi <= 80:
        category = "较差"
    else:
        category = "差"
    return {
        "aqi": str(aqi),
        "level": category,
        "category": category,
        "primary": "PM2.5",
        "pm2p5": str(current.get("pm2_5", "")),
        "pm10": str(current.get("pm10", "")),
        "provider": "open-meteo",
    }


async def _search_fallback(city: str, type: str) -> ToolResult:
    """使用网页搜索（DeepSeek / 智谱）作为天气查询兜底。"""
    try:
        from .search_web import search_web
        query_map = {
            "forecast": f"{city} 未来几天天气预报",
            "air": f"{city} 空气质量 AQI",
            "life": f"{city} 穿衣指数 生活建议",
        }
        query = query_map.get(type, f"{city} 今天天气")
        result = await search_web(query=query, count=3, recency="oneWeek")
        if result.success:
            result.data["_weather_fallback"] = True
            result.data["city"] = city
            return result
        return ToolResult.fail(f"查{city}天气的时候出了一点小问题……")
    except Exception as e:
        logger.error("weather.fallback_error", error=str(e))
        return ToolResult.fail(f"查{city}天气的时候出了一点小问题……")


# ── API 调用 ──────────────────────────────────────────

async def _lookup_city(city: str) -> str | None:
    """通过 GeoAPI 查找城市 LocationID。"""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(GEO_URL, params={
            "location": city,
            "key": _qweather_key(),
        })
        data = resp.json()
        if data.get("code") == "200" and data.get("location"):
            loc = data["location"][0]
            lid = loc.get("id", "")
            logger.debug("weather.city_lookup", city=city, id=lid,
                        name=loc.get("name", ""))
            return lid
    return None


async def _get_now(location_id: str) -> dict | None:
    """实时天气。"""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(NOW_URL, params={
            "location": location_id,
            "key": _qweather_key(),
        })
        data = resp.json()
        if data.get("code") == "200" and data.get("now"):
            now = data["now"]
            return {
                "temp": now.get("temp", ""),
                "feels_like": now.get("feelsLike", ""),
                "text": now.get("text", ""),
                "wind_dir": now.get("windDir", ""),
                "wind_scale": now.get("windScale", ""),
                "humidity": now.get("humidity", ""),
                "precip": now.get("precip", "0.0"),
            }
    return None


async def _get_forecast(location_id: str) -> dict | None:
    """3 日预报。"""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(FORECAST_URL, params={
            "location": location_id,
            "key": _qweather_key(),
        })
        data = resp.json()
        if data.get("code") == "200" and data.get("daily"):
            days = []
            for d in data["daily"][:3]:
                days.append({
                    "date": d.get("fxDate", ""),
                    "temp_max": d.get("tempMax", ""),
                    "temp_min": d.get("tempMin", ""),
                    "text_day": d.get("textDay", ""),
                    "text_night": d.get("textNight", ""),
                    "wind_dir": d.get("windDirDay", ""),
                    "wind_scale": d.get("windScaleDay", ""),
                    "precip": d.get("precip", "0.0"),
                    "humidity": d.get("humidity", ""),
                })
            return {"forecast": days}
    return None


async def _get_air(location_id: str) -> dict | None:
    """实时空气质量。"""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(AIR_URL, params={
            "location": location_id,
            "key": _qweather_key(),
        })
        data = resp.json()
        if data.get("code") == "200" and data.get("now"):
            now = data["now"]
            return {
                "aqi": now.get("aqi", ""),
                "level": now.get("level", ""),
                "category": now.get("category", ""),
                "primary": now.get("primary", ""),
                "pm2p5": now.get("pm2p5", ""),
                "pm10": now.get("pm10", ""),
            }
    return None


async def _get_indices(location_id: str) -> dict | None:
    """生活指数（穿衣、洗车等）。"""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(INDICES_URL, params={
            "location": location_id,
            "key": _qweather_key(),
            "type": "0",  # 全部指数
        })
        data = resp.json()
        if data.get("code") == "200" and data.get("daily"):
            indices = []
            for d in data["daily"][:6]:
                indices.append({
                    "name": d.get("name", ""),
                    "category": d.get("category", ""),
                    "text": d.get("text", ""),
                })
            return {"indices": indices}
    return None


# ── 结果模板（不需要 LLM 二次包装）──

def _register_template():
    from ..result_wrapper import register_template

    @register_template("query_weather")
    def wrap_weather(data):
        city = data.get("city", "那里")

        # Fallback: 网页搜索结果
        if data.get("_weather_fallback"):
            results = data.get("results", [])
            if not results:
                return f"唔……人家找了一下「{city}」的天气，好像没有找到呢 (´•ω•̥`)"
            lines = [f"人家帮你搜了一下{city}的天气～"]
            for r in results[:3]:
                title = r.get("title", "")
                content = r.get("content", "")[:200]
                lines.append(f"· {title}")
                if content:
                    lines.append(f"  {content}")
            lines.append("以上是搜索到的信息，供伙伴参考 ~♪")
            return "\n".join(lines)

        if not data.get("found", True):
            return f"唔……人家找了一下「{city}」，好像没有找到这个地方呢 (´•ω•̥`) 伙伴确认一下城市名好不好？"

        # 实时天气
        if "temp" in data:
            lines = [f"人家帮你看了看{city}的天气～"]
            text = data["text"]
            temp = data["temp"]
            feels = data.get("feels_like", "")
            wind = f"{data.get('wind_dir', '')}{data.get('wind_scale', '')}级" if data.get("wind_dir") else ""
            humidity = data.get("humidity", "")

            lines.append(f"现在是{text}，气温{temp}°C")
            if feels and feels != temp:
                lines.append(f"体感大概{feels}°C的样子……")
            if wind:
                lines.append(f"吹{wind}风")
            if humidity:
                lines.append(f"湿度{humidity}%")

            # 温馨提醒
            t = int(temp) if temp and temp.lstrip("-").isdigit() else 0
            if t <= 5:
                lines.append("外面挺冷的呢，穿厚一点哦 ~♪")
            elif t <= 15:
                lines.append("天有点凉，记得带件薄外套～")
            elif t >= 32:
                lines.append("今天挺热的……多喝水，注意防晒呀 ♪")
            elif 20 <= t <= 28 and data.get("precip", "0") == "0.0":
                if "晴" in text:
                    lines.append("是适合出门走走的好天气呢 ♪")

            return "\n".join(lines)

        # 预报
        if "forecast" in data:
            lines = [f"人家帮你看了看{city}接下来几天的天气～"]
            for d in data["forecast"]:
                lines.append(
                    f"{d['date']}：{d['text_day']}，{d['temp_min']}~{d['temp_max']}°C"
                )
            return "\n".join(lines)

        # 空气质量
        if "aqi" in data:
            return (
                f"人家帮你查了{city}的空气质量～\n"
                f"AQI {data['aqi']}，{data['category']}。\n"
                f"主要污染物是{data.get('primary', '无')}。\n"
                f"PM2.5: {data.get('pm2p5', '-')}，PM10: {data.get('pm10', '-')}"
            )

        # 生活指数
        if "indices" in data:
            lines = [f"{city}的生活指数～"]
            for idx in data["indices"]:
                lines.append(f"{idx['name']}：{idx['category']}——{idx['text']}")
            return "\n".join(lines)

        return f"人家查到了{city}的天气……不过数据有点奇怪呢，等会儿再试试好不好？"

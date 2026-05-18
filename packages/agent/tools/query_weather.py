"""
query_weather — 天气查询工具

两步查询：城市名 → LocationID (GeoAPI) → 实时天气 + 3日预报。
支持：实时天气 / 3日预报 / 空气质量 / 生活指数。
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
)
async def query_weather(city: str, type: str = "now", ctx=None) -> ToolResult:
    """
    查询城市天气。优先使用 QWeather API，失败时 fallback 到网页搜索。
    """
    # 尝试 QWeather API
    if QWEATHER_KEY:
        try:
            location_id = await _lookup_city(city)
            if location_id:
                data = None
                if type == "forecast":
                    data = await _get_forecast(location_id)
                elif type == "air":
                    data = await _get_air(location_id)
                elif type == "life":
                    data = await _get_indices(location_id)
                else:
                    data = await _get_now(location_id)

                if data:
                    data["city"] = city
                    return ToolResult.ok(data, trigger_portrait_update=True)
        except Exception as e:
            logger.warning("weather.qweather_failed", error=str(e))

    # Fallback: 使用网页搜索
    return await _search_fallback(city, type)


async def _search_fallback(city: str, type: str) -> ToolResult:
    """使用智谱搜索作为天气查询 fallback。"""
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
            "key": QWEATHER_KEY,
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
            "key": QWEATHER_KEY,
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
            "key": QWEATHER_KEY,
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
            "key": QWEATHER_KEY,
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
            "key": QWEATHER_KEY,
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

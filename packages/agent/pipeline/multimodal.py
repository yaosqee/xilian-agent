"""MultimodalProcessor — 多模态图片处理（URL 解析 + base64 转换 + 视觉模型描述）"""

import os
from pathlib import Path
from loguru import logger

from ._base import ServiceModule


class MultimodalProcessor(ServiceModule):
    """多模态处理。依赖 router（MiMo adapter 调用）。"""

    def __init__(self, ctx, router=None, db=None):
        super().__init__(ctx, router=router, db=db)
        self._desc_cache: dict[str, str] = {}  # 图片描述缓存，移至 Processor 内部管理

    def convert_to_multimodal(self, messages: list[dict], images: list[str], provider: str):
        """将最后一条 user 消息的 content 从 str 转为 multimodal content array。"""
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]["role"] == "user":
                text = messages[i]["content"]
                parts = [{"type": "text", "text": text}]
                for img_url in images:
                    resolved = self._resolve_image_url(img_url)
                    parts.append({
                        "type": "image_url",
                        "image_url": {"url": resolved},
                    })
                messages[i]["content"] = parts
                break

    def _resolve_image_url(self, url: str) -> str:
        """将本地相对路径转为 base64 data URL，远程 URL 原样返回。"""
        if url.startswith("/api/uploads/"):
            try:
                import base64
                rel_path = url[len("/api/uploads/"):]
                local_path = Path("data/uploads") / rel_path
                if local_path.exists():
                    image_data = local_path.read_bytes()
                    ext = local_path.suffix.lower()
                    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                                ".webp": "image/webp", ".gif": "image/gif"}
                    mime = mime_map.get(ext, "image/webp")
                    b64 = base64.b64encode(image_data).decode("ascii")
                    logger.debug("image.to_base64", url=url[:50], path=str(local_path), size=len(image_data))
                    return f"data:{mime};base64,{b64}"
                else:
                    logger.warning("image.file_not_found", path=str(local_path))
            except Exception as e:
                logger.warning("image.base64_failed", error=str(e))
        return url

    async def describe_image(self, image_url: str) -> str:
        """用视觉模型描述图片内容（默认 DeepSeek，复用主 Key）。

        VISION_PROVIDER=deepseek|mimo（默认 deepseek）
        VISION_MODEL=deepseek-v4-flash-vision-exp（默认）
        缓存：同一 URL 单次会话只调用一次。
        """
        if image_url in self._desc_cache:
            return self._desc_cache[image_url]

        resolved_url = self._resolve_image_url(image_url)
        provider = (os.getenv("VISION_PROVIDER") or "deepseek").strip().lower()
        default_model = (
            "deepseek-v4-flash-vision-exp" if provider == "deepseek" else ""
        )
        model = (os.getenv("VISION_MODEL") or default_model).strip()

        try:
            adapter = self._router._adapters.get(provider) if self._router else None
            if adapter is None and self._router:
                adapter = self._router._create_adapter(provider)
                if adapter is not None:
                    self._router._adapters[provider] = adapter
            if adapter is None:
                logger.warning("agent.describe_image.no_adapter", provider=provider)
                return ""

            if provider == "deepseek":
                description = await adapter.describe_image(resolved_url, model=model)
            else:
                description = await adapter.describe_image(resolved_url)
            if description:
                self._desc_cache[image_url] = description
                logger.debug(
                    "agent.describe_image.ok",
                    provider=provider, model=model, preview=description[:80],
                )
                return description
        except Exception as e:
            logger.warning(
                "agent.describe_image.failed",
                provider=provider, model=model, error=str(e)[:200],
            )

        return ""

    @staticmethod
    def compress_image_desc(description: str, max_chars: int = 30) -> str:
        """将视觉描述压缩为短句，用于嵌入 user_message 存入历史。"""
        if not description:
            return ""
        desc = description.split("。")[0].strip()
        if len(desc) <= max_chars:
            return desc
        return desc[:max_chars] + "…"

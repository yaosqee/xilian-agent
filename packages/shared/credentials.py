"""供应商凭据解析（M2-5）。

统一读取入口：DB（UI 添加）优先，`.env` 作为 bootstrap/CI fallback。
adapter 不再需要自己决定 Key 从哪来。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ProviderCredential:
    provider: str
    api_key: str = ""
    base_url: str = ""
    source: str = ""  # "db" | "env" | ""

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


class CredentialResolver:
    """DB 优先、环境变量兜底的凭据解析器。

    用法：
        resolver = CredentialResolver(db)
        await resolver.load()
        cred = resolver.resolve("deepseek")
        adapter = DeepSeekAdapter(api_key=cred.api_key, base_url=cred.base_url)
    """

    def __init__(self, db=None, env: Mapping[str, str] | None = None):
        self._db = db
        self._env = env if env is not None else os.environ
        self._providers: dict[str, dict] = {}

    async def load(self) -> None:
        if self._db is None:
            return
        try:
            rows = await self._db.get_model_providers()
        except Exception:
            rows = []
        self._providers = {
            str(row.get("provider")): dict(row) for row in rows
            if row.get("provider")
        }

    def reload_from_rows(self, rows: list[dict]) -> None:
        self._providers = {
            str(row.get("provider")): dict(row) for row in rows
            if row.get("provider")
        }

    def configured_providers(self) -> list[str]:
        return sorted(self._providers)

    def resolve(self, provider: str) -> ProviderCredential:
        row = self._providers.get(provider)
        if row and row.get("api_key"):
            return ProviderCredential(
                provider=provider,
                api_key=str(row.get("api_key") or ""),
                base_url=str(row.get("base_url") or ""),
                source="db",
            )

        env_key = self._env.get(f"{provider.upper()}_API_KEY", "")
        if not env_key and provider == "deepseek":
            env_key = self._env.get("DEEPSEEK_API_KEY_2", "")
        env_base = self._env.get(f"{provider.upper()}_BASE_URL", "")
        return ProviderCredential(
            provider=provider,
            api_key=env_key,
            base_url=env_base,
            source="env" if env_key else "",
        )

    def apply_to_env(self) -> None:
        """让 search_web 等仍读 env 的旧模块也能用 DB 配置的 Key。"""
        for provider, row in self._providers.items():
            key = str(row.get("api_key") or "")
            if key:
                os.environ[f"{provider.upper()}_API_KEY"] = key
            base_url = str(row.get("base_url") or "")
            if base_url:
                os.environ[f"{provider.upper()}_BASE_URL"] = base_url

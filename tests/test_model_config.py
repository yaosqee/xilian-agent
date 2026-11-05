"""M2-1 声明式路由配置：加载 / 校验 / 解析单测。"""
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, ".")

from packages.shared.model_config import (
    ModelConfigError,
    load_model_routing,
)
from packages.shared.providers import TASK_TIER_MAP


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "model_routing.toml"


def _write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "model_routing.toml"
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return path


BASE = """
version = 1

[providers.mock]
api_key_env = "MOCK_KEY"

[models.base]
provider = "mock"
capabilities = ["tools"]

[profiles.dialogue]
model = "base"

[routing]
chat = "dialogue"
"""


def test_default_config_matches_current_routes():
    config = load_model_routing(DEFAULT_CONFIG)

    assert config.version == 1
    assert config.resolve("chat").model == "deepseek-flash"
    assert config.resolve("chat").profile == "dialogue"
    assert config.resolve("tool_decision").model == "deepseek-flash"
    assert config.resolve("autobiography").profile == "background"
    assert config.resolve("reasoning").model == "deepseek-v4-pro"
    assert config.resolve("reasoning").profile == "reasoning"
    assert config.resolve("chat").source == "file"
    assert config.embedding is not None
    assert config.embedding.model == "BAAI/bge-m3"
    assert config.policy_for("deepseek-v4-pro").supports_thinking is True
    assert config.policy_for("deepseek-flash").supports_tools is True


def test_effective_routes_cover_all_registered_tasks():
    config = load_model_routing(DEFAULT_CONFIG)
    routes = config.effective_routes()

    assert set(routes) == set(TASK_TIER_MAP)
    assert routes["chat"]["model"] == "deepseek-flash"
    assert routes["code"]["profile"] == "reasoning"


def test_group_default_for_unlisted_task(tmp_path):
    path = _write_config(
        tmp_path,
        BASE
        + """
[profiles.background]
model = "base"

[routing_groups]
dialogue = "dialogue"
background = "background"
""",
    )
    config = load_model_routing(path)

    route = config.resolve("autobiography")
    assert route.profile == "background"
    assert route.model == "base"


def test_reasoning_group_resolves_unlisted_task(tmp_path):
    path = _write_config(
        tmp_path,
        BASE
        + """
[profiles.reasoning]
model = "base"

[routing_groups]
reasoning = "reasoning"
""",
    )
    config = load_model_routing(path)

    route = config.resolve("code")
    assert route.profile == "reasoning"
    assert route.model == "base"


def test_capability_fallback_selects_next_model(tmp_path):
    path = _write_config(
        tmp_path,
        """
version = 1

[providers.mock]
api_key_env = "MOCK_KEY"

[models.no_tools]
provider = "mock"
capabilities = ["streaming"]

[models.with_tools]
provider = "mock"
capabilities = ["tools"]

[profiles.tool]
model = "no_tools"
requires = ["tools"]
fallbacks = ["with_tools"]

[routing]
tool_decision = "tool"
""",
    )
    config = load_model_routing(path)
    route = config.resolve("tool_decision")

    assert route.model == "with_tools"
    assert route.capability_fallback is True
    assert route.fallbacks == ()


def test_extra_tools_requirement_uses_fallback(tmp_path):
    path = _write_config(
        tmp_path,
        """
version = 1

[providers.mock]
api_key_env = "MOCK_KEY"

[models.no_tools]
provider = "mock"
capabilities = ["streaming"]

[models.with_tools]
provider = "mock"
capabilities = ["tools"]

[profiles.dialogue]
model = "no_tools"
fallbacks = ["with_tools"]

[routing]
chat = "dialogue"
""",
    )
    config = load_model_routing(path)

    route = config.resolve("chat", extra_requires=("tools",))
    assert route.model == "with_tools"
    assert route.requires == ("tools",)
    assert route.capability_fallback is True


def test_profile_overrides_apply_source_and_fallbacks():
    config = load_model_routing(DEFAULT_CONFIG)
    overridden = config.with_profile_overrides({
        "dialogue": {
            "model": "deepseek-v4-pro",
            "fallbacks": ["deepseek-flash"],
            "temperature": 0.5,
            "max_tokens": 900,
        }
    })

    route = overridden.resolve("chat")
    assert route.model == "deepseek-v4-pro"
    assert route.fallbacks == ("deepseek-flash",)
    assert route.temperature == 0.5
    assert route.max_tokens == 900
    assert route.source == "ui"
    assert overridden.profiles["dialogue"].source == "ui"


def test_profile_overrides_reject_unknown_model():
    config = load_model_routing(DEFAULT_CONFIG)
    with pytest.raises(ModelConfigError, match="未知模型"):
        config.with_profile_overrides({
            "dialogue": {"model": "missing-model", "fallbacks": []}
        })


def test_invalid_model_reference_is_rejected(tmp_path):
    path = _write_config(
        tmp_path,
        """
version = 1

[providers.mock]
api_key_env = "MOCK_KEY"

[models.base]
provider = "mock"
capabilities = ["tools"]

[profiles.dialogue]
model = "missing-model"

[routing]
chat = "dialogue"
""",
    )
    with pytest.raises(ModelConfigError, match="未知模型"):
        load_model_routing(path)


def test_unknown_capability_is_rejected(tmp_path):
    path = _write_config(
        tmp_path,
        """
version = 1

[providers.mock]
api_key_env = "MOCK_KEY"

[models.base]
provider = "mock"
capabilities = ["toolz"]

[profiles.dialogue]
model = "base"

[routing]
chat = "dialogue"
""",
    )
    with pytest.raises(ModelConfigError, match="未知能力"):
        load_model_routing(path)


def test_plaintext_secret_is_rejected(tmp_path):
    path = _write_config(
        tmp_path,
        BASE.replace(
            'api_key_env = "MOCK_KEY"',
            'api_key = "sk-should-not-be-here"',
        ),
    )
    with pytest.raises(ModelConfigError, match="明文密钥"):
        load_model_routing(path)


def test_env_interpolation_and_api_key_resolution(tmp_path):
    path = _write_config(
        tmp_path,
        BASE.replace(
            'api_key_env = "MOCK_KEY"',
            'api_key_env = "MOCK_KEY"\nbase_url = "${MOCK_BASE}"',
        ),
    )
    config = load_model_routing(
        path,
        env={"MOCK_BASE": "https://mock.example/v1", "MOCK_KEY": "secret-value"},
    )

    assert config.providers["mock"].base_url == "https://mock.example/v1"
    assert config.resolve_api_key("mock", env={"MOCK_KEY": "secret-value"}) == "secret-value"


def test_missing_env_interpolation_is_rejected(tmp_path):
    path = _write_config(
        tmp_path,
        BASE.replace(
            'api_key_env = "MOCK_KEY"',
            'api_key_env = "MOCK_KEY"\nbase_url = "${MISSING_BASE}"',
        ),
    )
    with pytest.raises(ModelConfigError, match="未设置的环境变量"):
        load_model_routing(path, env={})


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(ModelConfigError, match="不存在"):
        load_model_routing(tmp_path / "nope.toml")


def test_embedding_is_parsed_without_secret_value():
    config = load_model_routing(DEFAULT_CONFIG)
    assert config.embedding is not None
    assert config.embedding.provider == "siliconflow"
    assert config.embedding.api_key_env == "EMBED_API_KEY"
    assert "sk-" not in str(config.embedding.to_dict())

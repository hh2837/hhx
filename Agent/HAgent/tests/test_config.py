"""配置加载的测试。"""

from __future__ import annotations

from pathlib import Path

from core import ConfigLoader
from core.errors import ConfigError

INI_CONTENT = """
[LLM]
base_url = http://127.0.0.1:1234/v1
api_key = test-key
model = test-model
timeout = 30
temperature = 0.2

[Agent]
max_tool_rounds = 5

[Filesystem]
max_read_bytes = 1024

[UI]
theme = textual-light
show_sidebar = false
"""


def _write_ini(tmp_path: Path) -> Path:
    path = tmp_path / "config.ini"
    path.write_text(INI_CONTENT, encoding="utf-8")
    return path


def test_从ini读取配置(tmp_path: Path) -> None:
    config = ConfigLoader(config_path=_write_ini(tmp_path)).load()

    assert config.llm.base_url == "http://127.0.0.1:1234/v1"
    assert config.llm.api_key == "test-key"
    assert config.llm.model == "test-model"
    assert config.llm.timeout == 30.0
    assert config.llm.temperature == 0.2
    assert config.agent.max_tool_rounds == 5
    assert config.filesystem.max_read_bytes == 1024
    assert config.ui.theme == "textual-light"
    assert config.ui.show_sidebar is False


def test_环境变量优先级更高(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XAGENT_LLM_MODEL", "env-model")
    monkeypatch.setenv("XAGENT_LLM_API_KEY", "env-key")
    monkeypatch.setenv("XAGENT_MAX_TOOL_ROUNDS", "9")

    config = ConfigLoader(config_path=_write_ini(tmp_path)).load()

    assert config.llm.model == "env-model"
    assert config.llm.api_key == "env-key"
    assert config.agent.max_tool_rounds == 9


def test_工作目录成为文件沙箱根目录(tmp_path: Path) -> None:
    config = ConfigLoader(config_path=_write_ini(tmp_path)).load()
    config = config.with_workspace(tmp_path)

    assert config.filesystem.root is None
    assert config.sandbox_root == tmp_path.resolve()
    assert config.workspace == tmp_path.resolve()


def test_聊天接口地址拼接正确() -> None:
    config = ConfigLoader(config_path=None).load()
    assert config.llm.chat_completions_url.endswith("/chat/completions")


def test_非法浮点配置会报错(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XAGENT_LLM_TIMEOUT", "abc")
    try:
        ConfigLoader(config_path=_write_ini(tmp_path)).load()
    except ConfigError:
        return
    raise AssertionError("应当抛出 ConfigError")

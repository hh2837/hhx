"""服务配置。

所有配置均可通过环境变量覆盖（pydantic-settings 大小写不敏感映射）：

- ``MCP_HOST`` / ``MCP_PORT``：MCP 服务监听地址（默认 127.0.0.1:8000）
- ``PET_HOSPITAL_BASE_URL``：上游 Go 宠物医院 REST API 地址
- ``BACKEND_TIMEOUT_SECONDS``：单次后端调用超时（秒）
- ``BACKEND_MAX_RETRIES``：瞬时失败（超时/连接失败）的最大重试次数
- ``LOG_LEVEL``：日志级别
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """MCP 服务配置。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # MCP 服务监听
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8000

    # 上游 Go 宠物医院 REST API
    pet_hospital_base_url: str = "http://127.0.0.1:8080"

    # 后端调用策略：超时 + 有限重试（重试仅针对瞬时错误）
    backend_timeout_seconds: float = 10.0
    backend_max_retries: int = 2
    backend_retry_backoff_seconds: float = 0.5

    # 日志
    log_level: str = "INFO"

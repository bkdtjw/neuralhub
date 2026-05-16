import os
import sys
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode

from backend.common.errors import AgentError


class Settings(BaseSettings):
    enable_tool_search: bool = True
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    default_provider: str = "anthropic"
    default_model: str = "kimi-k2.6"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    database_url: str = ""
    redis_url: str = ""
    database_pool_size: int = 5
    database_max_overflow: int = 10
    database_pool_timeout: int = 30
    database_pool_recycle: int = 1800
    metrics_ttl_days: int = 30
    log_search_backend: str = "file"
    log_search_fallback: str = "file"
    log_search_trace_minutes: int = Field(default=7 * 24 * 60, ge=60)
    loki_base_url: str = "http://127.0.0.1:3100"
    loki_tenant_id: str = ""
    loki_query_timeout_seconds: float = Field(default=10.0, ge=1.0)
    loki_app_label: str = "agent-studio"
    sub_worker_concurrency: int = Field(default=2, ge=1)
    auth_secret: str = "change-me-in-production"
    server_base_url: str = ""
    feishu_webhook_url: str = ""
    feishu_webhook_secret: str = ""
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_chat_id: str = ""
    feishu_verification_token: str = ""
    feishu_encrypt_key: str = ""
    morning_report_user_ids: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["default"]
    )
    morning_report_chat_id: str = ""
    morning_report_config_dir: str = "config/sites"
    mihomo_api_url: str = "http://127.0.0.1:9090"
    mihomo_secret: str = ""
    mihomo_path: str = ""
    mihomo_config_path: str = ""
    mihomo_work_dir: str = ""
    mihomo_sub_path: str = ""
    mihomo_custom_nodes_path: str = ""
    youtube_api_key: str = ""
    youtube_proxy_url: str = ""
    twitter_username: str = ""
    twitter_email: str = ""
    twitter_password: str = ""
    twitter_proxy_url: str = ""
    twitter_cookies_file: str = "twitter_cookies.json"
    notion_api_key: str = ""
    llm_fallback_provider_ids: str = ""
    llm_fallback_error_codes: str = (
        "NETWORK_ERROR,RATE_LIMIT,RATE_LIMIT_1113,RATE_LIMIT_1305,RATE_LIMIT_1312,SERVER_ERROR"
    )
    llm_fallback_deadline_seconds: float = Field(default=180.0, ge=1.0)
    llm_fallback_circuit_threshold: int = Field(default=3, ge=1)
    llm_fallback_circuit_seconds: float = Field(default=300.0, ge=1.0)
    main_agent_provider_id: str = ""
    vision_subagent_provider_id: str = ""
    jd_union_app_key: str = ""
    jd_union_app_secret: str = ""
    jd_union_access_token: str = ""
    zhetaoke_app_key: str = ""
    zhetaoke_tb_sid: str = ""
    zhetaoke_tb_pid: str = ""

    @field_validator("morning_report_user_ids", mode="before")
    @classmethod
    def parse_user_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    model_config = {
        "env_file": os.path.join(
            os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else ".",
            ".env",
        ),
        "env_file_encoding": "utf-8",
    }


def _validate_runtime_settings(config: Settings) -> Settings:
    database_url = config.database_url.strip()
    redis_url = config.redis_url.strip()
    if not database_url:
        raise AgentError(
            "DATABASE_URL_MISSING",
            "DATABASE_URL must be set to a PostgreSQL connection string.",
        )
    if not database_url.startswith("postgresql"):
        raise AgentError(
            "DATABASE_URL_INVALID",
            "DATABASE_URL must start with 'postgresql'.",
        )
    if not redis_url:
        raise AgentError(
            "REDIS_URL_MISSING",
            "REDIS_URL must be set to a Redis connection string.",
        )
    return config


settings = _validate_runtime_settings(Settings())

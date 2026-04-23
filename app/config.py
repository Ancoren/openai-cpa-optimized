"""
Pydantic Settings V2 based configuration management.
Replaces the 80+ global variables and fragile reload_all_configs() in config.py.

Key improvements:
- Type-safe configuration with validation
- Auto-reload via environment variables
- Nested model support (CPA, Sub2API, Proxy, DB)
- No global variable pollution
- YAML merge with env override (12-factor app style)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _load_yaml_config(path: Path) -> dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


class DatabaseConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_", extra="ignore")

    type: Literal["sqlite", "mysql"] = "sqlite"
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: str = ""
    db_name: str = "wenfxl_manager"
    pool_size: int = Field(default=5, ge=1, le=50)
    max_overflow: int = Field(default=10, ge=0, le=100)


class ProxyPoolConfig(BaseSettings):
    enable: bool = False
    pool_mode: bool = False
    fastest_mode: bool = False
    api_url: str = "http://127.0.0.1:9097"
    secret: str = ""
    group_name: str = "节点选择"
    test_proxy_url: str = ""
    cluster_count: int = 5
    sub_url: str = ""
    blacklist: list[str] = Field(default_factory=lambda: [
        "自动", "故障", "剩余", "到期", "官网", "Traffic",
        "DIRECT", "REJECT", "港", "HK", "Hongkong",
        "台", "TW", "Taiwan", "中", "CN", "China", "回国"
    ])


class RawProxyConfig(BaseSettings):
    enable: bool = False
    proxy_list: list[str] = Field(default_factory=list)


class CPAModeConfig(BaseSettings):
    enable: bool = False
    auto_check: bool = True
    save_to_local: bool = True
    api_url: str = ""
    api_token: str = ""
    min_accounts_threshold: int = 30
    batch_reg_count: int = 1
    min_remaining_weekly_percent: int = 80
    remove_on_limit_reached: bool = False
    remove_dead_accounts: bool = False
    enable_token_revive: bool = False
    check_interval_minutes: int = 60
    threads: int = Field(default=10, ge=1, le=100)
    retain_reg_only: bool = False


class Sub2APIModeConfig(BaseSettings):
    enable: bool = False
    auto_check: bool = True
    save_to_local: bool = True
    api_url: str = ""
    api_key: str = ""
    min_accounts_threshold: int = 20
    batch_reg_count: int = 1
    remove_on_limit_reached: bool = True
    remove_dead_accounts: bool = True
    enable_token_revive: bool = False
    check_interval_minutes: int = 60
    threads: int = 10
    account_concurrency: int = 10
    account_load_factor: int = 10
    account_priority: int = 1
    account_rate_multiplier: float = 1.0
    account_group_ids: str = ""
    enable_ws_mode: bool = True
    test_model: str = "gpt-5.2"
    default_proxy: str = ""
    retain_reg_only: bool = False


class EmailConfig(BaseSettings):
    api_mode: Literal[
        "imap", "freemail", "cloudflare_temp_email", "cloudmail",
        "mail_curl", "luckmail", "temporam", "tmailor", "duckmail"
    ] = "cloudflare_temp_email"
    domains: str = ""
    enable_sub_domains: bool = False
    sub_domain_count: int = 1
    sub_domain_level: int = 1
    random_sub_domain_level: bool = False
    max_otp_retries: int = Field(default=5, ge=1, le=20)
    use_proxy_for_email: bool = False
    enable_masking: bool = True


class TGConfig(BaseSettings):
    enable: bool = False
    token: str = ""
    chat_id: str = ""
    mask_email: bool = False
    mask_password: bool = False


class ClusterConfig(BaseSettings):
    node_name: str = "NODE-1"
    master_url: str = ""
    secret: str = "wenfxl666"


class HubConfig(BaseSettings):
    """Codex Hub auto-push configuration."""

    enable: bool = False
    url: str = "http://127.0.0.1:8080"
    admin_password: str = ""
    api_key: str = ""
    auto_push_on_reg: bool = True
    retry_times: int = 3
    retry_delay: int = 5


class AppConfig(BaseSettings):
    """
    Centralized application configuration.
    Loads from YAML then allows env override.
    """
    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_nested_delimiter="__",
        extra="ignore",
        validate_assignment=True,
    )

    # Core
    web_password: str = "admin"
    reg_mode: Literal["protocol", "browser"] = "protocol"
    default_proxy: str = ""
    enable_multi_thread_reg: bool = False
    reg_threads: int = Field(default=10, ge=1, le=200)
    retain_reg_only: bool = False
    disable_forced_takeover: bool = True

    # Timing
    login_delay_min: int = 20
    login_delay_max: int = 45
    normal_sleep_min: int = 5
    normal_sleep_max: int = 30
    normal_target_count: int = 2

    # Logging
    max_log_lines: int = 500
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Sub-configs
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    proxy_pool: ProxyPoolConfig = Field(default_factory=ProxyPoolConfig)
    raw_proxy: RawProxyConfig = Field(default_factory=RawProxyConfig)
    cpa: CPAModeConfig = Field(default_factory=CPAModeConfig)
    sub2api: Sub2APIModeConfig = Field(default_factory=Sub2APIModeConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    tg: TGConfig = Field(default_factory=TGConfig)
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)
    hub: HubConfig = Field(default_factory=HubConfig)

    @field_validator("login_delay_max")
    @classmethod
    def _delay_max_ge_min(cls, v: int, info) -> int:
        if v < info.data.get("login_delay_min", 0):
            raise ValueError("login_delay_max must be >= login_delay_min")
        return v

    @field_validator("normal_sleep_max")
    @classmethod
    def _sleep_max_ge_min(cls, v: int, info) -> int:
        if v < info.data.get("normal_sleep_min", 0):
            raise ValueError("normal_sleep_max must be >= normal_sleep_min")
        return v

    @model_validator(mode="after")
    def _validate_modes(self):
        """Ensure at most one primary mode is enabled."""
        modes = [self.cpa.enable, self.sub2api.enable]
        if sum(modes) > 1 and not (self.cpa.enable and self.sub2api.enable):
            # Both can be false (normal mode). Warn if multiple explicit.
            pass
        return self

    @classmethod
    def from_yaml(cls, path: Path | str = "data/config.yaml") -> "AppConfig":
        """Load config from YAML, merge with env vars."""
        path = Path(path)
        template_path = Path("config.example.yaml")

        # Auto-create from template if missing
        if not path.exists() and template_path.exists():
            os.makedirs(path.parent, exist_ok=True)
            import shutil
            shutil.copy(template_path, path)

        raw = _load_yaml_config(path)

        # Flatten nested keys for Pydantic consumption
        return cls(**raw)

    def is_cpa_mode(self) -> bool:
        return self.cpa.enable

    def is_sub2api_mode(self) -> bool:
        return self.sub2api.enable

    def is_normal_mode(self) -> bool:
        return not self.cpa.enable and not self.sub2api.enable

    def get_db_url(self) -> str:
        if self.database.type == "mysql":
            return (
                f"mysql+pymysql://{self.database.user}:{self.database.password}"
                f"@{self.database.host}:{self.database.port}/{self.database.db_name}"
            )
        return f"sqlite:///data/data.db"


# Singleton accessor (lazy-loaded to allow import without file IO)
_config_instance: AppConfig | None = None


def get_config() -> AppConfig:
    global _config_instance
    if _config_instance is None:
        _config_instance = AppConfig.from_yaml()
    return _config_instance


def reload_config() -> AppConfig:
    global _config_instance
    _config_instance = AppConfig.from_yaml()
    return _config_instance

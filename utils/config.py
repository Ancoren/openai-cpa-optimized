"""
Compatibility shim for legacy code that expects `utils.config`.
Reads from the new Pydantic-based `app.config` and exports the old globals.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone, timedelta

from app.config import get_config

# Lock for thread-safe GLOBAL_STOP
_stop_lock = threading.Lock()
_GLOBAL_STOP = False


def ts() -> str:
    tz_utc_8 = timezone(timedelta(hours=8))
    return datetime.now(tz_utc_8).strftime("%H:%M:%S")


def format_docker_url(url: str) -> str:
    if not url or not isinstance(url, str):
        return url
    if os.path.exists("/.dockerenv"):
        url = url.replace("127.0.0.1", "host.docker.internal")
        url = url.replace("localhost", "host.docker.internal")
    return url


# Property-like accessors for legacy code
class _ConfigProxy:
    """Maps old global names to new Pydantic config fields."""

    def __getattr__(self, name: str):
        cfg = get_config()

        # Direct mappings
        mappings = {
            "EMAIL_API_MODE": cfg.email.api_mode,
            "MAIL_DOMAINS": cfg.email.domains,
            "ENABLE_SUB_DOMAINS": cfg.email.enable_sub_domains,
            "SUB_DOMAIN_COUNT": cfg.email.sub_domain_count,
            "SUB_DOMAIN_LEVEL": cfg.email.sub_domain_level,
            "RANDOM_SUB_DOMAIN_LEVEL": cfg.email.random_sub_domain_level,
            "MAX_OTP_RETRIES": cfg.email.max_otp_retries,
            "USE_PROXY_FOR_EMAIL": cfg.email.use_proxy_for_email,
            "ENABLE_EMAIL_MASKING": cfg.email.enable_masking,
            "DEFAULT_PROXY": cfg.default_proxy,
            "ENABLE_MULTI_THREAD_REG": cfg.enable_multi_thread_reg,
            "REG_THREADS": cfg.reg_threads,
            "LOGIN_DELAY_MIN": cfg.login_delay_min,
            "LOGIN_DELAY_MAX": cfg.login_delay_max,
            "RETAIN_REG_ONLY": cfg.retain_reg_only,
            "ENABLE_CPA_MODE": cfg.cpa.enable,
            "SAVE_TO_LOCAL_IN_CPA_MODE": cfg.cpa.save_to_local,
            "CPA_RETAIN_REG_ONLY": cfg.cpa.retain_reg_only,
            "CPA_API_URL": cfg.cpa.api_url,
            "CPA_API_TOKEN": cfg.cpa.api_token,
            "CPA_THREADS": cfg.cpa.threads,
            "CPA_AUTO_CHECK": cfg.cpa.auto_check,
            "CHECK_INTERVAL_MINUTES": cfg.cpa.check_interval_minutes,
            "ENABLE_SUB2API_MODE": cfg.sub2api.enable,
            "SUB2API_SAVE_TO_LOCAL": cfg.sub2api.save_to_local,
            "SUB2API_RETAIN_REG_ONLY": cfg.sub2api.retain_reg_only,
            "SUB2API_URL": cfg.sub2api.api_url,
            "SUB2API_KEY": cfg.sub2api.api_key,
            "SUB2API_THREADS": cfg.sub2api.threads,
            "AI_API_BASE": cfg.ai_api_base if hasattr(cfg, "ai_api_base") else "",
            "AI_API_KEY": cfg.ai_api_key if hasattr(cfg, "ai_api_key") else "",
            "AI_MODEL": cfg.ai_model if hasattr(cfg, "ai_model") else "gpt-5.1-codex-mini",
            "AI_ENABLE_PROFILE": cfg.ai_enable_profile if hasattr(cfg, "ai_enable_profile") else False,
            "WEB_PASSWORD": cfg.web_password,
            "MAX_LOG_LINES": cfg.max_log_lines,
            "NORMAL_SLEEP_MIN": cfg.normal_sleep_min,
            "NORMAL_SLEEP_MAX": cfg.normal_sleep_max,
            "NORMAL_TARGET_COUNT": cfg.normal_target_count,
            "DISABLE_FORCED_TAKEOVER": cfg.disable_forced_takeover,
            "LUCKMAIL_API_KEY": "",
            "LUCKMAIL_PREFERRED_DOMAIN": "",
            "LUCKMAIL_EMAIL_TYPE": "",
            "LUCKMAIL_VARIANT_MODE": "",
            "LUCKMAIL_REUSE_PURCHASED": False,
            "LUCKMAIL_TAG_ID": None,
            "DUCKMAIL_API_URL": "https://api.duckmail.com",
            "DUCKMAIL_DOMAIN": "",
            "DUCKMAIL_MODE": "custom_api",
            "DUCK_API_TOKEN": "",
            "DUCK_COOKIE": "",
            "DUCK_OFFICIAL_API_BASE": "https://quack.duckduckgo.com",
            "DUCKMAIL_FORWARD_MODE": "Gmail_OAuth",
            "DUCKMAIL_FORWARD_EMAIL": "",
            "DUCK_USE_PROXY": True,
            "HERO_SMS_ENABLED": False,
            "HERO_SMS_API_KEY": "",
            "HERO_SMS_BASE_URL": "https://hero-sms.com/stubs/handler_api.php",
            "HERO_SMS_COUNTRY": "US",
            "HERO_SMS_SERVICE": "openai",
            "HERO_SMS_AUTO_PICK_COUNTRY": False,
            "HERO_SMS_REUSE_PHONE": True,
            "HERO_SMS_VERIFY_ON_REGISTER": False,
            "HERO_SMS_MAX_PRICE": 2.0,
            "HERO_SMS_MIN_BALANCE": 2.0,
            "HERO_SMS_MAX_TRIES": 3,
            "HERO_SMS_POLL_TIMEOUT_SEC": 120,
            "TEMPORAM_COOKIE": "",
            "TMAILOR_CURRENT_TOKEN": "",
            "FVIA_TOKEN": "",
            "GMAIL_OAUTH_MASTER_EMAIL": "",
            "GMAIL_OAUTH_FISSION_ENABLE": False,
            "GMAIL_OAUTH_FISSION_MODE": "suffix",
            "GMAIL_OAUTH_SUFFIX_MODE": "fixed",
            "GMAIL_OAUTH_SUFFIX_LEN_MIN": 8,
            "GMAIL_OAUTH_SUFFIX_LEN_MAX": 8,
            "DB_TYPE": cfg.database.type,
            "MYSQL_CFG": cfg.database.model_dump() if hasattr(cfg.database, "model_dump") else {},
            "_c": cfg.model_dump() if hasattr(cfg, "model_dump") else {},
            # Hub config (legacy shim)
            "HUB_ENABLE": cfg.hub.enable if hasattr(cfg, "hub") else False,
            "HUB_URL": cfg.hub.url if hasattr(cfg, "hub") else "",
            "HUB_ADMIN_PASSWORD": cfg.hub.admin_password if hasattr(cfg, "hub") else "",
            "HUB_API_KEY": cfg.hub.api_key if hasattr(cfg, "hub") else "",
            "HUB_AUTO_PUSH": cfg.hub.auto_push_on_reg if hasattr(cfg, "hub") else True,
        }

        if name in mappings:
            return mappings[name]

        if name == "GLOBAL_STOP":
            with _stop_lock:
                return _GLOBAL_STOP

        # Fallback: try reading directly from new config
        if hasattr(cfg, name.lower()):
            return getattr(cfg, name.lower())

        raise AttributeError(f"Legacy config '{name}' not mapped in compatibility shim")

    def __setattr__(self, name: str, value):
        if name == "GLOBAL_STOP":
            global _GLOBAL_STOP
            with _stop_lock:
                _GLOBAL_STOP = value
            return
        # Most other globals are read-only in new config
        raise AttributeError(f"Cannot set legacy config '{name}' — use app.config or env vars")


# Create singleton proxy instance
cfg = _ConfigProxy()

# Legacy code does `from utils import config as cfg` then `cfg.ts()`
# So we also expose module-level attributes for direct access
ts = ts
format_docker_url = format_docker_url

# Allow `cfg.GLOBAL_STOP = True` from engine.stop()
GLOBAL_STOP = property(lambda self: _GLOBAL_STOP)

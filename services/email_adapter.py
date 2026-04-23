"""
Compatibility adapter for the original email provider stack.

Since the original mail_service.py and its provider modules are complex
(1500+ lines, 10+ backends), this adapter provides a bridge so the new
RegistrationService can call them without modification.

Migration steps:
1. Copy the original `utils/email_providers/` directory into this project.
2. Ensure `utils/email_providers/mail_service.py` is importable.
3. If you use the compiled `auth_core` extension, place the appropriate
   `.so` / `.pyd` next to `services/openai_register.py` or in PYTHONPATH.

Once migrated, set the environment variable to enable:
    EMAIL_ADAPTER_LEGACY=1
"""

from __future__ import annotations

import os
from typing import Any, Optional, Tuple

from app.config import AppConfig
from utils.logger import get_logger

logger = get_logger("email_adapter")

_LEGACY_AVAILABLE = False
try:
    # Try importing the original mail_service stack
    from utils.email_providers.mail_service import get_email_and_token, get_oai_code, mask_email
    _LEGACY_AVAILABLE = True
    logger.info("Legacy email provider stack loaded successfully")
except ImportError as e:
    logger.warning(f"Legacy email provider stack not available: {e}")
    logger.warning("Registration will fail until email providers are integrated")


def legacy_get_email(proxies: Any = None) -> Tuple[Optional[str], Optional[str]]:
    """Bridge to original get_email_and_token()."""
    if not _LEGACY_AVAILABLE:
        raise RuntimeError(
            "Legacy email providers not loaded. "
            "Please copy the original utils/email_providers/ into this project."
        )
    return get_email_and_token(proxies)


def legacy_get_otp(
    email: str,
    jwt: str = "",
    proxies: Any = None,
    processed_mail_ids: set | None = None,
) -> Optional[str]:
    """Bridge to original get_oai_code()."""
    if not _LEGACY_AVAILABLE:
        raise RuntimeError("Legacy email providers not loaded.")
    return get_oai_code(email, jwt=jwt, proxies=proxies, processed_mail_ids=processed_mail_ids)


def legacy_mask_email(text: str) -> str:
    if not _LEGACY_AVAILABLE:
        # Fallback simple mask
        if "@" in text:
            user, domain = text.split("@", 1)
            return f"{user[:2]}***@{domain[:2]}***"
        return text
    return mask_email(text)

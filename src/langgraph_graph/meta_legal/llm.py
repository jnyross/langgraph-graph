"""OpenRouter chat model factory for meta_legal workers.

Uses langchain_openai.ChatOpenAI against the OpenRouter OpenAI-compatible API.
No langchain-deepseek dependency required.
"""

from __future__ import annotations

import os
from typing import Any

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# OpenRouter rolling alias for current DeepSeek V4 Flash (see /api/v1/models).
# Currently resolves to deepseek/deepseek-v4-flash-0731.
DEFAULT_MODEL = "~deepseek/deepseek-v4-flash-latest"


def get_llm(model: str | None = None, **kwargs: Any):
    """Return a ChatOpenAI client pointed at OpenRouter (lazy import).

    Defaults:
        model: OPENROUTER_MODEL or DEEPSEEK_MODEL or ``~deepseek/deepseek-v4-flash-latest``
        api_key: OPENROUTER_API_KEY, falling back to OPENAI_API_KEY
        base_url: OPENROUTER_BASE_URL or ``https://openrouter.ai/api/v1``
        temperature: 0
    """
    from langchain_openai import ChatOpenAI

    resolved_model = (
        model
        or os.getenv("OPENROUTER_MODEL")
        or os.getenv("DEEPSEEK_MODEL")
        or DEFAULT_MODEL
    )
    api_key = (
        kwargs.pop("api_key", None)
        or os.getenv("OPENROUTER_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or "OPENROUTER_API_KEY_NOT_SET"
    )
    base_url = (
        kwargs.pop("base_url", None)
        or os.getenv("OPENROUTER_BASE_URL")
        or DEFAULT_OPENROUTER_BASE_URL
    )
    temperature = kwargs.pop("temperature", 0)

    init_kwargs: dict[str, Any] = {
        "model": resolved_model,
        "temperature": temperature,
        "base_url": base_url,
        "api_key": api_key,
        **kwargs,
    }
    return ChatOpenAI(**init_kwargs)

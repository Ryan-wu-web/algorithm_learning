"""读取并校验模型配置。"""

import math
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelConfig:
    """模型调用所需的只读配置。"""
    api_key: str
    base_url: str
    model: str
    max_tokens: int = 300
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 60.0
    total_timeout_seconds: float = 90.0
    max_retries: int = 2
    retry_backoff_seconds: float = 1.0


def _read_int_config(name: str, default: int, *, minimum: int) -> int:
    """读取整数配置，并校验允许的最小值。"""
    raw_value = os.getenv(name, str(default)).strip()

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"配置 {name} 必须是整数") from exc

    if value < minimum:
        raise ValueError(f"配置 {name} 不能小于 {minimum}")

    return value


def _read_float_config(
    name: str,
    default: float,
    *,
    allow_zero: bool,
) -> float:
    """读取浮点数配置，并校验是否允许零值。"""
    raw_value = os.getenv(name, str(default)).strip()

    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"配置 {name} 必须是数字") from exc

    if not math.isfinite(value):
        raise ValueError(f"配置 {name} 必须是有限数字")

    if value < 0 or (value == 0 and not allow_zero):
        expectation = "大于等于 0" if allow_zero else "大于 0"
        raise ValueError(f"配置 {name} 必须{expectation}")

    return value


def validate_model_config() -> ModelConfig:
    """读取并校验模型调用所需的本地配置。"""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    model = os.getenv("OPENAI_MODEL", "").strip()

    missing_names = []

    if not api_key:
        missing_names.append("OPENAI_API_KEY")
    if not base_url:
        missing_names.append("OPENAI_BASE_URL")
    if not model:
        missing_names.append("OPENAI_MODEL")

    if missing_names:
        missing_text = "、".join(missing_names)
        raise ValueError(f"缺少配置：{missing_text}")

    return ModelConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        max_tokens=_read_int_config("OPENAI_MAX_TOKENS", 300, minimum=1),
        connect_timeout_seconds=_read_float_config(
            "OPENAI_CONNECT_TIMEOUT_SECONDS",
            10.0,
            allow_zero=False,
        ),
        read_timeout_seconds=_read_float_config(
            "OPENAI_READ_TIMEOUT_SECONDS",
            60.0,
            allow_zero=False,
        ),
        total_timeout_seconds=_read_float_config(
            "OPENAI_TOTAL_TIMEOUT_SECONDS",
            90.0,
            allow_zero=False,
        ),
        max_retries=_read_int_config("OPENAI_MAX_RETRIES", 2, minimum=0),
        retry_backoff_seconds=_read_float_config(
            "OPENAI_RETRY_BACKOFF_SECONDS",
            1.0,
            allow_zero=True,
        ),
    )

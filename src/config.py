"""读取并校验模型配置。"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelConfig:
    """模型调用所需的只读配置。"""

    api_key: str
    base_url: str
    model: str


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
    )

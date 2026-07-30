"""构造模型请求、调用模型并提取响应。"""

from collections.abc import Iterator

import openai

from src.config import ModelConfig


class ModelCallError(Exception):
    """模型调用失败时对应用暴露的统一异常。"""


def build_request_messages(
    system_prompt: str,
    messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    """将 System Prompt 与会话历史组合成完整请求消息。"""
    return [
        {
            "role": "system",
            "content": system_prompt,
        },
        *messages,
    ]


def call_model(
    config: ModelConfig,
    system_prompt: str,
    messages: list[dict[str, str]],
) -> Iterator[openai.types.chat.ChatCompletionChunk]:
    """调用 OpenAI 兼容接口，并将 SDK 异常映射为应用异常。"""
    client = openai.OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
    )
    request_messages = build_request_messages(system_prompt, messages)

    try:
        stream = client.chat.completions.create(
            model=config.model,
            messages=request_messages,
            max_tokens=300,
            stream=True,
            stream_options={"include_usage": True},
        )
        yield from stream
    except openai.AuthenticationError as exc:
        raise ModelCallError("认证失败，请检查 OPENAI_API_KEY 是否正确。") from exc
    except openai.RateLimitError as exc:
        raise ModelCallError("调用受限，请稍后重试或检查模型额度。") from exc
    except openai.APIConnectionError as exc:
        raise ModelCallError("连接失败，请检查网络或 OPENAI_BASE_URL。") from exc
    except openai.APIStatusError as exc:
        raise ModelCallError(f"API 调用失败：HTTP {exc.status_code}") from exc


def extract_stream_chunk_text(
    chunk: openai.types.chat.ChatCompletionChunk,
) -> str:
    """从流式响应块中提取第一条增量文本。"""
    if not chunk.choices:
        return ""

    return chunk.choices[0].delta.content or ""

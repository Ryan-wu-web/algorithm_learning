"""构造模型请求、调用模型并提取响应。"""
from collections.abc import Callable, Iterator
from dataclasses import dataclass
import logging
import time
from time import perf_counter
from uuid import uuid4

import httpx
import openai

from src.config import ModelConfig

logger = logging.getLogger(__name__)


class ModelCallError(Exception):
    """模型调用失败时对应用暴露的统一异常。"""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        request_id: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.request_id = request_id
        self.conversation_id = conversation_id


class ModelCallPartialOutputError(ModelCallError):
    """流式响应已经输出部分文本后发生的调用错误。"""


@dataclass(frozen=True)
class TokenUsage:
    """一次模型调用返回的 Token 用量。"""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class ModelCallResult:
    """一次模型调用完成后的具名结果。"""

    request_id: str
    conversation_id: str
    answer: str
    usage: TokenUsage | None
    elapsed_seconds: float


@dataclass(frozen=True)
class StreamEvent:
    """模型调用过程中向上层发送的文本或最终结果。"""

    request_id: str
    conversation_id: str
    text: str = ""
    result: ModelCallResult | None = None


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
    """创建一次流式请求，并将 SDK 异常映射为应用异常。"""
    timeout = httpx.Timeout(
        config.read_timeout_seconds,
        connect=config.connect_timeout_seconds,
        read=config.read_timeout_seconds,
        write=config.read_timeout_seconds,
        pool=config.connect_timeout_seconds,
    )
    client = openai.OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=timeout,
        max_retries=0,
    )
    request_messages = build_request_messages(system_prompt, messages)

    try:
        stream = client.chat.completions.create(
            model=config.model,
            messages=request_messages,
            max_tokens=config.max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        yield from stream
    except openai.AuthenticationError as exc:
        raise ModelCallError(
            "认证失败，请检查 OPENAI_API_KEY 是否正确。",
        ) from exc
    except openai.BadRequestError as exc:
        raise ModelCallError(
            "请求参数无效，请检查模型名称、消息内容和 Token 限制。",
        ) from exc
    except openai.RateLimitError as exc:
        raise ModelCallError(
            "调用受限，请稍后重试或检查模型额度。",
            retryable=True,
        ) from exc
    except openai.APITimeoutError as exc:
        raise ModelCallError(
            "模型响应超时，请稍后重试。",
            retryable=True,
        ) from exc
    except openai.APIConnectionError as exc:
        raise ModelCallError(
            "连接失败，请检查网络或 OPENAI_BASE_URL。",
            retryable=True,
        ) from exc
    except openai.APIStatusError as exc:
        raise ModelCallError(
            f"API 调用失败：HTTP {exc.status_code}",
            retryable=is_retryable_status_code(exc.status_code),
        ) from exc
    except openai.OpenAIError as exc:
        raise ModelCallError("模型调用失败，请检查请求配置。") from exc


def extract_stream_chunk_text(
    chunk: openai.types.chat.ChatCompletionChunk,
) -> str:
    """从流式响应块中提取第一条增量文本。"""
    if not chunk.choices:
        return ""

    return chunk.choices[0].delta.content or ""


def extract_token_usage(
    chunk: openai.types.chat.ChatCompletionChunk,
) -> TokenUsage | None:
    """从流式响应块中提取 Token 用量。"""
    usage = chunk.usage
    if usage is None:
        return None

    return TokenUsage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
    )


def is_retryable_status_code(status_code: int) -> bool:
    """判断 HTTP 状态码是否表示适合重试的临时错误。"""
    return status_code in {408, 409, 429, 500, 502, 503, 504}


def calculate_backoff_seconds(base_seconds: float, retry_index: int) -> float:
    """按照指数退避计算第 retry_index 次重试前的等待时间。"""
    return base_seconds * (2**retry_index)


def _total_timeout_error(
    *,
    request_id: str,
    conversation_id: str,
) -> ModelCallError:
    """创建包含关联 ID 的总等待超时错误。"""
    return ModelCallError(
        "模型调用超过总等待时间限制。",
        request_id=request_id,
        conversation_id=conversation_id,
    )


def stream_model_response(
    config: ModelConfig,
    system_prompt: str,
    messages: list[dict[str, str]],
    *,
    conversation_id: str,
    request_id: str | None = None,
    now: Callable[[], float] = perf_counter,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[StreamEvent]:
    """安全地重试流式调用，并在最后产生完整调用结果。"""
    resolved_request_id = request_id or uuid4().hex
    started_at = now()
    retry_count = 0

    while True:
        answer_parts: list[str] = []
        usage = None
        has_output = False

        try:
            stream = call_model(
                config=config,
                system_prompt=system_prompt,
                messages=messages,
            )

            for chunk in stream:
                if now() - started_at > config.total_timeout_seconds:
                    raise _total_timeout_error(
                        request_id=resolved_request_id,
                        conversation_id=conversation_id,
                    )

                text = extract_stream_chunk_text(chunk)
                if text:
                    has_output = True
                    answer_parts.append(text)
                    yield StreamEvent(
                        request_id=resolved_request_id,
                        conversation_id=conversation_id,
                        text=text,
                    )

                chunk_usage = extract_token_usage(chunk)
                if chunk_usage is not None:
                    usage = chunk_usage

            elapsed_seconds = now() - started_at
            if elapsed_seconds > config.total_timeout_seconds:
                raise _total_timeout_error(
                    request_id=resolved_request_id,
                    conversation_id=conversation_id,
                )

            result = ModelCallResult(
                request_id=resolved_request_id,
                conversation_id=conversation_id,
                answer="".join(answer_parts),
                usage=usage,
                elapsed_seconds=elapsed_seconds,
            )
            logger.info(
                "模型流式调用成功 request_id=%s conversation_id=%s attempts=%d elapsed=%.2f",
                resolved_request_id,
                conversation_id,
                retry_count + 1,
                elapsed_seconds,
            )
            yield StreamEvent(
                request_id=resolved_request_id,
                conversation_id=conversation_id,
                result=result,
            )
            return
        except ModelCallError as exc:
            if has_output:
                raise ModelCallPartialOutputError(
                    "响应已中断：模型已经输出部分内容，本次不会自动重试。",
                    request_id=resolved_request_id,
                    conversation_id=conversation_id,
                ) from exc

            exc.request_id = resolved_request_id
            exc.conversation_id = conversation_id
            if not exc.retryable or retry_count >= config.max_retries:
                raise

            delay = calculate_backoff_seconds(
                config.retry_backoff_seconds,
                retry_count,
            )
            elapsed_seconds = now() - started_at
            if elapsed_seconds + delay > config.total_timeout_seconds:
                raise _total_timeout_error(
                    request_id=resolved_request_id,
                    conversation_id=conversation_id,
                ) from exc

            logger.warning(
                "模型调用准备重试 request_id=%s conversation_id=%s retry=%d delay=%.2f error=%s",
                resolved_request_id,
                conversation_id,
                retry_count + 1,
                delay,
                exc,
            )
            sleep(delay)
            retry_count += 1

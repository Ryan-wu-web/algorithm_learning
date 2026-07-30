from types import SimpleNamespace

import pytest

from src.config import ModelConfig, validate_model_config
from src.conversation import (
    append_message,
    build_messages,
    is_clear_command,
    is_exit_command,
    normalize_question,
)
from src.llm_client import (
    ModelCallError,
    ModelCallPartialOutputError,
    ModelCallResult,
    TokenUsage,
    calculate_backoff_seconds,
    call_model,
    extract_stream_chunk_text,
    extract_token_usage,
    is_retryable_status_code,
    stream_model_response,
)
from src.main import print_call_result


def test_normalize_question_removes_surrounding_whitespace() -> None:
    """问题两侧的空白应该被删除。"""
    # assert normalize_question("  什么是 Token？  ") == "什么是 Token？"
    # Arrange
    raw_question = "  什么是 Token？  "
    # Act
    result = normalize_question(raw_question)
    # Assert
    assert result == "什么是 Token？"

def test_normalize_question_rejects_blank_input() -> None:
    """只有空白字符的问题应该被拒绝。"""
    with pytest.raises(ValueError, match="问题不能为空"):
        normalize_question("   ")


def test_validate_model_config_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """配置完整时，应返回清理并解析后的全部配置值。"""
    monkeypatch.setenv("OPENAI_API_KEY", " test-key ")
    monkeypatch.setenv("OPENAI_BASE_URL", " https://example.com/v1 ")
    monkeypatch.setenv("OPENAI_MODEL", " test-model ")
    monkeypatch.setenv("OPENAI_MAX_TOKENS", " 500 ")
    monkeypatch.setenv("OPENAI_CONNECT_TIMEOUT_SECONDS", " 3 ")
    monkeypatch.setenv("OPENAI_READ_TIMEOUT_SECONDS", " 20 ")
    monkeypatch.setenv("OPENAI_TOTAL_TIMEOUT_SECONDS", " 30 ")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", " 1 ")
    monkeypatch.setenv("OPENAI_RETRY_BACKOFF_SECONDS", " 0.5 ")

    assert validate_model_config() == ModelConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        max_tokens=500,
        connect_timeout_seconds=3.0,
        read_timeout_seconds=20.0,
        total_timeout_seconds=30.0,
        max_retries=1,
        retry_backoff_seconds=0.5,
    )


def test_validate_model_config_reports_missing_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配置缺失时，应一次性报告缺少的变量名。"""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    with pytest.raises(
        ValueError,
        match="缺少配置：OPENAI_API_KEY、OPENAI_MODEL",
    ):
        validate_model_config()


def test_validate_model_config_uses_day04_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未提供可靠性配置时，应使用 Day 04 默认值。"""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    for name in (
        "OPENAI_MAX_TOKENS",
        "OPENAI_CONNECT_TIMEOUT_SECONDS",
        "OPENAI_READ_TIMEOUT_SECONDS",
        "OPENAI_TOTAL_TIMEOUT_SECONDS",
        "OPENAI_MAX_RETRIES",
        "OPENAI_RETRY_BACKOFF_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    assert validate_model_config() == ModelConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("OPENAI_MAX_TOKENS", "abc"),
        ("OPENAI_CONNECT_TIMEOUT_SECONDS", "slow"),
        ("OPENAI_MAX_RETRIES", "1.5"),
        ("OPENAI_TOTAL_TIMEOUT_SECONDS", "nan"),
        ("OPENAI_RETRY_BACKOFF_SECONDS", "inf"),
    ],
)
def test_validate_model_config_rejects_invalid_numbers(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    """数字配置无法解析时，应指出对应环境变量。"""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        validate_model_config()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("OPENAI_MAX_TOKENS", "0"),
        ("OPENAI_CONNECT_TIMEOUT_SECONDS", "0"),
        ("OPENAI_READ_TIMEOUT_SECONDS", "-1"),
        ("OPENAI_TOTAL_TIMEOUT_SECONDS", "0"),
        ("OPENAI_MAX_RETRIES", "-1"),
        ("OPENAI_RETRY_BACKOFF_SECONDS", "-0.1"),
    ],
)
def test_validate_model_config_rejects_out_of_range_numbers(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    """可靠性配置越界时，应指出对应环境变量。"""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        validate_model_config()


def test_extract_stream_chunk_text_returns_delta_content() -> None:
    """应从流式响应块中提取增量文本。"""
    chunk = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content="这是模型回答。"),
            )
        ]
    )

    assert extract_stream_chunk_text(chunk) == "这是模型回答。"


def test_extract_stream_chunk_text_handles_empty_choices() -> None:
    """Usage 响应块没有候选回答时，应返回空字符串。"""
    chunk = SimpleNamespace(choices=[])

    assert extract_stream_chunk_text(chunk) == ""


def test_extract_stream_chunk_text_handles_none_content() -> None:
    """增量文本为 None 时，应返回空字符串。"""
    chunk = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=None),
            )
        ]
    )

    assert extract_stream_chunk_text(chunk) == ""


def test_call_model_creates_streaming_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """模型调用应启用流式输出并请求 Token 用量。"""
    expected_stream = iter([])
    captured: dict[str, object] = {}

    class FakeCompletions:
        def create(self, **kwargs: object) -> object:
            captured.update(kwargs)
            return expected_stream

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=FakeCompletions(),
        )
    )

    def fake_openai(
        *,
        api_key: str,
        base_url: str,
        timeout: object,
        max_retries: int,
    ) -> object:
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        captured["timeout"] = timeout
        captured["max_retries"] = max_retries
        return fake_client

    def fake_timeout(
        timeout: float,
        *,
        connect: float,
        read: float,
        write: float,
        pool: float,
    ) -> object:
        captured["timeout_values"] = {
            "timeout": timeout,
            "connect": connect,
            "read": read,
            "write": write,
            "pool": pool,
        }
        return "fake-timeout"

    monkeypatch.setattr("src.llm_client.openai.OpenAI", fake_openai)
    monkeypatch.setattr("src.llm_client.httpx.Timeout", fake_timeout)

    config = ModelConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        max_tokens=123,
        connect_timeout_seconds=4.0,
        read_timeout_seconds=9.0,
    )
    messages = [{"role": "user", "content": "你好"}]
    result = call_model(
        config=config,
        system_prompt="你是助手。",
        messages=messages,
    )
    list(result)

    assert captured == {
        "api_key": "test-key",
        "base_url": "https://example.com/v1",
        "timeout": "fake-timeout",
        "max_retries": 0,
        "timeout_values": {
            "timeout": 9.0,
            "connect": 4.0,
            "read": 9.0,
            "write": 9.0,
            "pool": 4.0,
        },
        "model": "test-model",
        "messages": [
            {"role": "system", "content": "你是助手。"},
            {"role": "user", "content": "你好"},
        ],
        "max_tokens": 123,
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def test_validate_model_config_rejects_whitespace_only_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只有空白字符的配置值应该被视为缺失。"""
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")

    with pytest.raises(ValueError, match="缺少配置：OPENAI_API_KEY"):
        validate_model_config()


def test_build_messages_creates_user_message() -> None:
    """用户问题应该被构造成一条 User 消息。"""
    assert build_messages("什么是 Token？") == [
        {
            "role": "user",
            "content": "什么是 Token？",
        }
    ]


def test_append_message_preserves_conversation_order() -> None:
    """追加消息时应该保持真实的对话顺序。"""
    messages: list[dict[str, str]] = []

    append_message(messages, "user", "我的名字叫小明。")
    append_message(messages, "assistant", "你好，小明。")
    append_message(messages, "user", "我叫什么名字？")

    assert messages == [
        {"role": "user", "content": "我的名字叫小明。"},
        {"role": "assistant", "content": "你好，小明。"},
        {"role": "user", "content": "我叫什么名字？"},
    ]


def test_append_message_keeps_conversations_independent() -> None:
    """修改一个会话时不应该影响另一个会话。"""
    conversation_a: list[dict[str, str]] = []
    conversation_b: list[dict[str, str]] = []

    append_message(conversation_a, "user", "你好")

    assert conversation_a == [{"role": "user", "content": "你好"}]
    assert conversation_b == []


@pytest.mark.parametrize("command", ["exit", " EXIT ", "quit", "QUIT", "退出"])
def test_is_exit_command_accepts_supported_commands(command: str) -> None:
    """程序应该识别支持的退出命令。"""
    assert is_exit_command(command) is True


def test_is_exit_command_rejects_normal_question() -> None:
    """普通问题不应该被识别为退出命令。"""
    assert is_exit_command("什么是 Token？") is False


@pytest.mark.parametrize("command", ["clear", " CLEAR ", "清空"])
def test_is_clear_command_accepts_supported_commands(command: str) -> None:
    """程序应该识别支持的清空历史命令。"""
    assert is_clear_command(command) is True


def test_is_clear_command_rejects_normal_question() -> None:
    """普通问题不应该被识别为清空命令。"""
    assert is_clear_command("什么是上下文？") is False


def make_stream_chunk(
    text: str | None = None,
    *,
    usage: object | None = None,
) -> SimpleNamespace:
    """构造测试所需的最小流式响应块。"""
    choices = []
    if text is not None:
        choices = [SimpleNamespace(delta=SimpleNamespace(content=text))]
    return SimpleNamespace(choices=choices, usage=usage)


def test_extract_token_usage_returns_named_usage() -> None:
    """SDK Usage 应转换为项目自己的只读结果对象。"""
    chunk = make_stream_chunk(
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=2,
            total_tokens=12,
        )
    )

    assert extract_token_usage(chunk) == TokenUsage(
        prompt_tokens=10,
        completion_tokens=2,
        total_tokens=12,
    )


def test_extract_token_usage_handles_missing_usage() -> None:
    """普通文本块没有 Usage 时，应返回 None。"""
    assert extract_token_usage(make_stream_chunk("你好")) is None


@pytest.mark.parametrize("status_code", [408, 409, 429, 500, 502, 503, 504])
def test_retryable_status_codes_include_transient_errors(status_code: int) -> None:
    """临时性 HTTP 状态码应该允许重试。"""
    assert is_retryable_status_code(status_code) is True


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
def test_retryable_status_codes_exclude_permanent_errors(status_code: int) -> None:
    """请求和权限类 HTTP 状态码不应该重试。"""
    assert is_retryable_status_code(status_code) is False


def test_calculate_backoff_seconds_uses_exponential_growth() -> None:
    """每次重试的等待时间应该按 1、2、4 倍增长。"""
    assert [calculate_backoff_seconds(0.5, index) for index in range(3)] == [
        0.5,
        1.0,
        2.0,
    ]


def test_stream_model_response_yields_text_and_final_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """流式调用应实时产生文本，并在最后给出完整具名结果。"""
    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=2,
        total_tokens=12,
    )
    chunks = iter(
        [
            make_stream_chunk("你"),
            make_stream_chunk("好"),
            make_stream_chunk(usage=usage),
        ]
    )
    monkeypatch.setattr("src.llm_client.call_model", lambda **kwargs: chunks)
    times = iter([100.0, 100.0, 100.0, 100.0, 101.5])

    events = list(
        stream_model_response(
            config=ModelConfig("key", "https://example.com/v1", "model"),
            system_prompt="你是助手。",
            messages=[{"role": "user", "content": "你好"}],
            conversation_id="conv-test",
            request_id="req-test",
            now=lambda: next(times),
            sleep=lambda seconds: None,
        )
    )

    assert [event.text for event in events[:-1]] == ["你", "好"]
    assert events[-1].result == ModelCallResult(
        request_id="req-test",
        conversation_id="conv-test",
        answer="你好",
        usage=TokenUsage(10, 2, 12),
        elapsed_seconds=1.5,
    )


def test_stream_model_response_retries_before_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """尚未输出文本的临时失败，应该按配置退避后重试。"""
    attempts = 0

    def fake_call_model(**kwargs: object) -> object:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ModelCallError("临时连接失败", retryable=True)
        return iter([make_stream_chunk("成功")])

    sleep_calls: list[float] = []
    monkeypatch.setattr("src.llm_client.call_model", fake_call_model)

    events = list(
        stream_model_response(
            config=ModelConfig(
                "key",
                "https://example.com/v1",
                "model",
                max_retries=2,
                retry_backoff_seconds=0.5,
            ),
            system_prompt="你是助手。",
            messages=[],
            conversation_id="conv-test",
            request_id="req-test",
            now=lambda: 100.0,
            sleep=sleep_calls.append,
        )
    )

    assert attempts == 2
    assert sleep_calls == [0.5]
    assert events[-1].result is not None
    assert events[-1].result.answer == "成功"


def test_stream_model_response_does_not_retry_permanent_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不可重试错误应立即向上层报告。"""
    attempts = 0

    def fake_call_model(**kwargs: object) -> object:
        nonlocal attempts
        attempts += 1
        raise ModelCallError("认证失败", retryable=False)

    sleep_calls: list[float] = []
    monkeypatch.setattr("src.llm_client.call_model", fake_call_model)

    with pytest.raises(ModelCallError, match="认证失败"):
        list(
            stream_model_response(
                config=ModelConfig("key", "url", "model"),
                system_prompt="你是助手。",
                messages=[],
                conversation_id="conv-test",
                now=lambda: 100.0,
                sleep=sleep_calls.append,
            )
        )

    assert attempts == 1
    assert sleep_calls == []


def test_stream_model_response_stops_after_retries_are_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """额外重试次数耗尽后，应保留最后一次模型错误。"""
    attempts = 0

    def fake_call_model(**kwargs: object) -> object:
        nonlocal attempts
        attempts += 1
        raise ModelCallError("服务暂时不可用", retryable=True)

    sleep_calls: list[float] = []
    monkeypatch.setattr("src.llm_client.call_model", fake_call_model)

    with pytest.raises(ModelCallError, match="服务暂时不可用"):
        list(
            stream_model_response(
                config=ModelConfig(
                    "key",
                    "url",
                    "model",
                    max_retries=2,
                    retry_backoff_seconds=1.0,
                ),
                system_prompt="你是助手。",
                messages=[],
                conversation_id="conv-test",
                now=lambda: 100.0,
                sleep=sleep_calls.append,
            )
        )

    assert attempts == 3
    assert sleep_calls == [1.0, 2.0]


def test_stream_model_response_never_retries_after_text_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已经输出部分回答后中断，不应重试并混合两次回答。"""
    attempts = 0

    def broken_stream() -> object:
        yield make_stream_chunk("部分回答")
        raise ModelCallError("读取中断", retryable=True)

    def fake_call_model(**kwargs: object) -> object:
        nonlocal attempts
        attempts += 1
        return broken_stream()

    sleep_calls: list[float] = []
    monkeypatch.setattr("src.llm_client.call_model", fake_call_model)
    iterator = stream_model_response(
        config=ModelConfig("key", "url", "model", max_retries=2),
        system_prompt="你是助手。",
        messages=[],
        conversation_id="conv-test",
        now=lambda: 100.0,
        sleep=sleep_calls.append,
    )

    assert next(iterator).text == "部分回答"
    with pytest.raises(ModelCallPartialOutputError, match="不会自动重试"):
        list(iterator)

    assert attempts == 1
    assert sleep_calls == []


def test_stream_model_response_stops_when_backoff_exceeds_total_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """下一次退避会超过总预算时，不应继续 sleep 或重试。"""
    attempts = 0

    def fake_call_model(**kwargs: object) -> object:
        nonlocal attempts
        attempts += 1
        raise ModelCallError("临时失败", retryable=True)

    times = iter([100.0, 109.5])
    sleep_calls: list[float] = []
    monkeypatch.setattr("src.llm_client.call_model", fake_call_model)

    with pytest.raises(ModelCallError, match="总等待时间"):
        list(
            stream_model_response(
                config=ModelConfig(
                    "key",
                    "url",
                    "model",
                    total_timeout_seconds=10.0,
                    retry_backoff_seconds=1.0,
                ),
                system_prompt="你是助手。",
                messages=[],
                conversation_id="conv-test",
                now=lambda: next(times),
                sleep=sleep_calls.append,
            )
        )

    assert attempts == 1
    assert sleep_calls == []


def test_stream_model_response_stops_when_first_chunk_arrives_after_total_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """首个响应块到达时已超出总预算，不应再向用户输出文本。"""
    monkeypatch.setattr(
        "src.llm_client.call_model",
        lambda **kwargs: iter([make_stream_chunk("迟到的回答")]),
    )
    times = iter([100.0, 111.0])

    with pytest.raises(ModelCallError, match="总等待时间"):
        list(
            stream_model_response(
                config=ModelConfig(
                    "key",
                    "url",
                    "model",
                    total_timeout_seconds=10.0,
                ),
                system_prompt="你是助手。",
                messages=[],
                conversation_id="conv-test",
                request_id="req-test",
                now=lambda: next(times),
                sleep=lambda seconds: None,
            )
        )


def test_stream_model_response_rejects_result_completed_after_total_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """流已结束但总耗时越界时，不应把迟到结果标记为成功。"""
    monkeypatch.setattr(
        "src.llm_client.call_model",
        lambda **kwargs: iter([make_stream_chunk("及时到达的回答")]),
    )
    times = iter([100.0, 109.0, 111.0])

    iterator = stream_model_response(
        config=ModelConfig(
            "key",
            "url",
            "model",
            total_timeout_seconds=10.0,
        ),
        system_prompt="你是助手。",
        messages=[],
        conversation_id="conv-test",
        request_id="req-test",
        now=lambda: next(times),
        sleep=lambda seconds: None,
    )

    assert next(iterator).text == "及时到达的回答"
    with pytest.raises(ModelCallPartialOutputError, match="不会自动重试"):
        list(iterator)


def test_stream_model_response_keeps_usage_optional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """兼容接口未返回 Usage 时，最终结果仍应成功且 usage 为 None。"""
    monkeypatch.setattr(
        "src.llm_client.call_model",
        lambda **kwargs: iter([make_stream_chunk("你好")]),
    )

    events = list(
        stream_model_response(
            config=ModelConfig("key", "url", "model"),
            system_prompt="你是助手。",
            messages=[],
            conversation_id="conv-test",
            request_id="req-test",
            now=lambda: 100.0,
            sleep=lambda seconds: None,
        )
    )

    assert events[-1].result is not None
    assert events[-1].result.usage is None


def test_print_call_result_displays_ids_elapsed_and_usage(capsys: pytest.CaptureFixture[str]) -> None:
    """CLI 应使用具名结果统一展示调用统计。"""
    result = ModelCallResult(
        request_id="req-test",
        conversation_id="conv-test",
        answer="你好",
        usage=TokenUsage(10, 2, 12),
        elapsed_seconds=1.25,
    )

    print_call_result(result)

    output = capsys.readouterr().out
    assert "请求 ID：req-test" in output
    assert "请求耗时：1.25 秒" in output
    assert "输入 Token：10" in output
    assert "输出 Token：2" in output
    assert "总 Token：12" in output

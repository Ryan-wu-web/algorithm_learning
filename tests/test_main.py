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
from src.llm_client import call_model, extract_stream_chunk_text


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
    """配置完整时，应返回清理过的三个配置值。"""
    monkeypatch.setenv("OPENAI_API_KEY", " test-key ")
    monkeypatch.setenv("OPENAI_BASE_URL", " https://example.com/v1 ")
    monkeypatch.setenv("OPENAI_MODEL", " test-model ")

    assert validate_model_config() == ModelConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
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

    def fake_openai(*, api_key: str, base_url: str) -> object:
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        return fake_client

    monkeypatch.setattr("src.llm_client.openai.OpenAI", fake_openai)

    config = ModelConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
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
        "model": "test-model",
        "messages": [
            {"role": "system", "content": "你是助手。"},
            {"role": "user", "content": "你好"},
        ],
        "max_tokens": 300,
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

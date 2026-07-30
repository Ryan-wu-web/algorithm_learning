"""运行多轮大模型命令行助手。"""

import logging
import sys
from uuid import uuid4

import openai
from dotenv import load_dotenv

from src.config import validate_model_config
from src.conversation import (
    append_message,
    build_system_prompt,
    is_clear_command,
    is_exit_command,
    normalize_question,
)
from src.llm_client import (
    ModelCallError,
    ModelCallResult,
    stream_model_response,
)

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """配置应用日志格式与级别。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def print_call_result(result: ModelCallResult) -> None:
    """向用户展示一次模型调用的关联信息与统计数据。"""
    print(f"\n请求 ID：{result.request_id}")
    print(f"请求耗时：{result.elapsed_seconds:.2f} 秒")

    if result.usage is not None:
        print(f"输入 Token：{result.usage.prompt_tokens}")
        print(f"输出 Token：{result.usage.completion_tokens}")
        print(f"总 Token：{result.usage.total_tokens}")


def main() -> None:
    """运行命令行程序。"""
    configure_logging()
    load_dotenv()

    try:
        config = validate_model_config()
    except ValueError as exc:
        logger.error("模型配置无效：%s", exc)
        print(f"\n配置错误：{exc}")
        return

    system_prompt = build_system_prompt()
    messages: list[dict[str, str]] = []
    conversation_id = uuid4().hex

    print("\nSystem Prompt：")
    print(system_prompt)

    print(f"\nOpenAI SDK 版本：{openai.__version__}")
    print(f"模型：{config.model}")
    print(f"API 地址：{config.base_url}")
    print(f"API Key：已加载（长度 {len(config.api_key)} 个字符，不显示内容）")
    print(f"会话 ID：{conversation_id}")
    print(f"最大输出 Token：{config.max_tokens}")
    print(f"连接超时：{config.connect_timeout_seconds:g} 秒")
    print(f"读取超时：{config.read_timeout_seconds:g} 秒")
    print(f"总等待上限：{config.total_timeout_seconds:g} 秒")
    print(f"最大重试次数：{config.max_retries}")
    print("\n多轮对话已启动。输入 exit、quit 或‘退出’结束；输入 clear 或‘清空’清除历史。")
    logger.info(
        "聊天程序启动 model=%s conversation_id=%s",
        config.model,
        conversation_id,
    )

    while True:
        raw_question = input("\n你：")

        if is_exit_command(raw_question):
            print("\n对话已结束。")
            logger.info("用户结束对话 history_messages=%d", len(messages))
            break

        if is_clear_command(raw_question):
            messages.clear()
            print("\n会话历史已清空。")
            logger.info("会话历史已清空")
            continue

        try:
            question = normalize_question(raw_question)
        except ValueError as exc:
            print(f"\n输入错误：{exc}")
            logger.warning("用户输入无效：%s", exc)
            continue

        append_message(messages, "user", question)

        print("\n模型响应：")
        final_result: ModelCallResult | None = None

        try:
            events = stream_model_response(
                config=config,
                system_prompt=system_prompt,
                messages=messages,
                conversation_id=conversation_id,
            )

            for event in events:
                if event.text:
                    print(event.text, end="", flush=True)
                if event.result is not None:
                    final_result = event.result
        except ModelCallError as exc:
            messages.pop()
            print(f"\n模型调用失败：{exc}")
            logger.error(
                "模型调用失败 request_id=%s conversation_id=%s retryable=%s error=%s",
                exc.request_id,
                exc.conversation_id or conversation_id,
                exc.retryable,
                exc,
            )
            continue

        if final_result is None:
            messages.pop()
            print("\n模型调用失败：没有收到最终结果。")
            logger.error(
                "模型调用缺少最终结果 conversation_id=%s",
                conversation_id,
            )
            continue

        append_message(messages, "assistant", final_result.answer)

        if not final_result.answer:
            print("（模型没有返回文本内容）", end="")
        print()

        print_call_result(final_result)
        print(f"当前历史消息数：{len(messages)}")
        logger.info(
            "模型调用成功 model=%s request_id=%s conversation_id=%s elapsed=%.2f history_messages=%d",
            config.model,
            final_result.request_id,
            final_result.conversation_id,
            final_result.elapsed_seconds,
            len(messages),
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n对话已中断。")
        sys.exit(130)

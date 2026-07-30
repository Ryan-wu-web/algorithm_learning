"""运行多轮大模型命令行助手。"""

import logging
import sys
from time import perf_counter

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
from src.llm_client import ModelCallError, call_model, extract_stream_chunk_text

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """配置应用日志格式与级别。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


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

    print("\nSystem Prompt：")
    print(system_prompt)

    print(f"\nOpenAI SDK 版本：{openai.__version__}")
    print(f"模型：{config.model}")
    print(f"API 地址：{config.base_url}")
    print(f"API Key：已加载（长度 {len(config.api_key)} 个字符，不显示内容）")
    print("\n多轮对话已启动。输入 exit、quit 或‘退出’结束；输入 clear 或‘清空’清除历史。")
    logger.info("聊天程序启动 model=%s", config.model)

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
        started_at = perf_counter()
        response_parts: list[str] = []
        usage = None

        try:
            stream = call_model(
                config=config,
                system_prompt=system_prompt,
                messages=messages,
            )

            for chunk in stream:
                text = extract_stream_chunk_text(chunk)
                if text:
                    response_parts.append(text)
                    print(text, end="", flush=True)
                if chunk.usage is not None:
                    usage = chunk.usage
        except ModelCallError as exc:
            messages.pop()
            print(f"\n模型调用失败：{exc}")
            logger.error("模型调用失败：%s", exc)
            continue

        elapsed = perf_counter() - started_at
        response_text = "".join(response_parts)
        append_message(messages, "assistant", response_text)

        if not response_text:
            print("（模型没有返回文本内容）", end="")
        print()

        print(f"\n请求耗时：{elapsed:.2f} 秒")

        if usage is not None:
            print(f"输入 Token：{usage.prompt_tokens}")
            print(f"输出 Token：{usage.completion_tokens}")
            print(f"总 Token：{usage.total_tokens}")

        print(f"当前历史消息数：{len(messages)}")
        logger.info(
            "模型调用成功 model=%s elapsed=%.2f history_messages=%d",
            config.model,
            elapsed,
            len(messages),
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n对话已中断。")
        sys.exit(130)

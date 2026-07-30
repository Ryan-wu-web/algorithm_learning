"""处理用户输入、命令判断和会话历史。"""
def normalize_question(question: str) -> str:
    """清理并校验用户问题。"""
    question = question.strip()

    if not question:
        raise ValueError("问题不能为空")

    return question


def build_system_prompt() -> str:
    """构建学习助手的 System Prompt。"""
    return (
        "你是一名大模型应用开发学习助手，"
        "请使用清晰、准确的语言回答问题。"
    )

def build_messages(question: str) -> list[dict[str, str]]:
    """将用户问题构造成模型消息列表。"""
    return [
        {
            "role": "user",
            "content": question,
        }
    ]

def append_message(
    messages: list[dict[str, str]],
    role: str,
    content: str,
) -> None:
    """按顺序向会话历史追加一条消息。"""
    messages.append(
        {
            "role": role,
            "content": content,
        }
    )

def is_exit_command(text: str) -> bool:
    """判断用户是否希望结束对话。"""
    return text.strip().lower() in {"exit", "quit", "退出"}


def is_clear_command(text: str) -> bool:
    """判断用户是否希望清空会话历史。"""
    return text.strip().lower() in {"clear", "清空"}

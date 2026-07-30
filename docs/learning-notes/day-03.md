# Day 03：从单文件 Demo 走向结构化 Python 项目

## 1. 今日目标与完成情况

Day 01 完成了真实模型调用，Day 02 实现了多轮会话和基础测试。随着配置、会话、模型调用、流式输出、错误处理和 CLI 交互不断增加，所有代码继续集中在 `src/main.py` 会使模块职责越来越混乱。

Day 03 的核心目标不是增加更多模型能力，而是完成一次工程化重构：

```text
按职责拆分模块
→ 使用具名配置对象
→ 保留流式多轮调用
→ 建立应用级异常边界
→ 区分用户输出与运行日志
→ 使用少量回归测试保证行为不变
```

今日完成情况：

- [x] 将单文件程序拆分为四个职责明确的模块；
- [x] 测试直接从函数真正定义的模块导入；
- [x] 使用 `@dataclass(frozen=True)` 定义只读配置对象；
- [x] 将模型配置从位置元组改为具名属性；
- [x] 独立封装完整请求消息的构造；
- [x] 保留流式模型输出；
- [x] 使用生成器覆盖流创建和流迭代阶段的异常；
- [x] 将 OpenAI SDK 异常映射为应用级 `ModelCallError`；
- [x] 简化 `main.py` 对外部 SDK 异常的了解；
- [x] 引入 `logging`，区分运行日志与用户界面；
- [x] 支持 `Ctrl+C` 友好退出；
- [x] 22 个测试全部通过；
- [x] 四个模块通过 Python 语法检查；
- [x] CLI 启动和退出冒烟测试通过。

---

## 2. 重构后的项目结构

```text
src/
├── main.py           # 命令行入口，组织整体流程
├── config.py         # 配置对象、环境变量读取与校验
├── conversation.py   # 用户输入、命令判断和会话历史
└── llm_client.py     # 请求构造、流式调用、响应提取和异常映射
```

### 模块依赖关系

```text
main.py
├── config.py
├── conversation.py
└── llm_client.py
      └── config.py
```

关键原则：

```text
入口层依赖功能模块
功能模块不反向依赖入口层
```

这样未来增加 FastAPI 入口时，可以继续复用底层模块：

```text
CLI main.py ─────┐
                 ├→ config / conversation / llm_client
FastAPI app.py ──┘
```

---

## 3. 为什么要拆分模块

模块拆分不是为了增加文件数量，而是为了让同一类变化集中在同一位置。

### `config.py` 的变化原因

- 增加环境变量；
- 修改配置名称；
- 增加超时、最大 Token 或重试配置；
- 调整配置校验规则。

### `conversation.py` 的变化原因

- 增加新的会话命令；
- 修改问题清理规则；
- 修改 System Prompt；
- 调整历史消息结构。

### `llm_client.py` 的变化原因

- 更换或升级 SDK；
- 调整模型参数；
- 修改流式请求方式；
- 增加超时、重试或错误映射。

### `main.py` 的变化原因

- 修改 CLI 交互流程；
- 改变各模块的调用顺序；
- 调整用户界面输出。

这体现了：

> 关注点分离（Separation of Concerns）：每个模块只关心一类问题。

---

## 4. `config.py`：只读配置对象

### 4.1 ModelConfig

当前配置模型：

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelConfig:
    """模型调用所需的只读配置。"""

    api_key: str
    base_url: str
    model: str
```

`@dataclass` 会根据字段声明自动生成初始化、比较和对象展示等常用方法，避免手写重复的 `__init__()`。

创建对象：

```python
config = ModelConfig(
    api_key="test-key",
    base_url="https://example.com/v1",
    model="test-model",
)
```

读取字段：

```python
config.api_key
config.base_url
config.model
```

### 4.2 为什么不用元组

Day 02 返回：

```python
return api_key, base_url, model
```

调用方必须依赖位置：

```python
api_key, base_url, model = validate_model_config()
```

如果配置增加或顺序变化，调用方容易发生错位。

Day 03 改成：

```python
return ModelConfig(
    api_key=api_key,
    base_url=base_url,
    model=model,
)
```

调用方使用：

```python
config = validate_model_config()
print(config.model)
```

可以记成：

```text
索引告诉我“它排在哪里”
属性名告诉我“它是什么”
```

### 4.3 `frozen=True`

```python
@dataclass(frozen=True)
```

表示对象创建后不允许重新赋值：

```python
config.model = "another-model"
```

会抛出异常。

配置通常在程序启动时加载，运行期间只读取，不应被业务代码意外修改，因此适合使用只读对象。

注意：`frozen=True` 主要阻止字段重新赋值。如果字段本身是列表等可变对象，仍需额外考虑内部可变性；当前三个字段都是字符串，没有这个问题。

### 4.4 配置读取和校验

```python
def validate_model_config() -> ModelConfig:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    model = os.getenv("OPENAI_MODEL", "").strip()
```

使用 `.strip()` 保证纯空格配置也被视为缺失。

缺失字段被一次性收集：

```python
missing_names = []

if not api_key:
    missing_names.append("OPENAI_API_KEY")
```

最终统一报告：

```python
raise ValueError(f"缺少配置：{missing_text}")
```

这种方式比每次只报告一个缺失字段更便于排查。

---

## 5. `conversation.py`：会话相关纯逻辑

该模块不读取 API Key、不创建 OpenAI 客户端，也不执行终端输入输出。

### 5.1 输入清理

```python
def normalize_question(question: str) -> str:
    question = question.strip()

    if not question:
        raise ValueError("问题不能为空")

    return question
```

它负责将任意原始字符串转换为可用问题，或通过 `ValueError` 明确拒绝空输入。

### 5.2 System Prompt

```python
def build_system_prompt() -> str:
    return (
        "你是一名大模型应用开发学习助手，"
        "请使用清晰、准确的语言回答问题。"
    )
```

System Prompt 属于对话规则，而不是 CLI 或 SDK 细节，因此放在会话模块。

### 5.3 创建初始消息

```python
def build_messages(question: str) -> list[dict[str, str]]:
    return [
        {
            "role": "user",
            "content": question,
        }
    ]
```

它从零创建一份只有 User 消息的新列表。

当前多轮主流程没有直接使用该函数，而是统一使用 `append_message()`；目前选择保留它，作为“创建初始消息列表”的独立能力。后续如果长期没有正式调用，可以重新评估是否删除。

### 5.4 追加历史消息

```python
def append_message(
    messages: list[dict[str, str]],
    role: str,
    content: str,
) -> None:
    messages.append(
        {
            "role": role,
            "content": content,
        }
    )
```

`messages` 是可变列表，`.append()` 会直接修改原对象，因此函数返回 `None`。

### 5.5 退出和清空命令

```python
def is_exit_command(text: str) -> bool:
    return text.strip().lower() in {"exit", "quit", "退出"}
```

```python
def is_clear_command(text: str) -> bool:
    return text.strip().lower() in {"clear", "清空"}
```

通过 `strip()` 和 `lower()`，程序兼容英文大小写和两侧空格。

---

## 6. `llm_client.py`：模型调用边界

该模块知道 OpenAI SDK、请求参数、响应块结构和 SDK 异常，但不知道用户通过 CLI 还是 Web 提问。

### 6.1 构造完整请求消息

```python
def build_request_messages(
    system_prompt: str,
    messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": system_prompt,
        },
        *messages,
    ]
```

`*messages` 将历史列表中的每条消息展开到新列表中。

例如：

```python
messages = [
    {"role": "user", "content": "我的代号是蓝鲸。"},
    {"role": "assistant", "content": "已记住。"},
]
```

得到：

```python
[
    {"role": "system", "content": "你是一名学习助手……"},
    {"role": "user", "content": "我的代号是蓝鲸。"},
    {"role": "assistant", "content": "已记住。"},
]
```

这样请求构造逻辑不再隐藏在 SDK 调用内部。

### 6.2 call_model() 接收配置对象

```python
def call_model(
    config: ModelConfig,
    system_prompt: str,
    messages: list[dict[str, str]],
) -> Iterator[openai.types.chat.ChatCompletionChunk]:
```

调用方不再分别传入三个配置参数：

```python
call_model(
    config=config,
    system_prompt=system_prompt,
    messages=messages,
)
```

客户端创建：

```python
client = openai.OpenAI(
    api_key=config.api_key,
    base_url=config.base_url,
)
```

### 6.3 流式请求

```python
stream = client.chat.completions.create(
    model=config.model,
    messages=request_messages,
    max_tokens=300,
    stream=True,
    stream_options={"include_usage": True},
)
```

关键参数：

```text
stream=True
```

表示返回流式响应，模型生成的文本会分成多个响应块。

```text
stream_options={"include_usage": True}
```

请求服务在流结束时额外返回 Token 用量。包含用量的响应块可能没有候选文本，因此 `extract_stream_chunk_text()` 必须允许 `choices=[]`。

### 6.4 Iterator 与生成器

返回类型：

```python
Iterator[ChatCompletionChunk]
```

表示调用方可以逐项遍历响应块：

```python
for chunk in stream:
    ...
```

`call_model()` 使用：

```python
yield from stream
```

它等价于：

```python
for chunk in stream:
    yield chunk
```

因此 `call_model()` 本身成为生成器函数。

重要特点：调用生成器函数时，函数体不会立即完整执行；只有开始迭代时，创建流和读取流的代码才开始推进。

### 6.5 为什么使用 `yield from`

流式请求的错误可能发生在两个阶段：

```text
创建流时
或
遍历流、读取后续响应块时
```

如果只在创建流外层捕获异常，流迭代阶段的错误可能逃出模型层。

现在：

```python
try:
    stream = client.chat.completions.create(...)
    yield from stream
except ...:
    ...
```

使“创建流”和“消费流”都处于同一异常映射边界中。

---

## 7. 应用级异常映射

### 7.1 ModelCallError

```python
class ModelCallError(Exception):
    """模型调用失败时对应用暴露的统一异常。"""
```

它代表应用层统一理解的“模型调用失败”。

### 7.2 SDK 异常到应用异常

```python
except openai.AuthenticationError as exc:
    raise ModelCallError(
        "认证失败，请检查 OPENAI_API_KEY 是否正确。"
    ) from exc
```

其他映射：

```text
RateLimitError      → 调用受限
APIConnectionError  → 网络或 Base URL 问题
APIStatusError      → HTTP 状态错误
```

### 7.3 错误映射的意义

重构前，`main.py` 必须知道所有 SDK 异常：

```python
openai.AuthenticationError
openai.RateLimitError
openai.APIConnectionError
openai.APIStatusError
```

重构后，`main.py` 只需要捕获：

```python
except ModelCallError as exc:
```

职责变成：

```text
llm_client.py
→ 理解外部 SDK 的异常
→ 转换成应用自己的错误语言

main.py
→ 决定发生应用错误后如何更新状态、记录日志和提示用户
```

这可以降低入口层对某个模型供应商 SDK 的耦合。

### 7.4 `raise ... from exc`

```python
raise ModelCallError("连接失败") from exc
```

对上层暴露易理解的应用异常，同时保留原始 SDK 异常作为原因链。

用户看到简洁消息，开发者查看 traceback 时仍能追踪根因。

---

## 8. 流式文本提取

```python
def extract_stream_chunk_text(
    chunk: openai.types.chat.ChatCompletionChunk,
) -> str:
    if not chunk.choices:
        return ""

    return chunk.choices[0].delta.content or ""
```

流式响应与普通响应路径不同：

```text
普通响应：choices[0].message.content
流式响应：choices[0].delta.content
```

需要处理：

1. `choices=[]`：例如只包含 Token 用量的最终响应块；
2. `delta.content=None`：当前响应块没有增量文本；
3. 正常文本：返回当前增量内容。

---

## 9. `main.py`：编排层

`main.py` 现在主要负责组织模块，而不是实现所有底层细节。

### 9.1 启动流程

```python
configure_logging()
load_dotenv()
config = validate_model_config()
system_prompt = build_system_prompt()
messages = []
```

### 9.2 每轮流程

```text
读取输入
→ 判断退出或清空命令
→ 清理问题
→ 追加 User 消息
→ 流式调用模型
→ 实时打印响应块
→ 拼接完整回答
→ 追加 Assistant 消息
→ 输出耗时、Token 和历史数量
```

这叫做编排层：

> 不负责每件事内部怎样实现，而负责它们按照怎样的顺序协作。

### 9.3 流式显示与完整回答

```python
response_parts: list[str] = []
```

每收到一个文本块：

```python
response_parts.append(text)
print(text, end="", flush=True)
```

- `end=""`：输出后不自动换行；
- `flush=True`：立即刷新到终端，使用户看到实时生成效果。

流结束后拼接：

```python
response_text = "".join(response_parts)
```

再保存完整 Assistant 消息：

```python
append_message(messages, "assistant", response_text)
```

因此：

```text
显示阶段使用增量块
历史阶段保存完整回答
```

### 9.4 Token 用量

```python
usage = None
```

遍历每个流块时：

```python
if chunk.usage is not None:
    usage = chunk.usage
```

服务通常在接近流结束的响应块中返回用量，因此先保存，流结束后统一输出。

### 9.5 调用失败后的状态回滚

调用前已经追加了 User 消息：

```python
append_message(messages, "user", question)
```

如果模型失败：

```python
except ModelCallError as exc:
    messages.pop()
```

删除本轮最后加入的 User 消息，避免会话历史留下没有 Assistant 回答的半轮状态。

注意：流式输出可能在已经打印部分文本后才失败。当前实现仍然回滚 User 消息，但终端中已经显示的部分文本无法撤回。这是流式系统比普通请求更复杂的一个边界，后续可考虑显示“响应中断”并记录部分输出。

---

## 10. logging：用户输出与运行记录分离

### 10.1 日志配置

```python
def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
```

日志包含：

```text
时间
日志级别
模块名
日志消息
```

### 10.2 logger

```python
logger = logging.getLogger(__name__)
```

`__name__` 表示当前模块名。使用 `python -m src.main` 启动时，该模块名可能显示为 `__main__`。

### 10.3 当前日志级别

#### INFO

正常运行事件：

```python
logger.info("聊天程序启动 model=%s", config.model)
logger.info("会话历史已清空")
```

#### WARNING

程序可以继续，但输入有问题：

```python
logger.warning("用户输入无效：%s", exc)
```

#### ERROR

本次操作失败：

```python
logger.error("模型配置无效：%s", exc)
logger.error("模型调用失败：%s", exc)
```

### 10.4 为什么不全部替换 print()

```text
print()   → 程序在和用户说话
logging   → 程序在记录自己发生了什么
```

模型回答、输入提示和退出消息属于用户界面，继续使用 `print()`。

模型名称、耗时、历史消息数和错误状态属于运行记录，使用日志。

### 10.5 参数化日志

使用：

```python
logger.info("聊天程序启动 model=%s", config.model)
```

而不是：

```python
logger.info(f"聊天程序启动 model={config.model}")
```

前者将模板和参数分开，日志级别未启用时可避免不必要的字符串格式化，也更符合 Python logging 的常见写法。

---

## 11. Ctrl+C 友好退出

程序入口：

```python
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n对话已中断。")
        sys.exit(130)
```

用户按 `Ctrl+C` 时，Python 会抛出 `KeyboardInterrupt`。

程序捕获后不显示长 traceback，而是输出友好提示并以状态码 `130` 退出。`130` 是命令行程序被中断时的常见退出码。

---

## 12. 测试策略与结果

Day 03 按用户要求减少测试学习比例，不为每个简单函数安排新的练习；测试主要作为重构安全网。

运行：

```powershell
uv run pytest -q
```

最终结果：

```text
......................                                                   [100%]
22 passed in 1.35s
```

### 当前测试覆盖

#### 配置

- 完整环境变量返回 `ModelConfig`；
- 配置值会被 `.strip()` 清理；
- 多个缺失字段一次报告；
- 纯空格配置被视为缺失。

#### 会话

- 问题两侧空白被清理；
- 空问题抛出 `ValueError`；
- 构造初始 User 消息；
- 追加消息保持顺序；
- 两个会话列表互不影响；
- 退出和清空命令正确识别。

#### 流式响应

- 提取 `delta.content`；
- `choices=[]` 返回空字符串；
- `delta.content=None` 返回空字符串。

#### 模型请求

- OpenAI 客户端收到正确的 API Key 和 Base URL；
- 请求包含 System Prompt 和历史消息；
- 模型名称正确；
- `max_tokens=300`；
- `stream=True`；
- 请求 Token 用量。

### 一次预期内的测试失败

将 `call_model()` 改成使用 `yield from` 后，旧测试断言：

```python
assert result is expected_stream
```

失败，因为 `call_model()` 现在返回应用自己的生成器，而不是原始 SDK 流对象。

测试改为：

```python
result = call_model(...)
list(result)
```

消费生成器后检查 SDK 收到的请求参数。

这次修正使测试从关注内部对象身份，转为关注真正重要的外部行为：

```text
是否创建了正确的流式请求
```

---

## 13. 语法与冒烟验证

### 13.1 语法检查

```powershell
uv run python -m py_compile src/main.py src/config.py src/conversation.py src/llm_client.py
```

命令无输出，表示四个模块语法正确。

### 13.2 CLI 冒烟测试

使用模块方式启动：

```powershell
uv run python -m src.main
```

已验证：

- 配置成功加载；
- 日志成功输出；
- 程序进入会话；
- `exit` 被正确识别；
- 程序正常结束。

自动冒烟测试通过 Git Bash 管道运行时中文出现乱码，这是 Git Bash 管道与 Windows 控制台编码差异导致的显示问题，不是 Python 文件内容或业务逻辑错误。PowerShell 或 PyCharm 直接运行通常不会出现该现象。

---

## 14. 当前完整数据流

```text
main.py 启动
→ configure_logging()
→ load_dotenv()
→ config.validate_model_config()
    → 读取环境变量
    → 清理和校验
    → 返回只读 ModelConfig
→ conversation.build_system_prompt()
→ 创建 messages 历史列表
→ 等待用户输入
    ├─ exit / quit / 退出
    │   → 记录结束日志
    │   → break
    ├─ clear / 清空
    │   → messages.clear()
    │   → 记录日志
    │   → continue
    ├─ 空白输入
    │   → normalize_question() 抛出 ValueError
    │   → 显示提示并记录 WARNING
    │   → continue
    └─ 普通问题
        → append_message(user)
        → llm_client.call_model()
            → build_request_messages()
            → 创建 OpenAI 客户端
            → 发起流式请求
            → yield from SDK stream
            → SDK 异常映射为 ModelCallError
        → main.py 遍历响应块
            → extract_stream_chunk_text()
            → 实时打印文本
            → 收集 response_parts
            → 保存 usage
        ├─ 调用失败
        │   → pop() 回滚 User 消息
        │   → 显示错误并记录 ERROR
        │   → continue
        └─ 调用成功
            → join() 拼接完整回答
            → append_message(assistant)
            → 输出耗时、Token 和历史数量
            → 记录成功日志
```

---

## 15. 今日遇到并解决的问题

### 问题 1：模块职责判断

最初容易把退出命令和终端输入误认为模型调用逻辑。

最终边界：

```text
input()              → main.py，CLI 入口
退出和清空规则       → conversation.py
OpenAI SDK 调用      → llm_client.py
环境变量读取         → config.py
```

### 问题 2：位置索引看似明确，但缺少业务语义

最初认为 `config[2]` 指向性更强。进一步比较后理解：

```text
config[2]     → 明确第三个位置，但不知道它是什么
config.model  → 直接表达模型名称
```

### 问题 3：间接导入虽然能运行，但边界不清晰

函数移动后，测试曾可通过 `src.main` 间接导入会话函数，因为 `main.py` 又导入了它们。

最终改为从真正定义模块直接导入：

```python
from src.conversation import append_message
```

### 问题 4：生成器改变了测试假设

`yield from` 使返回对象不再等于原始 SDK 流。最终测试不再断言对象身份，而是消费生成器并检查请求参数。

### 问题 5：流式错误可能在迭代阶段发生

单纯围绕 `create()` 的异常捕获不一定覆盖后续流读取。使用生成器把创建和迭代放在同一个 `try` 内。

---

## 16. 今日纠正的认识

### 纠正 1：模块拆分不等于随意移动函数

应按职责和变化原因拆分，并保持依赖方向清晰。

### 纠正 2：具名属性比位置索引更具业务指向性

`config.model` 比 `config[2]` 更容易阅读和维护。

### 纠正 3：入口层不应了解所有 SDK 细节

`main.py` 只处理 `ModelCallError`，由模型层负责供应商异常映射。

### 纠正 4：流式调用不是一次返回完整文本

流式响应由多个 Chunk 组成，需要实时显示、收集、拼接，最终再写入 Assistant 历史。

### 纠正 5：日志不等于把所有 print() 换掉

用户交互与运行记录服务于不同受众，应分别处理。

### 纠正 6：重构测试应关注行为，而不是内部实现细节

测试 SDK 请求参数比断言返回对象必须是某个特定实例更稳健。

---

## 17. 当前仍需注意的边界

### 17.1 流式中途失败

如果模型已经输出部分文本后连接中断：

- 部分文本已经显示在终端；
- 当前代码回滚 User 消息；
- 部分 Assistant 文本不会写入历史；
- 用户需要知道这次回答是不完整的。

后续可以设计：

```text
记录部分输出
→ 显示“响应中断”
→ 决定是否保存 incomplete 状态
→ 支持重试或继续生成
```

### 17.2 `ModelCallError` 尚未直接测试

当前测试覆盖正确流式请求，但尚未分别模拟认证、限流、连接和 HTTP 错误，验证它们是否映射为正确消息。

考虑到 Day 03 希望减少测试，这部分可以留到后续错误处理专题。

### 17.3 `build_messages()` 当前未被主流程使用

它仍有“创建初始消息列表”的独立语义，但当前主流程统一使用 `append_message()`。如果长期无正式调用，应删除无用函数和对应测试，避免维护两个重叠入口。

### 17.4 配置参数仍有硬编码

以下参数目前写在 `llm_client.py`：

```python
max_tokens=300
```

未来可移动到 `ModelConfig`：

```text
max_tokens
timeout
temperature
retry_count
```

### 17.5 日志暂时只输出到终端

尚未实现：

- 日志文件；
- 日志轮转；
- JSON 结构化日志；
- request_id / conversation_id；
- 敏感字段过滤规则。

当前阶段不记录 API Key 内容，只记录模型、耗时和消息数量。

---

## 18. 今日成果

### `src/config.py`

- 新增 `ModelConfig`；
- 使用 `@dataclass(frozen=True)`；
- 配置校验返回具名对象。

### `src/conversation.py`

- 集中输入清理、System Prompt、消息和命令规则；
- 不依赖 OpenAI SDK 或终端输入输出。

### `src/llm_client.py`

- 独立请求消息构造；
- 接收 `ModelConfig`；
- 保留流式请求；
- 使用 `Iterator` 和 `yield from`；
- 新增 `ModelCallError`；
- 映射常见 SDK 异常；
- 提取流式增量文本。

### `src/main.py`

- 作为 CLI 编排层；
- 引入日志；
- 统一处理 `ModelCallError`；
- 实时显示模型回答；
- 拼接完整响应并写入历史；
- 支持 Ctrl+C 友好退出。

### `tests/test_main.py`

- 更新为直接从定义模块导入；
- 适配 `ModelConfig`；
- 验证流式请求结构；
- 最终 22 个测试通过。

---

## 19. 今日知识验收

完成 Day 03 后，我应该能够解释：

1. 为什么要按职责和变化原因拆分模块；
2. `main.py` 为什么称为编排层；
3. 为什么功能模块不应反向依赖入口层；
4. `@dataclass` 自动提供了什么；
5. `frozen=True` 为什么适合配置对象；
6. `config.model` 为什么优于 `config[2]`；
7. `*messages` 如何展开历史列表；
8. 普通响应和流式响应的文本路径有何不同；
9. `Iterator` 和 `yield from` 在当前代码中的用途；
10. 为什么流式错误可能在迭代时发生；
11. 什么是应用级异常映射；
12. `raise ... from exc` 有什么意义；
13. `print()` 和 `logging` 分别服务于谁；
14. 为什么调用失败后需要回滚会话状态；
15. 为什么重构测试应关注行为而非内部对象身份。

---

## 20. 仍需巩固

- [ ] 独立阅读和解释四个模块的职责；
- [ ] 熟悉 Python 模块导入路径；
- [ ] 理解 dataclass 与普通类的关系；
- [ ] 理解生成器延迟执行；
- [ ] 理解 `yield`、`yield from` 和 `Iterator`；
- [ ] 理解流式响应中 Usage Chunk 的特点；
- [ ] 理解异常映射和异常链；
- [ ] 掌握 INFO、WARNING、ERROR 的使用边界；
- [ ] 思考流式中断后的会话一致性策略；
- [ ] 运行真实多轮流式对话并观察日志、Token 和历史增长。

---

## 21. Day 04 建议

Day 04 可继续第一阶段的可靠性工程，建议主题：

```text
超时、重试与模型调用结果对象
```

候选内容：

1. 将 `max_tokens`、超时等参数加入 `ModelConfig`；
2. 区分连接超时、读取超时和总等待时间；
3. 理解哪些错误适合重试，哪些不适合；
4. 加入有限次数、带退避的重试；
5. 避免流式已经输出后进行无意识重试；
6. 将回答、Token 和耗时封装为具名结果对象；
7. 为每次调用增加 request ID 或 conversation ID；
8. 继续为后续 FastAPI 服务层做准备。

---

## 22. 今日一句话总结

> Day 03 我将单文件多轮聊天程序重构为配置、会话、模型客户端和 CLI 编排四个模块，使用只读 `ModelConfig` 代替位置元组，通过生成器保留流式输出并覆盖迭代异常，使用 `ModelCallError` 隔离 OpenAI SDK 错误，同时用 logging 建立了最初的运行记录边界，最终 22 个测试、语法检查和 CLI 冒烟验证全部通过。

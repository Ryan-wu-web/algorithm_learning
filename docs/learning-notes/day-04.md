# Day 04：超时、重试与模型调用结果对象

## 1. 今日目标与完成情况

Day 03 已经把单文件程序拆分为配置、会话、模型调用和 CLI 四个模块，但模型调用仍有几个明显的可靠性缺口：

- `max_tokens=300` 写死在模型客户端中；
- OpenAI SDK 默认会自动重试，但应用并不知道真实尝试次数；
- 连接超时、读取超时和整轮总等待时间没有清楚区分；
- 流式输出中断后，如果从头重试，用户可能看到两份回答混在一起；
- 回答、Token 和耗时由 CLI 使用多个零散变量保存；
- 日志无法通过 request ID 和 conversation ID 关联同一轮请求。

Day 04 的目标是把调用流程升级为：

```text
读取可靠性配置
→ 创建带细分超时的模型客户端
→ 发起流式请求
→ 在安全边界内执行有限退避重试
→ 实时输出文本事件
→ 返回包含回答、Token、耗时和关联 ID 的具名结果
```

今日完成情况：

- [x] 将 `max_tokens` 加入只读 `ModelConfig`；
- [x] 增加连接、读取和应用层总等待时间配置；
- [x] 增加最大重试次数和基础退避时间配置；
- [x] 对数字环境变量进行类型与范围校验；
- [x] 显式关闭 OpenAI SDK 内建重试；
- [x] 区分可重试与不可重试错误；
- [x] 实现有限次数的指数退避重试；
- [x] 将初次请求、重试和等待统一计入总时间预算；
- [x] 禁止在已经输出文本后自动重试；
- [x] 增加 `TokenUsage`、`ModelCallResult` 和 `StreamEvent`；
- [x] 增加 request ID 与 conversation ID；
- [x] 让 CLI 继续实时输出，同时使用最终具名结果更新历史；
- [x] 增加到 59 个自动化测试；
- [x] 完成语法检查、CLI 启停和真实两轮模型验证。

---

## 2. Day 04 后的关键文件

```text
src/
├── config.py         # 配置默认值、环境变量读取和数字校验
├── conversation.py   # 用户输入、命令和消息历史（本日无功能改动）
├── llm_client.py     # 超时、错误映射、重试、流式事件和最终结果
└── main.py           # CLI 输入输出、会话历史和结果展示

tests/
└── test_main.py      # 配置、流式、重试、超时和 CLI 展示测试
```

模块关系变为：

```text
main.py
  ├── conversation.py
  ├── config.py
  └── llm_client.py
        ├── OpenAI SDK
        └── httpx.Timeout
```

CLI 不再负责计算耗时、拼接回答或从原始 chunk 中读取 Token。这些属于模型调用结果，应由 `llm_client.py` 统一处理。

---

## 3. 配置对象为什么需要扩展

`ModelConfig` 现在除了 API Key、地址和模型名称，还保存：

```python
max_tokens: int = 300
connect_timeout_seconds: float = 10.0
read_timeout_seconds: float = 60.0
total_timeout_seconds: float = 90.0
max_retries: int = 2
retry_backoff_seconds: float = 1.0
```

好处是调用行为不再散落在代码中：

- 本地开发可以使用默认值；
- 不修改源码就能通过 `.env` 调整；
- 测试可以构造不同配置验证边界；
- 将来 FastAPI 服务也能复用同一个配置对象。

对应环境变量：

```env
OPENAI_MAX_TOKENS=300
OPENAI_CONNECT_TIMEOUT_SECONDS=10
OPENAI_READ_TIMEOUT_SECONDS=60
OPENAI_TOTAL_TIMEOUT_SECONDS=90
OPENAI_MAX_RETRIES=2
OPENAI_RETRY_BACKOFF_SECONDS=1
```

`max_retries=2` 的含义是：初始调用失败后，最多再尝试 2 次。因此总尝试次数最多为 3 次。

### 数字校验

环境变量读取到的都是字符串，所以程序需要显式解析：

- `OPENAI_MAX_TOKENS` 必须是大于 0 的整数；
- 三种超时必须是大于 0 的数字；
- `OPENAI_MAX_RETRIES` 必须是大于等于 0 的整数；
- 基础退避时间允许为 0，便于本地关闭等待。

非法配置会在程序启动阶段直接报错，而不是等到请求模型时才暴露。

---

## 4. 三种超时的区别

### 4.1 连接超时

```text
connect_timeout_seconds
```

它限制客户端建立网络连接所能等待的时间。

常见问题包括：

- 域名解析失败；
- 网络不可达；
- 代理或中转站地址错误；
- 服务器无法接受连接。

### 4.2 读取超时

```text
read_timeout_seconds
```

连接成功后，客户端等待下一批响应数据的时间不能无限长。对流式接口来说，可以把它理解成：

> 已经连上服务器后，等待下一个 chunk 最多多久。

如果模型一直不返回下一块数据，OpenAI SDK 会抛出 `APITimeoutError`。

### 4.3 应用层总等待时间

```text
total_timeout_seconds
```

它限制整轮模型调用的总预算，包括：

- 第一次请求；
- 每次读取；
- 失败后的等待；
- 后续重试。

程序会在尝试、响应块和退避边界检查预算。如果下一次等待必然导致超时，就不会继续 sleep 和重试。

### 当前边界

同步流在等待网络返回 chunk 时，应用代码无法主动执行检查，因此真正阻止单次读取长期阻塞的是 `read_timeout_seconds`；应用层总等待限制负责控制完整调用流程。这两个限制需要一起使用。

---

## 5. 为什么关闭 SDK 自动重试

OpenAI Python SDK 默认会自动重试部分连接错误、超时、限流和服务端错误。

Day 04 创建客户端时显式设置：

```python
max_retries=0
```

原因不是 SDK 重试不好，而是本项目需要自己掌握：

- 到底尝试了几次；
- 每次等待多久；
- 是否超过总等待预算；
- 是否已经向用户展示文本；
- 日志中的 attempt 是否准确。

如果 SDK 重试 2 次，应用又重试 2 次，最坏情况下实际请求次数会变得难以理解。关闭 SDK 自动重试后，项目只有一层明确的重试策略。

---

## 6. 哪些错误适合重试

### 可以重试

| 错误 | 原因 |
|---|---|
| `APITimeoutError` | 服务可能只是暂时响应较慢 |
| `APIConnectionError` | 网络可能短暂波动 |
| `RateLimitError` | 限流窗口可能很快恢复 |
| HTTP 408 / 409 / 429 | 常见临时状态 |
| HTTP 500 / 502 / 503 / 504 | 服务端可能暂时不可用 |

### 不应该自动重试

| 错误 | 原因 |
|---|---|
| `AuthenticationError` | API Key 错误不会因重试恢复 |
| `BadRequestError` | 参数、消息或 Token 限制需要修改 |
| HTTP 400 / 401 / 403 / 404 / 422 | 多数属于请求、权限或资源问题 |
| 其他未知 SDK 错误 | 默认保守处理，避免重复请求 |

项目的 `ModelCallError` 增加了 `retryable` 属性，让重试循环不需要了解所有 SDK 异常类型。

---

## 7. 指数退避

程序使用以下计算：

```python
base_seconds * (2 ** retry_index)
```

当基础时间为 1 秒时：

```text
第一次重试前等待 1 秒
第二次重试前等待 2 秒
第三次重试前等待 4 秒
```

这样可以避免服务异常时立刻连续发送大量请求。

Day 04 暂时没有加入随机抖动 jitter，是为了保持实现和测试清晰。生产系统中通常会加入 jitter，避免大量客户端同时重试。

---

## 8. 为什么流式输出后不能盲目重试

假设第一轮请求已经向终端输出：

```text
Python 是一种
```

随后网络中断。如果程序从头重试，第二轮又输出：

```text
Python 是一种高级编程语言……
```

用户最终可能看到：

```text
Python 是一种Python 是一种高级编程语言……
```

更严重时，两次回答可能采用不同思路，造成内容矛盾。

Day 04 的规则是：

```text
只要当前请求已经产生过任何非空文本，之后的错误就不再自动重试。
```

此时程序抛出 `ModelCallPartialOutputError`，提示：

```text
响应已中断：模型已经输出部分内容，本次不会自动重试。
```

CLI 会回滚本轮 user message，也不会把不完整的 assistant 回答写入历史。已经打印到终端的文字无法撤回，这是流式界面的现实边界。

---

## 9. 三个具名结果对象

### 9.1 `TokenUsage`

```python
@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
```

项目不再把 SDK 的 usage 对象直接传到 CLI，而是转换为自己的稳定数据结构。

### 9.2 `ModelCallResult`

```python
@dataclass(frozen=True)
class ModelCallResult:
    request_id: str
    conversation_id: str
    answer: str
    usage: TokenUsage | None
    elapsed_seconds: float
```

它完整描述一次成功调用。兼容服务没有返回 usage 时，`usage` 为 `None`，回答仍然可以成功返回。

### 9.3 `StreamEvent`

```python
@dataclass(frozen=True)
class StreamEvent:
    request_id: str
    conversation_id: str
    text: str = ""
    result: ModelCallResult | None = None
```

普通事件携带增量文本：

```text
StreamEvent(text="你")
StreamEvent(text="好")
```

最后一个事件携带完整结果：

```text
StreamEvent(result=ModelCallResult(answer="你好", ...))
```

这使同一个 API 同时满足：

1. CLI 需要实时打印；
2. 调用结束后需要完整回答、Token 和耗时；
3. 后续 FastAPI 可以把事件转换为 SSE，把最终结果记录到日志或数据库。

---

## 10. request ID 与 conversation ID

### conversation ID

程序启动时生成一次：

```text
同一个 CLI 会话中的多轮问题共享同一个 conversation ID
```

输入 `clear` 只清空消息历史，不会创建新的 CLI 进程，因此 conversation ID 保持不变。

### request ID

每次模型调用生成一次：

```text
第一轮问题 → request A
第二轮问题 → request B
```

它们属于同一个 conversation，但代表两次独立模型请求。

日志中同时记录两个 ID，之后就能回答：

- 这条错误属于哪一次模型请求？
- 这几次请求是否来自同一个会话？
- 某一轮请求等待了多久、重试了几次？

这些 ID 只用于应用关联，不会被塞进模型消息，因此不会额外消耗 Token。

---

## 11. CLI 如何变薄

Day 03 的 CLI 自己维护：

```text
started_at
response_parts
usage
```

Day 04 后，CLI 只做：

1. 读取用户输入；
2. 把 user 消息加入历史；
3. 遍历 `stream_model_response()`；
4. 收到 `event.text` 就立即打印；
5. 收到 `event.result` 后追加完整 assistant 回答；
6. 使用 `print_call_result()` 展示统计；
7. 失败时回滚本轮 user 消息。

模型调用的内部可靠性不会泄漏到 UI 层。这就是为后续 FastAPI 做准备：未来新增 HTTP 入口时，不需要复制重试和结果拼装逻辑。

---

## 12. 当前完整数据流

```text
程序启动
→ load_dotenv()
→ validate_model_config()
→ 创建 conversation_id
→ 用户输入问题
→ append_message(user)
→ stream_model_response()
    → 创建 request_id
    → 记录 started_at
    → call_model()
        → httpx.Timeout(connect/read/write/pool)
        → OpenAI(max_retries=0)
        → chat.completions.create(stream=True)
    → 收到文本 chunk
        → 检查总时间预算
        → 产生 StreamEvent(text=...)
        → CLI 实时打印
    → 收到 usage chunk
        → 转换为 TokenUsage
    → 临时错误且尚未输出
        → 检查次数和总预算
        → 指数退避
        → 重新创建请求
    → 已经输出后失败
        → ModelCallPartialOutputError
        → 不重试
    → 正常结束
        → ModelCallResult
        → 最终 StreamEvent(result=...)
→ append_message(assistant)
→ 打印 request ID、耗时、Token 和历史长度
```

---

## 13. 测试策略与结果

Day 04 延续纯单元测试优先，不访问真实网络，不真实 sleep。

新增或加强的测试覆盖：

- 配置覆盖和默认值；
- 非法整数、浮点数、非有限数字和范围；
- timeout 与 `max_retries=0` 传入客户端；
- 配置化 `max_tokens`；
- usage 提取与 usage 缺失；
- HTTP 状态码分类；
- 指数退避序列；
- 文本事件和最终结果；
- 临时错误重试成功；
- 永久错误不重试；
- 重试次数耗尽；
- 部分输出后绝不重试；
- 退避会超过总预算时停止；
- 首个 chunk 到达时已经超出预算，不向用户输出；
- 流结束时总耗时越界，不把迟到结果标记为成功；
- CLI 结果统计展示。

最终结果：

```text
59 passed
```

---

## 14. 语法与真实运行验证

### 14.1 Python 语法检查

执行：

```bash
uv run python -m py_compile \
  src/main.py \
  src/config.py \
  src/conversation.py \
  src/llm_client.py
```

结果：通过，无语法错误。

### 14.2 CLI 启动和退出

执行：

```bash
printf 'exit\n' | uv run python -m src.main
```

结果：

- 配置成功加载；
- 打印 conversation ID 和 Day 04 新配置；
- 输入 `exit` 后正常退出。

### 14.3 真实两轮模型调用

真实调用模型：`gpt-5.4`。

第一轮：

```text
Explain connect timeout in one short sentence.
```

模型成功流式返回，耗时约 3.51 秒，并返回 Token usage。

第二轮：

```text
What timeout did I ask about?
```

模型回答 `connect timeout`，说明历史上下文仍然有效。

验证到：

- 两轮 conversation ID 相同；
- 两轮 request ID 不同；
- 两轮均实时输出；
- 两轮均显示耗时和 Token；
- 历史消息数从 2 增长到 4；
- 无 traceback。

Windows Git Bash 的重定向输出出现中文终端编码乱码，但 Python 程序、网络请求与数据结果均正常；交互终端中不影响源码的 UTF-8 内容。

---

## 15. 当前仍需注意的边界

1. **总等待时间不是独立线程计时器**
   - 同步代码等待 chunk 时依赖 read timeout 打断；总预算在代码重新获得控制权后检查。

2. **流式部分文本无法从终端撤回**
   - 程序能够保证不把不完整回答加入历史，也不会盲目重试，但无法删除已经打印的字符。

3. **暂时没有 jitter**
   - 当前退避是确定性的，适合学习和测试；大规模生产服务通常加入随机抖动。

4. **仍然是同步 CLI**
   - 尚未学习 async、FastAPI 或 SSE。本日只建立了后续可复用的调用边界。

5. **尚未裁剪历史**
   - 多轮会话持续增长后，仍可能超过上下文窗口。这属于后续上下文工程任务。

6. **重试只能提高临时故障恢复能力**
   - 它不能修复错误 API Key、错误模型名称、非法参数或低质量回答。

---

## 16. 推荐源码学习顺序

既然更适合通过源码学习，建议按以下顺序阅读：

### 第一步：`src/config.py`

重点看：

- dataclass 默认值；
- `_read_int_config()`；
- `_read_float_config()`；
- 环境变量如何进入 `ModelConfig`。

### 第二步：`src/llm_client.py`

建议分五段看：

1. 异常类和三个 dataclass；
2. `call_model()` 如何配置 timeout 并关闭 SDK 重试；
3. 文本与 Token 提取函数；
4. 状态码和退避纯函数；
5. `stream_model_response()` 的 while/try/except 重试循环。

### 第三步：`src/main.py`

重点看 CLI 如何只消费两种事件：

- `event.text`；
- `event.result`。

并观察成功和失败时会话历史分别如何处理。

### 第四步：`tests/test_main.py`

优先阅读以下测试主题：

- 重试前成功；
- 不可重试错误；
- 重试耗尽；
- 部分输出中断；
- 总时间预算；
- 完整结果对象。

测试通常比实现更容易说明“代码应该做什么”。

### 第五步：回到本笔记

对照源码复盘每个概念，尝试用自己的话解释：

- 为什么关闭 SDK 重试？
- 为什么文本输出后不重试？
- connect/read/total timeout 有何区别？
- StreamEvent 与 ModelCallResult 为什么不能简单合并？

---

## 17. 今日知识验收

完成源码阅读后，尝试回答：

1. `max_retries=2` 最多会请求几次？
2. 为什么连接超时和读取超时不能只用一个概念解释？
3. 为什么应用层还需要 total timeout？
4. `retryable=True` 是 SDK 提供的还是项目自己的抽象？
5. 为什么已经输出文本后，即使是连接错误也不重试？
6. 为什么 SDK 的 usage 要转换成 `TokenUsage`？
7. 普通 `StreamEvent` 和最终 `StreamEvent` 分别携带什么？
8. request ID 与 conversation ID 的生命周期分别是什么？
9. 为什么测试要注入 `sleep` 和 `now`？
10. CLI 清空历史后，conversation ID 是否变化？为什么？

---

## 18. Day 05 建议

Day 05 可以进入 FastAPI 基础服务层，但建议仍保持小步前进：

```text
FastAPI 请求模型、依赖注入与健康检查
```

候选内容：

1. 增加 `/health` 健康检查；
2. 增加非流式 `/chat` 请求模型；
3. 使用 Pydantic 定义请求和响应结构；
4. 将 `ModelCallResult` 转换为 HTTP 响应；
5. 通过依赖注入提供配置和模型服务；
6. 使用 TestClient 编写接口测试；
7. 暂不急着实现 SSE，先把普通 HTTP 边界做稳。

---

## 19. 今日一句话总结

> Day 04 我将模型生成长度、三类超时和重试策略集中到只读配置对象，关闭 SDK 隐式重试并实现可测试的有限指数退避，通过流式事件保持实时输出，同时用具名结果统一回答、Token、耗时和关联 ID，并明确保证模型已经输出部分文本后绝不盲目重试；最终 59 个测试、语法检查、CLI 启停和真实两轮模型验证全部通过。

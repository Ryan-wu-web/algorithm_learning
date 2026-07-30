# Day 02：用测试守住模型调用，并实现多轮对话

## 1. 今日目标与完成情况

Day 01 完成了第一次真实模型调用，Day 02 在此基础上完成两项升级：

1. 使用 pytest 验证输入、配置、响应提取和会话操作等确定性逻辑；
2. 将单次问答程序升级为支持历史消息、退出和清空操作的多轮命令行助手。

今日最终完成情况：

- [x] 理解 pytest 基础输出；
- [x] 理解 Arrange、Act、Assert 测试结构；
- [x] 理解 `pytest.raises()` 如何验证异常；
- [x] 理解 `monkeypatch` 如何隔离环境变量；
- [x] 区分空候选列表与空回答内容；
- [x] 补充配置、消息和命令判断的边界测试；
- [x] 实现多轮对话历史；
- [x] 支持退出与清空历史命令；
- [x] 模型调用失败时回滚本轮 User 消息；
- [x] 显示每轮耗时、Token 用量和历史消息数；
- [x] 完成“蓝鲸代号”真实多轮实验；
- [x] 全部 21 个 pytest 用例通过；
- [x] Python 语法检查通过。

今日没有引入 FastAPI、数据库、RAG、Agent 或第三方工作流框架。重点仍然是理解最小机制，并为后续工程化打基础。

---

## 2. Day 01 到 Day 02 的变化

### Day 01

```text
输入一个问题
→ 调用一次模型
→ 输出回答、耗时和 Token
→ 程序结束
```

### Day 02

```text
启动程序
→ 创建会话历史列表
→ 用户输入问题
→ 保存 User 消息
→ 携带完整历史调用模型
→ 保存 Assistant 消息
→ 输出回答、耗时、Token 和历史消息数
→ 继续等待输入
→ 用户主动退出
```

程序已经从“单次模型调用 Demo”升级为一个具备基础状态管理的命令行聊天程序。

---

## 3. 今日测试结果

### 3.1 运行测试

在 PowerShell 中执行：

```powershell
uv run pytest -q
```

最终结果：

```text
.....................                                                    [100%]
21 passed in 1.32s
```

每一个 `.` 表示一个测试用例通过，`[100%]` 表示所有收集到的测试均已执行。

常见 pytest 标记：

```text
.  测试通过
F  断言失败
E  测试收集或执行时发生错误
```

### 3.2 语法检查

运行：

```powershell
uv run python -m py_compile src/main.py
```

命令没有输出，表示 `src/main.py` 通过 Python 语法检查。

### 3.3 PowerShell 与 Claude Code 命令区别

学习过程中曾在 PowerShell 中输入：

```powershell
! uv run pytest -q
```

PowerShell 将 `!` 当作运算符，因此出现语法错误。正确方式是：

```text
PowerShell 终端：uv run pytest -q
Claude Code 输入框：! uv run pytest -q
```

`!` 是 Claude Code 输入框中执行 Shell 命令的前缀，不是 PowerShell 命令的一部分。

---

## 4. Arrange、Act、Assert

一个单元测试可以按三个阶段理解：

```python
def test_normalize_question_removes_surrounding_whitespace() -> None:
    # Arrange：准备输入和测试环境
    raw_question = "  什么是 Token？  "

    # Act：执行被测试的行为
    result = normalize_question(raw_question)

    # Assert：比较实际结果与预期结果
    assert result == "什么是 Token？"
```

三个问题分别是：

```text
Arrange：测试需要什么输入和条件？
Act：调用了哪个函数或执行了哪个行为？
Assert：实际结果是否符合预期？
```

简单测试可以写在一行中；当输入、模拟对象和断言变多时，三段式结构更容易阅读和排查。

---

## 5. 使用 pytest 测试异常

输入只有空白字符时，`normalize_question()` 不会正常返回，而会抛出：

```python
raise ValueError("问题不能为空")
```

对应测试：

```python
with pytest.raises(ValueError, match="问题不能为空"):
    normalize_question("   ")
```

它同时验证：

1. 异常类型是 `ValueError`；
2. 异常消息匹配“问题不能为空”。

以下情况都会导致测试失败：

```python
# 没有抛异常
return ""

# 抛出的异常类型不同
raise TypeError("问题不能为空")

# 类型正确，但消息不匹配
raise ValueError("输入不能为空")
```

因此，异常也是函数对调用方公开的一部分行为，需要被测试保护。

---

## 6. 使用 monkeypatch 测试环境变量

配置函数通过环境变量读取：

```python
api_key = os.getenv("OPENAI_API_KEY", "").strip()
base_url = os.getenv("OPENAI_BASE_URL", "").strip()
model = os.getenv("OPENAI_MODEL", "").strip()
```

测试中不应该依赖本机真实 `.env`，也不应该使用真实 API Key。因此使用 pytest 提供的 `monkeypatch`：

```python
monkeypatch.setenv("OPENAI_API_KEY", " test-key ")
monkeypatch.setenv("OPENAI_BASE_URL", " https://example.com/v1 ")
monkeypatch.setenv("OPENAI_MODEL", " test-model ")
```

也可以临时删除变量：

```python
monkeypatch.delenv("OPENAI_API_KEY", raising=False)
```

`monkeypatch` 的作用：

```text
测试开始
→ 临时设置或删除环境变量
→ 执行测试
→ 测试结束后自动恢复环境
```

这样可以避免：

- 依赖开发者机器的真实配置；
- 在测试中暴露真实密钥；
- 不同测试相互污染；
- 测试在另一台机器上无法复现。

### 纯空格配置

环境变量存在不代表值有效：

```python
monkeypatch.setenv("OPENAI_API_KEY", "   ")
```

经过：

```python
"   ".strip() == ""
```

所以纯空格仍然应被视为缺失配置。新增测试验证了这一边界。

---

## 7. 使用假对象测试响应提取

模型响应文本位于：

```python
response.choices[0].message.content
```

测试响应提取逻辑时不需要真的调用模型，只需要创建一个具有相同属性形状的轻量对象：

```python
response = SimpleNamespace(
    choices=[
        SimpleNamespace(
            message=SimpleNamespace(content="这是模型回答。"),
        )
    ]
)
```

这类测试具有以下优点：

- 不访问网络；
- 不需要 API Key；
- 不产生模型费用；
- 执行速度快；
- 输入和结果稳定；
- 可以精确构造边界情况。

---

## 8. 空列表与空回答内容的区别

当前响应提取函数：

```python
def extract_response_text(response: openai.types.chat.ChatCompletion) -> str:
    if not response.choices:
        return ""

    return response.choices[0].message.content or ""
```

它需要处理两种不同的“没有回答”。

### 8.1 `choices=[]`

```python
response.choices = []
```

含义是：

```text
候选回答列表存在
但列表中没有第一条候选回答
```

此时直接访问：

```python
response.choices[0]
```

会抛出：

```text
IndexError: list index out of range
```

所以必须先判断：

```python
if not response.choices:
    return ""
```

### 8.2 `content=None`

```python
response.choices = [
    SimpleNamespace(
        message=SimpleNamespace(content=None),
    )
]
```

含义是：

```text
第一条候选回答存在
message 存在
content 属性存在
但 content 的值是 None，没有实际文本
```

此时：

```python
response.choices[0].message.content or ""
```

相当于：

```python
None or ""
```

最终得到空字符串。

可以用以下类比记忆：

```text
choices=[]       → 柜子不存在
content=None     → 柜子存在，但里面没有东西
```

---

## 9. 单元测试与真实模型实验的边界

### 单元测试

适合验证确定性逻辑：

- 输入清理；
- 配置校验；
- 消息构造；
- 响应文本提取；
- 会话历史追加；
- 退出和清空命令判断。

特点：

```text
不访问网络
执行快
结果稳定
不产生模型费用
```

### 真实 API 集成验证

用于验证：

```text
本地程序
→ OpenAI SDK
→ New API 中转站
→ 上游模型
```

它会受到以下因素影响：

- 网络状态；
- API Key；
- 中转站与上游服务；
- 模型额度和限流；
- 模型输出的非确定性。

不应该在默认单元测试中断言固定模型文本，例如：

```python
# 不稳定，不推荐
assert model_answer == "你的代号是蓝鲸。"
```

模型也可能回答：

```text
你之前设置的代号是“蓝鲸”。
```

两者语义相同，但字符串不同。

今日形成的边界认识：

```text
pytest：验证自己的确定性代码
真实调用：验证程序与外部模型服务能否协作
```

---

## 10. 模型 API 的无状态特征

普通 Chat Completions 请求通常不会自动继承上一次独立请求的内容。

第一次请求：

```python
[
    {"role": "system", "content": "你是一名学习助手。"},
    {"role": "user", "content": "我的代号是蓝鲸。"},
]
```

如果第二次只发送：

```python
[
    {"role": "system", "content": "你是一名学习助手。"},
    {"role": "user", "content": "我的代号是什么？"},
]
```

第二次请求里不存在“蓝鲸”这个信息，模型通常无法知道答案。

要实现多轮上下文，应用需要重新发送历史：

```python
[
    {"role": "system", "content": "你是一名学习助手。"},
    {"role": "user", "content": "我的代号是蓝鲸。"},
    {"role": "assistant", "content": "已记住。"},
    {"role": "user", "content": "我的代号是什么？"},
]
```

因此当前程序中的“记忆”实际是：

```text
Python 列表保存 User / Assistant 历史
→ 每次请求重新发送完整历史
→ 模型根据收到的上下文回答
```

模型能力与应用会话存储是两个不同概念。

---

## 11. 多轮消息的数据结构

程序在循环外创建历史列表：

```python
messages: list[dict[str, str]] = []
```

一条消息用字典表示：

```python
{
    "role": "user",
    "content": "我的代号是蓝鲸。",
}
```

多条消息按时间顺序保存在列表中：

```python
[
    {"role": "user", "content": "我的代号是蓝鲸。"},
    {"role": "assistant", "content": "已记住。"},
    {"role": "user", "content": "我的代号是什么？"},
]
```

消息顺序必须反映真实对话过程：

```text
User 1 → Assistant 1 → User 2 → Assistant 2
```

消息内容相同但顺序错误，模型理解到的对话含义也可能不同。

---

## 12. append_message() 与 Python 可变列表

新增函数：

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

调用：

```python
append_message(messages, "user", question)
```

会直接修改传入的原列表，因此函数返回类型为：

```python
-> None
```

它不需要返回一个新列表。

测试还验证了两个独立列表互不影响：

```python
conversation_a = []
conversation_b = []
```

只修改 A 时，B 仍然为空。这是未来多用户会话隔离的最小基础：不同会话不能共享同一个全局历史列表。

---

## 13. 多轮循环与控制语句

程序核心循环：

```python
while True:
    raw_question = input("\n你：")
    ...
```

今日进一步理解了三个控制语句：

```text
continue → 跳过当前一轮，开始下一轮
break    → 结束当前循环
return   → 结束整个函数
```

### 空白输入

```python
try:
    question = normalize_question(raw_question)
except ValueError as exc:
    print(f"\n输入错误：{exc}")
    continue
```

空白输入只会跳过当前轮次，不会结束整个聊天程序。

### 退出命令

```python
def is_exit_command(text: str) -> bool:
    return text.strip().lower() in {"exit", "quit", "退出"}
```

支持：

```text
exit
quit
退出
 EXIT 
QUIT
```

命令被识别后：

```python
break
```

结束对话循环。

### 清空命令

```python
def is_clear_command(text: str) -> bool:
    return text.strip().lower() in {"clear", "清空"}
```

命令被识别后：

```python
messages.clear()
continue
```

程序保留运行，但旧会话历史被删除。

---

## 14. System Prompt 与历史消息的边界

历史列表只保存 User 和 Assistant 消息：

```python
messages = [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好！"},
]
```

每次真正调用模型前，再组合 System Prompt：

```python
request_messages = [
    {
        "role": "system",
        "content": system_prompt,
    },
    *messages,
]
```

其中：

```python
*messages
```

表示把历史列表中的每一项展开到新列表中。

最终请求类似：

```python
[
    {"role": "system", "content": "你是一名大模型应用开发学习助手……"},
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好！"},
]
```

没有把 System Prompt 每轮追加到历史，是为了避免：

- System 消息重复；
- 无意义占用 Token；
- 请求结构混乱；
- 多条重复规则产生潜在冲突。

---

## 15. 模型调用失败与状态回滚

每轮执行顺序是：

```text
保存 User 消息
→ 调用模型
→ 保存 Assistant 消息
```

如果模型调用失败，历史会暂时出现：

```text
上一轮 User
上一轮 Assistant
本轮 User
没有本轮 Assistant
```

今日采用的规则是：调用失败时删除刚加入的 User 消息。

```python
except openai.APIConnectionError:
    messages.pop()
    print("\n连接失败：请检查网络连接或 OPENAI_BASE_URL 是否正确。")
    continue
```

`messages.pop()` 默认删除并返回列表最后一项，因此会移除本轮刚加入的 User 消息。

相同处理用于：

- `AuthenticationError`；
- `RateLimitError`；
- `APIConnectionError`；
- `APIStatusError`。

这使历史保持为完整轮次：

```text
User → Assistant
User → Assistant
```

而不是无意识地留下半轮状态。这是今天接触到的第一个状态一致性问题。

---

## 16. 多轮历史与 Token 增长

每次调用都重新发送之前的消息，所以输入内容会逐轮增长：

```text
第 1 轮 = System + User 1
第 2 轮 = System + User 1 + Assistant 1 + User 2
第 3 轮 = System + 前两轮历史 + User 3
```

因此历史增长通常会导致：

- 输入 Token 增加；
- 上下文窗口占用增加；
- 调用费用增加；
- 请求延迟可能增加；
- 早期信息可能逐渐受到更多上下文干扰。

当前程序每轮还会显示：

```python
print(f"当前历史消息数：{len(messages)}")
```

正常情况下：

```text
第一轮完成：2 条消息
第二轮完成：4 条消息
第三轮完成：6 条消息
```

System Prompt 没有保存在 `messages` 中，因此不计入这里的数量。

历史裁剪、摘要和 Token 预算将在后续学习中实现。

---

## 17. 参数化测试

退出和清空命令有多组相似输入，因此使用：

```python
@pytest.mark.parametrize("command", ["exit", " EXIT ", "quit", "QUIT", "退出"])
def test_is_exit_command_accepts_supported_commands(command: str) -> None:
    assert is_exit_command(command) is True
```

pytest 会为列表中的每个参数分别执行一次测试。

优点：

- 减少重复测试代码；
- 容易新增边界输入；
- 每组参数仍作为独立测试统计；
- 失败时可以看出是哪一组输入出错。

这也是测试数量从 7 增加到 21 的原因之一，并不代表手写了 21 个完全独立的测试函数。

---

## 18. 今日测试覆盖内容

`tests/test_main.py` 当前覆盖：

### 输入处理

- [x] 删除问题两侧空白；
- [x] 拒绝纯空白问题；
- [x] 异常类型和消息正确。

### 配置处理

- [x] 读取并清理三个环境变量；
- [x] 一次报告多个缺失配置；
- [x] 纯空格配置被视为缺失；
- [x] 测试不依赖真实 `.env`。

### 响应提取

- [x] 提取第一条候选回答；
- [x] `choices=[]` 时返回空字符串；
- [x] `content=None` 时返回空字符串。

### 消息与会话

- [x] `build_messages()` 构造 User 消息；
- [x] `append_message()` 保持对话顺序；
- [x] 两个独立会话互不影响。

### 命令判断

- [x] 识别 `exit`、`quit`、`退出`；
- [x] 兼容英文大小写和两侧空格；
- [x] 普通问题不会被误判为退出；
- [x] 识别 `clear`、`清空`；
- [x] 普通问题不会被误判为清空。

尚未自动测试的部分：

- `main()` 的完整交互循环；
- 真实网络请求；
- 各类 OpenAI SDK 异常发生时的完整输出；
- 真实 Token 数值和模型回答质量。

这些内容当前通过手动运行和真实模型实验验证，后续模块拆分后再通过依赖注入提高可测试性。

---

## 19. “蓝鲸代号”真实多轮实验

### 实验步骤

启动程序：

```powershell
uv run python src/main.py
```

第一轮输入：

```text
请记住：我的代号是蓝鲸。只回复“已记住”。
```

第二轮输入：

```text
我的代号是什么？
```

随后输入：

```text
clear
```

再次询问：

```text
我的代号是什么？
```

最后输入：

```text
exit
```

### 实验结果

- [x] 携带历史时，第二轮能够根据第一轮信息回答代号；
- [x] 第二轮请求包含第一轮 User 和 Assistant 消息；
- [x] 观察到历史增加后输入 Token 随之变化；
- [x] 输入 `clear` 后，旧历史被清空；
- [x] 清空后，模型不再拥有之前对话中的代号信息；
- [x] 输入 `exit` 后程序正常结束；
- [x] 整体结果符合预期。

本次学习没有在笔记中保存具体 Token 数值和完整 Base URL，避免记录不必要的环境信息。后续实验应在运行时单独记录可比较的 Token、耗时和模型版本。

### 实验结论

```text
携带历史时，应用把之前的 User 和 Assistant 消息重新发送给模型，
所以模型能够根据上下文回答。
清空历史后，新请求不再包含代号信息，模型通常无法知道答案。
因此当前程序的“记忆”来自应用对历史的保存和传递，而不是模型自动永久记住。
```

---

## 20. 今日遇到并解决的问题

### 问题 1：Assert 不只是预期值

最初把 Assert 理解为：

```python
"什么是 Token？"
```

更准确的理解是：

```python
assert result == "什么是 Token？"
```

即比较实际结果与预期结果，而预期字符串只是 Assert 的一部分。

### 问题 2：不理解 `pytest.raises(..., match=...)`

最终理解：

```text
pytest.raises(ValueError) → 检查异常类型
match="问题不能为空"      → 检查异常消息
```

### 问题 3：混淆空候选列表和空内容

最终区分：

```text
choices=[]   → 第一条候选回答不存在，访问 [0] 会越界
content=None → 第一条候选回答存在，但没有文本值
```

### 问题 4：在 PowerShell 中使用 `!`

原因是混淆了 Claude Code 输入框和 PowerShell 终端的命令格式。

正确方式：

```text
PowerShell：uv run pytest -q
Claude Code：! uv run pytest -q
```

### 问题 5：Day 02 测试内容较多

最终明确测试不是学习终点，而是为了保护多轮对话中的确定性状态逻辑。真正的功能增量是：

- 多轮循环；
- 历史保存；
- 清空和退出命令；
- 调用失败后的状态回滚；
- Token 与历史增长观察。

---

## 21. 今日纠正的认识

### 纠正 1：模型不会自动继承所有历史

普通 API 请求通常是独立的。应用必须主动保存并重新发送历史。

### 纠正 2：模型的“记忆”不等于永久记忆

当前程序中的记忆只是 Python 进程内的一份列表。程序退出或清空列表后，历史就不存在了。

### 纠正 3：列表存在不代表第一项存在

```python
choices = []
```

列表对象存在，但没有索引 `0`。

### 纠正 4：候选项存在不代表有文本

```python
choices[0].message.content = None
```

候选项存在，但文本值为空。

### 纠正 5：真实模型回答不适合固定字符串断言

模型输出具有非确定性。单元测试应优先验证消息结构、状态变化和响应提取等确定性逻辑。

### 纠正 6：外部调用失败也会影响本地状态

如果先修改会话历史再调用模型，调用失败后必须明确决定保留、重试或回滚，不能忽略半完成状态。

---

## 22. 今日核心代码流程

```text
加载 .env
→ 校验 API Key、Base URL 和模型名
→ 创建 System Prompt
→ 在循环外创建 messages 历史列表
→ 等待用户输入
    ├─ exit / quit / 退出 → break，结束循环
    ├─ clear / 清空      → messages.clear()，继续循环
    ├─ 空白输入           → 显示错误，continue
    └─ 普通问题
         → 追加 User 消息
         → 组合 System Prompt + 完整历史
         → 调用模型
             ├─ 失败 → pop() 回滚 User 消息，continue
             └─ 成功
                  → 提取回答
                  → 追加 Assistant 消息
                  → 输出回答、耗时和 Token
                  → 输出历史消息数
                  → 等待下一轮
```

---

## 23. 今日成果

### 代码成果

- `src/main.py`
  - 新增 `append_message()`；
  - 新增 `is_exit_command()`；
  - 新增 `is_clear_command()`；
  - 单次问答改为多轮循环；
  - 保存 User / Assistant 历史；
  - 支持退出与清空；
  - 空白输入后继续运行；
  - API 失败后回滚本轮消息；
  - 输出历史消息数量。

- `tests/test_main.py`
  - 增加 `content=None` 测试；
  - 增加纯空格配置测试；
  - 增加消息构造测试；
  - 增加对话顺序测试；
  - 增加会话隔离测试；
  - 增加退出命令参数化测试；
  - 增加清空命令参数化测试。

### 验证成果

- [x] `21 passed`；
- [x] Python 语法检查通过；
- [x] 多轮真实模型实验通过；
- [x] 清空历史对照实验通过；
- [x] 未在代码或测试中暴露真实 API Key。

---

## 24. 今日知识验收

完成 Day 02 后，我已经能够解释：

1. Arrange、Act、Assert 分别表示什么；
2. `pytest.raises()` 如何验证异常类型和消息；
3. `monkeypatch` 为什么适合测试环境变量；
4. 为什么单元测试不应默认调用真实模型；
5. `choices=[]` 与 `content=None` 的区别；
6. 为什么模型第二轮需要重新接收第一轮历史；
7. 为什么 User 和 Assistant 消息都需要保存；
8. 为什么消息顺序不能打乱；
9. 为什么多轮历史通常会增加输入 Token；
10. `continue`、`break` 和 `return` 的区别；
11. 为什么消息列表要在循环外创建；
12. 为什么 System Prompt 不应每轮重复追加到历史；
13. 为什么外部调用失败后可能需要回滚本地状态。

---

## 25. 仍需巩固与后续改进

- [ ] 更熟练地独立编写 pytest 测试；
- [ ] 更熟练地使用 `monkeypatch`；
- [ ] 理解并测试 `main()` 的交互流程；
- [ ] 减少 `main()` 中重复的异常回滚和输出代码；
- [ ] 为 `call_model()` 注入假客户端，验证请求消息结构；
- [ ] 将配置、模型调用、会话逻辑和 CLI 交互拆分到不同模块；
- [ ] 使用日志替代部分 `print()`；
- [ ] 后续实现历史裁剪、摘要和 Token 预算；
- [ ] 将进程内会话扩展为可持久化、可隔离的会话存储。

---

## 26. Day 03 预告

Day 03 建议继续第一阶段的 Python 工程基础，主题为：

```text
配置、异常、日志与模块拆分
```

计划内容：

1. 将配置读取从 `main.py` 拆分到独立模块；
2. 将模型调用与命令行交互分离；
3. 定义更清晰的错误边界；
4. 使用 `logging` 记录运行信息；
5. 通过依赖注入为模型调用提供假客户端；
6. 测试最终发送给 SDK 的 System 和历史消息；
7. 为后续 FastAPI 聊天网关形成可复用服务层。

---

## 27. 今日一句话总结

> Day 02 我用 pytest 为输入、配置、响应和会话状态建立了 21 个测试，并将单次模型调用升级为支持历史保存、清空、退出和失败回滚的多轮命令行助手；通过真实实验确认，当前对话“记忆”来自应用保存并重新发送 User 与 Assistant 历史消息。

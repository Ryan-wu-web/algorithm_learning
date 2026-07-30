# Day 01：大模型应用开发起步

## 1. 今日目标

今天的目标不是学习复杂的 RAG、Agent 或 Transformer 原理，而是完成第一个可验证的大模型应用闭环：

```text
准备 Python 工程环境
→ 理解模型消息角色
→ 构造请求数据
→ 安全读取模型配置
→ 通过 SDK 调用真实模型
→ 提取回答
→ 观察耗时和 Token 用量
```

完成今天的学习后，我应当能够：

- 解释一次大模型 API 调用的基本过程。
- 区分 System、User、Assistant 和 Tool 消息。
- 使用 Python 的函数、类型标注、列表、字典和异常处理。
- 使用 `.env` 安全管理 API 配置。
- 通过 OpenAI Python SDK 调用 OpenAI 兼容接口。
- 从响应对象中提取模型回答和 Token 用量。

---

## 2. 我的技术背景

- 前端技术：Vue、React、HTML、CSS、JavaScript、TypeScript 等。
- 后端技术：Node.js、Java、Go、Python。
- 数据库：MySQL、MyBatis-Plus。
- 部署与运维：阿里云。
- Python 熟练度（0～10 分）：2。
- 其他相关经验：目前主要以 Vibe Coding 为主，对各技术栈还没有形成清晰、系统的认识。

### 我的转型目标

完成学习路线后，我希望能够：

1. 对大模型形成清晰、系统的认知。
2. 独立完成大模型应用、RAG 和 Agent 工作流。
3. 自己尝试 LoRA / QLoRA 等模型微调。
4. 理解模型训练和推理部署的主要流程。

目前感兴趣的方向：

- [x] 大模型应用开发
- [x] RAG
- [x] Agent / 工作流
- [x] 模型微调
- [x] 本地模型部署
- [ ] 目前还不确定

### 学习前的理解

在正式学习前，我认为大模型应用开发主要是在做：

> 整理和清洗数据，通过 RAG 为模型提供外部知识，或者通过微调让模型适应特定领域。

这个理解包含 RAG 和微调，但还不完整。大模型应用开发也包括模型 API 接入、上下文管理、结构化输出、工具调用、评测、安全、监控和部署等工程工作。

### 当前困惑

1. 不知道应该怎样系统学习，还没有清晰的学习路径。
2. 希望找到一种适合自己、能够长期坚持的学习方式。
3. 希望逐渐从依赖 Vibe Coding 转向真正理解和独立实现。

---

## 3. Python 开发环境

### 当前项目环境

- 操作系统：Windows 11
- IDE：PyCharm
- Python：3.12.13
- 环境与依赖管理：uv 0.11.32
- Git：2.50.1
- 项目虚拟环境：`D:\algorithm_learning\.venv`
- 项目解释器：`D:\algorithm_learning\.venv\Scripts\python.exe`

### 为什么每个项目需要独立虚拟环境

最初终端错误地激活了另一个项目的环境：

```text
D:\hermes-agent\.venv
```

如果直接在该环境中安装依赖，会导致两个项目相互影响。当前项目因此创建了自己的 `.venv`：

```text
algorithm_learning/
└─ .venv/
   ├─ Python 解释器
   └─ 当前项目独立安装的第三方包
```

### 使用 uv 创建环境

```powershell
uv python install 3.12
uv venv --python 3.12 .venv
```

验证结果：

```text
Python 3.12.13
D:\algorithm_learning\.venv\Scripts\python.exe
venv: True
```

### PyCharm 解释器问题

PyCharm 最初使用的是 `hermes-agent` 项目的 Python 3.13 环境，因此运行程序时显示了错误的 OpenAI SDK 版本。

修正后，PyCharm 使用：

```text
Python 3.12 (algorithm_learning)
D:\algorithm_learning\.venv\Scripts\python.exe
```

验证命令：

```powershell
uv run python -c "import sys, openai; print(sys.executable); print(openai.__version__)"
```

预期输出：

```text
D:\algorithm_learning\.venv\Scripts\python.exe
2.50.0
```

### pyproject.toml

项目通过 `pyproject.toml` 记录基本信息、Python 版本和正式依赖。它可以暂时类比为 Node.js 项目里的 `package.json`。

当前核心配置：

```toml
[project]
name = "llm-learning"
version = "0.1.0"
description = "全栈开发转大模型学习项目"
requires-python = ">=3.12,<3.13"
dependencies = [
  "openai>=2.50.0",
  "python-dotenv>=1.2.2",
]

[tool.uv]
package = false
```

`uv.lock` 用于锁定实际安装的依赖版本，便于在其他环境中重复安装。

---

## 4. 今天学习的 Python 基础

### 4.1 函数和类型标注

```python
def normalize_question(question: str) -> str:
    ...
```

含义：

- `question: str`：函数预期接收字符串。
- `-> str`：函数预期返回字符串。
- 类型标注主要服务于可读性、IDE 提示和静态检查，并不会默认像 Java 一样在运行时强制所有类型。

### 4.2 字符串不可变与 strip()

```python
question = question.strip()
```

`strip()` 删除字符串开头和结尾的空白字符，但不会直接修改原字符串，而是返回一个新字符串。

因此不能只写：

```python
question.strip()
```

必须接收返回值：

```python
question = question.strip()
```

纯空格输入经过处理后会变成空字符串：

```python
"   ".strip() == ""
```

### 4.3 抛出和捕获异常

```python
if not question:
    raise ValueError("问题不能为空")
```

- `raise`：主动抛出异常。
- `ValueError`：数据类型可能正确，但值不符合要求。

调用方通过 `try/except` 捕获：

```python
try:
    question = normalize_question(raw_question)
except ValueError as exc:
    print(f"输入错误：{exc}")
    return
```

- `except ValueError`：捕获指定类型的异常。
- `exc`：指向被捕获的异常对象。

### 4.4 dict 和 list

一条消息使用 Python 字典表示：

```python
{
    "role": "user",
    "content": "什么是 Token？",
}
```

对应关系：

```text
Python dict ≈ JavaScript object
Python list ≈ JavaScript Array
```

多条消息使用列表保存：

```python
[
    {"role": "user", "content": "我的名字叫小明。"},
    {"role": "assistant", "content": "你好，小明。"},
    {"role": "user", "content": "我叫什么名字？"},
]
```

需要记住：

```text
一个字典 = 一条消息
一个列表 = 按顺序排列的多条消息
```

### 4.5 程序入口

```python
if __name__ == "__main__":
    main()
```

- 直接运行该文件时执行 `main()`。
- 其他文件导入该模块时不会自动启动交互程序。

---

## 5. 大模型消息角色

### System

由应用开发者设置的高层行为约束，例如：

```text
你是一名大模型应用开发学习助手，请使用清晰、准确的语言回答问题。
```

主要定义模型的角色、任务边界和回答方式。

### User

用户提出的问题、要求或补充信息，例如：

```text
请解释 Python 中的列表和元组有什么区别。
```

即使用户说的是“以后回答时请使用 JavaScript 和 Python 对比”，它仍然属于 User，因为角色由消息来源决定，而不是由内容看起来像不像规则决定。

### Assistant

模型在之前轮次中生成的回答。多轮对话时，应用需要保存并重新发送历史 Assistant 消息。

### Tool

外部工具执行后返回的数据，例如天气 API、数据库查询或知识库检索结果。

### 判断角色的核心原则

```text
应用开发者设置的高层规则 → System
用户提出的问题或要求       → User
模型生成的回复             → Assistant
工具执行后返回的数据       → Tool
```

用户不能通过在普通输入里声明“我是 System”，把自己的 User 消息升级成真正的 System 消息。

---

## 6. 模型供应商与本地配置

### 调用方式

今天使用：

- OpenAI Python SDK
- 自建 New API 中转站
- OpenAI 兼容的 Chat Completions 接口
- 模型：`gpt-5.4`

调用链路：

```text
Python 程序
→ OpenAI Python SDK
→ 自建 New API 中转站
→ 上游 GPT 模型
→ 返回 OpenAI 兼容响应
```

### 安全管理配置

真实配置保存在项目根目录的 `.env` 中：

```dotenv
OPENAI_API_KEY=在本地填写
OPENAI_BASE_URL=在本地填写
OPENAI_MODEL=在本地填写
```

`.env` 已通过 `.gitignore` 排除，不应提交。

`.env.example` 只保存变量名称和示例，不保存真实密钥：

```dotenv
OPENAI_API_KEY=
OPENAI_BASE_URL=https://你的中转站域名/v1
OPENAI_MODEL=填写中转站支持的模型ID
```

禁止将真实 Key 直接写进代码：

```python
# 错误示例：不要这样做
client = OpenAI(api_key="真实 API Key")
```

程序只验证 Key 已加载，不打印内容：

```python
print(f"API Key：已加载（长度 {len(api_key)} 个字符，不显示内容）")
```

---

## 7. 第一次真实模型调用

### 测试问题

> 请你用 50 字以内解释，什么是上下文工程？

### System Prompt

> 你是一名大模型应用开发学习助手，请使用清晰、准确的语言回答问题。

### 模型回答

> 上下文工程：系统设计并组织提示、记忆、工具与状态，让模型在正确情境中稳定完成任务。

### 调用结果

- 接口类型：OpenAI 兼容接口
- SDK：OpenAI Python SDK
- 模型：`gpt-5.4`
- 调用方式：Chat Completions
- 请求耗时：5.49 秒
- 输入 Token：340
- 输出 Token：43
- 总 Token：383
- 程序退出代码：0
- 是否在源代码中保存 API Key：否

### 本次调用的数据流

```text
读取 .env
→ 校验 API Key、Base URL 和模型名称
→ 读取用户问题
→ 使用 strip() 清理输入
→ 构造 System Prompt
→ 构造 User Message
→ 组合完整请求消息
→ OpenAI SDK 请求 New API 中转站
→ 中转站将请求路由到上游模型
→ 获取 ChatCompletion 响应
→ 从 choices[0].message.content 提取回答
→ 输出耗时和 Token 用量
```

---

## 8. 模型请求与响应结构

### 实际请求消息

程序前面分别构造：

```python
system_prompt = build_system_prompt()
messages = build_messages(question)
```

在调用 API 前组合成：

```python
request_messages = [
    {
        "role": "system",
        "content": system_prompt,
    },
    *messages,
]
```

实际结构类似：

```python
[
    {
        "role": "system",
        "content": "你是一名大模型应用开发学习助手……",
    },
    {
        "role": "user",
        "content": "请解释什么是上下文工程。",
    },
]
```

### 响应文本路径

模型回答位于：

```python
response.choices[0].message.content
```

可以记成：

```text
response
→ choices[0]
→ message
→ content
```

注意：列表索引从 `0` 开始，因此：

```text
choices[0] = 第一条候选回答
choices[1] = 第二条候选回答
```

### messages 与 choices 的区别

```text
messages = 发送给模型的对话消息
choices  = 模型生成的候选回答
```

`choices` 是列表，是因为接口可以用列表结构承载一个或多个候选回答。当前程序只读取第一条。

### 为什么需要检查空列表

```python
if not response.choices:
    return ""
```

如果 `choices` 是空列表：

```python
[]
```

直接访问 `choices[0]` 会产生：

```text
IndexError: list index out of range
```

还需要处理回答内容为 `None` 的情况：

```python
return response.choices[0].message.content or ""
```

### Token 用量

```python
response.usage.prompt_tokens
response.usage.completion_tokens
response.usage.total_tokens
```

对应：

```text
prompt_tokens     = 输入 Token
completion_tokens = 输出 Token
total_tokens      = 输入 + 输出 Token
```

输入 Token 不只来自用户问题，还可能包括：

- System Prompt；
- 历史 User 和 Assistant 消息；
- 消息格式开销；
- 未来加入的工具定义；
- 未来加入的 RAG 检索内容。

### 请求耗时

```python
started_at = perf_counter()
response = call_model(...)
elapsed = perf_counter() - started_at
```

这里记录的是本地程序观察到的总耗时，可能包括：

```text
本地构造请求
→ 网络传输
→ New API 中转站处理
→ 上游模型生成
→ 响应返回
→ SDK 解析响应
```

---

## 9. 今天纠正的认识

### 纠正 1：大模型应用开发不等于微调

大模型应用开发还包括：

- 模型 API 接入；
- Prompt 和上下文管理；
- 结构化输出；
- Tool Calling；
- RAG；
- Agent 工作流；
- 评测、安全、监控和部署。

### 纠正 2：调用模型不等于训练模型

今天做的是推理调用：

```text
输入内容 → 已训练好的模型 → 生成回答
```

没有修改模型参数，也没有训练模型。

### 纠正 3：列表存在和内容为空是两种情况

```python
choices = []
```

表示没有第一项，访问 `[0]` 会越界。

而：

```python
choices[0].message.content = None
```

表示第一项存在，但回答文本为空。

### 纠正 4：choices 不保存请求消息

- System 和 User 输入保存在请求的 `messages` 中。
- 模型生成的候选回答保存在响应的 `choices` 中。

### 纠正 5：外部 API 必须考虑失败

模型调用可能出现：

- 认证失败；
- 额度或限流问题；
- 网络连接失败；
- Base URL 配置错误；
- 模型名不存在；
- 中转站或上游服务错误；
- 返回结构不符合预期。

因此模型调用不能只写成功路径。

---

## 10. 今日复盘

### 今天学到的核心内容

1. 大模型应用由确定性的软件系统和非确定性的模型能力共同组成。
2. Python 项目应拥有独立虚拟环境，并通过 `pyproject.toml` 和 `uv.lock` 管理依赖。
3. `strip()` 返回新字符串，字符串本身不可变。
4. `raise` 用于抛出异常，`except` 用于捕获和处理异常。
5. System、User、Assistant、Tool 的角色由消息来源和职责决定。
6. 一条消息可以使用 `dict` 表示，多条消息使用 `list` 保存。
7. API Key 必须通过环境变量管理，不能硬编码或提交到 Git。
8. 模型回答位于 `response.choices[0].message.content`。
9. Token 同时影响上下文容量、调用成本和响应延迟。
10. 模型调用是外部网络请求，必须处理认证、限流、网络和服务端错误。

### 我已经完成的成果

- [x] 建立 Day 01 学习档案。
- [x] 安装并配置 Python 3.12。
- [x] 使用 uv 创建项目独立虚拟环境。
- [x] 创建 `pyproject.toml` 和 `uv.lock`。
- [x] 修正 PyCharm 项目解释器。
- [x] 编写带输入清理和异常处理的命令行程序。
- [x] 构造 System Prompt 和消息列表。
- [x] 使用 `.env` 管理模型配置。
- [x] 安装 OpenAI Python SDK。
- [x] 通过自建 New API 中转站完成第一次真实模型调用。
- [x] 输出模型回答、调用耗时和 Token 用量。

### 仍需巩固的内容

- `messages` 与 `choices` 的区别。
- 列表索引从 `0` 开始。
- 空列表和空文本的区别。
- 类型标注的阅读方式。
- OpenAI SDK 响应对象的层级结构。
- 如何为确定性代码编写单元测试。

### 下一步

下一阶段将继续完成：

1. 为输入清理、配置校验和响应提取编写单元测试。
2. 进一步完善模型调用的异常处理。
3. 理解模型 API 通常为什么是无状态的。
4. 开始构建最小多轮对话。
5. 比较固定 Prompt 与明确指定受众、长度和格式后的回答差异。

---

## 11. 今日一句话总结

> 今天我完成了从 Python 本地程序，经 OpenAI SDK 和 New API 中转站，到 GPT 模型并返回回答的第一次完整调用闭环，同时开始理解输入消息、响应结构、Token、耗时和安全配置之间的关系。

# DeepSeek Advisor 模块

为 pH 控制项目添加 AI 顾问功能，实现类似 Anthropic Advisor Tool 的模式。

## 功能特性

- 🤖 **多角色顾问**: 代码调试专家、pH控制专家、数据分析员、通用顾问
- ⚡ **同步/异步支持**: 支持同步调用和后台异步处理
- 📊 **质量分级**: 快速响应、标准响应、详细分析
- 🎨 **GUI集成**: 可直接集成到现有 Tkinter 界面
- 🔄 **历史记录**: 自动保存对话历史
- 🛡️ **错误重试**: 内置重试机制和超时处理

## 文件说明

| 文件 | 说明 |
|------|------|
| `advisor.py` | 核心模块，提供 DeepSeek API 封装 |
| `advisor_gui.py` | GUI 集成示例，可独立运行 |
| `advisor_example.py` | 使用示例代码 |
| `advisor_config_example.json` | 配置文件示例 |

## 快速开始

### 1. 安装依赖

```bash
pip install httpx
```

### 2. 配置 API 密钥

复制配置文件示例：

```bash
copy advisor_config_example.json advisor_config.json
```

编辑 `advisor_config.json`，填入你的 DeepSeek API 密钥：

```json
{
    "api_key": "sk-your-actual-api-key-here",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat",
    "timeout": 30.0,
    "max_retries": 3,
    "enabled": true
}
```

### 3. 运行示例

```bash
# 运行使用示例
python advisor_example.py

# 运行 GUI 演示
python advisor_gui.py
```

## 使用方法

### 基础使用

```python
from advisor import create_advisor, AdvisorRole, quick_ask

# 创建顾问
advisor = create_advisor(api_key="your-api-key")

# 快速提问
response = quick_ask(
    advisor=advisor,
    query="Python中如何实现PID控制？",
    role=AdvisorRole.CODE_DEBUGGER,
)

if response.success:
    print(response.content)
```

### 代码调试

```python
from advisor import debug_code

response = debug_code(
    advisor=advisor,
    code=problematic_code,
    error_msg="TypeError: ...",
    expected_behavior="应该正确处理 None 值",
)
```

### pH控制专家

```python
from advisor import AdviceRequest, AdvisorRole, AdviceQuality

request = AdviceRequest(
    query="请分析当前的pH控制情况，提供优化建议。",
    context={
        "current_ph": 3.2,
        "target_ph": 5.0,
        "orp_reading": -150,
        "problem": "滴定速度太慢",
    },
    role=AdvisorRole.PH_CONTROL_EXPERT,
    quality=AdviceQuality.DETAILED,
)

response = advisor.ask(request)
```

### 异步使用

```python
def on_advice(response):
    if response.success:
        print(response.content)

# 异步提问
thread = advisor.ask_async(request, callback=on_advice)

# 不阻塞主线程，继续做其他事
```

### 批量处理

```python
from advisor import AsyncAdvisorQueue

# 创建队列
queue = AsyncAdvisorQueue(advisor, max_workers=2)
queue.start()

# 提交多个任务
for query in queries:
    queue.submit(request, callback=on_result)

# 程序结束时停止
queue.stop()
```

## 顾问角色

| 角色 | 说明 | 适用场景 |
|------|------|----------|
| `CODE_DEBUGGER` | 代码调试专家 | 调试代码、优化性能 |
| `PH_CONTROL_EXPERT` | pH控制专家 | 优化滴定策略、标定建议 |
| `DATA_ANALYST` | 数据分析员 | 分析实验数据、识别趋势 |
| `GENERAL_ADVISOR` | 通用顾问 | 其他技术问题 |

## 质量级别

| 级别 | 说明 | 最大Token | 温度 |
|------|------|----------|------|
| `QUICK` | 快速响应 | 512 | 0.3 |
| `STANDARD` | 标准响应 | 1024 | 0.7 |
| `DETAILED` | 详细分析 | 2048 | 0.9 |

## 集成到现有项目

### 1. 导入并创建顾问

```python
from advisor import create_advisor

# 在程序启动时创建
advisor = create_advisor(api_key="your-key")
```

### 2. 在需要时提问

```python
# 在pH读数异常时
request = AdviceRequest(
    query="pH读数不稳定，可能是什么原因？",
    context={"recent_readings": [...], "sensor_status": "..."},
    role=AdvisorRole.PH_CONTROL_EXPERT,
)

response = advisor.ask(request)
if response.success:
    show_advice(response.content)
```

### 3. 集成GUI面板

```python
from advisor_gui import AdvisorPanel

# 在主窗口中添加顾问面板
advisor_panel = AdvisorPanel(main_frame, advisor)
```

## API 说明

### DeepSeekAdvisor 类

主要方法：

- `ask(request: AdviceRequest) -> AdviceResponse` - 同步提问
- `ask_async(request, callback) -> Thread` - 异步提问
- `get_history(limit=10) -> List` - 获取历史记录
- `clear_history()` - 清除历史

### AdviceRequest 类

字段：

- `query: str` - 问题内容
- `context: Dict` - 上下文信息
- `role: AdvisorRole` - 顾问角色
- `quality: AdviceQuality` - 回答质量
- `max_tokens: Optional[int]` - 最大Token数（可选）

### AdviceResponse 类

字段：

- `success: bool` - 是否成功
- `content: str` - 回答内容
- `error: str` - 错误信息（如果失败）
- `tokens_used: int` - 使用的Token数
- `latency: float` - 响应耗时（秒）
- `timestamp: float` - 时间戳

## 配置选项

在 `AdvisorConfig` 中可配置：

- `api_key` - API密钥（必需）
- `base_url` - API基础URL
- `model` - 模型名称
- `timeout` - 超时时间（秒）
- `max_retries` - 最大重试次数

## 注意事项

1. **API密钥安全**: 不要将 `advisor_config.json` 提交到版本控制
2. **Token成本**: 监控使用量，避免意外产生高额费用
3. **错误处理**: 始终检查 `response.success`
4. **异步优先**: GUI程序中推荐使用异步方式避免卡顿
5. **上下文限制**: 上下文内容会增加Token使用，保持精简

## 获取 API 密钥

1. 访问 [DeepSeek 开放平台](https://platform.deepseek.com)
2. 注册账号并创建 API Key
3. 填入配置文件

## 许可证

与项目其余部分使用相同的许可证。

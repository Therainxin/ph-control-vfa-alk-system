# -*- coding: utf-8 -*-
"""
Advisor Module - 实现类似 Anthropic Advisor Tool 的模式
使用 DeepSeek API 作为顾问模型，提供智能建议
"""
import json
import time
import httpx
import threading
from typing import Callable, Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
from queue import Queue, Empty


class AdvisorRole(Enum):
    """顾问角色类型"""
    CODE_DEBUGGER = auto()      # 代码调试专家
    PH_CONTROL_EXPERT = auto()  # pH控制专家
    DATA_ANALYST = auto()       # 数据分析员
    GENERAL_ADVISOR = auto()    # 通用顾问


class AdviceQuality(Enum):
    """建议质量"""
    QUICK = "quick"      # 快速响应（短回答）
    STANDARD = "standard"  # 标准响应
    DETAILED = "detailed"  # 详细分析


@dataclass
class AdviceRequest:
    """顾问请求"""
    query: str
    context: Dict[str, Any] = field(default_factory=dict)
    role: AdvisorRole = AdvisorRole.GENERAL_ADVISOR
    quality: AdviceQuality = AdviceQuality.STANDARD
    include_code: bool = True
    max_tokens: Optional[int] = None


@dataclass
class AdviceResponse:
    """顾问响应"""
    success: bool
    content: str = ""
    thinking: str = ""
    error: str = ""
    tokens_used: int = 0
    latency: float = 0.0
    timestamp: float = field(default_factory=time.time)


class AdvisorConfig:
    """顾问配置"""

    # 系统提示词模板
    SYSTEM_PROMPTS = {
        AdvisorRole.CODE_DEBUGGER: """你是一位资深的Python/嵌入式系统调试专家。
你的任务是：
1. 分析代码问题和错误信息
2. 找出根本原因
3. 提供具体的修复方案
4. 给出可直接使用的代码示例

请保持回答专业、简洁、实用。""",

        AdvisorRole.PH_CONTROL_EXPERT: """你是一位pH控制和滴定分析专家。
你的任务是：
1. 分析pH控制策略
2. 优化滴定参数
3. 解释传感器数据
4. 提供标定建议

请基于化学原理和控制理论给出建议。""",

        AdvisorRole.DATA_ANALYST: """你是一位实验数据分析专家。
你的任务是：
1. 分析实验数据趋势
2. 识别异常和模式
3. 提供数据解释
4. 建议改进方案

请用科学严谨的方式分析数据。""",

        AdvisorRole.GENERAL_ADVISOR: """你是一位全能的技术顾问。
请帮助用户解决各种技术问题，提供实用的建议。""",
    }

    # 质量级别配置
    QUALITY_CONFIG = {
        AdviceQuality.QUICK: {
            "temperature": 0.3,
            "max_tokens": 512,
        },
        AdviceQuality.STANDARD: {
            "temperature": 0.7,
            "max_tokens": 1024,
        },
        AdviceQuality.DETAILED: {
            "temperature": 0.9,
            "max_tokens": 2048,
        },
    }

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries


class DeepSeekAdvisor:
    """DeepSeek API 顾问"""

    def __init__(self, config: AdvisorConfig):
        self.config = config
        self._client: Optional[httpx.Client] = None
        self._history: List[Dict] = []
        self._lock = threading.Lock()

    def _get_client(self) -> httpx.Client:
        """获取或创建HTTP客户端"""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def _build_messages(self, request: AdviceRequest) -> List[Dict]:
        """构建对话消息"""
        messages = []

        # 系统提示
        system_prompt = self.config.SYSTEM_PROMPTS[request.role]
        messages.append({"role": "system", "content": system_prompt})

        # 添加上下文
        if request.context:
            context_text = self._format_context(request.context)
            messages.append({
                "role": "user",
                "content": f"参考上下文：\n{context_text}"
            })

        # 添加当前查询
        messages.append({"role": "user", "content": request.query})

        return messages

    def _format_context(self, context: Dict[str, Any]) -> str:
        """格式化上下文"""
        lines = []
        for key, value in context.items():
            if isinstance(value, str) and len(value) > 500:
                value = value[:500] + "..."
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        return "\n".join(lines)

    def _build_request_payload(self, request: AdviceRequest) -> Dict:
        """构建API请求体"""
        quality_config = self.config.QUALITY_CONFIG[request.quality]
        max_tokens = request.max_tokens or quality_config["max_tokens"]

        return {
            "model": self.config.model,
            "messages": self._build_messages(request),
            "temperature": quality_config["temperature"],
            "max_tokens": max_tokens,
            "stream": False,
        }

    def ask(self, request: AdviceRequest) -> AdviceResponse:
        """向顾问提问（同步）"""
        start_time = time.time()
        last_error = ""

        for attempt in range(self.config.max_retries):
            try:
                client = self._get_client()
                payload = self._build_request_payload(request)

                response = client.post(
                    "/v1/chat/completions",
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()

                content = result["choices"][0]["message"]["content"]
                tokens_used = result["usage"]["total_tokens"]
                latency = time.time() - start_time

                with self._lock:
                    self._history.append({
                        "request": request,
                        "response": content,
                        "tokens": tokens_used,
                        "timestamp": start_time,
                    })

                return AdviceResponse(
                    success=True,
                    content=content,
                    tokens_used=tokens_used,
                    latency=latency,
                )

            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code}: {e.response.text}"
                if e.response.status_code in (429, 500, 502, 503, 504):
                    wait_time = (attempt + 1) * 2
                    time.sleep(wait_time)
                    continue
                break
            except Exception as e:
                last_error = str(e)
                time.sleep(1)
                continue

        return AdviceResponse(
            success=False,
            error=last_error,
            latency=time.time() - start_time,
        )

    def ask_async(
        self,
        request: AdviceRequest,
        callback: Optional[Callable[[AdviceResponse], None]] = None,
    ) -> threading.Thread:
        """异步提问"""
        def _task():
            response = self.ask(request)
            if callback:
                callback(response)
        thread = threading.Thread(target=_task, daemon=True)
        thread.start()
        return thread

    def get_history(self, limit: int = 10) -> List[Dict]:
        """获取历史记录"""
        with self._lock:
            return list(self._history[-limit:])

    def clear_history(self):
        """清除历史"""
        with self._lock:
            self._history.clear()


class AsyncAdvisorQueue:
    """异步顾问队列 - 后台处理多个请求"""

    def __init__(self, advisor: DeepSeekAdvisor, max_workers: int = 2):
        self.advisor = advisor
        self._queue: Queue[Tuple[AdviceRequest, Callable]] = Queue()
        self._workers: List[threading.Thread] = []
        self._running = False
        self._max_workers = max_workers

    def start(self):
        """启动工作线程"""
        if self._running:
            return
        self._running = True
        for _ in range(self._max_workers):
            worker = threading.Thread(target=self._worker_loop, daemon=True)
            worker.start()
            self._workers.append(worker)

    def stop(self):
        """停止工作线程"""
        self._running = False
        for _ in range(self._max_workers):
            self._queue.put((None, None))
        for worker in self._workers:
            worker.join(timeout=5.0)
        self._workers.clear()

    def submit(
        self,
        request: AdviceRequest,
        callback: Callable[[AdviceResponse], None],
    ):
        """提交请求"""
        self._queue.put((request, callback))

    def _worker_loop(self):
        """工作线程循环"""
        while self._running:
            try:
                request, callback = self._queue.get(timeout=0.5)
                if request is None:
                    break
                response = self.advisor.ask(request)
                if callback:
                    try:
                        callback(response)
                    except Exception as e:
                        print(f"Advisor callback error: {e}")
            except Empty:
                continue
            except Exception as e:
                print(f"Advisor worker error: {e}")


# 快捷函数
def create_advisor(
    api_key: str,
    base_url: str = "https://api.deepseek.com",
    model: str = "deepseek-chat",
) -> DeepSeekAdvisor:
    """创建顾问实例"""
    config = AdvisorConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
    )
    return DeepSeekAdvisor(config)


def quick_ask(
    advisor: DeepSeekAdvisor,
    query: str,
    context: Optional[Dict] = None,
    role: AdvisorRole = AdvisorRole.GENERAL_ADVISOR,
) -> AdviceResponse:
    """快速提问"""
    request = AdviceRequest(
        query=query,
        context=context or {},
        role=role,
        quality=AdviceQuality.QUICK,
    )
    return advisor.ask(request)


# 预设的代码调试场景
def debug_code(
    advisor: DeepSeekAdvisor,
    code: str,
    error_msg: str = "",
    expected_behavior: str = "",
) -> AdviceResponse:
    """调试代码"""
    context = {}
    if code:
        context["code"] = code
    if error_msg:
        context["error"] = error_msg
    if expected_behavior:
        context["expected"] = expected_behavior

    query = "请分析这段代码的问题并提供修复方案。"
    if error_msg:
        query = f"错误信息：{error_msg}\n请分析问题并修复。"

    request = AdviceRequest(
        query=query,
        context=context,
        role=AdvisorRole.CODE_DEBUGGER,
        quality=AdviceQuality.DETAILED,
    )
    return advisor.ask(request)

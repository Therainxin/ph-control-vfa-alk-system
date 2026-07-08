# -*- coding: utf-8 -*-
"""
Advisor GUI 集成示例
展示如何将 DeepSeek Advisor 集成到现有的 pH 控制程序中
"""
import json
import os
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from typing import Optional
from advisor import (
    DeepSeekAdvisor,
    AdvisorConfig,
    AdvisorRole,
    AdviceQuality,
    AdviceRequest,
    create_advisor,
    AsyncAdvisorQueue,
)


class AdvisorPanel:
    """顾问面板 - 可集成到主GUI中"""

    def __init__(
        self,
        parent: tk.Widget,
        advisor: Optional[DeepSeekAdvisor] = None,
    ):
        self.advisor = advisor
        self._queue: Optional[AsyncAdvisorQueue] = None
        self._history: list = []

        self._build_ui(parent)

    def _build_ui(self, parent: tk.Widget):
        """构建UI"""
        frame = ttk.LabelFrame(parent, text="智能顾问 (DeepSeek)", padding=8)
        frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 配置区域
        config_frame = ttk.Frame(frame)
        config_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(config_frame, text="API密钥:").pack(side=tk.LEFT)
        self.api_key_var = tk.StringVar()
        self.api_key_entry = ttk.Entry(
            config_frame,
            textvariable=self.api_key_var,
            width=30,
            show="*",
        )
        self.api_key_entry.pack(side=tk.LEFT, padx=5)

        self.btn_connect = ttk.Button(
            config_frame,
            text="连接",
            command=self._connect_advisor,
        )
        self.btn_connect.pack(side=tk.LEFT, padx=2)

        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=5)

        # 角色选择
        role_frame = ttk.Frame(frame)
        role_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(role_frame, text="顾问角色:").pack(side=tk.LEFT)
        self.role_var = tk.StringVar(value="general")
        role_combo = ttk.Combobox(
            role_frame,
            textvariable=self.role_var,
            values=[
                ("通用顾问", "general"),
                ("代码调试", "code"),
                ("pH控制专家", "ph"),
                ("数据分析", "data"),
            ],
            state="readonly",
            width=15,
        )
        role_combo.pack(side=tk.LEFT, padx=5)

        # 质量选择
        ttk.Label(role_frame, text="回答质量:").pack(side=tk.LEFT, padx=(10, 0))
        self.quality_var = tk.StringVar(value="standard")
        quality_combo = ttk.Combobox(
            role_frame,
            textvariable=self.quality_var,
            values=[
                ("快速", "quick"),
                ("标准", "standard"),
                ("详细", "detailed"),
            ],
            state="readonly",
            width=10,
        )
        quality_combo.pack(side=tk.LEFT, padx=5)

        # 输入区域
        input_frame = ttk.LabelFrame(frame, text="问题描述", padding=5)
        input_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        self.query_text = scrolledtext.ScrolledText(
            input_frame,
            height=4,
            wrap=tk.WORD,
        )
        self.query_text.pack(fill=tk.BOTH, expand=True)

        # 快捷按钮
        quick_frame = ttk.Frame(frame)
        quick_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Button(
            quick_frame,
            text="分析当前pH数据",
            command=lambda: self._quick_query("ph"),
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            quick_frame,
            text="检查代码问题",
            command=lambda: self._quick_query("code"),
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            quick_frame,
            text="标定建议",
            command=lambda: self._quick_query("calibration"),
        ).pack(side=tk.LEFT, padx=2)

        # 发送按钮
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(0, 5))

        self.btn_send = ttk.Button(
            btn_frame,
            text="发送问题",
            command=self._send_query,
            state=tk.DISABLED,
        )
        self.btn_send.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_clear = ttk.Button(
            btn_frame,
            text="清空",
            command=self._clear,
        )
        self.btn_clear.pack(side=tk.LEFT, padx=2)

        self.status_label = ttk.Label(btn_frame, text="未连接")
        self.status_label.pack(side=tk.RIGHT)

        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=5)

        # 输出区域
        output_frame = ttk.LabelFrame(frame, text="顾问回答", padding=5)
        output_frame.pack(fill=tk.BOTH, expand=True)

        self.response_text = scrolledtext.ScrolledText(
            output_frame,
            height=8,
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        self.response_text.pack(fill=tk.BOTH, expand=True)

        # 统计信息
        self.stats_label = ttk.Label(frame, text="", foreground="gray")
        self.stats_label.pack(anchor=tk.W, pady=(5, 0))

    def _connect_advisor(self):
        """连接顾问"""
        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showwarning("提示", "请输入API密钥")
            return

        try:
            self.advisor = create_advisor(api_key=api_key)
            self._queue = AsyncAdvisorQueue(self.advisor)
            self._queue.start()

            self.btn_connect.config(text="断开", command=self._disconnect_advisor)
            self.btn_send.config(state=tk.NORMAL)
            self.status_label.config(text="已连接", foreground="#4CAF50")
            self._append_response("✓ 顾问已连接，可以开始提问了。")

            # 尝试加载配置文件
            self._try_load_config()

        except Exception as e:
            messagebox.showerror("错误", f"连接失败: {e}")

    def _disconnect_advisor(self):
        """断开连接"""
        if self._queue:
            self._queue.stop()
            self._queue = None

        self.advisor = None
        self.btn_connect.config(text="连接", command=self._connect_advisor)
        self.btn_send.config(state=tk.DISABLED)
        self.status_label.config(text="未连接", foreground="gray")
        self._append_response("已断开连接。")

    def _try_load_config(self):
        """尝试加载配置文件"""
        config_file = "advisor_config.json"
        if os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                if config.get("api_key") and not self.api_key_var.get():
                    self.api_key_var.set(config["api_key"])
            except Exception:
                pass

    def _get_role(self) -> AdvisorRole:
        """获取选择的角色"""
        role_map = {
            "general": AdvisorRole.GENERAL_ADVISOR,
            "code": AdvisorRole.CODE_DEBUGGER,
            "ph": AdvisorRole.PH_CONTROL_EXPERT,
            "data": AdvisorRole.DATA_ANALYST,
        }
        return role_map.get(self.role_var.get(), AdvisorRole.GENERAL_ADVISOR)

    def _get_quality(self) -> AdviceQuality:
        """获取选择的质量"""
        quality_map = {
            "quick": AdviceQuality.QUICK,
            "standard": AdviceQuality.STANDARD,
            "detailed": AdviceQuality.DETAILED,
        }
        return quality_map.get(self.quality_var.get(), AdviceQuality.STANDARD)

    def _send_query(self):
        """发送问题"""
        if not self.advisor:
            return

        query = self.query_text.get("1.0", tk.END).strip()
        if not query:
            messagebox.showwarning("提示", "请输入问题")
            return

        # 禁用UI
        self.btn_send.config(state=tk.DISABLED)
        self.status_label.config(text="思考中...", foreground="#FF9800")

        # 收集上下文（这里可以添加实际的pH数据）
        context = self._collect_context()

        request = AdviceRequest(
            query=query,
            context=context,
            role=self._get_role(),
            quality=self._get_quality(),
        )

        def callback(response):
            self.root.after(0, lambda: self._on_response(response))

        if self._queue:
            self._queue.submit(request, callback)
        else:
            self.advisor.ask_async(request, callback)

    def _collect_context(self) -> dict:
        """收集上下文信息（示例）"""
        # 这里可以集成实际的pH控制程序数据
        context = {}
        try:
            # 尝试读取一些配置文件
            if os.path.exists("calibrations.json"):
                with open("calibrations.json", "r", encoding="utf-8") as f:
                    calib_data = json.load(f)
                    context["calibration"] = str(calib_data)[:500]
        except Exception:
            pass

        return context

    def _on_response(self, response):
        """收到响应"""
        # 重新启用UI
        self.btn_send.config(state=tk.NORMAL)

        if response.success:
            self.status_label.config(
                text=f"完成 ({response.tokens_used} tokens, {response.latency:.1f}s)",
                foreground="#4CAF50",
            )
            self._append_response(f"Q: {self.query_text.get('1.0', tk.END).strip()}\n")
            self._append_response(f"A: {response.content}\n")
            self._append_response("-" * 60 + "\n")
        else:
            self.status_label.config(text="错误", foreground="#F44336")
            self._append_response(f"✗ 错误: {response.error}\n")

        # 保存历史
        self._history.append(response)

    def _append_response(self, text: str):
        """追加响应文本"""
        self.response_text.config(state=tk.NORMAL)
        self.response_text.insert(tk.END, text)
        self.response_text.see(tk.END)
        self.response_text.config(state=tk.DISABLED)

    def _quick_query(self, query_type: str):
        """快速提问"""
        queries = {
            "ph": "请分析当前的pH控制情况，提供优化建议。",
            "code": "请检查代码可能存在的问题，提供改进建议。",
            "calibration": "请提供pH/ORP标定的最佳实践建议。",
        }

        self.query_text.delete("1.0", tk.END)
        self.query_text.insert("1.0", queries.get(query_type, ""))

        if query_type == "ph":
            self.role_var.set("ph")
        elif query_type in ("code", "calibration"):
            self.role_var.set("code")

    def _clear(self):
        """清空"""
        self.query_text.delete("1.0", tk.END)
        self.response_text.config(state=tk.NORMAL)
        self.response_text.delete("1.0", tk.END)
        self.response_text.config(state=tk.DISABLED)

    def set_context_provider(self, provider):
        """设置上下文提供者（可选）"""
        self._context_provider = provider

    def shutdown(self):
        """关闭"""
        if self._queue:
            self._queue.stop()


def create_advisor_demo_window():
    """创建演示窗口"""
    root = tk.Tk()
    root.title("DeepSeek Advisor 集成示例")
    root.geometry("700x700")

    panel = AdvisorPanel(root)
    panel.root = root  # 保存根引用

    # 尝试预加载配置
    try:
        if os.path.exists("advisor_config.json"):
            with open("advisor_config.json", "r", encoding="utf-8") as f:
                config = json.load(f)
                if config.get("api_key"):
                    panel.api_key_var.set(config["api_key"])
    except Exception:
        pass

    root.protocol("WM_DELETE_WINDOW", lambda: (panel.shutdown(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    create_advisor_demo_window()

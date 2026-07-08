# -*- coding: utf-8 -*-
"""
ORP/pH 上位机 v6 — pH曲线 + 三路泵 + 流速/体积 + 数据记录CSV + 多点标定
Arduino: D13=碱泵, D12=酸泵, D11=水泵
指令: B1/B0, A1/A0, W1/W0
"""

import os
import json
import csv
import time
import re
import math
import queue
import threading
from collections import deque
from datetime import datetime
from enum import Enum, auto
from tkinter import ttk, filedialog, messagebox
import tkinter as tk

import serial
import serial.tools.list_ports
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ── 全局配置 ──────────────────────────────────────────────
DEFAULT_BAUD = 115200
DATA_WINDOW = 120
MAX_POINTS = 2400
REFRESH_MS = 150
RECORD_DIR = "记录"
CONFIG_FILE = "calibrations.json"  # 标定历史 + 参数持久化
RESULT_FACTOR_MIN = 0.2
RESULT_FACTOR_MAX = 5.0
RESULT_HISTORY_MAX = 50
MEASUREMENT_HISTORY_MAX = 50
PUMP_CAL_HISTORY_MAX = 50
PUMP_CAL_DURATION_OPTIONS = (5, 10, 30, 60)
PUMP_CAL_MIN_SECONDS = 3
PUMP_CAL_MAX_SECONDS = 120
PUMP_CAL_MIN_VALID_SECONDS = 3.0
PUMP_CAL_MIN_VOLUME_ML = 0.01
PUMP_CAL_MAX_VOLUME_ML = 5000.0
PUMP_CAL_WARN_DEVIATION = 0.10
PUMP_CAL_FLOW_MIN = 0.001
PUMP_CAL_FLOW_MAX = 100.0
FLOW_APPLY_TIMEOUT_MS = 3000
PARAM_APPLY_TIMEOUT_MS = 3000
RESULT_MIN_R2 = 0.95
RESULT_MAX_REL_ERR = 0.20

# ── 枚举 ──────────────────────────────────────────────────
class TitrationState(Enum):
    IDLE = auto()
    CHECKING = auto()
    PUMPING = auto()
    WAITING = auto()

class TitrationDir(Enum):
    ADD_BASE = "加碱 (pH偏低时)"
    ADD_ACID = "加酸 (pH偏高时)"

# ── 配色 ─────────────────────────────────────────────────
PUMP_COLORS = {
    "idle":    {"bg": "#4CAF50", "fg": "white"},
    "running": {"bg": "#F44336", "fg": "white"},
}

# ── 串口读写线程 ──────────────────────────────────────────
class SerialReader(threading.Thread):
    def __init__(self, port, baud, data_queue):
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.data_queue = data_queue
        self.running = False
        self.ser = None
        self._write_lock = threading.Lock()

    def run(self):
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
        except Exception as e:
            self.data_queue.put(("error", str(e)))
            return

        self.running = True
        self.data_queue.put(("connected", self.port))
        buf = b""
        while self.running:
            try:
                n = self.ser.in_waiting
                if n > 0:
                    chunk = self.ser.read(n)
                    buf += chunk
                    while b"\n" in buf:
                        idx = buf.index(b"\n")
                        raw_line = buf[:idx]
                        buf = buf[idx + 1:]
                        raw_line = raw_line.rstrip(b"\r")
                        try:
                            line = raw_line.decode("utf-8")
                        except UnicodeDecodeError:
                            line = raw_line.decode("utf-8", errors="replace")
                        if line.strip():
                            self.data_queue.put(("line", line.strip()))
                else:
                    time.sleep(0.02)
            except serial.SerialException as e:
                self.data_queue.put(("error", str(e)))
                break

        if self.ser and self.ser.is_open:
            self.ser.close()
        self.running = False
        self.data_queue.put(("disconnected", ""))

    def send(self, cmd: str):
        with self._write_lock:
            if self.ser and self.ser.is_open:
                self.ser.write((cmd + "\n").encode())

    def stop(self):
        self.running = False
        if self.ser and self.ser.is_open:
            self.ser.close()


# ══════════════════════════════════════════════════════════
#  标定弹窗
# ══════════════════════════════════════════════════════════
class CalibrationWindow(tk.Toplevel):
    CALIB_SAMPLES = 30   # 每个点采集帧数

    def __init__(self, parent, orp_getter):
        """
        parent:   主窗口 ORPMonitor 实例
        orp_getter: callable, 返回当前 ORP_mV (int) 或 None
        """
        super().__init__(parent.root)
        self.parent = parent
        self.orp_getter = orp_getter

        self.title("多点标定")
        self.geometry("600x680")
        self.resizable(True, True)
        self.transient(parent.root)
        self.grab_set()

        # 标定点数据: [(已知pH, 采集到的ORP平均值), ...]
        self.points = []

        # 当前正在采集的点索引 (-1=无)
        self._collecting_idx = -1
        self._collect_count = 0
        self._collect_buf = []

        # 计算结果
        self._computed_K = None
        self._computed_B = None
        self._computed_R2 = None

        self._build_ui()

    def _build_ui(self):
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # 点数选择
        top = ttk.Frame(main)
        top.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(top, text="标定点数:").pack(side=tk.LEFT)
        self.pt_count = tk.IntVar(value=2)
        spin = ttk.Spinbox(top, from_=2, to=10, textvariable=self.pt_count,
                           width=4, command=self._rebuild_points)
        spin.pack(side=tk.LEFT, padx=5)

        # 标定点列表容器
        self.pt_frame = ttk.LabelFrame(main, text="标定点", padding=8)
        self.pt_frame.pack(fill=tk.BOTH, expand=True)

        self._rebuild_points()

        # 底部按钮
        bottom = ttk.Frame(main)
        bottom.pack(fill=tk.X, pady=(8, 0))

        ttk.Label(bottom, text="标签:").pack(side=tk.LEFT)
        self.label_var = tk.StringVar(value="")
        ttk.Entry(bottom, textvariable=self.label_var, width=14).pack(side=tk.LEFT, padx=3)

        ttk.Button(bottom, text="全部采集", command=self._collect_all).pack(side=tk.LEFT, padx=(8, 2))
        ttk.Button(bottom, text="计算", command=self._compute).pack(side=tk.LEFT, padx=2)

        self.btn_apply = ttk.Button(bottom, text="应用", command=self._apply, state=tk.DISABLED)
        self.btn_apply.pack(side=tk.RIGHT, padx=2)

        # 结果
        self.result_label = ttk.Label(main, text="", font=("", 14))
        self.result_label.pack(fill=tk.X, pady=(8, 0))

    def _rebuild_points(self):
        for w in self.pt_frame.winfo_children():
            w.destroy()
        n = self.pt_count.get()
        self.points = [(None, None)] * n
        self._collecting_idx = -1
        self._row_widgets = []

        header = ttk.Frame(self.pt_frame)
        header.pack(fill=tk.X, pady=(0, 3))
        ttk.Label(header, text="序号", width=5, font=("", 11, "bold")).pack(side=tk.LEFT)
        ttk.Label(header, text="已知pH值", width=12, font=("", 11, "bold")).pack(side=tk.LEFT, padx=5)
        ttk.Label(header, text="操作", width=14, font=("", 11, "bold")).pack(side=tk.LEFT, padx=5)
        ttk.Label(header, text="平均ORP", width=14, font=("", 11, "bold")).pack(side=tk.LEFT, padx=5)

        for i in range(n):
            self._add_point_row(i)

    def _add_point_row(self, i):
        row = ttk.Frame(self.pt_frame)
        row.pack(fill=tk.X, pady=2)

        ttk.Label(row, text=str(i + 1), width=5).pack(side=tk.LEFT)

        ph_var = tk.StringVar()
        ph_ent = ttk.Entry(row, textvariable=ph_var, width=10)
        ph_ent.pack(side=tk.LEFT, padx=5)

        btn = ttk.Button(row, text="采集", width=8,
                         command=lambda idx=i: self._start_collect(idx))
        btn.pack(side=tk.LEFT, padx=5)

        orp_lbl = ttk.Label(row, text="--", width=12, anchor=tk.W)
        orp_lbl.pack(side=tk.LEFT, padx=5)

        self._row_widgets.append({
            "ph_var": ph_var,
            "ph_ent": ph_ent,
            "btn": btn,
            "orp_lbl": orp_lbl,
        })

    def _start_collect(self, idx):
        if self._collecting_idx >= 0:
            return  # 已有采集在进行

        self._collecting_idx = idx
        self._collect_count = 0
        self._collect_buf = []
        self._row_widgets[idx]["btn"].config(text="采集中...", state=tk.DISABLED)
        self._row_widgets[idx]["orp_lbl"].config(text=f"0/{self.CALIB_SAMPLES}")
        self._poll_collect()

    def _poll_collect(self):
        if self._collecting_idx < 0:
            return

        idx = self._collecting_idx
        orp_val = self.orp_getter()
        if orp_val is not None:
            self._collect_buf.append(orp_val)
            self._collect_count += 1
            self._row_widgets[idx]["orp_lbl"].config(
                text=f"{self._collect_count}/{self.CALIB_SAMPLES}")

        if self._collect_count >= self.CALIB_SAMPLES:
            self._finish_collect()
        else:
            self.after(500, self._poll_collect)  # ~2Hz

    def _finish_collect(self):
        idx = self._collecting_idx
        self._collecting_idx = -1

        # 去噪: 去掉最大的10%和最小的10%, 取均值
        buf = sorted(self._collect_buf)
        trim = max(1, len(buf) // 10)
        trimmed = buf[trim:-trim] if len(buf) > trim * 2 else buf
        avg = sum(trimmed) / len(trimmed)

        self._row_widgets[idx]["orp_lbl"].config(text=f"{avg:.1f} mV")
        self._row_widgets[idx]["btn"].config(text="重新采集", state=tk.NORMAL)

        ph_str = self._row_widgets[idx]["ph_var"].get().strip()
        if ph_str:
            self.points[idx] = (float(ph_str), avg)

    def _collect_all(self):
        """按顺序全部采集"""
        # 找到第一个未采集的点
        for i in range(len(self.points)):
            if self.points[i][1] is None:
                ph_str = self._row_widgets[i]["ph_var"].get().strip()
                if not ph_str:
                    messagebox.showwarning("提示", f"请先输入第 {i+1} 个点的已知 pH 值")
                    return
                self._start_collect(i)
                return
        messagebox.showinfo("提示", "所有点已采集完毕")

    def _compute(self):
        valid = [(ph, orp) for ph, orp in self.points if orp is not None and ph is not None]
        if len(valid) < 2:
            messagebox.showwarning("提示", "至少需要 2 个有效标定点才能计算")
            return

        x = [p[1] for p in valid]  # ORP
        y = [p[0] for p in valid]  # pH
        n = len(x)
        sx = sum(x)
        sy = sum(y)
        sxy = sum(xi * yi for xi, yi in zip(x, y))
        sx2 = sum(xi * xi for xi in x)

        denom = n * sx2 - sx * sx
        if abs(denom) < 1e-10:
            messagebox.showerror("错误", "数据点过于集中，无法计算线性回归")
            return

        K = (n * sxy - sx * sy) / denom
        B = (sy - K * sx) / n

        y_mean = sy / n
        ss_tot = sum((yi - y_mean) ** 2 for yi in y)
        ss_res = sum((yi - (K * xi + B)) ** 2 for xi, yi in zip(x, y))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        self._computed_K = K
        self._computed_B = B
        self._computed_R2 = r2
        self._computed_points = [(ph, round(orp, 1)) for ph, orp in valid]

        self.result_label.config(
            text=f"K = {K:.6f}   B = {B:.4f}   R² = {r2:.4f}   ({n} 个点)")
        self.btn_apply.config(state=tk.NORMAL)

    def _apply(self):
        if not hasattr(self, '_computed_K') or self._computed_K is None:
            return
        label = self.label_var.get().strip()
        points = getattr(self, '_computed_points', [])
        r2 = getattr(self, '_computed_R2', 0.0)
        # 委托主窗口保存记录并应用
        self.parent._add_calibration_record(label, self._computed_K, self._computed_B, r2, points)
        messagebox.showinfo("标定完成",
                            f"公式已更新并保存:\npH = ORP_mV × {self._computed_K:.6f} + {self._computed_B:.4f}\n"
                            f"R² = {r2:.4f} | {len(points)} 个点")

    def _append_debug(self, text):
        if hasattr(self.parent, '_append_debug'):
            self.parent._append_debug(text)

    def destroy(self):
        self._collecting_idx = -1
        super().destroy()


class PumpFlowCalibrationWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent.root)
        self.parent = parent
        self.title("泵流量标定")
        self.geometry("980x760")
        self.minsize(860, 620)
        self.transient(parent.root)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.pump_var = tk.StringVar(value="B")
        self.duration_var = tk.StringVar(value="10")
        self.liquid_var = tk.StringVar(value="")
        self.tube_var = tk.StringVar(value="")
        self.channel_var = tk.StringVar(value="")
        self.temperature_var = tk.StringVar(value="")
        self.note_var = tk.StringVar(value="")
        self.history_var = tk.StringVar(value="")
        self.pending_volume_var = tk.StringVar(value="")
        self.pending_points = []
        self.pending_run = None
        self._history_records = []
        self._last_state_text = ""
        self._locked_pump_code = ""
        if self.parent._current_temperature_value() is not None:
            self.temperature_var.set(f"{self.parent._current_temperature_value():.1f}")

        self._build_ui()
        self._refresh_all()

    def _build_ui(self):
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        top = ttk.LabelFrame(main, text="基本信息", padding=8)
        top.pack(fill=tk.X)
        ttk.Label(top, text="泵").grid(row=0, column=0, sticky="w")
        self.cmb_pump = ttk.Combobox(
            top,
            textvariable=self.pump_var,
            state="readonly",
            width=10,
            values=("B - 碱泵", "A - 酸泵", "W - 水泵"),
        )
        self.cmb_pump.grid(row=0, column=1, sticky="w", padx=(4, 12))
        self.cmb_pump.current(0)
        self.cmb_pump.bind("<<ComboboxSelected>>", self._on_pump_changed)
        ttk.Label(top, text="标定时长(s)").grid(row=0, column=2, sticky="w")
        self.ent_duration = ttk.Entry(top, textvariable=self.duration_var, width=8)
        self.ent_duration.grid(row=0, column=3, sticky="w", padx=(4, 8))
        quick = ttk.Frame(top)
        quick.grid(row=0, column=4, sticky="w")
        self.quick_duration_buttons = []
        for seconds in PUMP_CAL_DURATION_OPTIONS:
            btn = ttk.Button(quick, text=str(seconds), command=lambda s=seconds: self.duration_var.set(str(s)))
            btn.pack(side=tk.LEFT, padx=2)
            self.quick_duration_buttons.append(btn)
        ttk.Label(top, text="液体名称").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.ent_liquid = ttk.Entry(top, textvariable=self.liquid_var, width=18)
        self.ent_liquid.grid(row=1, column=1, sticky="ew", padx=(4, 12), pady=(8, 0))
        ttk.Label(top, text="管规格").grid(row=1, column=2, sticky="w", pady=(8, 0))
        self.ent_tube = ttk.Entry(top, textvariable=self.tube_var, width=16)
        self.ent_tube.grid(row=1, column=3, sticky="ew", padx=(4, 12), pady=(8, 0))
        ttk.Label(top, text="泵/通道").grid(row=1, column=4, sticky="w", pady=(8, 0))
        self.ent_channel = ttk.Entry(top, textvariable=self.channel_var, width=14)
        self.ent_channel.grid(row=1, column=5, sticky="ew", padx=(4, 0), pady=(8, 0))
        ttk.Label(top, text="温度").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.ent_temperature = ttk.Entry(top, textvariable=self.temperature_var, width=18)
        self.ent_temperature.grid(row=2, column=1, sticky="ew", padx=(4, 12), pady=(8, 0))
        ttk.Label(top, text="备注").grid(row=2, column=2, sticky="w", pady=(8, 0))
        self.ent_note = ttk.Entry(top, textvariable=self.note_var, width=40)
        self.ent_note.grid(row=2, column=3, columnspan=3, sticky="ew", padx=(4, 0), pady=(8, 0))
        for col in (1, 3, 5):
            top.columnconfigure(col, weight=1)

        state = ttk.LabelFrame(main, text="运行状态", padding=8)
        state.pack(fill=tk.X, pady=(8, 0))
        self.lbl_support = ttk.Label(state, text="FCAL: --", font=("", 10, "bold"))
        self.lbl_support.pack(anchor=tk.W)
        self.lbl_state = ttk.Label(state, text="--", foreground="#555")
        self.lbl_state.pack(anchor=tk.W, pady=(4, 0))
        row = ttk.Frame(state)
        row.pack(fill=tk.X, pady=(6, 0))
        self.btn_prime = ttk.Button(row, text="开始预充", command=self._toggle_prime)
        self.btn_run = ttk.Button(row, text="开始标定", command=self._start_run)
        self.btn_stop = ttk.Button(row, text="立即停止", command=self._stop_run)
        self.btn_prime.pack(side=tk.LEFT, padx=(0, 4))
        self.btn_run.pack(side=tk.LEFT, padx=4)
        self.btn_stop.pack(side=tk.LEFT, padx=4)

        pending = ttk.LabelFrame(main, text="待回填运行", padding=8)
        pending.pack(fill=tk.X, pady=(8, 0))
        self.lbl_pending = ttk.Label(pending, text="暂无待回填运行")
        self.lbl_pending.grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(pending, text="量筒体积 (ml)").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(pending, textvariable=self.pending_volume_var, width=12).grid(row=1, column=1, sticky="w", padx=(4, 12), pady=(6, 0))
        ttk.Button(pending, text="保存为下一点", command=self._save_pending_point).grid(row=1, column=2, sticky="w", padx=(0, 4), pady=(6, 0))
        ttk.Button(pending, text="丢弃本次", command=self._discard_pending_run).grid(row=1, column=3, sticky="w", pady=(6, 0))

        points = ttk.LabelFrame(main, text="本次候选点位", padding=8)
        points.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        cols = ("idx", "plan", "actual", "volume", "flow", "flags")
        self.tree_points = ttk.Treeview(points, columns=cols, show="headings", height=5)
        headers = {
            "idx": "点位",
            "plan": "计划(s)",
            "actual": "MCU实际(s)",
            "volume": "体积(ml)",
            "flow": "单点流速",
            "flags": "标记",
        }
        widths = {"idx": 70, "plan": 90, "actual": 100, "volume": 100, "flow": 110, "flags": 180}
        for col in cols:
            self.tree_points.heading(col, text=headers[col])
            self.tree_points.column(col, width=widths[col], anchor=tk.CENTER)
        self.tree_points.pack(fill=tk.BOTH, expand=True)
        self.lbl_summary = ttk.Label(points, text="至少需 1 个有效点")
        self.lbl_summary.pack(anchor=tk.W, pady=(6, 0))
        rowp = ttk.Frame(points)
        rowp.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(rowp, text="保存记录", command=lambda: self._save_record(False)).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(rowp, text="保存并应用", command=lambda: self._save_record(True)).pack(side=tk.LEFT, padx=4)
        ttk.Button(rowp, text="清空本次点位", command=self._clear_points).pack(side=tk.LEFT, padx=4)

        hist = ttk.LabelFrame(main, text="历史记录", padding=8)
        hist.pack(fill=tk.X, pady=(8, 0))
        top_hist = ttk.Frame(hist)
        top_hist.pack(fill=tk.X)
        self.cmb_history = ttk.Combobox(top_hist, textvariable=self.history_var, state="readonly")
        self.cmb_history.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.cmb_history.bind("<<ComboboxSelected>>", lambda _e: self._refresh_history_detail())
        ttk.Button(top_hist, text="应用所选", command=self._apply_selected_history).pack(side=tk.LEFT, padx=4)
        ttk.Button(top_hist, text="删除所选", command=self._delete_selected_history).pack(side=tk.LEFT, padx=4)
        ttk.Button(top_hist, text="CSV导出", command=self._export_history_csv).pack(side=tk.LEFT, padx=4)
        self.lbl_history = ttk.Label(hist, text="--", justify=tk.LEFT)
        self.lbl_history.pack(anchor=tk.W, pady=(6, 0))

    def _selected_pump(self):
        value = self.pump_var.get()
        if value.startswith("A"):
            return "A"
        if value.startswith("W"):
            return "W"
        return "B"

    def _pump_name(self, pump=None):
        return self.parent.pump_flow_meta[pump or self._selected_pump()]["name"]

    def _selected_state(self):
        return self.parent.pump_flow_calibration[self._selected_pump()]

    def _duration_seconds(self):
        try:
            seconds = int(float(self.duration_var.get()))
        except ValueError:
            raise ValueError("标定时长必须是数字。")
        if seconds < PUMP_CAL_MIN_SECONDS or seconds > PUMP_CAL_MAX_SECONDS:
            raise ValueError(f"标定时长需在 {PUMP_CAL_MIN_SECONDS}-{PUMP_CAL_MAX_SECONDS} 秒之间。")
        return seconds

    def _session_locked(self):
        return bool(self.pending_run or self.pending_points)

    def _locked_pump(self):
        if self.pending_run:
            return self.pending_run.get("pump", "")
        if self.pending_points:
            return self.pending_points[0].get("pump", "")
        return self._locked_pump_code

    def _sync_lock_state(self):
        has_pending_points = bool(self.pending_points)
        has_pending_run = bool(self.pending_run)
        fcal_active = self.parent.fcal_status.get("state") in {"PRIME", "RUN"}
        pump_locked = has_pending_points or has_pending_run or fcal_active
        state = tk.DISABLED if pump_locked else "readonly"
        self.cmb_pump.config(state=state)
        point_limit_reached = len(self.pending_points) >= 3
        duration_locked = has_pending_run or fcal_active or point_limit_reached
        duration_state = tk.DISABLED if duration_locked else tk.NORMAL
        self.ent_duration.config(state=duration_state)
        for btn in self.quick_duration_buttons:
            btn.config(state=duration_state)
        meta_state = tk.DISABLED if pump_locked else tk.NORMAL
        for widget in (self.ent_liquid, self.ent_tube, self.ent_channel, self.ent_temperature, self.ent_note):
            widget.config(state=meta_state)
        if pump_locked:
            locked_pump = self._locked_pump() or self.parent.fcal_status.get("pump", "")
            if locked_pump:
                self.pump_var.set(f"{locked_pump} - {self.parent.pump_flow_meta[locked_pump]['name']}")

    def _on_pump_changed(self, _event=None):
        if self._session_locked():
            messagebox.showwarning("提示", "当前还有待保存的点位，请先保存或丢弃。")
            locked_pump = self._locked_pump() or "B"
            self.pump_var.set(f"{locked_pump} - {self.parent.pump_flow_meta[locked_pump]['name']}")
            return
        self._refresh_all()

    def _refresh_all(self):
        self._refresh_support()
        self._refresh_points_view()
        self._refresh_history_combo()
        self._refresh_history_detail()
        self._refresh_pending()
        self._sync_lock_state()

    def _refresh_support(self):
        if self.parent.fcal_supported:
            self.lbl_support.config(text=f"FCAL: {self.parent.fcal_capabilities or 'V1'}")
        else:
            self.lbl_support.config(text="FCAL: 未探测到支持")
        st = self.parent.fcal_status
        state_text = (
            f"状态: {st.get('state','--')}  泵: {st.get('pump','--')}  "
            f"计划: {st.get('plan_ms',0)/1000:.1f}s  已运行: {st.get('elapsed_ms',0)/1000:.1f}s"
        )
        if st.get("reason"):
            state_text += f"  原因: {st.get('reason')}"
        self.lbl_state.config(text=state_text)
        state = st.get("state")
        prime_running = state == "PRIME"
        run_running = state == "RUN"
        running = prime_running or run_running
        supported = self.parent.fcal_supported
        connected = self.parent._is_connected()
        point_limit_reached = len(self.pending_points) >= 3
        pending_refill = bool(self.pending_run)
        self.btn_prime.config(
            text="停止预充" if prime_running else "开始预充",
            state=tk.NORMAL if supported and connected and not run_running and not pending_refill and not point_limit_reached else tk.DISABLED,
        )
        self.btn_run.config(
            state=tk.NORMAL if supported and connected and not running and not pending_refill and not point_limit_reached else tk.DISABLED
        )
        self.btn_stop.config(state=tk.NORMAL if running else tk.DISABLED)

    def _refresh_pending(self):
        if not self.pending_run:
            self.lbl_pending.config(text="暂无待回填运行")
            return
        run = self.pending_run
        parts = [
            f"泵: {self.parent.pump_flow_meta[run['pump']]['name']}",
            f"事件: {run['mode']}",
            f"计划: {run['plan_ms']/1000:.1f}s",
            f"实际: {run['actual_ms']/1000:.3f}s",
        ]
        if run.get("reason"):
            parts.append(f"原因: {run['reason']}")
        if run.get("early_stop"):
            parts.append("提前停止有效")
        self.lbl_pending.config(text="  ".join(parts))

    def _refresh_points_view(self):
        self.tree_points.delete(*self.tree_points.get_children())
        for idx, point in enumerate(self.pending_points, start=1):
            flags = []
            if point.get("early_stop"):
                flags.append("提前停止")
            if point.get("warning"):
                flags.append(point["warning"])
            self.tree_points.insert("", tk.END, values=(
                f"P{idx}",
                f"{point['plan_s']:.1f}",
                f"{point['actual_s']:.3f}",
                f"{point['volume_ml']:.2f}",
                f"{point['flow_ml_s']:.4f}",
                " / ".join(flags) if flags else "--",
            ))
        self.lbl_summary.config(text=self._summary_text())

    def _summary_text(self):
        if not self.pending_points:
            return "至少需 1 个有效点"
        stats = self._point_stats(self.pending_points)
        count = len(self.pending_points)
        base = f"已采点 {count}/3 | 加权流速 {stats['weighted_flow']:.4f} ml/s | 算术均值 {stats['mean_flow']:.4f} ml/s"
        if count == 1:
            return base + " | 未验证重复性"
        if count == 2:
            return (
                base
                + f" | 两点差值 {stats['range_abs']:.4f} ml/s"
                + f" | 相对差异 {stats['range_rel_pct']:.1f}%"
            )
        return base + f" | 最大偏离均值 {stats['max_deviation_pct']:.1f}%"

    def _point_stats(self, points):
        total_vol = sum(p["volume_ml"] for p in points)
        total_s = sum(p["actual_s"] for p in points)
        weighted = total_vol / total_s if total_s > 0 else 0.0
        flows = [p["flow_ml_s"] for p in points]
        mean_flow = sum(flows) / len(flows) if flows else 0.0
        deviations = []
        if mean_flow > 0:
            deviations = [abs(flow - mean_flow) / mean_flow for flow in flows]
        range_abs = (max(flows) - min(flows)) if flows else 0.0
        range_rel_pct = (range_abs / mean_flow * 100.0) if mean_flow > 0 else 0.0
        return {
            "weighted_flow": weighted,
            "mean_flow": mean_flow,
            "max_deviation_pct": (max(deviations) * 100.0) if deviations else 0.0,
            "range_abs": range_abs,
            "range_rel_pct": range_rel_pct,
        }

    def _refresh_history_combo(self):
        self._history_records = self._selected_state().get("histories", [])
        current_id = ""
        idx = self.cmb_history.current()
        if 0 <= idx < len(self._history_records):
            current_id = self._history_records[idx].get("id", "")
        values = []
        for rec in self._history_records:
            active = " *" if rec.get("active") else ""
            values.append(f"{rec.get('id','--')} | {rec.get('weighted_flow',0):.4f} ml/s | {len(rec.get('points',[]))} 点{active}")
        self.cmb_history["values"] = values
        if values:
            new_index = 0
            for i, rec in enumerate(self._history_records):
                if rec.get("id", "") == current_id and current_id:
                    new_index = i
                    break
            self.cmb_history.current(new_index)
        else:
            self.history_var.set("")

    def _refresh_history_detail(self):
        idx = self.cmb_history.current()
        if idx < 0 or idx >= len(self._history_records):
            self.lbl_history.config(text="--")
            return
        rec = self._history_records[idx]
        self.lbl_history.config(text=(
            f"ID: {rec.get('id','--')}\n"
            f"加权流速: {rec.get('weighted_flow',0):.4f} ml/s\n"
            f"有效点数: {len(rec.get('points', []))} | 算术均值: {rec.get('mean_flow',0):.4f} ml/s | 最大偏离: {rec.get('max_deviation_pct',0):.1f}%\n"
            f"液体: {rec.get('liquid_name','')} | 管规格: {rec.get('tube_spec','')} | 泵/通道: {rec.get('channel','')}\n"
            f"温度: {rec.get('temperature','')} | 备注: {rec.get('note','')}"
        ))

    def on_fcal_update(self):
        st = self.parent.fcal_status
        self._refresh_support()
        if st.get("event") in {"DONE", "STOPPED", "ABORTED"}:
            self._accept_terminal_event(st)

    def on_parent_disconnect(self):
        if self.parent.fcal_status.get("state") in {"PRIME", "RUN"}:
            self.lbl_state.config(text="连接已断开，未完成标定作废。")
        self._refresh_support()

    def _can_start(self):
        if not self.parent._is_connected():
            messagebox.showwarning("提示", "当前未连接 Arduino，不能开始泵流量标定。")
            return False
        if not self.parent.fcal_supported:
            messagebox.showwarning("提示", "当前固件未支持泵流量标定，请先升级 MCU 固件。")
            return False
        reason = self.parent._pump_calibration_interlock_reason(include_candidate_points=False)
        if reason:
            messagebox.showwarning("提示", reason)
            return False
        if self.pending_run:
            messagebox.showwarning("提示", "请先保存或丢弃待回填运行。")
            return False
        if len(self.pending_points) >= 3:
            messagebox.showwarning("提示", "已达到3点，请保存记录、保存并应用或清空本次点位。")
            return False
        if self.parent.titration_enabled.get() or self.parent.titration_state != TitrationState.IDLE:
            messagebox.showwarning("提示", "PC 自动滴定未关闭，不能开始标定。")
            return False
        if self.parent.fcal_status.get("state") in {"PRIME", "RUN"}:
            messagebox.showwarning("提示", "已有正在进行的标定运行。")
            return False
        return True

    def _toggle_prime(self):
        if self.parent.fcal_status.get("state") == "PRIME":
            self.parent._send_cmd("FCAL STOP")
            return
        self._start_prime()

    def _start_prime(self):
        if not self._can_start():
            return
        pump = self._selected_pump()
        self.parent._send_cmd(f"FCAL PRIME {pump}")

    def _start_run(self):
        if not self._can_start():
            return
        try:
            seconds = self._duration_seconds()
        except ValueError as exc:
            messagebox.showwarning("提示", str(exc))
            return
        pump = self._selected_pump()
        liquid = self.liquid_var.get().strip() or self._pump_name(pump)
        prompt = (
            f"泵: {self._pump_name(pump)}\n"
            f"时长: {seconds}s\n"
            f"液体: {liquid}\n\n"
            "请确认出口已放入量筒，此次标定液不计入累计体积。"
        )
        if not messagebox.askyesno("安全确认", prompt):
            return
        self._locked_pump_code = pump
        self.parent._send_cmd(f"FCAL RUN {pump} {seconds}")

    def _stop_run(self):
        self.parent._send_cmd("FCAL STOP")

    def _accept_terminal_event(self, st):
        event = st.get("event")
        if event not in {"DONE", "STOPPED", "ABORTED"}:
            return
        mode = st.get("mode", "")
        actual_s = st.get("actual_ms", 0) / 1000.0
        self.pending_volume_var.set("")
        if mode == "PRIME":
            self.pending_run = None
            self.lbl_pending.config(text=f"预充结束: {st.get('reason','AUTO')}")
            return
        if event == "ABORTED":
            self.pending_run = None
            self.lbl_pending.config(text=f"本次运行无效: {st.get('reason','ERROR')}")
            return
        if event == "STOPPED" and st.get("reason") != "USER":
            self.pending_run = None
            self.lbl_pending.config(text=f"本次运行无效: {st.get('reason','ERROR')}")
            return
        if actual_s < PUMP_CAL_MIN_VALID_SECONDS and event != "DONE":
            self.pending_run = None
            self.lbl_pending.config(text=f"运行仅 {actual_s:.3f}s，小于 {PUMP_CAL_MIN_VALID_SECONDS}s，作废。")
            return
        self.pending_run = {
            "pump": st.get("pump") or self._selected_pump(),
            "mode": event,
            "plan_ms": st.get("plan_ms", 0),
            "actual_ms": st.get("actual_ms", 0),
            "reason": st.get("reason", ""),
            "early_stop": event == "STOPPED" and st.get("reason") == "USER",
        }
        self._refresh_pending()

    def _next_point_slot(self):
        return len(self.pending_points) + 1

    def _save_pending_point(self):
        if not self.pending_run:
            messagebox.showwarning("提示", "没有待回填运行。")
            return
        if len(self.pending_points) >= 3:
            messagebox.showwarning("提示", "每次最多 3 个点位。")
            return
        raw_volume = self.pending_volume_var.get().strip()
        if not re.fullmatch(r"\d+(?:\.\d{1,2})?", raw_volume):
            messagebox.showwarning("提示", "体积需为 0.01-5000.00 ml，且最多保留 2 位小数。")
            return
        try:
            volume = float(raw_volume)
        except ValueError:
            messagebox.showwarning("提示", "请输入合法的体积。")
            return
        if volume < PUMP_CAL_MIN_VOLUME_ML or volume > PUMP_CAL_MAX_VOLUME_ML:
            messagebox.showwarning("提示", f"体积需在 {PUMP_CAL_MIN_VOLUME_ML}-{PUMP_CAL_MAX_VOLUME_ML} ml 之间。")
            return
        actual_s = self.pending_run["actual_ms"] / 1000.0
        flow = volume / actual_s if actual_s > 0 else 0.0
        point = {
            "pump": self.pending_run["pump"],
            "plan_s": self.pending_run["plan_ms"] / 1000.0,
            "actual_s": actual_s,
            "volume_ml": round(volume, 2),
            "flow_ml_s": flow,
            "early_stop": bool(self.pending_run.get("early_stop")),
            "reason": self.pending_run.get("reason", ""),
        }
        self.pending_points.append(point)
        self._locked_pump_code = point["pump"]
        self.pending_run = None
        self.pending_volume_var.set("")
        self._mark_point_warnings()
        self._refresh_all()

    def _mark_point_warnings(self):
        if not self.pending_points:
            return
        stats = self._point_stats(self.pending_points)
        mean_flow = stats["mean_flow"]
        for point in self.pending_points:
            point.pop("warning", None)
            if mean_flow > 0:
                dev = abs(point["flow_ml_s"] - mean_flow) / mean_flow
                if dev > PUMP_CAL_WARN_DEVIATION:
                    point["warning"] = f"偏离 {dev*100:.1f}%"

    def _discard_pending_run(self):
        self.pending_run = None
        self.pending_volume_var.set("")
        self._refresh_pending()
        self._sync_lock_state()

    def _clear_points(self):
        if self.pending_run:
            messagebox.showwarning("提示", "请先处理待回填运行。")
            return
        self.pending_points = []
        self._locked_pump_code = ""
        self._refresh_points_view()
        self._sync_lock_state()

    def _build_record(self):
        if not self.pending_points:
            raise ValueError("至少需 1 个有效点。")
        ts = datetime.now()
        stats = self._point_stats(self.pending_points)
        return {
            "id": f"{self._selected_pump()}_{ts.strftime('%Y%m%d_%H%M%S_%f')}",
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "pump": self._selected_pump(),
            "liquid_name": self.liquid_var.get().strip(),
            "tube_spec": self.tube_var.get().strip(),
            "channel": self.channel_var.get().strip(),
            "temperature": self.temperature_var.get().strip(),
            "note": self.note_var.get().strip(),
            "points": [dict(p) for p in self.pending_points],
            "weighted_flow": stats["weighted_flow"],
            "mean_flow": stats["mean_flow"],
            "max_deviation_pct": stats["max_deviation_pct"],
            "range_abs": stats["range_abs"],
            "range_rel_pct": stats["range_rel_pct"],
            "point_count": len(self.pending_points),
            "active": False,
            "source": "calibration",
        }

    def _save_record(self, apply_now):
        try:
            rec = self._build_record()
        except ValueError as exc:
            messagebox.showwarning("提示", str(exc))
            return
        if rec["weighted_flow"] < PUMP_CAL_FLOW_MIN or rec["weighted_flow"] > PUMP_CAL_FLOW_MAX:
            if not messagebox.askyesno("再次确认", f"计算流速 {rec['weighted_flow']:.4f} ml/s 超出推荐范围，仍然保存吗？"):
                return
        state = self._selected_state()
        histories = state.setdefault("histories", [])
        histories.insert(0, rec)
        state["histories"] = histories[:PUMP_CAL_HISTORY_MAX]
        self.parent._save_config()
        self.pending_points = []
        self._locked_pump_code = ""
        self._refresh_all()
        if apply_now:
            self.parent._begin_flow_apply(self._selected_pump(), rec["weighted_flow"], "calibration", rec)
        else:
            messagebox.showinfo("已保存", "标定记录已保存。")

    def _apply_selected_history(self):
        idx = self.cmb_history.current()
        if idx < 0 or idx >= len(self._history_records):
            return
        rec = self._history_records[idx]
        if rec.get("weighted_flow", 0.0) < PUMP_CAL_FLOW_MIN or rec.get("weighted_flow", 0.0) > PUMP_CAL_FLOW_MAX:
            if not messagebox.askyesno("超范围确认", f"所选历史流速 {rec.get('weighted_flow', 0.0):.6f} ml/s 超出推荐范围，仍要应用吗？"):
                return
        if not messagebox.askyesno("确认应用", f"确认应用历史记录 {rec.get('id','--')} 到 {self._pump_name()} 吗？"):
            return
        self.parent._begin_flow_apply(self._selected_pump(), rec.get("weighted_flow", 0.0), "calibration", rec)

    def _delete_selected_history(self):
        idx = self.cmb_history.current()
        if idx < 0 or idx >= len(self._history_records):
            return
        rec = self._history_records[idx]
        if rec.get("active"):
            messagebox.showwarning("提示", "当前生效记录不能直接删除。")
            return
        if not messagebox.askyesno("确认", f"删除 {rec.get('id','--')} ？"):
            return
        state = self._selected_state()
        state["histories"] = [item for item in state.get("histories", []) if item.get("id") != rec.get("id")]
        self.parent._save_config()
        self._refresh_all()

    def _export_history_csv(self):
        state = self._selected_state()
        histories = state.get("histories", [])
        if not histories:
            messagebox.showwarning("提示", "没有可导出的标定历史。")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile=f"pump_cal_{self._selected_pump()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow([
                "pump", "id", "timestamp", "weighted_flow", "point_index", "plan_s", "actual_s",
                "volume_ml", "flow_ml_s", "early_stop", "reason", "max_deviation_pct",
                "liquid_name", "tube_spec", "channel", "temperature", "note", "active",
            ])
            for rec in histories:
                points = rec.get("points", []) or [{}]
                for idx, point in enumerate(points, start=1):
                    w.writerow([
                        rec.get("pump", ""),
                        rec.get("id", ""),
                        rec.get("timestamp", ""),
                        f"{rec.get('weighted_flow', 0):.6f}",
                        idx if rec.get("points") else "",
                        point.get("plan_s", ""),
                        point.get("actual_s", ""),
                        point.get("volume_ml", ""),
                        point.get("flow_ml_s", ""),
                        point.get("early_stop", False),
                        point.get("reason", ""),
                        f"{rec.get('max_deviation_pct', 0):.2f}",
                        rec.get("liquid_name", ""),
                        rec.get("tube_spec", ""),
                        rec.get("channel", ""),
                        rec.get("temperature", ""),
                        rec.get("note", ""),
                        rec.get("active", False),
                    ])
        messagebox.showinfo("导出成功", f"已导出到:\n{path}")

    def on_close(self):
        if self.parent.fcal_status.get("state") in {"PRIME", "RUN"}:
            self.parent._send_cmd("FCAL STOP")
            messagebox.showwarning("提示", "已请求立即停止，请等 MCU 确认后再关闭窗口。")
            return
        if self.pending_run or self.pending_points:
            if not messagebox.askyesno("确认", "仍有未保存的标定数据，确定丢弃吗？"):
                return
        self.parent.fcal_window = None
        self.destroy()


class ResultCalibrationWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent.root)
        self.parent = parent
        self.title("VFA / ALK 三点校正")
        self.geometry("1180x620")
        self.resizable(True, True)
        self.transient(parent.root)
        self.grab_set()

        self.selected_sample_var = tk.StringVar(value="")
        self.selected_note_var = tk.StringVar(value="")
        self.selected_result_var = tk.StringVar(value="")
        self._metrics = {"vfa": None, "alk": None}
        self._point_vars = []
        self._history_results = []
        self._selected_result = None

        self._build_ui()
        self._refresh_measurement_selector()
        self._refresh_history_boxes()

    def _build_ui(self):
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        latest = ttk.LabelFrame(main, text="测量结果选择", padding=6)
        latest.pack(fill=tk.X, pady=(0, 8))
        top_row = ttk.Frame(latest)
        top_row.pack(fill=tk.X)
        ttk.Label(top_row, text="历史测量").grid(row=0, column=0, sticky="w")
        self.cmb_measurements = ttk.Combobox(
            top_row,
            textvariable=self.selected_result_var,
            state="readonly",
            width=76,
        )
        self.cmb_measurements.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.cmb_measurements.bind("<<ComboboxSelected>>", self._on_measurement_selected)
        top_row.columnconfigure(1, weight=1)

        self.lbl_selected = ttk.Label(
            latest,
            text="暂无测量结果",
            font=("", 11, "bold"),
            justify=tk.LEFT,
            wraplength=1120,
        )
        self.lbl_selected.pack(anchor=tk.W, pady=(6, 0))
        latest.bind(
            "<Configure>",
            lambda event: self.lbl_selected.configure(wraplength=max(320, event.width - 16)),
        )

        meta = ttk.Frame(latest)
        meta.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(meta, text="样本名称").grid(row=0, column=0, sticky="w")
        ttk.Entry(meta, textvariable=self.selected_sample_var, width=18).grid(row=0, column=1, sticky="w", padx=(4, 12))
        ttk.Label(meta, text="备注").grid(row=0, column=2, sticky="w")
        ttk.Entry(meta, textvariable=self.selected_note_var, width=42).grid(row=0, column=3, sticky="ew", padx=(4, 0))
        meta.columnconfigure(3, weight=1)

        points = ttk.LabelFrame(main, text="三点校正数据", padding=6)
        points.pack(fill=tk.BOTH, expand=True)

        headers = [
            "点位",
            "测量ID",
            "测量时间",
            "VFA原始值",
            "VFA参考值",
            "ALK原始值",
            "ALK参考值",
            "样本名称",
            "备注",
            "操作",
        ]
        for col, header in enumerate(headers):
            ttk.Label(points, text=header, font=("", 10, "bold"), anchor=tk.CENTER, justify=tk.CENTER).grid(
                row=0, column=col, sticky="ew", padx=3, pady=(0, 4)
            )

        for idx in range(3):
            vars_row = {
                "measurement_id": tk.StringVar(value=""),
                "measurement_time": tk.StringVar(value=""),
                "raw_vfa": tk.StringVar(value=""),
                "ref_vfa": tk.StringVar(value=""),
                "raw_alk": tk.StringVar(value=""),
                "ref_alk": tk.StringVar(value=""),
                "sample": tk.StringVar(value=""),
                "note": tk.StringVar(value=""),
            }
            self._point_vars.append(vars_row)
            row = idx + 1
            ttk.Label(points, text=f"P{idx + 1}").grid(row=row, column=0, sticky="w", padx=3, pady=2)
            ttk.Entry(points, textvariable=vars_row["measurement_id"], width=16).grid(row=row, column=1, sticky="ew", padx=3)
            ttk.Entry(points, textvariable=vars_row["measurement_time"], width=16).grid(row=row, column=2, sticky="ew", padx=3)
            ttk.Entry(points, textvariable=vars_row["raw_vfa"], width=10).grid(row=row, column=3, sticky="ew", padx=3)
            ttk.Entry(points, textvariable=vars_row["ref_vfa"], width=10).grid(row=row, column=4, sticky="ew", padx=3)
            ttk.Entry(points, textvariable=vars_row["raw_alk"], width=10).grid(row=row, column=5, sticky="ew", padx=3)
            ttk.Entry(points, textvariable=vars_row["ref_alk"], width=10).grid(row=row, column=6, sticky="ew", padx=3)
            ttk.Entry(points, textvariable=vars_row["sample"], width=12).grid(row=row, column=7, sticky="ew", padx=3)
            ttk.Entry(points, textvariable=vars_row["note"], width=16).grid(row=row, column=8, sticky="ew", padx=3)
            ttk.Button(points, text="使用所选结果", command=lambda i=idx: self._assign_selected_to_point(i)).grid(
                row=row, column=9, sticky="ew", padx=3
            )

        for col in range(10):
            weight = 1 if col in (1, 2, 7, 8, 9) else 0
            minsize = 84 if col in (3, 4, 5, 6) else 0
            points.columnconfigure(col, weight=weight, minsize=minsize)

        action = ttk.Frame(main)
        action.pack(fill=tk.X, pady=(8, 0))
        action.columnconfigure(0, weight=1)

        self.lbl_vfa_metrics = ttk.Label(action, text="VFA：尚未计算")
        self.lbl_vfa_metrics.grid(row=0, column=0, sticky="w")
        ttk.Button(action, text="计算 VFA", command=lambda: self._compute("vfa")).grid(row=0, column=1, padx=4)
        ttk.Button(action, text="应用 VFA", command=lambda: self._apply("vfa")).grid(row=0, column=2, padx=4)

        self.lbl_alk_metrics = ttk.Label(action, text="ALK（碳酸氢根）：尚未计算")
        self.lbl_alk_metrics.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(action, text="计算 ALK", command=lambda: self._compute("alk")).grid(row=1, column=1, padx=4, pady=(6, 0))
        ttk.Button(action, text="应用 ALK", command=lambda: self._apply("alk")).grid(row=1, column=2, padx=4, pady=(6, 0))

        hist = ttk.LabelFrame(main, text="校正历史", padding=6)
        hist.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(hist, text="VFA").grid(row=0, column=0, sticky="w")
        self.cmb_vfa_hist = ttk.Combobox(hist, state="readonly", width=52)
        self.cmb_vfa_hist.grid(row=0, column=1, sticky="ew", padx=4)
        self.cmb_vfa_hist.bind("<<ComboboxSelected>>", lambda _event: self._activate_selected("vfa"))
        ttk.Label(hist, text="ALK（碳酸氢根）").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.cmb_alk_hist = ttk.Combobox(hist, state="readonly", width=52)
        self.cmb_alk_hist.grid(row=1, column=1, sticky="ew", padx=4, pady=(6, 0))
        self.cmb_alk_hist.bind("<<ComboboxSelected>>", lambda _event: self._activate_selected("alk"))
        hist.columnconfigure(1, weight=1)

    def _measurement_entry_text(self, result):
        return (
            f"{result['measurement_id']} | {result['timestamp']} | "
            f"VFA原始值 {result['vfa_raw']:.3f} | ALK原始值 {result['alk_raw']:.3f}"
        )

    def _refresh_measurement_selector(self):
        self._history_results = self.parent._get_measurement_history_snapshots()
        values = [self._measurement_entry_text(item) for item in self._history_results]
        self.cmb_measurements["values"] = values
        if values:
            self.cmb_measurements.current(0)
            self.selected_result_var.set(values[0])
            self._selected_result = self._history_results[0]
        else:
            self.selected_result_var.set("")
            self._selected_result = None
        self._refresh_selected_result_details()

    def _refresh_selected_result_details(self):
        result = self._selected_result
        if not result:
            self.lbl_selected.config(text="暂无测量结果")
            return
        self.lbl_selected.config(
            text=(
                f"测量ID {result['measurement_id']}  测量时间 {result['timestamp']}  "
                f"VFA原始值 {result['vfa_raw']:.3f} mmol/L  ALK原始值 {result['alk_raw']:.3f} mmol/L  "
                f"VFA {result['vfa']:.2f} mmol/L  ALK {result['alk']:.2f} mmol/L"
            )
        )

    def _on_measurement_selected(self, _event=None):
        idx = self.cmb_measurements.current()
        if idx < 0 or idx >= len(self._history_results):
            self._selected_result = None
        else:
            self._selected_result = self._history_results[idx]
        self._refresh_selected_result_details()

    def _assign_selected_to_point(self, idx):
        selected = self._selected_result
        if not selected:
            messagebox.showwarning("提示", "暂无可用于校正赋值的测量结果。")
            return
        row = self._point_vars[idx]
        if row["measurement_id"].get().strip():
            if not messagebox.askyesno("确认覆盖", f"是否替换点位 P{idx + 1} 的现有数据？"):
                return
        row["measurement_id"].set(selected["measurement_id"])
        row["measurement_time"].set(selected["timestamp"])
        row["raw_vfa"].set(f"{selected['vfa_raw']:.3f}")
        row["raw_alk"].set(f"{selected['alk_raw']:.3f}")
        row["sample"].set(self.selected_sample_var.get().strip())
        row["note"].set(self.selected_note_var.get().strip())

    def _collect_points(self, analyte):
        ref_key = "ref_vfa" if analyte == "vfa" else "ref_alk"
        raw_key = "raw_vfa" if analyte == "vfa" else "raw_alk"
        points = []
        ids = []
        for idx, row in enumerate(self._point_vars, start=1):
            mid = row["measurement_id"].get().strip()
            raw_s = row[raw_key].get().strip()
            ref_s = row[ref_key].get().strip()
            if not (mid and raw_s and ref_s):
                continue
            try:
                raw_v = float(raw_s)
                ref_v = float(ref_s)
            except ValueError:
                raise ValueError(f"点位 P{idx} 存在无效数值。")
            if raw_v <= 0 or ref_v <= 0:
                raise ValueError(f"点位 P{idx} 的原始值和参考值都必须大于 0。")
            ids.append(mid)
            points.append({
                "measurement_id": mid,
                "timestamp": row["measurement_time"].get().strip(),
                "raw_value": raw_v,
                "reference_value": ref_v,
                "raw_vfa": float(row["raw_vfa"].get().strip() or 0),
                "raw_alk": float(row["raw_alk"].get().strip() or 0),
                "sample_name": row["sample"].get().strip(),
                "note": row["note"].get().strip(),
            })
        if len(points) != 3:
            raise ValueError(f"{analyte.upper()} 校正需要恰好 3 个完整点位。")
        if len(set(ids)) != 3:
            raise ValueError("三个点位的测量 ID 必须互不相同。")
        return points

    def _compute(self, analyte):
        try:
            points = self._collect_points(analyte)
        except ValueError as exc:
            messagebox.showwarning("提示", str(exc))
            return
        denom = sum(p["raw_value"] ** 2 for p in points)
        if denom <= 0:
            messagebox.showerror("错误", "原始值无效，无法进行拟合。")
            return
        numer = sum(p["raw_value"] * p["reference_value"] for p in points)
        k = numer / denom
        preds = [k * p["raw_value"] for p in points]
        refs = [p["reference_value"] for p in points]
        sse = sum((pred - ref) ** 2 for pred, ref in zip(preds, refs))
        sst0 = sum(ref ** 2 for ref in refs)
        r2 = 1.0 - sse / sst0 if sst0 > 0 else 0.0
        max_rel = max(abs(pred - ref) / ref for pred, ref in zip(preds, refs))
        metrics = {
            "k": k,
            "r2": r2,
            "max_rel_error": max_rel,
            "points": points,
            "quality_ok": (
                RESULT_FACTOR_MIN <= k <= RESULT_FACTOR_MAX
                and r2 >= RESULT_MIN_R2
                and max_rel <= RESULT_MAX_REL_ERR
            ),
        }
        self._metrics[analyte] = metrics
        label_name = "VFA" if analyte == "vfa" else "ALK（碳酸氢根）"
        quality_text = "合格" if metrics["quality_ok"] else "不合格"
        text = f"{label_name}：K={k:.6f}  R²={r2:.4f}  最大相对误差={max_rel * 100:.1f}%  {quality_text}"
        if analyte == "vfa":
            self.lbl_vfa_metrics.config(text=text)
        else:
            self.lbl_alk_metrics.config(text=text)

    def _apply(self, analyte):
        metrics = self._metrics.get(analyte)
        if not metrics:
            messagebox.showwarning("提示", f"请先计算 {analyte.upper()} 的校正结果。")
            return
        if not metrics["quality_ok"]:
            messagebox.showwarning("提示", f"{analyte.upper()} 的拟合指标未达到应用阈值。")
            return
        rec = self.parent._create_result_calibration_record(analyte, metrics)
        self.parent._apply_result_calibration_record(analyte, rec)
        self._refresh_history_boxes()
        messagebox.showinfo("已应用", f"{analyte.upper()} 校正已应用?\nK={metrics['k']:.6f}")

    def _refresh_history_boxes(self):
        self.cmb_vfa_hist["values"] = self.parent._result_history_entries("vfa")
        self.cmb_alk_hist["values"] = self.parent._result_history_entries("alk")
        self.cmb_vfa_hist.set(self.parent._result_active_entry("vfa"))
        self.cmb_alk_hist.set(self.parent._result_active_entry("alk"))

    def _activate_selected(self, analyte):
        combo = self.cmb_vfa_hist if analyte == "vfa" else self.cmb_alk_hist
        idx = combo.current()
        if idx < 0:
            return
        self.parent._activate_result_history_index(analyte, idx)
        self._refresh_history_boxes()


# 主 GUI
class ORPMonitor:
    def __init__(self, root):
        self.root = root
        self.root.title("ORP/pH 监测上位机 v6")
        self.root.geometry("1350x1050")
        self.root.minsize(900, 600)

        plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "WenQuanYi Micro Hei"]
        plt.rcParams["axes.unicode_minus"] = False
        plt.rcParams["font.size"] = 12
        plt.rcParams["axes.titlesize"] = 14
        plt.rcParams["axes.labelsize"] = 12
        plt.rcParams["legend.fontsize"] = 10
        plt.rcParams["xtick.labelsize"] = 10
        plt.rcParams["ytick.labelsize"] = 10

        self.reader: SerialReader | None = None
        self.data_queue = queue.Queue()
        self.frame_count = 0

        self.status_text = "--"
        self.orp_adc = "--"
        self.orp_mv = "--"
        self.ph_value = None
        self.ph_text = "--"
        self.temp_adc = "--"
        self.temp_text = "--"

        self.pump_base = False
        self.pump_acid = False
        self.pump_water = False

        self.times = deque(maxlen=MAX_POINTS)
        self.ph_values = deque(maxlen=MAX_POINTS)

        # 公式
        self.ph_k = tk.DoubleVar(value=1.0 / 200.0)
        self.ph_b = tk.DoubleVar(value=4.0)
        self.mcu_ph_value = None
        self.mcu_ph_text = "--"
        self.applied_ph_k = float(self.ph_k.get())
        self.applied_ph_b = float(self.ph_b.get())
        self.ph_sync_ok = False

        # 流速
        self.flow_base = tk.DoubleVar(value=10.0)
        self.flow_acid = tk.DoubleVar(value=10.0)
        self.flow_water = tk.DoubleVar(value=10.0)
        self.applied_flow_values = {"B": 10.0, "A": 10.0, "W": 10.0}
        self.flow_source_labels = {}
        self.pump_flow_meta = {
            "B": {"name": "碱泵", "cmd": "FB", "var": self.flow_base},
            "A": {"name": "酸泵", "cmd": "FA", "var": self.flow_acid},
            "W": {"name": "水泵", "cmd": "FW", "var": self.flow_water},
        }
        self.pump_flow_calibration = {
            pump: {"active_id": "", "source": "default", "histories": []}
            for pump in self.pump_flow_meta
        }
        self.flow_apply_pending = None
        self._flow_apply_after_id = None
        self.fcal_supported = False
        self.fcal_capabilities = ""
        self.fcal_status = {
            "state": "UNSUPPORTED",
            "pump": "",
            "mode": "",
            "plan_ms": 0,
            "elapsed_ms": 0,
            "actual_ms": 0,
            "reason": "",
            "event": "",
        }
        self.fcal_window = None
        self.pump_flow_source_dirty = False
        self._disconnect_after_fcal_stop = False
        self._close_after_fcal_stop = False
        self._fcal_stop_timeout_id = None
        self._pending_disconnect_warning = False

        # VFA 参数
        self.acid_N = tk.DoubleVar(value=0.1)
        self.sample_ml = tk.DoubleVar(value=50.0)
        self.vfa_result_text = tk.StringVar(value="")
        self.kv = tk.DoubleVar(value=1.0)
        self.ka = tk.DoubleVar(value=1.0)
        self.latest_result_valid = False
        self.latest_result = None
        self.latest_measurement_seq = 0
        self.measurement_results = []
        self.pending_vfa_trace = None
        self.result_vfa_raw = None
        self.result_alk_raw = None
        self.result_vfa = None
        self.result_alk = None
        self.active_result_calibration_ids = {"vfa": "", "alk": ""}
        self.result_calibration_histories = {"vfa": [], "alk": []}
        self.vfa_active = False
        self.vfa_request_pending = False
        self.flow_state_known = False
        self.flow_state = ""
        self._disconnect_after_vfa_cancel = False
        self._close_after_vfa_cancel = False
        self._vfa_cancel_timeout_id = None

        # 累积体积
        self.vol_base = 0.0
        self.vol_acid = 0.0
        self.vol_water = 0.0

        # 数据记录
        self.recording = False
        self.record_rows = []

        # 滴定
        self.titration_enabled = tk.BooleanVar(value=False)
        self.titration_dir = tk.StringVar(value=TitrationDir.ADD_BASE.value)
        self.target_ph = tk.DoubleVar(value=5.0)
        self.trigger_ph = tk.DoubleVar(value=3.7)
        self.tolerance = tk.DoubleVar(value=0.2)
        self.mix_wait = tk.DoubleVar(value=5.0)

        self.titration_state = TitrationState.IDLE
        self._pump_timer_id = None
        self._wait_timer_id = None
        self.param_apply_pending = None
        self._param_apply_after_id = None
        self._sync_after_ids = []
        self._poll_queue_after_id = None

        self.debug_lines = deque(maxlen=50)
        self.calib_records = []
        self._build_ui()
        self._refresh_flow_source_labels()
        self._load_config()
        self._poll_queue()

    # ═══════════ UI ════════════════════════════════════════
    def _build_ui(self):
        # ── Root grid: 3 rows (top / mid / bottom), 1 column ──
        self.root.grid_rowconfigure(0, weight=0)  # top bar — fixed height
        self.root.grid_rowconfigure(1, weight=1)  # mid area — absorbs all extra space
        self.root.grid_rowconfigure(2, weight=0)  # bottom debug — fixed height
        self.root.grid_columnconfigure(0, weight=1)

        # Top bar
        top = ttk.Frame(self.root, padding=5)
        top.grid(row=0, column=0, sticky="ew")

        ttk.Label(top, text="COM口:").pack(side=tk.LEFT)
        self.combo_port = ttk.Combobox(top, width=14, state="readonly")
        self.combo_port.pack(side=tk.LEFT, padx=3)
        ttk.Button(top, text="刷新", command=self._refresh_ports).pack(side=tk.LEFT, padx=3)
        ttk.Label(top, text="波特率:").pack(side=tk.LEFT, padx=(10, 0))
        self.combo_baud = ttk.Combobox(
            top, width=8, values=["9600", "115200", "38400", "57600"], state="readonly")
        self.combo_baud.set(str(DEFAULT_BAUD))
        self.combo_baud.pack(side=tk.LEFT, padx=3)
        self.btn_connect = ttk.Button(top, text="连接", command=self._toggle_connect)
        self.btn_connect.pack(side=tk.LEFT, padx=10)
        self.lbl_conn_status = ttk.Label(top, text="未连接", foreground="gray")
        self.lbl_conn_status.pack(side=tk.LEFT, padx=10)

        # ── Mid area: 3-column grid (data | chart | titration) ──
        mid = ttk.Frame(self.root, padding=5)
        mid.grid(row=1, column=0, sticky="nsew")
        mid.grid_rowconfigure(0, weight=1)               # single row stretches vertically
        mid.grid_columnconfigure(0, weight=0, minsize=280)  # data panel — fixed width
        mid.grid_columnconfigure(1, weight=1)               # chart — the ONLY expanding column
        mid.grid_columnconfigure(2, weight=0, minsize=310)  # titration panel — fixed width

        self._build_data_panel(mid)
        self._build_chart(mid)
        self._build_titration_panel(mid)

        # ── Bottom: debug log + status bar ──
        bottom = ttk.Frame(self.root, padding=3)
        bottom.grid(row=2, column=0, sticky="ew")
        self._build_debug(bottom)
        self.status_bar = ttk.Label(bottom, text="就绪 | 帧数: 0", anchor=tk.W)
        self.status_bar.pack(fill=tk.X, pady=(3, 0))

        self._refresh_ports()

    def _build_data_panel(self, parent):
        # Scrollable wrapper so data panel is accessible on small windows
        outer = ttk.Frame(parent)
        outer.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

        canvas = tk.Canvas(outer, width=260, highlightthickness=0)
        self.data_canvas = canvas
        scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        panel = ttk.LabelFrame(canvas, text="实时数据", padding=8)
        win_id = canvas.create_window((0, 0), window=panel, anchor=tk.NW)

        def _configure_scroll(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        panel.bind("<Configure>", _configure_scroll)

        def _configure_width(event):
            canvas.itemconfig(win_id, width=event.width)
        canvas.bind("<Configure>", _configure_width)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        fields = [
            ("状态", "status_text"),
            ("ORP 内码", "orp_adc"),
            ("ORP 值 (mV)", "orp_mv"),
            ("pH 值", "ph_text"),
            ("温度内码", "temp_adc"),
            ("温度", "temp_text"),
        ]
        self.val_labels = {}
        for label, attr in fields:
            row = ttk.Frame(panel)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=label + ":", width=12, anchor=tk.E).pack(side=tk.LEFT)
            val = ttk.Label(row, text="--", font=("", 16, "bold"), width=14, anchor=tk.W)
            val.pack(side=tk.LEFT, padx=5)
            self.val_labels[attr] = val

        sep = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep.pack(fill=tk.X, pady=6)
        ttk.Label(panel, text="泵 / 累积体积", font=("", 11, "bold")).pack(anchor=tk.W, pady=(0, 4))

        self.pump_labels = {}
        self.vol_labels = {}
        for key, name in [
            ("pump_base_lbl", "碱泵"),
            ("pump_acid_lbl", "酸泵"),
            ("pump_water_lbl", "水泵"),
        ]:
            row = ttk.Frame(panel)
            row.pack(fill=tk.X, pady=2)
            row.columnconfigure(2, weight=1)

            ttk.Label(row, text=name + ":", width=6, anchor=tk.E).grid(
                row=0, column=0, sticky="w"
            )
            lbl = tk.Label(row, text="待机", font=("", 14, "bold"), width=6,
                          anchor=tk.CENTER, bg=PUMP_COLORS["idle"]["bg"],
                          fg=PUMP_COLORS["idle"]["fg"], relief=tk.SUNKEN)
            lbl.grid(row=0, column=1, sticky="w", padx=(6, 4))
            self.pump_labels[key] = lbl
            vol_lbl = ttk.Label(row, text="0.0 ml", font=("", 12), anchor=tk.E)
            vol_lbl.grid(row=0, column=2, sticky="ew")
            self.vol_labels[key] = vol_lbl

        # 记录状态指示
        sep2 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep2.pack(fill=tk.X, pady=6)
        self.lbl_record_status = tk.Label(panel, text="未记录", font=("", 12, "bold"),
                                          bg="#9E9E9E", fg="white", relief=tk.SUNKEN)
        self.lbl_record_status.pack(fill=tk.X, pady=2)

    def _build_chart(self, parent):
        frame = ttk.LabelFrame(parent, text="pH 实时曲线", padding=5)
        frame.grid(row=0, column=1, sticky="nsew", padx=5)

        self.fig, self.ax = plt.subplots(figsize=(5, 3.2), dpi=130)
        self.fig.patch.set_facecolor("#f0f0f0")
        self.ax.set_facecolor("#fafafa")
        self.ax.set_xlabel("时间")
        self.ax.set_ylabel("pH")
        self.ax.grid(True, linestyle="--", alpha=0.5)
        self.line_ph, = self.ax.plot([], [], "#4CAF50", linewidth=1.5, label="pH")
        self.line_target, = self.ax.plot([], [], "#FF9800", linewidth=1, linestyle="--", label="目标")
        self.line_trigger, = self.ax.plot([], [], "#F44336", linewidth=1, linestyle=":", label="触发线")
        self.ax.legend(loc="upper left", fontsize=8)
        self.fig.tight_layout(pad=2.0)
        self.canvas = FigureCanvasTkAgg(self.fig, master=frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _build_titration_panel(self, parent):
        # Scrollable outer container so content is accessible when window is short
        outer = ttk.Frame(parent)
        outer.grid(row=0, column=2, sticky="nsew", padx=(5, 0))

        canvas = tk.Canvas(outer, width=310, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Inner panel with all titration controls
        panel = ttk.LabelFrame(canvas, text="滴定控制", padding=8)
        win_id = canvas.create_window((0, 0), window=panel, anchor=tk.NW)

        # Keep scroll region in sync with content size
        def _configure_scroll(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        panel.bind("<Configure>", _configure_scroll)

        # Stretch inner panel to match canvas viewport width
        def _configure_width(event):
            canvas.itemconfig(win_id, width=event.width)
        canvas.bind("<Configure>", _configure_width)

        # Mouse-wheel scrolling over the titration panel
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        ttk.Checkbutton(panel, text="启用自动滴定", variable=self.titration_enabled,
                        command=self._on_titration_toggle).pack(anchor=tk.W, pady=(0, 4))

        # pH公式
        cal = ttk.LabelFrame(panel, text="pH 换算公式", padding=4)
        cal.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(cal, text="pH = ORP_mV × K + B", font=("", 11)).pack(anchor=tk.W)
        row = ttk.Frame(cal)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="K:").pack(side=tk.LEFT)
        self.ph_k_entry = ttk.Entry(row, textvariable=self.ph_k, width=10)
        self.ph_k_entry.pack(side=tk.LEFT, padx=2)
        ttk.Label(row, text="B:").pack(side=tk.LEFT, padx=(6, 0))
        self.ph_b_entry = ttk.Entry(row, textvariable=self.ph_b, width=8)
        self.ph_b_entry.pack(side=tk.LEFT, padx=2)
        ttk.Button(row, text="应用K/B", command=self._on_ph_calibration_commit).pack(side=tk.LEFT, padx=(6, 0))
        self.ph_k_entry.bind("<Return>", self._on_ph_calibration_commit)
        self.ph_k_entry.bind("<FocusOut>", self._on_ph_calibration_commit)
        self.ph_b_entry.bind("<Return>", self._on_ph_calibration_commit)
        self.ph_b_entry.bind("<FocusOut>", self._on_ph_calibration_commit)
        ttk.Button(cal, text="标定", command=self._open_calibration).pack(side=tk.RIGHT, padx=2)

        # 标定历史选择
        hist = ttk.Frame(cal)
        hist.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(hist, text="历史:", font=("", 9)).pack(side=tk.LEFT)
        self.calib_history_var = tk.StringVar(value="")
        self.calib_history_combo = ttk.Combobox(hist, textvariable=self.calib_history_var,
                                                state="readonly", width=28)
        self.calib_history_combo.pack(side=tk.LEFT, padx=3, fill=tk.X, expand=True)
        self.calib_history_combo.bind("<<ComboboxSelected>>", self._on_calib_history_selected)
        self.lbl_ph_sync = ttk.Label(cal, text="", font=("", 8), foreground="#A66")
        self.lbl_ph_sync.pack(anchor=tk.W, pady=(2, 0))
        self.lbl_calib_info = ttk.Label(hist, text="", font=("", 8), foreground="#888")
        self.lbl_calib_info.pack(side=tk.LEFT, padx=3)

        # 流速
        flow = ttk.LabelFrame(panel, text="泵流速 (ml/s)", padding=4)
        flow.pack(fill=tk.X, pady=(0, 4))
        for name, var, letter in [("碱泵", self.flow_base, "B"), ("酸泵", self.flow_acid, "A"), ("水泵", self.flow_water, "W")]:
            row = ttk.Frame(flow)
            row.pack(fill=tk.X, pady=1)
            ttk.Label(row, text=name, width=6).pack(side=tk.LEFT)
            ent = ttk.Entry(row, textvariable=var, width=8)
            ent.pack(side=tk.LEFT, padx=3)
            ent.bind("<Return>", lambda e, p=letter: self._apply_manual_flow(p))
            ttk.Button(row, text="应用", command=lambda p=letter: self._apply_manual_flow(p)).pack(side=tk.LEFT, padx=2)
            src = ttk.Label(row, text="来源: 默认", width=22, foreground="#666")
            src.pack(side=tk.LEFT, padx=(4, 0))
            self.flow_source_labels[letter] = src
        ttk.Button(flow, text="流量标定", command=self._open_pump_flow_calibration).pack(fill=tk.X, pady=(4, 0))

        # VFA 参数 + 测量
        self.vfa_frame = ttk.LabelFrame(panel, text="VFA/ALK测量（原样起始pH≥5.5）", padding=4)
        self.vfa_frame.pack(fill=tk.X, pady=(0, 4))
        row = ttk.Frame(self.vfa_frame)
        row.pack(fill=tk.X, pady=1)
        ttk.Label(row, text="酸浓度(N):", width=10).pack(side=tk.LEFT)
        ent_n = ttk.Entry(row, textvariable=self.acid_N, width=6)
        ent_n.pack(side=tk.LEFT, padx=2)
        ent_n.bind("<Return>", self._on_vfa_param_commit)
        ent_n.bind("<FocusOut>", self._on_vfa_param_commit)
        ttk.Label(row, text="样品(ml):", width=8).pack(side=tk.LEFT, padx=(6,0))
        ent_s = ttk.Entry(row, textvariable=self.sample_ml, width=6)
        ent_s.pack(side=tk.LEFT, padx=2)
        ent_s.bind("<Return>", self._on_vfa_param_commit)
        ent_s.bind("<FocusOut>", self._on_vfa_param_commit)
        row2 = ttk.Frame(self.vfa_frame)
        row2.pack(fill=tk.X, pady=(3, 0))
        row2.columnconfigure(0, weight=1)
        row2.columnconfigure(1, weight=1)
        self.btn_vfa_start = ttk.Button(row2, text="开始VFA/ALK", command=self._start_vfa_measurement)
        self.btn_vfa_cancel = ttk.Button(row2, text="取消", command=self._cancel_vfa_measurement)
        self.btn_vfa_reset = ttk.Button(row2, text="清结果", command=self._reset_results)
        self.btn_vfa_cal = ttk.Button(row2, text="校正", command=self._open_result_calibration)
        self.btn_vfa_start.grid(row=0, column=0, sticky="ew", padx=(0, 2), pady=(0, 2))
        self.btn_vfa_cancel.grid(row=0, column=1, sticky="ew", padx=(2, 0), pady=(0, 2))
        self.btn_vfa_reset.grid(row=1, column=0, sticky="ew", padx=(0, 2), pady=(2, 0))
        self.btn_vfa_cal.grid(row=1, column=1, sticky="ew", padx=(2, 0), pady=(2, 0))
        ttk.Label(
            self.vfa_frame,
            text="直接测原始样品；不要先调到普通目标pH",
            foreground="#666",
            wraplength=220,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(2, 0))

        self.lbl_vfa_result = ttk.Label(self.vfa_frame, text="VFA --.--  ALK --.--", font=("", 11, "bold"), foreground="#2196F3")
        self.lbl_vfa_result.pack(anchor=tk.W, pady=(4, 0))
        self.lbl_vfa_secondary = ttk.Label(self.vfa_frame, text="RAW -- / --   KV 1.000000  KA 1.000000", font=("", 9), foreground="#666")
        self.lbl_vfa_secondary.pack(anchor=tk.W, pady=(2, 0))
        self.lbl_vfa_measurement = ttk.Label(self.vfa_frame, text="ID --", font=("", 9), foreground="#666")
        self.lbl_vfa_measurement.pack(anchor=tk.W, pady=(2, 0))

        # 普通pH调节控制
        self.offline_flow_frame = ttk.LabelFrame(panel, text="普通pH调节（独立于VFA）", padding=4)
        self.offline_flow_frame.pack(fill=tk.X, pady=(4, 0))
        row3 = ttk.Frame(self.offline_flow_frame)
        row3.pack(fill=tk.X)
        ttk.Button(row3, text="启动", command=self._start_offline_flow).pack(side=tk.LEFT, padx=2)
        ttk.Button(row3, text="停止", command=self._stop_offline_flow).pack(side=tk.LEFT, padx=2)
        self.lbl_flow_state = ttk.Label(row3, text="", font=("", 10, "bold"), foreground="#4CAF50")
        self.lbl_flow_state.pack(side=tk.LEFT, padx=(8, 0))

        # 方向 + 参数
        dir_frame = ttk.LabelFrame(panel, text="滴定方向", padding=4)
        dir_frame.pack(fill=tk.X, pady=(0, 4))
        for d in [TitrationDir.ADD_BASE, TitrationDir.ADD_ACID]:
            ttk.Radiobutton(dir_frame, text=d.value, variable=self.titration_dir,
                           value=d.value).pack(anchor=tk.W)

        for label, var in [
            ("普通调节目标 pH:", self.target_ph),
            ("触发线:", self.trigger_ph),
            ("允许误差 (±):", self.tolerance),
            ("混合等待 (秒):", self.mix_wait),
        ]:
            row = ttk.Frame(panel)
            row.pack(fill=tk.X, pady=2)
            lbl = ttk.Label(row, text=label, width=16, anchor=tk.E)
            lbl.pack(side=tk.LEFT)
            if label.startswith("普通调节目标 pH"):
                self.target_ph_label = lbl
            entry = ttk.Entry(row, textvariable=var, width=8)
            entry.pack(side=tk.LEFT, padx=3)
            if label.startswith("普通调节目标 pH"):
                self.target_ph_entry = entry
                entry.bind("<Return>", self._on_target_ph_commit)
                entry.bind("<FocusOut>", self._on_target_ph_commit)

        # 手动控制
        sep = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep.pack(fill=tk.X, pady=6)

        ttk.Label(panel, text="手动控制", font=("", 11, "bold")).pack(anchor=tk.W)
        for name, on_fn, off_fn in [
            ("碱泵", self._base_on, self._base_off),
            ("酸泵", self._acid_on, self._acid_off),
            ("水泵", self._water_on, self._water_off),
        ]:
            row = ttk.Frame(panel)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=name, width=6).pack(side=tk.LEFT)
            ttk.Button(row, text="开", width=4, command=on_fn).pack(side=tk.LEFT, padx=1)
            ttk.Button(row, text="关", width=4, command=off_fn).pack(side=tk.LEFT, padx=1)
        ttk.Button(panel, text="全部停止", command=self._all_off).pack(fill=tk.X, pady=(3, 0))
        ttk.Button(panel, text="重置体积统计", command=self._reset_volumes).pack(fill=tk.X, pady=(3, 0))

        # 数据记录
        sep2 = ttk.Separator(panel, orient=tk.HORIZONTAL)
        sep2.pack(fill=tk.X, pady=6)

        ttk.Label(panel, text="数据记录", font=("", 11, "bold")).pack(anchor=tk.W)
        self.btn_record = ttk.Button(panel, text="开始记录", command=self._toggle_record)
        self.btn_record.pack(fill=tk.X, pady=3)

        # 策略
        info = ttk.LabelFrame(panel, text="分级策略", padding=4)
        info.pack(fill=tk.X, pady=(6, 0))
        for txt in ["差距>1.0 → 开泵 5秒", "0.5~1.0 → 2秒", "0.2~0.5 → 1秒", "<0.2  → 停止"]:
            ttk.Label(info, text=txt, font=("", 10)).pack(anchor=tk.W)

        # 状态提示
        self.lbl_titration_note = tk.Label(panel, text="", font=("", 12),
                                           fg="#666", wraplength=180, justify=tk.LEFT)
        self.lbl_titration_note.pack(fill=tk.X, pady=(4, 0))

    def _build_debug(self, parent):
        frame = ttk.LabelFrame(parent, text="调试日志", padding=3)
        frame.pack(fill=tk.BOTH, expand=True)
        self.debug_text = tk.Text(frame, height=5, font=("Consolas", 10),
                                  bg="#1e1e1e", fg="#d4d4d4",
                                  insertbackground="white", state=tk.DISABLED)
        scroll = ttk.Scrollbar(frame, command=self.debug_text.yview)
        self.debug_text.configure(yscrollcommand=scroll.set)
        self.debug_text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        scroll.pack(fill=tk.Y, side=tk.RIGHT)

    def _append_debug(self, text: str):
        self.debug_lines.append(text)
        self.debug_text.configure(state=tk.NORMAL)
        self.debug_text.delete("1.0", tk.END)
        self.debug_text.insert("1.0", "\n".join(self.debug_lines))
        self.debug_text.see(tk.END)
        self.debug_text.configure(state=tk.DISABLED)

    # ═══════════ 公式 / 标定 ═════════════════════════════
    def _orp_to_ph(self, orp_mv: float) -> float:
        return orp_mv * self.ph_k.get() + self.ph_b.get()

    def _controller_param_float(self, raw_value, field_name):
        try:
            return float(raw_value)
        except (TypeError, ValueError, tk.TclError):
            raise ValueError(f"{field_name} 必须是数字。")

    def _set_mcu_ph_sync(self, synced, note=None):
        self.ph_sync_ok = bool(synced)
        if synced:
            self.applied_ph_k = float(self.ph_k.get())
            self.applied_ph_b = float(self.ph_b.get())
        if hasattr(self, "lbl_ph_sync"):
            if note:
                text = note
            elif self.ph_sync_ok:
                text = f"MCU 已应用 K={self.applied_ph_k:.6f}, B={self.applied_ph_b:.4f}"
            else:
                text = (
                    f"本地 K/B={self.ph_k.get():.6f}/{self.ph_b.get():.4f}，"
                    f"MCU 已确认={self.applied_ph_k:.6f}/{self.applied_ph_b:.4f}"
                )
            self.lbl_ph_sync.config(text=text, foreground=("#2E7D32" if self.ph_sync_ok else "#A66"))

    def _update_host_ph_from_orp(self, orp_mv):
        ph = self._orp_to_ph(orp_mv)
        self.ph_value = ph
        self.ph_text = f"{ph:.2f}"
        self.times.append(time.time())
        self.ph_values.append(ph)
        return ph

    def _update_mcu_ph_diagnostic(self, ph_raw):
        self.mcu_ph_text = str(ph_raw)
        try:
            self.mcu_ph_value = float(ph_raw)
        except (TypeError, ValueError):
            self.mcu_ph_value = None

    def get_current_orp(self):
        """供标定窗口调用, 返回当前 ORP_mV 数值或 None"""
        if self.orp_mv and self.orp_mv != "--":
            try:
                return int(self.orp_mv)
            except ValueError:
                pass
        return None

    def _open_calibration(self):
        CalibrationWindow(self, self.get_current_orp)

    # ═══════════ 串口 ─════════════════════════════════════
    def _refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.combo_port["values"] = ports
        if ports and not self.combo_port.get():
            self.combo_port.set(ports[0])

    def _toggle_connect(self):
        if self.reader and self.reader.running:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        port = self.combo_port.get()
        baud = int(self.combo_baud.get())
        if not port:
            self.status_bar.config(text="请选择 COM 口")
            return
        self.btn_connect.config(text="连接中...", state=tk.DISABLED)
        self._append_debug(f"→ 尝试连接 {port} @ {baud} ...")
        self.reader = SerialReader(port, baud, self.data_queue)
        self.reader.start()
        # 连接后延迟同步流速+查询体积 (等Arduino启动完成)
        self.root.after(800, self._sync_to_arduino)

    def _finish_disconnect(self):
        self._cancel_timers()
        self._clear_vfa_activity()
        self.flow_state_known = False
        self.flow_state = ""
        self._set_mcu_ph_sync(False, "串口已断开，MCU pH 标定确认状态已清除。")
        self._disconnect_after_vfa_cancel = False
        self._close_after_vfa_cancel = False
        self._clear_vfa_cancel_wait()
        if self.fcal_window and self.fcal_window.winfo_exists():
            self.fcal_window.on_parent_disconnect()
        if self.reader:
            self.reader.stop()
            self.reader = None
        self._clear_fcal_support_state()
        self._clear_flow_apply_pending("连接已断开", restore_ui=True)
        self.btn_connect.config(text="连接", state=tk.NORMAL)
        self.lbl_conn_status.config(text="已断开", foreground="gray")
        self._update_all_pump_labels()

    def _clear_fcal_stop_wait(self):
        if self._fcal_stop_timeout_id:
            self.root.after_cancel(self._fcal_stop_timeout_id)
            self._fcal_stop_timeout_id = None

    def _clear_vfa_cancel_wait(self):
        if self._vfa_cancel_timeout_id:
            self.root.after_cancel(self._vfa_cancel_timeout_id)
            self._vfa_cancel_timeout_id = None

    def _finalize_post_fcal_stop(self):
        disconnect_after = self._disconnect_after_fcal_stop
        close_after = self._close_after_fcal_stop
        self._disconnect_after_fcal_stop = False
        self._close_after_fcal_stop = False
        self._clear_fcal_stop_wait()
        if disconnect_after:
            self._finish_disconnect()
        if close_after:
            self._finish_close()

    def _finalize_post_vfa_cancel(self):
        disconnect_after = self._disconnect_after_vfa_cancel
        close_after = self._close_after_vfa_cancel
        self._disconnect_after_vfa_cancel = False
        self._close_after_vfa_cancel = False
        self._clear_vfa_cancel_wait()
        if disconnect_after:
            self._finish_disconnect()
        if close_after:
            self._finish_close()

    def _fcal_stop_timeout(self):
        self._fcal_stop_timeout_id = None
        if self._disconnect_after_fcal_stop or self._close_after_fcal_stop:
            self._disconnect_after_fcal_stop = False
            self._close_after_fcal_stop = False
            self.lbl_titration_note.config(text="未确认停泵，已取消退出/断开，请使用立即停止或检查设备。")
            messagebox.showwarning(
                "停止确认超时",
                "未确认停泵，已取消退出/断开，请使用立即停止或检查设备，收到 MCU 终态后再重试。",
            )

    def _vfa_cancel_timeout(self):
        self._vfa_cancel_timeout_id = None
        if self._disconnect_after_vfa_cancel or self._close_after_vfa_cancel:
            self._disconnect_after_vfa_cancel = False
            self._close_after_vfa_cancel = False
            self.lbl_titration_note.config(text="未确认 VFA/ALK 已取消，已取消退出/断开，请检查设备后重试。")
            messagebox.showwarning(
                "取消确认超时",
                "未确认 VFA/ALK 已取消，已取消退出/断开，请先确认设备已停止反应后再重试。",
            )

    def _request_disconnect_or_close(self, close_app=False):
        if self.fcal_status.get("state") in {"PRIME", "RUN"} and self._is_connected():
            self._disconnect_after_fcal_stop = not close_app
            self._close_after_fcal_stop = close_app
            self._clear_fcal_stop_wait()
            self._send_cmd("FCAL STOP")
            self.lbl_titration_note.config(text="泵流量标定停止中，等待 MCU 终态确认...")
            self._fcal_stop_timeout_id = self.root.after(1500, self._fcal_stop_timeout)
            return True
        if self._vfa_interlock_active() and self._is_connected():
            self._disconnect_after_vfa_cancel = not close_app
            self._close_after_vfa_cancel = close_app
            self._clear_vfa_cancel_wait()
            self._send_cmd("VC")
            self.lbl_titration_note.config(text="VFA/ALK 取消中，等待 MCU 确认后再断开/退出...")
            self._vfa_cancel_timeout_id = self.root.after(1500, self._vfa_cancel_timeout)
            return True
        return False

    def _disconnect(self):
        if self._request_disconnect_or_close(close_app=False):
            return
        self._finish_disconnect()

    def _send_cmd(self, cmd: str):
        if self.reader and self.reader.running:
            self.reader.send(cmd)
            self._append_debug(f">>> {cmd}")
            return True
        else:
            self._append_debug(f">>> {cmd} (未连接!)")
            return False

    def _sync_to_arduino(self):
        """连接后同步所有参数到 Arduino EEPROM + 拉取体积"""
        self._send_cmd(f"FB {self._effective_flow_value('B'):.6f}")
        self._send_cmd(f"FA {self._effective_flow_value('A'):.6f}")
        self._send_cmd(f"FW {self._effective_flow_value('W'):.6f}")
        self._begin_runtime_param_sync(
            "连接参数同步",
            include_runtime=True,
            include_ph_cal=True,
            include_vfa=True,
        )
        self._sync_result_factors()
        self._sync_after_ids.append(self.root.after(300, lambda: self._send_cmd("RV")))
        self._sync_after_ids.append(self.root.after(450, lambda: self._send_cmd("RSTR")))
        self._sync_after_ids.append(self.root.after(600, self._probe_fcal_support))

    def _sync_result_factors(self):
        self._send_cmd(f"KV {self.kv.get():.6f}")
        self._send_cmd(f"KA {self.ka.get():.6f}")

    def _new_measurement_id(self):
        self.latest_measurement_seq += 1
        return datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{self.latest_measurement_seq:02d}"

    def _clear_latest_result(self):
        self.latest_result_valid = False
        self.latest_result = None
        self.result_vfa_raw = None
        self.result_alk_raw = None
        self.result_vfa = None
        self.result_alk = None
        self._refresh_result_labels()

    def _normalize_measurement_result(self, result):
        if not isinstance(result, dict):
            return None
        measurement_id = str(result.get("measurement_id", "")).strip()
        timestamp = str(result.get("timestamp", "")).strip()
        if not measurement_id or not timestamp:
            return None
        try:
            normalized = {
                "valid": bool(result.get("valid", True)),
                "measurement_id": measurement_id,
                "timestamp": timestamp,
                "vfa_raw": float(result.get("vfa_raw")),
                "alk_raw": float(result.get("alk_raw")),
                "vfa": float(result.get("vfa")),
                "alk": float(result.get("alk")),
            }
            optional_float_fields = (
                "ph0",
                "a1_ml",
                "a2_ml",
                "total_ml",
                "acid_n",
                "sample_ml",
                "blank_ml",
            )
            for key in optional_float_fields:
                if key in result and result.get(key) not in ("", None):
                    normalized[key] = float(result.get(key))
            return normalized
        except (TypeError, ValueError):
            return None

    def _append_measurement_result(self, result):
        normalized = self._normalize_measurement_result(result)
        if not normalized or not normalized.get("valid"):
            return
        measurement_id = normalized["measurement_id"]
        self.measurement_results = [
            item for item in self.measurement_results
            if item.get("measurement_id") != measurement_id
        ]
        self.measurement_results.insert(0, normalized)
        if len(self.measurement_results) > MEASUREMENT_HISTORY_MAX:
            self.measurement_results = self.measurement_results[:MEASUREMENT_HISTORY_MAX]
        self._save_config()

    def _get_measurement_history_snapshots(self):
        return [dict(item) for item in self.measurement_results]

    def _set_latest_result_from_controller(self, vfa_raw, alk_raw, vfa_corr, alk_corr, measurement_id=None, timestamp=None, append_history=False, trace=None):
        if measurement_id is None:
            measurement_id = self._new_measurement_id()
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.latest_result_valid = True
        self.result_vfa_raw = float(vfa_raw)
        self.result_alk_raw = float(alk_raw)
        self.result_vfa = float(vfa_corr)
        self.result_alk = float(alk_corr)
        self.latest_result = {
            "valid": True,
            "measurement_id": measurement_id,
            "timestamp": timestamp,
            "vfa_raw": self.result_vfa_raw,
            "alk_raw": self.result_alk_raw,
            "vfa": self.result_vfa,
            "alk": self.result_alk,
        }
        if isinstance(trace, dict):
            for key in ("ph0", "a1_ml", "a2_ml", "total_ml", "acid_n", "sample_ml", "blank_ml"):
                if key in trace and trace.get(key) is not None:
                    self.latest_result[key] = float(trace[key])
        if append_history:
            self._append_measurement_result(self.latest_result)
        self._refresh_result_labels()

    def _get_latest_result_snapshot(self):
        return dict(self.latest_result) if self.latest_result else None

    def _refresh_result_labels(self):
        if self.latest_result_valid and self.latest_result:
            self.lbl_vfa_result.config(text=f"VFA {self.result_vfa:.2f}  ALK {self.result_alk:.2f}")
            vfa_id = self.active_result_calibration_ids.get("vfa") or "1.0"
            alk_id = self.active_result_calibration_ids.get("alk") or "1.0"
            self.lbl_vfa_secondary.config(
                text=(
                    f"RAW {self.result_vfa_raw:.3f} / {self.result_alk_raw:.3f}   "
                    f"KV {self.kv.get():.6f} [{vfa_id}]  KA {self.ka.get():.6f} [{alk_id}]"
                )
            )
            self.lbl_vfa_measurement.config(
                text=f"ID {self.latest_result['measurement_id']}  {self.latest_result['timestamp']}"
            )
        else:
            self.lbl_vfa_result.config(text="VFA --.--  ALK --.--")
            self.lbl_vfa_secondary.config(
                text=(
                    f"RAW -- / --   KV {self.kv.get():.6f} [{self.active_result_calibration_ids.get('vfa') or '1.0'}]  "
                    f"KA {self.ka.get():.6f} [{self.active_result_calibration_ids.get('alk') or '1.0'}]"
                )
            )
            self.lbl_vfa_measurement.config(text="ID --")

    def _reset_results(self):
        self._send_cmd("RR")
        self._clear_latest_result()
        self._append_debug("→ Result reset requested")


    def _cancel_vfa_measurement(self):
        if self.fcal_status.get("state") in {"PRIME", "RUN"}:
            messagebox.showwarning("操作被阻止", "泵流量标定运行期间不能发送 VC。请使用立即停止。")
            self.lbl_titration_note.config(text="泵流量标定运行中，请使用立即停止。")
            return
        self._guard_vfa_measurement_interlock("取消 VFA/ALK", allow_cancel=True, show_warning=False)
        self._send_cmd("VC")



    def _stop_offline_flow(self):
        if self.fcal_status.get("state") in {"PRIME", "RUN"}:
            self._send_cmd("FCAL STOP")
            return
        if self._vfa_interlock_active():
            self._send_cmd("VC")
            return
        self._send_cmd("STOP")

    def _open_result_calibration(self):
        ResultCalibrationWindow(self)

    def _apply_ph_calibration_locally(self, ph_k, ph_b, status_text=None):
        self.ph_k.set(ph_k)
        self.ph_b.set(ph_b)
        self._save_config()
        self._set_mcu_ph_sync(False, status_text or "本地 pH 标定参数已更新，待同步 MCU。")

    def _on_ph_calibration_commit(self, _event=None):
        try:
            ph_k = self._controller_param_float(self.ph_k.get(), "pH K")
            ph_b = self._controller_param_float(self.ph_b.get(), "pH B")
        except ValueError as exc:
            messagebox.showwarning("参数无效", str(exc))
            self.lbl_titration_note.config(text=str(exc))
            return "break"
        self._apply_ph_calibration_locally(ph_k, ph_b)
        if self._is_connected():
            self._begin_runtime_param_sync("同步 pH 标定参数", include_ph_cal=True)
        else:
            self.lbl_titration_note.config(text="本地 pH 标定参数已保存，连接后会同步到 MCU。")
        return "break"

    def _on_vfa_param_commit(self, _event=None):
        self._save_config()
        if self._is_connected():
            self._begin_runtime_param_sync("同步 VFA 参数", include_vfa=True)
        return "break"

    def _start_vfa_measurement(self):
        if not self._guard_pump_calibration_interlock("VFA 测量启动"):
            return
        if self._flow_state_blocks_vfa_start():
            msg = f"当前 MCU FLOW 状态为 {self.flow_state or '--'}，请先停止或复位到空闲后再开始 VFA/ALK。"
            messagebox.showwarning("操作被阻止", msg)
            self.lbl_titration_note.config(text=msg)
            return
        if not self._is_connected():
            messagebox.showwarning("提示", "当前未连接 Arduino，不能开始 VFA/ALK 测量。")
            self.lbl_titration_note.config(text="未连接 Arduino，无法开始 VFA/ALK。")
            return
        if self._vfa_interlock_active():
            messagebox.showwarning("提示", "VFA/ALK 测量已经在进行中，如需停止请点“取消”。")
            self.lbl_titration_note.config(text="VFA/ALK 测量进行中，请勿重复启动。")
            return
        if self.ph_value is None or str(self.ph_text).strip() in {"", "--"}:
            messagebox.showwarning("提示", "当前还没有可用的 pH/EstPH，不能开始 VFA/ALK。请先连接并等待实时 pH 稳定显示。")
            self.lbl_titration_note.config(text="缺少当前 pH/EstPH，无法开始 VFA/ALK。")
            return
        if self.ph_value < 5.5:
            msg = (
                "联合 VFA/ALK 需要未经普通滴定的原始样品起始 pH>=5.5。\n"
                "不要先调到普通目标 5.0；本次没有产生新结果，应更换或重新取原始样品。"
            )
            messagebox.showwarning("起始样品不符合条件", msg)
            self.lbl_titration_note.config(text="起始 pH<5.5：请使用新的原始样品直接测量，本次无新结果。")
            return
        if self._has_local_titration_activity():
            msg = "PC 自动滴定或普通泵/混合仍在活动，不能开始 VFA/ALK。请先关闭自动滴定并等待泵停/混合完成。"
            messagebox.showwarning("操作被阻止", msg)
            self.lbl_titration_note.config(text=msg)
            return
        self._begin_runtime_param_sync(
            "VFA/ALK 测量启动",
            start_vfa=True,
            include_ph_cal=True,
            include_vfa=True,
        )

    def _on_target_ph_commit(self, _event=None):
        try:
            target = self._parse_bounded_float(self.target_ph.get(), "普通调节目标 pH", 0.0, 14.0)
        except ValueError as exc:
            messagebox.showwarning("参数无效", str(exc))
            self.lbl_titration_note.config(text=str(exc))
            return "break"
        self.target_ph.set(target)
        self._save_config()
        if self._is_connected():
            self._begin_runtime_param_sync("更新普通调节目标 pH", target_only=True)
        else:
            self.lbl_titration_note.config(text=f"普通调节目标 pH 已保存为 {target:.2f}，连接后会同步到 MCU。")
        return "break"

    def _start_offline_flow(self):
        if not self._guard_pump_calibration_interlock("脱机 START"):
            return
        if not self._guard_vfa_measurement_interlock("普通pH调节启动"):
            return
        self._begin_runtime_param_sync(
            "普通 pH 调节启动",
            start_after=True,
            include_runtime=True,
            include_ph_cal=True,
        )

    def _result_history_entries(self, analyte):
        entries = [f"\u672a\u6821\u6b63 1.0 ({analyte.upper()})"]
        for rec in self.result_calibration_histories.get(analyte, []):
            entries.append(
                f"{rec.get('label', rec.get('id','?'))}  K={rec.get('k',1.0):.6f}  "
                f"R\u00b2={rec.get('r2',0.0):.4f}  \u6700\u5927\u76f8\u5bf9\u8bef\u5dee={rec.get('max_rel_error',0.0)*100:.1f}%"
            )
        return entries

    def _result_active_entry(self, analyte):
        active_id = self.active_result_calibration_ids.get(analyte, "")
        if not active_id:
            return f"\u672a\u6821\u6b63 1.0 ({analyte.upper()})"
        for rec in self.result_calibration_histories.get(analyte, []):
            if rec.get("id") == active_id:
                return (
                    f"{rec.get('label', rec.get('id','?'))}  K={rec.get('k',1.0):.6f}  "
                    f"R\u00b2={rec.get('r2',0.0):.4f}  \u6700\u5927\u76f8\u5bf9\u8bef\u5dee={rec.get('max_rel_error',0.0)*100:.1f}%"
                )
        return f"\u672a\u6821\u6b63 1.0 ({analyte.upper()})"

    def _create_result_calibration_record(self, analyte, metrics):
        ts = datetime.now()
        rec = {
            "id": f"{analyte.upper()}_{ts.strftime('%Y%m%d_%H%M%S')}",
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "label": f"{analyte.upper()} {ts.strftime('%m-%d %H:%M')}",
            "analyte": analyte,
            "k": metrics["k"],
            "r2": metrics["r2"],
            "max_rel_error": metrics["max_rel_error"],
            "points": metrics["points"],
            "active": False,
        }
        hist = self.result_calibration_histories.setdefault(analyte, [])
        hist.insert(0, rec)
        if len(hist) > RESULT_HISTORY_MAX:
            self.result_calibration_histories[analyte] = hist[:RESULT_HISTORY_MAX]
            rec = self.result_calibration_histories[analyte][0]
        return rec

    def _apply_result_calibration_record(self, analyte, rec):
        hist = self.result_calibration_histories.setdefault(analyte, [])
        for item in hist:
            item["active"] = item.get("id") == rec.get("id")
        self.active_result_calibration_ids[analyte] = rec.get("id", "")
        if analyte == "vfa":
            self.kv.set(rec["k"])
        else:
            self.ka.set(rec["k"])
        if self.latest_result_valid:
            self.result_vfa = self.result_vfa_raw * self.kv.get()
            self.result_alk = self.result_alk_raw * self.ka.get()
            self.latest_result["vfa"] = self.result_vfa
            self.latest_result["alk"] = self.result_alk
        self._refresh_result_labels()
        self._save_config()
        self._sync_result_factors()

    def _activate_result_history_index(self, analyte, idx):
        if idx <= 0:
            self.active_result_calibration_ids[analyte] = ""
            for item in self.result_calibration_histories.get(analyte, []):
                item["active"] = False
            if analyte == "vfa":
                self.kv.set(1.0)
            else:
                self.ka.set(1.0)
        else:
            hist = self.result_calibration_histories.get(analyte, [])
            rec_idx = idx - 1
            if rec_idx >= len(hist):
                return
            self._apply_result_calibration_record(analyte, hist[rec_idx])
            return
        if self.latest_result_valid:
            self.result_vfa = self.result_vfa_raw * self.kv.get()
            self.result_alk = self.result_alk_raw * self.ka.get()
            self.latest_result["vfa"] = self.result_vfa
            self.latest_result["alk"] = self.result_alk
        self._refresh_result_labels()
        self._save_config()
        self._sync_result_factors()

    def _pump_flow_source_text(self, pump):
        state = self.pump_flow_calibration.get(pump, {})
        source = state.get("source", "default")
        if source == "manual":
            return "来源: 手动"
        if source == "calibration":
            active_id = state.get("active_id", "")
            return f"来源: 标定 {active_id or '--'}"
        return "来源: 默认"

    def _refresh_flow_source_labels(self):
        for pump, label in self.flow_source_labels.items():
            label.config(text=self._pump_flow_source_text(pump))

    def _effective_flow_value(self, pump):
        return float(self.applied_flow_values.get(pump, 0.0))

    def _restore_flow_entry(self, pump):
        self.pump_flow_meta[pump]["var"].set(self._effective_flow_value(pump))

    def _current_temperature_value(self):
        temp_text = str(getattr(self, "temp_text", "")).strip()
        try:
            return float(temp_text)
        except (TypeError, ValueError):
            return None

    def _fcal_window_has_pending_run(self):
        return bool(self.fcal_window and self.fcal_window.winfo_exists() and self.fcal_window.pending_run)

    def _fcal_window_has_candidate_points(self):
        return bool(self.fcal_window and self.fcal_window.winfo_exists() and self.fcal_window.pending_points)

    def _pump_calibration_interlock_reason(self, include_candidate_points=True):
        state = self.fcal_status.get("state", "")
        if state in {"PRIME", "RUN"}:
            return f"泵流量标定正在 {state}，仅允许立即停止。"
        if self._fcal_window_has_pending_run():
            return "泵流量标定仍有待回填运行，请先保存或丢弃。"
        if include_candidate_points and self._fcal_window_has_candidate_points():
            return "泵流量标定已有候选点，请先继续完成本轮、保存记录或清空本次点位。"
        return ""

    def _guard_pump_calibration_interlock(self, action_text, allow_stop=False, show_warning=True):
        reason = self._pump_calibration_interlock_reason()
        if not reason:
            return True
        if allow_stop:
            return True
        if show_warning:
            messagebox.showwarning("操作被阻止", f"{action_text}已被阻止。\n{reason}")
        self.lbl_titration_note.config(text=reason)
        return False

    def _vfa_interlock_active(self):
        return self.vfa_active or self.vfa_request_pending

    def _set_vfa_active(self, active, reason_text=""):
        self.vfa_active = bool(active)
        if active:
            self.vfa_request_pending = False
            self.pending_vfa_trace = None
        if reason_text:
            self.lbl_titration_note.config(text=reason_text)

    def _clear_vfa_activity(self, reason_text=""):
        self.vfa_active = False
        self.vfa_request_pending = False
        self.pending_vfa_trace = None
        if reason_text:
            self.lbl_titration_note.config(text=reason_text)

    def _vfa_measurement_interlock_reason(self):
        if not self._vfa_interlock_active():
            return ""
        if self.vfa_request_pending and not self.vfa_active:
            return "VFA/ALK 启动请求已发出，正在等待 MCU 响应，请勿并发启动普通泵、普通pH调节或PC自动滴定。"
        return "VFA/ALK 测量正在进行中，请勿并发启动普通泵、普通pH调节或PC自动滴定。需要停止时请点“取消”或“全部停止”。"

    def _guard_vfa_measurement_interlock(self, action_text, allow_cancel=False, show_warning=True):
        reason = self._vfa_measurement_interlock_reason()
        if not reason or allow_cancel:
            return True
        if show_warning:
            messagebox.showwarning("操作被阻止", f"{action_text}已被阻止。\n{reason}")
        self.lbl_titration_note.config(text=reason)
        return False

    def _flow_state_blocks_vfa_start(self):
        if not self.flow_state_known:
            return False
        state = (self.flow_state or "").strip().upper()
        return state not in {"", "IDLE", "STOP", "RESET"}

    def _has_local_titration_activity(self):
        return bool(
            self.titration_enabled.get()
            or self.titration_state != TitrationState.IDLE
            or self._pump_timer_id
            or self._wait_timer_id
            or self.pump_base
            or self.pump_acid
            or self.pump_water
        )

    def _is_connected(self):
        return bool(self.reader and self.reader.running)

    def _parse_bounded_float(self, raw_value, field_name, min_value, max_value):
        try:
            value = float(raw_value)
        except (TypeError, ValueError, tk.TclError):
            raise ValueError(f"{field_name} 必须是数字。")
        if not (min_value <= value <= max_value):
            raise ValueError(f"{field_name} 必须在 {min_value:g} - {max_value:g} 范围内。")
        return value

    def _runtime_param_payload(self, include_target_only=False):
        target = self._parse_bounded_float(self.target_ph.get(), "普通调节目标 pH", 0.0, 14.0)
        payload = {
            "TT": {"text": f"{target:.2f}", "value": target},
        }
        if include_target_only:
            return payload
        trigger = self._parse_bounded_float(self.trigger_ph.get(), "触发线", 0.0, 14.0)
        tolerance = self._parse_bounded_float(self.tolerance.get(), "允许误差", 0.001, 5.0)
        mix_wait = self._parse_bounded_float(self.mix_wait.get(), "混合等待", 0.5, 120.0)
        direction = 1 if self.titration_dir.get() == TitrationDir.ADD_ACID.value else 0
        payload.update({
            "TP": {"text": f"{trigger:.2f}", "value": trigger},
            "TL": {"text": f"{tolerance:.3f}", "value": tolerance},
            "TM": {"text": f"{mix_wait:.1f}", "value": mix_wait},
            "TD": {"text": str(direction), "value": direction},
        })
        return payload

    def _controller_param_payload(self, *, target_only=False, include_runtime=False, include_ph_cal=False, include_vfa=False):
        payload = {}
        if target_only or include_runtime:
            target_text = f"{self._parse_bounded_float(self.target_ph.get(), '普通调节目标 pH', 0.0, 14.0):.2f}"
            payload["TT"] = {"text": target_text, "value": float(target_text)}
        if include_runtime and not target_only:
            trigger_text = f"{self._parse_bounded_float(self.trigger_ph.get(), '触发线', 0.0, 14.0):.2f}"
            tolerance_text = f"{self._parse_bounded_float(self.tolerance.get(), '允许误差', 0.001, 5.0):.3f}"
            mix_wait_text = f"{self._parse_bounded_float(self.mix_wait.get(), '混合等待', 0.5, 120.0):.1f}"
            direction = 1 if self.titration_dir.get() == TitrationDir.ADD_ACID.value else 0
            payload.update({
                "TP": {"text": trigger_text, "value": float(trigger_text)},
                "TL": {"text": tolerance_text, "value": float(tolerance_text)},
                "TM": {"text": mix_wait_text, "value": float(mix_wait_text)},
                "TD": {"text": str(direction), "value": direction},
            })
        if include_ph_cal:
            ph_k_text = f"{self._controller_param_float(self.ph_k.get(), 'pH K'):.6f}"
            ph_b_text = f"{self._controller_param_float(self.ph_b.get(), 'pH B'):.4f}"
            payload.update({
                "TK": {"text": ph_k_text, "value": float(ph_k_text)},
                "TB": {"text": ph_b_text, "value": float(ph_b_text)},
            })
        if include_vfa:
            acid_n = self._controller_param_float(self.acid_N.get(), "标准酸浓度")
            sample_ml = self._controller_param_float(self.sample_ml.get(), "样品体积")
            if acid_n <= 0 or sample_ml <= 0:
                raise ValueError("标准酸浓度和样品体积必须大于 0。")
            acid_text = f"{acid_n:.6f}"
            sample_text = f"{sample_ml:.3f}"
            payload.update({
                "FN": {"text": acid_text, "value": float(acid_text)},
                "FS": {"text": sample_text, "value": float(sample_text)},
            })
        return payload

    def _clear_param_apply_pending(self):
        if self._param_apply_after_id:
            self.root.after_cancel(self._param_apply_after_id)
            self._param_apply_after_id = None
        pending = self.param_apply_pending
        self.param_apply_pending = None
        return pending






    def _param_apply_timeout(self):
        pending = self._clear_param_apply_pending()
        if not pending:
            return
        if pending.get("sync_ph"):
            self._set_mcu_ph_sync(False, "MCU pH 标定参数未确认，相关流程已阻止。")
        if pending.get("enable_titration"):
            self.titration_enabled.set(False)
        self.titration_state = TitrationState.IDLE
        self.lbl_titration_note.config(text=f"{pending['reason']} 参数下发超时，未启动。")
        messagebox.showwarning("参数未生效", f"{pending['reason']} 参数 ACK 超时，已取消本次操作。")

    def _can_upgrade_param_pending(self, pending, requested_keys, *, start_after=False, enable_titration=False, start_vfa=False):
        if not pending:
            return False
        if not (start_after or enable_titration or start_vfa):
            return False
        if pending.get("start_after") or pending.get("enable_titration") or pending.get("start_vfa"):
            return False
        return set(pending.get("params", {}).keys()) < set(requested_keys)

    def _begin_runtime_param_sync(self, reason_text, *, start_after=False, enable_titration=False, start_vfa=False,
                                  target_only=False, include_runtime=False, include_ph_cal=False, include_vfa=False):
        if not self._is_connected():
            if enable_titration:
                self.titration_enabled.set(False)
            messagebox.showwarning("提示", f"请先连接 Arduino，再执行“{reason_text}”。")
            self.lbl_titration_note.config(text=f"{reason_text}失败：未连接 Arduino。")
            return False
        try:
            params = self._controller_param_payload(
                target_only=target_only,
                include_runtime=include_runtime,
                include_ph_cal=include_ph_cal,
                include_vfa=include_vfa,
            )
        except ValueError as exc:
            if enable_titration:
                self.titration_enabled.set(False)
            messagebox.showwarning("参数无效", str(exc))
            self.lbl_titration_note.config(text=str(exc))
            return False
        if self.param_apply_pending and self._can_upgrade_param_pending(
            self.param_apply_pending,
            params.keys(),
            start_after=start_after,
            enable_titration=enable_titration,
            start_vfa=start_vfa,
        ):
            self._clear_param_apply_pending()
        elif self.param_apply_pending:
            if enable_titration:
                self.titration_enabled.set(False)
            messagebox.showwarning("提示", "当前仍有参数下发在等待 ACK，请稍后再试。")
            return False
        if not all(self._send_cmd(f"{cmd} {meta['text']}") for cmd, meta in params.items()):
            if enable_titration:
                self.titration_enabled.set(False)
            self.lbl_titration_note.config(text=f"{reason_text}失败：串口未连接。")
            return False
        self.param_apply_pending = {
            "reason": reason_text,
            "params": params,
            "remaining": set(params.keys()),
            "start_after": start_after,
            "enable_titration": enable_titration,
            "start_vfa": start_vfa,
            "sync_ph": include_ph_cal,
        }
        if include_ph_cal:
            self._set_mcu_ph_sync(False)
        self._param_apply_after_id = self.root.after(PARAM_APPLY_TIMEOUT_MS, self._param_apply_timeout)
        self.lbl_titration_note.config(text=f"{reason_text}参数下发中，等待 MCU 确认...")
        return True

    def _finish_runtime_param_sync(self, pending):
        target = pending["params"].get("TT", {}).get("value", self.target_ph.get())
        if pending.get("sync_ph"):
            self._set_mcu_ph_sync(True)
        if pending.get("start_after"):
            if not self._send_cmd("START"):
                self.lbl_titration_note.config(text=f"{pending['reason']}失败：串口未连接。")
                return
            self.lbl_titration_note.config(text=f"普通 pH 调节启动中，目标 {target:.2f}。")
            return
        if pending.get("start_vfa"):
            if not self._send_cmd("VF"):
                self.lbl_titration_note.config(text=f"{pending['reason']}失败：串口未连接。")
                return
            self.vfa_request_pending = True
            self.lbl_titration_note.config(text="已确认 VFA/ALK 所需参数，正在请求 MCU 开始测量...")
            return
        if pending.get("enable_titration"):
            self.titration_state = TitrationState.CHECKING
            self.lbl_titration_note.config(text=f"自动滴定已启用，目标 {target:.2f}，正在检查当前 pH。")
            self._titration_check()
            return
        if pending.get("sync_ph"):
            self.lbl_titration_note.config(text=f"MCU 已应用 pH 标定参数 K={self.applied_ph_k:.6f}, B={self.applied_ph_b:.4f}")
        else:
            self.lbl_titration_note.config(text=f"普通调节目标 pH 已确认：{target:.2f}")

    def _handle_runtime_param_reply(self, line):
        pending = self.param_apply_pending
        if not pending:
            return False
        for cmd, meta in pending["params"].items():
            if line.startswith(f"ACK:{cmd} "):
                ack_match = re.search(rf"ACK:{cmd}\s+([-]?\d+\.?\d*)", line)
                if not ack_match:
                    self._clear_param_apply_pending()
                    if pending.get("sync_ph"):
                        self._set_mcu_ph_sync(False, "MCU pH 标定参数未确认，相关流程已阻止。")
                    if pending.get("enable_titration"):
                        self.titration_enabled.set(False)
                    self.lbl_titration_note.config(text=f"{pending['reason']}失败：{cmd} ACK 格式错误。")
                    messagebox.showwarning("参数未生效", line)
                    return True
                ack_value = float(ack_match.group(1))
                expected = float(meta["value"])
                tol = 1e-6 if cmd in {"TD", "TK"} else 1e-3
                if abs(ack_value - expected) > tol:
                    self._clear_param_apply_pending()
                    if pending.get("sync_ph"):
                        self._set_mcu_ph_sync(False, "MCU pH 标定参数未确认，相关流程已阻止。")
                    if pending.get("enable_titration"):
                        self.titration_enabled.set(False)
                    self.lbl_titration_note.config(text=f"{pending['reason']}失败：{cmd} ACK 与请求不一致。")
                    messagebox.showwarning("参数未生效", line)
                    return True
                pending["remaining"].discard(cmd)
                if not pending["remaining"]:
                    done = self._clear_param_apply_pending()
                    if done:
                        self._save_config()
                        self._finish_runtime_param_sync(done)
                return True
            if line.startswith(f"ERR:{cmd}") or line.startswith(f"ACK:{cmd} BUSY"):
                self._clear_param_apply_pending()
                if pending.get("sync_ph"):
                    self._set_mcu_ph_sync(False, "MCU pH 标定参数未确认，相关流程已阻止。")
                if pending.get("enable_titration"):
                    self.titration_enabled.set(False)
                self.titration_state = TitrationState.IDLE
                self.lbl_titration_note.config(text=f"{pending['reason']}失败：{line}")
                messagebox.showwarning("参数未生效", line)
                return True
        return False

    def _clear_flow_apply_pending(self, reason_text="", restore_ui=False):
        if self._flow_apply_after_id:
            self.root.after_cancel(self._flow_apply_after_id)
            self._flow_apply_after_id = None
        pending = self.flow_apply_pending
        self.flow_apply_pending = None
        if pending and restore_ui:
            self._restore_flow_entry(pending["pump"])
        if reason_text:
            self.status_bar.config(text=f"Arduino: {reason_text} | 帧数: {self.frame_count}")
        return pending

    def _flow_apply_timeout(self):
        pending = self._clear_flow_apply_pending("流速应用超时", restore_ui=True)
        if pending:
            messagebox.showwarning("流速未生效", f"{self.pump_flow_meta[pending['pump']]['name']} 流速应用超时，已恢复为原生效值。")

    def _begin_flow_apply(self, pump, value, source, record=None):
        meta = self.pump_flow_meta[pump]
        if not self._is_connected():
            self._restore_flow_entry(pump)
            messagebox.showwarning("提示", "请先连接 Arduino，再应用新的泵流速。")
            return False
        if not self._guard_pump_calibration_interlock("流速应用"):
            self._restore_flow_entry(pump)
            return False
        if self.flow_apply_pending:
            messagebox.showwarning("提示", "当前仍有未完成的流速应用，请等待 ACK、ERR 或超时后再试。")
            self._restore_flow_entry(pump)
            return False
        expected_text = f"{float(value):.6f}"
        requested_value = float(expected_text)
        self.flow_apply_pending = {
            "pump": pump,
            "value": requested_value,
            "source": source,
            "record": record,
            "cmd": meta["cmd"],
            "expected_text": expected_text,
        }
        self._flow_apply_after_id = self.root.after(FLOW_APPLY_TIMEOUT_MS, self._flow_apply_timeout)
        self._send_cmd(f"{meta['cmd']} {expected_text}")
        self.status_bar.config(text=f"Arduino: 等待 {meta['cmd']} ACK | 帧数: {self.frame_count}")
        return True

    def _commit_flow_apply(self, pump, value, source, record=None):
        state = self.pump_flow_calibration.setdefault(pump, {"active_id": "", "source": "default", "histories": []})
        self.applied_flow_values[pump] = float(value)
        self.pump_flow_meta[pump]["var"].set(float(value))
        if source == "manual":
            state["source"] = "manual"
            state["active_id"] = ""
            for item in state.get("histories", []):
                item["active"] = False
        elif source == "calibration" and record:
            state["source"] = "calibration"
            state["active_id"] = record.get("id", "")
            for item in state.get("histories", []):
                item["active"] = item.get("id") == record.get("id")
        else:
            state["source"] = "default"
            state["active_id"] = ""
        self._refresh_flow_source_labels()
        self._save_config()

    def _apply_manual_flow(self, pump):
        meta = self.pump_flow_meta[pump]
        try:
            value = float(meta["var"].get())
        except (TypeError, ValueError):
            messagebox.showwarning("提示", "请输入合法的流速数值。")
            return
        if value <= 0:
            messagebox.showwarning("提示", "流速必须大于 0。")
            return
        if value < PUMP_CAL_FLOW_MIN or value > PUMP_CAL_FLOW_MAX:
            if not messagebox.askyesno("超范围确认", f"{meta['name']} 流速 {value:.6f} ml/s 超出推荐范围 {PUMP_CAL_FLOW_MIN}-{PUMP_CAL_FLOW_MAX}，仍要继续吗？"):
                self._restore_flow_entry(pump)
                return
        if not messagebox.askyesno("确认应用", f"确认将 {meta['name']} 流速应用为 {value:.6f} ml/s 吗？"):
            self._restore_flow_entry(pump)
            return
        self._begin_flow_apply(pump, value, "manual")

    def _open_pump_flow_calibration(self):
        if self.fcal_window and self.fcal_window.winfo_exists():
            self.fcal_window.lift()
            self.fcal_window.focus_force()
            return
        self.fcal_window = PumpFlowCalibrationWindow(self)

    def _clear_fcal_support_state(self):
        self.fcal_supported = False
        self.fcal_capabilities = ""
        self.fcal_status = {
            "state": "UNSUPPORTED",
            "pump": "",
            "mode": "",
            "plan_ms": 0,
            "elapsed_ms": 0,
            "actual_ms": 0,
            "reason": "",
            "event": "",
        }

    def _probe_fcal_support(self):
        self._clear_fcal_support_state()
        self._send_cmd("FCAL?")
        self._send_cmd("FCAL STATUS")

    def _update_volume_labels(self):
        self.vol_labels["pump_base_lbl"].config(text=f"{self.vol_base:.1f} ml")
        self.vol_labels["pump_acid_lbl"].config(text=f"{self.vol_acid:.1f} ml")
        self.vol_labels["pump_water_lbl"].config(text=f"{self.vol_water:.1f} ml")

    def _reset_volumes(self):
        self._send_cmd("RSTVOL")
        self.vol_base = 0.0
        self.vol_acid = 0.0
        self.vol_water = 0.0
        self._update_volume_labels()
        self._append_debug("→ 体积统计已重置 (PC + Arduino)")
        self.lbl_titration_note.config(text="体积已清零")

    # ═══════════ 配置持久化 ═════════════════════════════
    def _save_config(self):
        """保存标定历史、当前公式、流速等到 calibrations.json"""
        data = {
            "ph_k": self.ph_k.get(),
            "ph_b": self.ph_b.get(),
            "mcu_ph_k": self.applied_ph_k,
            "mcu_ph_b": self.applied_ph_b,
            "flow_base": self._effective_flow_value("B"),
            "flow_acid": self._effective_flow_value("A"),
            "flow_water": self._effective_flow_value("W"),
            "acid_N": self.acid_N.get(),
            "sample_ml": self.sample_ml.get(),
            "target_ph": self.target_ph.get(),
            "trigger_ph": self.trigger_ph.get(),
            "tolerance": self.tolerance.get(),
            "mix_wait": self.mix_wait.get(),
            "titration_dir": self.titration_dir.get(),
            "records": getattr(self, "calib_records", []),
            "result_calibration": {
                "kv": self.kv.get(),
                "ka": self.ka.get(),
                "active_ids": self.active_result_calibration_ids,
                "histories": self.result_calibration_histories,
                "measurement_history": self.measurement_results,
            },
            "pump_flow_calibration": self.pump_flow_calibration,
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self._append_debug(f"⚠ 保存配置失败: {e}")

    def _load_config(self):
        """从 calibrations.json 加载参数和标定历史"""
        if not os.path.exists(CONFIG_FILE):
            self._append_debug("→ 未找到配置文件, 使用默认参数")
            self.calib_records = []
            self.measurement_results = []
            self._refresh_calib_history()
            self._refresh_flow_source_labels()
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.ph_k.set(data.get("ph_k", self.ph_k.get()))
            self.ph_b.set(data.get("ph_b", self.ph_b.get()))
            self.applied_ph_k = float(data.get("mcu_ph_k", self.ph_k.get()))
            self.applied_ph_b = float(data.get("mcu_ph_b", self.ph_b.get()))
            self.ph_sync_ok = False
            self.flow_base.set(data.get("flow_base", self.flow_base.get()))
            self.flow_acid.set(data.get("flow_acid", self.flow_acid.get()))
            self.flow_water.set(data.get("flow_water", self.flow_water.get()))
            self.applied_flow_values["B"] = float(self.flow_base.get())
            self.applied_flow_values["A"] = float(self.flow_acid.get())
            self.applied_flow_values["W"] = float(self.flow_water.get())
            self.acid_N.set(data.get("acid_N", self.acid_N.get()))
            self.sample_ml.set(data.get("sample_ml", self.sample_ml.get()))
            self.target_ph.set(data.get("target_ph", self.target_ph.get()))
            self.trigger_ph.set(data.get("trigger_ph", self.trigger_ph.get()))
            self.tolerance.set(data.get("tolerance", self.tolerance.get()))
            self.mix_wait.set(data.get("mix_wait", self.mix_wait.get()))
            if "titration_dir" in data:
                self.titration_dir.set(data["titration_dir"])
            self.calib_records = data.get("records", [])
            result_cfg = data.get("result_calibration", {})
            self.kv.set(result_cfg.get("kv", 1.0))
            self.ka.set(result_cfg.get("ka", 1.0))
            if not (RESULT_FACTOR_MIN <= self.kv.get() <= RESULT_FACTOR_MAX):
                self.kv.set(1.0)
            if not (RESULT_FACTOR_MIN <= self.ka.get() <= RESULT_FACTOR_MAX):
                self.ka.set(1.0)
            histories = result_cfg.get("histories", {})
            self.result_calibration_histories = {
                "vfa": histories.get("vfa", [])[:RESULT_HISTORY_MAX],
                "alk": histories.get("alk", [])[:RESULT_HISTORY_MAX],
            }
            self.measurement_results = []
            for item in result_cfg.get("measurement_history", []):
                normalized = self._normalize_measurement_result(item)
                if normalized:
                    self.measurement_results.append(normalized)
            self.measurement_results = self.measurement_results[:MEASUREMENT_HISTORY_MAX]
            pump_flow_cfg = data.get("pump_flow_calibration", {})
            for pump in self.pump_flow_calibration:
                cfg = pump_flow_cfg.get(pump, {})
                state = self.pump_flow_calibration[pump]
                state["active_id"] = cfg.get("active_id", "")
                state["source"] = cfg.get("source", "default")
                state["histories"] = cfg.get("histories", [])[:PUMP_CAL_HISTORY_MAX]
            active_ids = result_cfg.get("active_ids", {})
            self.active_result_calibration_ids = {
                "vfa": active_ids.get("vfa", ""),
                "alk": active_ids.get("alk", ""),
            }
            for analyte in ("vfa", "alk"):
                hist = self.result_calibration_histories.get(analyte, [])
                active_id = self.active_result_calibration_ids.get(analyte, "")
                found = False
                for rec in hist:
                    rec["active"] = rec.get("id") == active_id and bool(active_id)
                    found = found or rec["active"]
                if active_id and not found:
                    self.active_result_calibration_ids[analyte] = ""
                    if analyte == "vfa":
                        self.kv.set(1.0)
                    else:
                        self.ka.set(1.0)
            self._refresh_calib_history()
            self._refresh_flow_source_labels()
            self._refresh_result_labels()
            self._set_mcu_ph_sync(False, "已加载本地 pH 标定参数，待连接后同步 MCU。")
            self._append_debug(f"✓ 已加载配置: K={self.ph_k.get():.6f}, B={self.ph_b.get():.4f}, "
                              f"标定记录 {len(self.calib_records)} 条")
        except Exception as e:
            self._append_debug(f"⚠ 加载配置失败: {e}")
            self.calib_records = []
            self.result_calibration_histories = {"vfa": [], "alk": []}
            self.active_result_calibration_ids = {"vfa": "", "alk": ""}
            self.measurement_results = []
            self.pump_flow_calibration = {
                pump: {"active_id": "", "source": "default", "histories": []}
                for pump in self.pump_flow_meta
            }
            self.applied_flow_values = {"B": 10.0, "A": 10.0, "W": 10.0}
            self.flow_base.set(10.0)
            self.flow_acid.set(10.0)
            self.flow_water.set(10.0)
            self.applied_ph_k = float(self.ph_k.get())
            self.applied_ph_b = float(self.ph_b.get())
            self.ph_sync_ok = False
            self.kv.set(1.0)
            self.ka.set(1.0)
            self._refresh_calib_history()
            self._refresh_flow_source_labels()
            self._refresh_result_labels()
            self._set_mcu_ph_sync(False, "使用本地默认 pH 标定参数，待连接后同步 MCU。")

    def _add_calibration_record(self, label, ph_k, ph_b, r2, points):
        """添加一条标定历史, 保存到文件"""
        ts = datetime.now()
        rec = {
            "id": ts.strftime("%Y%m%d_%H%M%S"),
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "label": label or ts.strftime("%m-%d %H:%M"),
            "ph_k": ph_k,
            "ph_b": ph_b,
            "r2": r2,
            "points": points,
        }
        if not hasattr(self, "calib_records"):
            self.calib_records = []
        self.calib_records.insert(0, rec)  # 最新的排前面
        # 最多保留 50 条
        if len(self.calib_records) > 50:
            self.calib_records = self.calib_records[:50]
        self._apply_ph_calibration_locally(ph_k, ph_b, "新 pH 标定记录已保存，待同步 MCU。")
        self._refresh_calib_history()
        if self._is_connected():
            self._begin_runtime_param_sync("同步 pH 标定参数", include_ph_cal=True)
        self._append_debug(f"✓ 标定已保存: {rec['label']} K={ph_k:.6f} B={ph_b:.4f} R²={r2:.4f}")

    def _refresh_calib_history(self):
        """刷新标定历史下拉框"""
        records = getattr(self, "calib_records", [])
        entries = ["— 默认 (K=1/200, B=4.0) —"]
        for r in records:
            label = r.get("label", r.get("id", "?"))
            n_pts = len(r.get("points", []))
            r2 = r.get("r2", 0)
            entries.append(f"{label}  {n_pts}点  R²={r2:.4f}")
        self.calib_history_combo["values"] = entries
        self.calib_history_var.set("")
        self.lbl_calib_info.config(text=f"共 {len(records)} 条记录")

    def _on_calib_history_selected(self, event):
        """用户在历史下拉框选择一条记录"""
        idx = self.calib_history_combo.current()
        if idx < 0:
            return
        if idx == 0:
            # 默认
            self._apply_ph_calibration_locally(1.0 / 200.0, 4.0, "已加载默认 pH 标定参数，待同步 MCU。")
            self.lbl_calib_info.config(text="已加载: 默认")
            self._append_debug("→ 加载标定: 默认公式")
            if self._is_connected():
                self._begin_runtime_param_sync("同步 pH 标定参数", include_ph_cal=True)
            return
        rec_idx = idx - 1
        records = getattr(self, "calib_records", [])
        if rec_idx < len(records):
            r = records[rec_idx]
            self._apply_ph_calibration_locally(r["ph_k"], r["ph_b"], "已加载 pH 标定历史，待同步 MCU。")
            info = f"已加载: {r.get('label','')} | {len(r.get('points',[]))}点 R²={r.get('r2',0):.4f}"
            self.lbl_calib_info.config(text=info)
            self._append_debug(f"→ 加载标定: {r.get('label','')} K={r['ph_k']:.6f} B={r['ph_b']:.4f}")
            if self._is_connected():
                self._begin_runtime_param_sync("同步 pH 标定参数", include_ph_cal=True)

    # ═══════════ 数据记录 ─══════════════════════════════
    def _toggle_record(self):
        if self.recording:
            self._stop_record()
        else:
            self._start_record()

    def _start_record(self):
        self.recording = True
        self.record_rows = []
        self.btn_record.config(text="停止并保存")
        self.lbl_record_status.config(text="记录中...", bg="#F44336")
        self._append_debug("→ 开始数据记录")
        # 同步初始pH到 OLED
        if self.ph_text and self.ph_text != "--":
            self._send_cmd(f"D0 {self.ph_text}")

    def _stop_record(self):
        self.recording = False
        self.btn_record.config(text="开始记录")
        self.lbl_record_status.config(text="未记录", bg="#9E9E9E")
        self._append_debug(f"→ 停止数据记录, 共 {len(self.record_rows)} 行")
        if self.record_rows:
            self._export_csv()
        else:
            messagebox.showinfo("提示", "没有记录到数据")

    def _export_csv(self):
        if not self.record_rows:
            messagebox.showinfo("提示", "没有可导出的数据")
            return

        os.makedirs(RECORD_DIR, exist_ok=True)
        default_name = f"滴定记录_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = filedialog.asksaveasfilename(
            initialdir=os.path.abspath(RECORD_DIR),
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")])
        if not path:
            return

        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["时间戳", "pH值", "ORP_mV", "ORP内码", "温度",
                        "碱泵", "酸泵", "水泵", "碱体积(ml)", "酸体积(ml)", "水体积(ml)",
                        "VFA_RAW", "ALK_RAW", "VFA", "ALK", "KV", "KA", "VFA_CAL_ID", "ALK_CAL_ID"])
            w.writerows(self.record_rows)

        self._append_debug(f"→ CSV 已导出: {path}")
        self.status_bar.config(text=f"已导出: {os.path.basename(path)} | {len(self.record_rows)}行")
        messagebox.showinfo("导出成功", f"已保存到:\n{path}")

    def _add_record_row(self):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [
            ts,
            self.ph_text,
            self.orp_mv,
            self.orp_adc,
            self.temp_text,
            1 if self.pump_base else 0,
            1 if self.pump_acid else 0,
            1 if self.pump_water else 0,
            f"{self.vol_base:.1f}",
            f"{self.vol_acid:.1f}",
            f"{self.vol_water:.1f}",
            "" if self.result_vfa_raw is None else f"{self.result_vfa_raw:.3f}",
            "" if self.result_alk_raw is None else f"{self.result_alk_raw:.3f}",
            "" if self.result_vfa is None else f"{self.result_vfa:.3f}",
            "" if self.result_alk is None else f"{self.result_alk:.3f}",
            f"{self.kv.get():.6f}",
            f"{self.ka.get():.6f}",
            self.active_result_calibration_ids.get("vfa", ""),
            self.active_result_calibration_ids.get("alk", ""),
        ]
        self.record_rows.append(row)

    # ═══════════ 泵控制 ─═════════════════════════════════
    def _base_on(self):
        if not self._guard_pump_calibration_interlock("手动启动碱泵"):
            return
        if not self._guard_vfa_measurement_interlock("手动启动碱泵"):
            return
        self._send_cmd("B1")
        self.pump_base = True
        self._update_all_pump_labels()
        self.lbl_titration_note.config(text="手动: 碱泵运行中")

    def _base_off(self):
        if self.fcal_status.get("state") in {"PRIME", "RUN"}:
            if self.fcal_status.get("pump") == "B":
                self._send_cmd("FCAL STOP")
            else:
                self._guard_pump_calibration_interlock("手动停止碱泵")
            return
        if self._vfa_interlock_active():
            self._guard_vfa_measurement_interlock("手动停止碱泵")
            return
        self._send_cmd("B0")
        self.pump_base = False
        self._update_all_pump_labels()

    def _acid_on(self):
        if not self._guard_pump_calibration_interlock("手动启动酸泵"):
            return
        if not self._guard_vfa_measurement_interlock("手动启动酸泵"):
            return
        self._send_cmd("A1")
        self.pump_acid = True
        self._update_all_pump_labels()
        self.lbl_titration_note.config(text="手动: 酸泵运行中")

    def _acid_off(self):
        if self.fcal_status.get("state") in {"PRIME", "RUN"}:
            if self.fcal_status.get("pump") == "A":
                self._send_cmd("FCAL STOP")
            else:
                self._guard_pump_calibration_interlock("手动停止酸泵")
            return
        if self._vfa_interlock_active():
            self._guard_vfa_measurement_interlock("手动停止酸泵")
            return
        self._send_cmd("A0")
        self.pump_acid = False
        self._update_all_pump_labels()

    def _water_on(self):
        if not self._guard_pump_calibration_interlock("手动启动水泵"):
            return
        if not self._guard_vfa_measurement_interlock("手动启动水泵"):
            return
        self._send_cmd("W1")
        self.pump_water = True
        self._update_all_pump_labels()
        self.lbl_titration_note.config(text="手动: 水泵运行中")

    def _water_off(self):
        if self.fcal_status.get("state") in {"PRIME", "RUN"}:
            if self.fcal_status.get("pump") == "W":
                self._send_cmd("FCAL STOP")
            else:
                self._guard_pump_calibration_interlock("手动停止水泵")
            return
        if self._vfa_interlock_active():
            self._guard_vfa_measurement_interlock("手动停止水泵")
            return
        self._send_cmd("W0")
        self.pump_water = False
        self._update_all_pump_labels()

    def _all_off(self):
        self._cancel_timers()
        if self.fcal_status.get("state") in {"PRIME", "RUN"}:
            self._send_cmd("FCAL STOP")
            self.lbl_titration_note.config(text="泵流量标定停止中...")
            return
        if self._vfa_interlock_active():
            self._send_cmd("VC")
            self.lbl_titration_note.config(text="VFA/ALK 取消中...")
            return
        self._send_cmd("B0")
        self._send_cmd("A0")
        self._send_cmd("W0")
        self.pump_base = False
        self.pump_acid = False
        self.pump_water = False
        self._update_all_pump_labels()
        self.titration_state = TitrationState.IDLE
        self.lbl_titration_note.config(text="全部停止")

    def _update_all_pump_labels(self):
        self._update_pump_label("pump_base_lbl", self.pump_base)
        self._update_pump_label("pump_acid_lbl", self.pump_acid)
        self._update_pump_label("pump_water_lbl", self.pump_water)

    def _update_pump_label(self, key, running):
        if key in self.pump_labels:
            c = PUMP_COLORS["running"] if running else PUMP_COLORS["idle"]
            self.pump_labels[key].config(text="运行中" if running else "待机",
                                         bg=c["bg"], fg=c["fg"])

    def _get_pump_duration(self, gap: float) -> float:
        if gap > 1.0:
            return 5.0
        elif gap > 0.5:
            return 2.0
        elif gap > self.tolerance.get():
            return 1.0
        else:
            return 0.0

    def _cancel_timers(self):
        if self._pump_timer_id:
            self.root.after_cancel(self._pump_timer_id)
        if self._wait_timer_id:
            self.root.after_cancel(self._wait_timer_id)
        if self._param_apply_after_id:
            self.root.after_cancel(self._param_apply_after_id)
        for after_id in list(getattr(self, "_sync_after_ids", [])):
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass
        self._pump_timer_id = None
        self._wait_timer_id = None
        self._param_apply_after_id = None
        self._sync_after_ids = []

    # ═══════════ 滴定状态机 ══════════════════════════════

    def _titration_check(self):
        if not self.titration_enabled.get():
            return
        if self.param_apply_pending:
            return
        if self._pump_calibration_interlock_reason():
            return
        if self.vfa_active:
            return
        if self.ph_value is None:
            return
        if self.titration_state not in (TitrationState.IDLE, TitrationState.CHECKING):
            return

        target = self.target_ph.get()
        tol = self.tolerance.get()
        ph = self.ph_value
        gap_delta = target - ph
        if abs(gap_delta) <= tol:
            self.titration_state = TitrationState.IDLE
            self.lbl_titration_note.config(
                text=f"达标: pH {ph:.2f} ≈ {target}\n碱:{self.vol_base:.1f}ml 酸:{self.vol_acid:.1f}ml")
            self._send_cmd(f"D1 {self.vol_base:.1f}")
            self._send_cmd(f"D2 {self.vol_acid:.1f}")
            return

        is_add_base = gap_delta > 0
        self.titration_dir.set(TitrationDir.ADD_BASE.value if is_add_base else TitrationDir.ADD_ACID.value)
        gap = abs(gap_delta)
        duration = self._get_pump_duration(gap)
        if duration <= 0:
            self.lbl_titration_note.config(text=f"已达目标: pH {ph:.2f} ≈ {target}")
            self.titration_state = TitrationState.IDLE
            return

        pump_cmd = "B1" if is_add_base else "A1"
        show_name = "碱泵" if is_add_base else "酸泵"
        flow_val = self._effective_flow_value("B") if is_add_base else self._effective_flow_value("A")
        vol_est = flow_val * duration

        self._append_debug(f"→ 自动 {show_name} {duration}s (pH={ph:.2f}, gap={gap:.2f}, 预计+{vol_est:.1f}ml)")
        self._send_cmd(pump_cmd)
        if is_add_base:
            self.pump_base = True
        else:
            self.pump_acid = True
        self._update_all_pump_labels()

        self.titration_state = TitrationState.PUMPING
        self.lbl_titration_note.config(
            text=f"滴定: {show_name} {duration}s\n预计+{vol_est:.1f}ml, pH={ph:.2f}→{target}")

        stop_cb = self._pump_stop_base if is_add_base else self._pump_stop_acid
        self._pump_timer_id = self.root.after(int(duration * 1000), stop_cb)

    def _pump_stop_base(self):
        self._pump_stop(True)

    def _pump_stop_acid(self):
        self._pump_stop(False)

    def _pump_stop(self, is_add_base: bool):
        self._pump_timer_id = None
        pump_cmd = "B0" if is_add_base else "A0"
        self._send_cmd(pump_cmd)
        if is_add_base:
            self.pump_base = False
        else:
            self.pump_acid = False

        self._update_all_pump_labels()
        self.titration_state = TitrationState.WAITING
        wait_s = self.mix_wait.get()
        self.lbl_titration_note.config(text=f"混合等待... {wait_s}s")
        self._wait_timer_id = self.root.after(int(wait_s * 1000), self._wait_done)

    def _wait_done(self):
        self._wait_timer_id = None
        self.titration_state = TitrationState.CHECKING
        self.lbl_titration_note.config(text="检测中...")

    def _on_titration_toggle(self):
        if self.titration_enabled.get() and not self._guard_pump_calibration_interlock("启用自动滴定"):
            self.titration_enabled.set(False)
            return
        if self.titration_enabled.get() and not self._guard_vfa_measurement_interlock("启用自动滴定"):
            self.titration_enabled.set(False)
            return
        if self.titration_enabled.get():
            if not self._begin_runtime_param_sync(
                "启用自动滴定",
                enable_titration=True,
                include_runtime=True,
                include_ph_cal=True,
            ):
                self.titration_enabled.set(False)
            return
        self._clear_param_apply_pending()
        self._cancel_timers()
        self.titration_state = TitrationState.IDLE
        self.lbl_titration_note.config(text="已禁用")

    # ═══════════ 数据解析 ═══════════════════════════════
    # unified serial parser is defined below
    def _poll_queue(self):
        try:
            while True:
                msg = self.data_queue.get_nowait()
                kind, payload = msg

                if kind == "connected":
                    self.btn_connect.config(text="断开", state=tk.NORMAL)
                    self.lbl_conn_status.config(text=f"已连接: {payload}", foreground="green")
                    self.status_bar.config(text="已连接 | 等待数据... | 帧数: 0")
                    self.frame_count = 0
                    self.times.clear()
                    self.ph_values.clear()
                    self._append_debug(f"✓ 已连接 {payload}")
                    self._cancel_timers()
                    self._clear_vfa_activity()
                    self.flow_state_known = False
                    self.flow_state = ""
                    self.titration_state = TitrationState.IDLE

                elif kind == "disconnected":
                    self._append_debug("✗ 串口断开")
                    self._clear_flow_apply_pending("串口断开", restore_ui=True)
                    pending = self._clear_param_apply_pending()
                    if pending and pending.get("sync_ph"):
                        self._set_mcu_ph_sync(False, "串口断开，MCU pH 标定确认状态已清除。")
                    if pending and pending.get("enable_titration"):
                        self.titration_enabled.set(False)
                    if self._vfa_interlock_active():
                        self._clear_vfa_activity("VFA/ALK 测量连接中断，本次无新结果。")
                    if self.fcal_status.get("state") in {"PRIME", "RUN"} and self.fcal_window and self.fcal_window.winfo_exists():
                        self.fcal_window.pending_run = None
                        self.fcal_window.lbl_pending.config(text="连接意外断开，本次运行作废。")
                    self._clear_fcal_support_state()
                    if self._disconnect_after_fcal_stop or self._close_after_fcal_stop:
                        self._finalize_post_fcal_stop()
                    else:
                        self._finish_disconnect()

                elif kind == "error":
                    self.lbl_conn_status.config(text="错误", foreground="red")
                    self.btn_connect.config(text="连接", state=tk.NORMAL)
                    self._append_debug(f"✗ 错误: {payload}")
                    if "Access" in payload or "denied" in payload.lower():
                        self._append_debug("  → 请关闭 Arduino IDE 串口监视器后重试")
                    self._clear_flow_apply_pending(f"串口错误: {payload}", restore_ui=True)
                    pending = self._clear_param_apply_pending()
                    if pending and pending.get("sync_ph"):
                        self._set_mcu_ph_sync(False, "串口错误，MCU pH 标定确认状态已清除。")
                    if pending and pending.get("enable_titration"):
                        self.titration_enabled.set(False)
                    self.reader = None
                    self._clear_fcal_support_state()
                    self._cancel_timers()
                    if self._vfa_interlock_active():
                        self._clear_vfa_activity("VFA/ALK 测量串口错误，本次无新结果。")
                    if self.fcal_window and self.fcal_window.winfo_exists():
                        self.fcal_window.pending_run = None
                        self.fcal_window.lbl_pending.config(text="串口错误，本次运行作废。")
                    if self._disconnect_after_fcal_stop or self._close_after_fcal_stop:
                        self._finalize_post_fcal_stop()

                elif kind == "line":
                    self._append_debug(f"← {payload}")
                    self._parse_line(payload)
                    if payload.startswith("STS:") or payload.startswith("状态: "):
                        self.frame_count += 1
                        self._update_display()
                        self._titration_check()
                        if self.recording:
                            self._add_record_row()
                            self.lbl_record_status.config(
                                text=f"记录中... {len(self.record_rows)}行", bg="#F44336")

        except queue.Empty:
            pass

        self._poll_queue_after_id = self.root.after(REFRESH_MS, self._poll_queue)

    def _update_display(self):
        for attr in ["status_text", "orp_adc", "orp_mv", "ph_text", "temp_adc", "temp_text"]:
            self.val_labels[attr].config(text=getattr(self, attr))

        self._update_volume_labels()

        self.status_bar.config(text=f"已连接 | 帧数: {self.frame_count} | ~2Hz")

        if len(self.times) >= 2:
            t = list(self.times)
            self.line_ph.set_xdata(t)
            self.line_ph.set_ydata(list(self.ph_values))
            if t:
                target = self.target_ph.get()
                trigger = self.trigger_ph.get()
                self.line_target.set_xdata([t[0], t[-1]])
                self.line_target.set_ydata([target, target])
                self.line_trigger.set_xdata([t[0], t[-1]])
                self.line_trigger.set_ydata([trigger, trigger])
            self.ax.relim()
            self.ax.autoscale_view(scalex=True, scaley=True)
            t0, t1 = t[0], t[-1]
            if t1 - t0 < DATA_WINDOW:
                self.ax.set_xlim(t0, t0 + DATA_WINDOW)
            else:
                self.ax.set_xlim(t1 - DATA_WINDOW, t1 + 5)
            self.canvas.draw_idle()

    def _parse_line(self, line: str):
        if line.startswith("泵状态: "):
            return
        if line.startswith("自算体积: ") or line.startswith("VOL:"):
            m = re.search(r"([\d.]+),([\d.]+),([\d.]+)", line)
            if m:
                self.vol_base = float(m.group(1))
                self.vol_acid = float(m.group(2))
                self.vol_water = float(m.group(3))
                self._update_volume_labels()
            return
        if line.startswith("STS:"):
            self.status_text = line[4:].strip()
            return
        if line.startswith("ORPADC:"):
            self.orp_adc = line[7:].strip()
            return
        if line.startswith("ORPMV:"):
            m = re.search(r"([-]?\d+)", line)
            if m:
                orp = int(m.group(1))
                self.orp_mv = str(orp)
                self._update_host_ph_from_orp(orp)
            return
        if line.startswith("PH:"):
            m = re.search(r"([-]?\d+\.?\d*)", line)
            if m:
                self._update_mcu_ph_diagnostic(m.group(1))
            return
        if line.startswith("TADC:"):
            self.temp_adc = line[5:].strip()
            return
        if line.startswith("TEMP:"):
            self.temp_text = line[5:].strip()
            return
        if line.startswith("PUMP:"):
            m = re.fullmatch(r"PUMP:([01]),([01]),([01])", line.strip())
            if m:
                self.pump_base = m.group(1) == "1"
                self.pump_acid = m.group(2) == "1"
                self.pump_water = m.group(3) == "1"
                self._update_all_pump_labels()
            return
        if line.startswith("FCAL:CAPS"):
            self.fcal_supported = True
            self.fcal_capabilities = line.split(":", 1)[1].strip()
            self.fcal_status.update({"state": "IDLE", "event": "", "reason": ""})
            if self.fcal_window and self.fcal_window.winfo_exists():
                self.fcal_window.on_fcal_update()
            return
        if line.startswith("FCAL:STATE"):
            state_match = re.search(
                r"FCAL:STATE\s+([A-Z]+)(?:\s+PUMP:([A-Z]))?(?:\s+PLAN_MS:(\d+))?(?:\s+ELAPSED_MS:(\d+))?",
                line,
            )
            if state_match:
                mode = state_match.group(1) if state_match.group(1) in {"PRIME", "RUN"} else ""
                self.fcal_status.update({
                    "state": state_match.group(1),
                    "pump": state_match.group(2) or "",
                    "plan_ms": int(state_match.group(3) or 0),
                    "elapsed_ms": int(state_match.group(4) or 0),
                    "event": "",
                    "reason": "",
                    "mode": mode,
                })
                if self.fcal_window and self.fcal_window.winfo_exists():
                    self.fcal_window.on_fcal_update()
            return
        if line.startswith("FCAL:DONE") or line.startswith("FCAL:STOPPED") or line.startswith("FCAL:ABORTED"):
            previous_mode = self.fcal_status.get("mode") or self.fcal_status.get("state", "")
            term_match = re.search(
                r"FCAL:(DONE|STOPPED|ABORTED)\s+PUMP:([A-Z])(?:\s+MODE:([A-Z]+))?\s+PLAN_MS:(\d+)\s+ACTUAL_MS:(\d+)\s+REASON:([A-Z]+)",
                line,
            )
            if term_match:
                self.fcal_supported = True
                self.fcal_status.update({
                    "state": "IDLE",
                    "pump": term_match.group(2),
                    "mode": term_match.group(3) or previous_mode,
                    "plan_ms": int(term_match.group(4)),
                    "elapsed_ms": 0,
                    "actual_ms": int(term_match.group(5)),
                    "reason": term_match.group(6),
                    "event": term_match.group(1),
                })
                if self.fcal_window and self.fcal_window.winfo_exists():
                    self.fcal_window.on_fcal_update()
                if self._disconnect_after_fcal_stop or self._close_after_fcal_stop:
                    self._finalize_post_fcal_stop()
            return
        if line.startswith("RSTR:"):
            m = re.search(
                r"VALID=(\d+),KV:([-]?\d+\.?\d*),KA:([-]?\d+\.?\d*),"
                r"VFA_RAW:([-]?\d+\.?\d*),ALK_RAW:([-]?\d+\.?\d*),"
                r"VFA:([-]?\d+\.?\d*),ALK:([-]?\d+\.?\d*)",
                line,
            )
            if m:
                self.kv.set(float(m.group(2)))
                self.ka.set(float(m.group(3)))
                if m.group(1) == "1":
                    current = self.latest_result or {}
                    self._set_latest_result_from_controller(
                        float(m.group(4)),
                        float(m.group(5)),
                        float(m.group(6)),
                        float(m.group(7)),
                        measurement_id=current.get("measurement_id"),
                        timestamp=current.get("timestamp"),
                        append_history=False,
                    )
                else:
                    self._clear_latest_result()
                self._refresh_result_labels()
            return
        if line.startswith("VFA:START"):
            self._set_vfa_active(True, "VFA/ALK 正在观察原样起始 pH（10秒）...")
            self._append_debug("VFA measurement started: " + line)
            return
        if line.startswith("VFA:CANCELLED"):
            self._clear_vfa_activity("VFA/ALK 已取消，本次无新结果。")
            if self._disconnect_after_vfa_cancel or self._close_after_vfa_cancel:
                self._finalize_post_vfa_cancel()
            self._append_debug("VFA measurement cancelled")
            return
        if line.startswith("VFA:REJECT"):
            m = re.search(r"VFA:REJECT\s+(\w+)\s+AVG:([-]?\d+\.?\d*)\s+MIN:([-]?\d+\.?\d*)\s+MAX:([-]?\d+\.?\d*)", line)
            self._clear_vfa_activity()
            if m:
                code = m.group(1)
                avg = float(m.group(2))
                min_ph = float(m.group(3))
                max_ph = float(m.group(4))
                if code == "LOW_PH":
                    msg = (
                        f"VFA/ALK 已拒绝：10秒平均起始 pH={avg:.2f} < 5.50。\n"
                        "联合 VFA/ALK 需要未经普通滴定的原始样品；不要先调到普通目标 pH 5.0。\n"
                        "本次无新结果，请更换或重新取符合条件的原始样品。"
                    )
                    self.lbl_titration_note.config(text=f"VFA/ALK 失败：起始 pH 过低（10秒均值 {avg:.2f}），本次无新结果。")
                else:
                    msg = (
                        f"VFA/ALK 已拒绝：10秒极差 {max_ph - min_ph:.2f} > 0.10（AVG {avg:.2f}, MIN {min_ph:.2f}, MAX {max_ph:.2f}）。\n"
                        "本次无新结果，请等待样品稳定或重新取原始样品后再测。"
                    )
                    self.lbl_titration_note.config(text=f"VFA/ALK 失败：10秒极差过大（AVG {avg:.2f}），本次无新结果。")
                messagebox.showwarning("VFA/ALK 测量失败", msg)
            else:
                self.lbl_titration_note.config(text="VFA/ALK 被拒绝，本次无新结果。")
            self._append_debug(line)
            return
        if line.startswith("VFA:ADMIT"):
            self._set_vfa_active(True, "VFA/ALK 起始 pH 合格，开始酸滴定到 5.1 和 3.5。")
            self._append_debug(line)
            return
        if line.startswith("VFA:TRACE "):
            m = re.search(
                r"PH0:([-]?\d+\.?\d*),A1:([-]?\d+\.?\d*),A2:([-]?\d+\.?\d*),"
                r"TOTAL:([-]?\d+\.?\d*),FN:([-]?\d+\.?\d*),FS:([-]?\d+\.?\d*),BLANK:([-]?\d+\.?\d*)",
                line,
            )
            if m:
                self.pending_vfa_trace = {
                    "ph0": float(m.group(1)),
                    "a1_ml": float(m.group(2)),
                    "a2_ml": float(m.group(3)),
                    "total_ml": float(m.group(4)),
                    "acid_n": float(m.group(5)),
                    "sample_ml": float(m.group(6)),
                    "blank_ml": float(m.group(7)),
                }
            self._append_debug(line)
            return
        if line.startswith("VFA:CALC_ERROR"):
            self._clear_vfa_activity(
                "VFA/ALK 计算失败，本次无有效结果；已保留上一条有效结果，请检查端点与参数。"
            )
            messagebox.showwarning(
                "VFA/ALK 计算失败",
                f"{line}\n本次无有效结果，未写入新的测量历史，也未覆盖上一条有效结果。",
            )
            self._append_debug(line)
            return
        if line.startswith("VFA_RAW:"):
            m = re.search(
                r"VFA_RAW:([-]?\d+\.?\d*),ALK_RAW:([-]?\d+\.?\d*),"
                r"VFA:([-]?\d+\.?\d*),ALK:([-]?\d+\.?\d*)",
                line,
            )
            if m:
                trace = dict(self.pending_vfa_trace) if isinstance(self.pending_vfa_trace, dict) else None
                self._clear_vfa_activity()
                self._set_latest_result_from_controller(
                    float(m.group(1)),
                    float(m.group(2)),
                    float(m.group(3)),
                    float(m.group(4)),
                    append_history=True,
                    trace=trace,
                )
                self.lbl_titration_note.config(
                    text=f"VFA done\nVFA {self.result_vfa:.2f}  ALK {self.result_alk:.2f}"
                )
                self._append_debug(
                    f"Result raw/corrected: VFA={self.result_vfa_raw:.3f}/{self.result_vfa:.3f} "
                    f"ALK={self.result_alk_raw:.3f}/{self.result_alk:.3f}"
                )
            return
        if line.startswith("ACK:") or line.startswith("ERR:"):
            if self._handle_runtime_param_reply(line):
                self.status_bar.config(text=f"Arduino: {line} | 帧数: {self.frame_count}")
                return
            if line.startswith("ACK:VF BUSY"):
                self._clear_vfa_activity("VFA/ALK 启动被占用，请先停止当前流程或复位到空闲。")
                messagebox.showwarning("VFA/ALK 正忙", "VFA/ALK 正忙：MCU 当前忙，无法开始新的 VFA/ALK。请先停止或复位到空闲后重试。")
            elif line.startswith("ACK:VF OK"):
                self._set_vfa_active(True, "VFA/ALK 启动已被 MCU 接受，等待观察阶段反馈...")
            elif line.startswith("ACK:VC OK"):
                self._clear_vfa_activity("VFA/ALK 取消确认已收到。")
                if self._disconnect_after_vfa_cancel or self._close_after_vfa_cancel:
                    self._finalize_post_vfa_cancel()
            if self.flow_apply_pending:
                pending = self.flow_apply_pending
                expected = self.pump_flow_meta[pending["pump"]]["cmd"]
                if line.startswith(f"ACK:{expected} "):
                    ack_match = re.search(rf"ACK:{expected}\s+([-]?\d+\.?\d*)", line)
                    ack_value = float(ack_match.group(1)) if ack_match else None
                    self._clear_flow_apply_pending()
                    if ack_value is None or abs(ack_value - pending["value"]) > 1e-6:
                        self._restore_flow_entry(pending["pump"])
                        messagebox.showwarning("流速未生效", f"{expected} ACK 数值与请求不一致，已恢复旧生效值。\n{line}")
                    else:
                        self._commit_flow_apply(
                            pending["pump"],
                            pending["value"],
                            pending["source"],
                            pending.get("record"),
                        )
                elif line.startswith(f"ERR:{expected}") or line.startswith(f"ACK:{expected} BUSY"):
                    self._clear_flow_apply_pending(restore_ui=True)
                    messagebox.showwarning("流速未生效", line)
            if line.startswith("ERR:FCAL") or line.startswith("ACK:FCAL"):
                self.lbl_titration_note.config(text=line)
                if self.fcal_window and self.fcal_window.winfo_exists():
                    self.fcal_window._refresh_support()
            elif line.startswith("ACK:START BUSY"):
                self.lbl_titration_note.config(text=line)
            self.status_bar.config(text=f"Arduino: {line} | 帧数: {self.frame_count}")
            return
        if line.startswith("状态: "):
            self.status_text = line[4:]
            return
        if line.startswith("ORP内码: "):
            self.orp_adc = line[7:]
            return
        if line.startswith("ORP值: "):
            m = re.search(r"([-]?\d+)", line)
            if m:
                orp = int(m.group(1))
                self.orp_mv = str(orp)
                self._update_host_ph_from_orp(orp)
            return
        if line.startswith("pH值: "):
            m = re.search(r"([-]?\d+\.?\d*)", line)
            if m:
                self._update_mcu_ph_diagnostic(m.group(1))
            return
        if line.startswith("温度内码: "):
            self.temp_adc = line[7:]
            return
        if line.startswith("温度: "):
            self.temp_text = line[4:]
            return
        if line.startswith("流程状态: ") or line.startswith("FLOW:"):
            st = line.split(": ", 1)[-1].strip() if ": " in line else line[5:].strip()
            color = {"IDLE": "#4CAF50", "TITRATION": "#FF9800", "MIXING": "#2196F3", "VFA": "#9C27B0", "DONE": "#F44336"}
            self.lbl_flow_state.config(text=st, foreground=color.get(st, "#000"))
            self.flow_state_known = True
            self.flow_state = st
            flow_head = st.split()[0] if st else ""
            if flow_head == "VFA":
                self._set_vfa_active(True)
            elif flow_head in {"IDLE", "DONE", "STOP", "RESET"}:
                self._clear_vfa_activity()
            if st == "DONE":
                self.lbl_titration_note.config(text="Flow done")

    def _finish_close(self):
        self._cancel_timers()
        if self._poll_queue_after_id:
            self.root.after_cancel(self._poll_queue_after_id)
            self._poll_queue_after_id = None
        self._clear_fcal_stop_wait()
        self._clear_vfa_cancel_wait()
        self._save_config()
        if self.reader:
            self.reader.stop()
        self.root.destroy()

    def on_close(self):
        if self._request_disconnect_or_close(close_app=True):
            return
        if self.recording:
            self._stop_record()
        self._finish_close()


if __name__ == "__main__":
    # Windows 高DPI适配
    import sys
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # Per-monitor DPI
        except Exception:
            pass

    root = tk.Tk()

    # 全局字体放大 (基础字号从9→11)
    style = ttk.Style()
    style.configure(".", font=("Microsoft YaHei UI", 11))
    style.configure("TLabel", font=("Microsoft YaHei UI", 11))
    style.configure("TButton", font=("Microsoft YaHei UI", 11))
    style.configure("TCheckbutton", font=("Microsoft YaHei UI", 11))
    style.configure("TRadiobutton", font=("Microsoft YaHei UI", 11))
    style.configure("TEntry", font=("Microsoft YaHei UI", 11))
    style.configure("TCombobox", font=("Microsoft YaHei UI", 11))
    style.configure("TLabelframe.Label", font=("Microsoft YaHei UI", 11, "bold"))

    app = ORPMonitor(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()

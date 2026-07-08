import ast
import importlib.util
import json
import math
import tempfile
import types
import unittest
from pathlib import Path

import tkinter as tk


MODULE_PATH = next(Path(__file__).resolve().parents[1].glob("*/orp_monitor.py"))
SPEC = importlib.util.spec_from_file_location("orp_monitor_module", MODULE_PATH)
orp_monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(orp_monitor)

FIRMWARE_PATH = Path(__file__).resolve().parents[1] / "xy_orp_arduino" / "xy_orp_arduino.ino"


def vfa_reference_calc(ph0, stage1_ml, stage2_increment_ml, acid_n, sample_ml, blank_ml=0.25):
    k1 = 6.6e-7
    k2 = 2.4e-5
    h1 = 10 ** (-ph0)
    h2 = 10 ** (-5.1)
    h3 = 10 ** (-3.5)
    total_ml = stage1_ml + stage2_increment_ml
    v1_ml = stage1_ml
    v2_ml = total_ml - blank_ml
    c1 = v1_ml * acid_n / sample_ml
    c2 = v2_ml * acid_n / sample_ml
    a1 = (h2 - h1) / (k2 + h2)
    a2 = (h3 - h1) / (k2 + h3)
    b1 = (h2 - h1) / (k1 + h2)
    b2 = (h3 - h1) / (k1 + h3)
    den = b1 * a2 - b2 * a1
    vad = (c2 * b1 - c1 * b2) / den
    hco3 = (c1 * a2 - c2 * a1) / den
    vat = vad * (h1 + k2) / k2
    return {
        "vfa_raw": vat * 1000.0,
        "alk_raw": hco3 * 1000.0,
        "total_ml": total_ml,
        "v2_ml": v2_ml,
    }


class FakeMessageBox:
    def __init__(self):
        self.calls = []
        self.askyesno_result = True

    def showwarning(self, title, message):
        self.calls.append(("warning", title, message))
        return "ok"

    def showinfo(self, title, message):
        self.calls.append(("info", title, message))
        return "ok"

    def askyesno(self, title, message):
        self.calls.append(("askyesno", title, message))
        return self.askyesno_result


class FakeReader:
    def __init__(self):
        self.running = True
        self.stopped = False
        self.sent = []

    def send(self, cmd):
        self.sent.append(cmd)

    def stop(self):
        self.running = False
        self.stopped = True


class PumpFlowCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "calibrations.json"
        self._orig_config = orp_monitor.CONFIG_FILE
        self._orig_messagebox = orp_monitor.messagebox
        orp_monitor.CONFIG_FILE = str(self.config_path)
        self.fake_messagebox = FakeMessageBox()
        orp_monitor.messagebox = self.fake_messagebox

        self.root = tk.Tk()
        self.root.withdraw()
        self.monitor = orp_monitor.ORPMonitor(self.root)
        self.reader = FakeReader()
        self.monitor.reader = self.reader
        self.sent_cmds = []
        self.monitor._send_cmd = lambda cmd: self.sent_cmds.append(cmd) or True
        if getattr(self.monitor, "_poll_queue_after_id", None):
            self.monitor.root.after_cancel(self.monitor._poll_queue_after_id)
            self.monitor._poll_queue_after_id = None
        self.root.update_idletasks()

    def tearDown(self):
        try:
            try:
                self.monitor._cancel_timers()
            except Exception:
                pass
            if getattr(self.monitor, "_poll_queue_after_id", None):
                self.monitor.root.after_cancel(self.monitor._poll_queue_after_id)
                self.monitor._poll_queue_after_id = None
            if getattr(self.monitor, "_flow_apply_after_id", None):
                self.monitor.root.after_cancel(self.monitor._flow_apply_after_id)
                self.monitor._flow_apply_after_id = None
            if getattr(self.monitor, "_param_apply_after_id", None):
                self.monitor.root.after_cancel(self.monitor._param_apply_after_id)
                self.monitor._param_apply_after_id = None
            if getattr(self.monitor, "_fcal_stop_timeout_id", None):
                self.monitor.root.after_cancel(self.monitor._fcal_stop_timeout_id)
                self.monitor._fcal_stop_timeout_id = None
            if getattr(self.monitor, "_vfa_cancel_timeout_id", None):
                self.monitor.root.after_cancel(self.monitor._vfa_cancel_timeout_id)
                self.monitor._vfa_cancel_timeout_id = None
        except Exception:
            pass
        try:
            try:
                self.root.update_idletasks()
                self.root.update()
            except Exception:
                pass
            try:
                orp_monitor.plt.close(self.monitor.fig)
            except Exception:
                pass
            for child in list(self.root.winfo_children()):
                try:
                    child.destroy()
                except Exception:
                    pass
            self.root.destroy()
        except Exception:
            pass
        orp_monitor.CONFIG_FILE = self._orig_config
        orp_monitor.messagebox = self._orig_messagebox
        self.temp_dir.cleanup()

    def _open_window(self):
        window = orp_monitor.PumpFlowCalibrationWindow(self.monitor)
        self.monitor.fcal_window = window
        window.withdraw()
        self.root.update_idletasks()
        return window

    def _prime_vfa_start_conditions(self, ph=6.3):
        self.monitor.reader = FakeReader()
        self.monitor.ph_value = ph
        self.monitor.ph_text = f"{ph:.2f}"
        self.monitor.titration_enabled.set(False)
        self.monitor.titration_state = orp_monitor.TitrationState.IDLE
        self.monitor._pump_timer_id = None
        self.monitor._wait_timer_id = None
        self.monitor.pump_base = False
        self.monitor.pump_acid = False
        self.monitor.pump_water = False
        self.monitor.flow_state_known = False
        self.monitor.flow_state = ""

    def _ack_vfa_preflight(self, ph_k=0.005000, ph_b=4.0000, acid_n=0.100000, sample_ml=50.000):
        self.monitor._parse_line(f"ACK:TK {ph_k:.6f}")
        self.monitor._parse_line(f"ACK:TB {ph_b:.4f}")
        self.monitor._parse_line(f"ACK:FN {acid_n:.6f}")
        self.monitor._parse_line(f"ACK:FS {sample_ml:.3f}")

    def _set_active_fcal(self, pump="B", state="RUN"):
        self.monitor.fcal_supported = True
        self.monitor.fcal_status.update({
            "state": state,
            "pump": pump,
            "mode": state,
            "plan_ms": 10000,
            "elapsed_ms": 2500,
            "actual_ms": 0,
            "reason": "",
            "event": "",
        })

    def _add_point(self, window, pump, plan_ms, actual_ms, volume_text, reason="AUTO", mode="DONE", early_stop=False):
        window.pending_run = {
            "pump": pump,
            "mode": mode,
            "plan_ms": plan_ms,
            "actual_ms": actual_ms,
            "reason": reason,
            "early_stop": early_stop,
        }
        window.pending_volume_var.set(volume_text)
        window._save_pending_point()

    def test_fcal_protocol_and_prime_run_handling(self):
        window = self._open_window()
        self.monitor._parse_line("FCAL:CAPS V1 PRIME RUN STOP STATUS")
        window.btn_prime.invoke()
        self.assertIn("FCAL PRIME B", self.sent_cmds)

        self.sent_cmds.clear()
        self.monitor._parse_line("FCAL:STATE PRIME PUMP:B PLAN_MS:30000 ELAPSED_MS:5000")
        self.assertEqual(window.btn_prime.cget("text"), "停止预充")
        self.assertEqual(str(window.btn_prime["state"]), "normal")
        window.btn_prime.invoke()
        self.assertIn("FCAL STOP", self.sent_cmds)

        self.sent_cmds.clear()
        self.monitor._parse_line("FCAL:STOPPED PUMP:B MODE:PRIME PLAN_MS:30000 ACTUAL_MS:6000 REASON:USER")
        self.assertEqual(window.btn_prime.cget("text"), "开始预充")

        self.monitor._parse_line("FCAL:STATE RUN PUMP:B PLAN_MS:10000 ELAPSED_MS:4000")
        self.monitor._parse_line("FCAL:DONE PUMP:B MODE:RUN PLAN_MS:10000 ACTUAL_MS:10000 REASON:AUTO")
        self.assertTrue(self.monitor.fcal_supported)
        self.assertIsNotNone(window.pending_run)
        self.assertEqual(window.pending_run["pump"], "B")
        self.assertEqual(window.pending_run["plan_ms"], 10000)

        window.pending_run = None
        self.monitor._parse_line("FCAL:STATE PRIME PUMP:A PLAN_MS:30000 ELAPSED_MS:5000")
        self.monitor._parse_line("FCAL:STOPPED PUMP:A MODE:PRIME PLAN_MS:30000 ACTUAL_MS:6000 REASON:USER")
        self.assertIsNone(window.pending_run)
        self.assertIn("预充结束", window.lbl_pending.cget("text"))

    def test_interlocks_block_actions_during_active_or_pending_fcal(self):
        window = self._open_window()
        self._set_active_fcal("B", "RUN")
        window._refresh_support()

        self.monitor._base_on()
        self.monitor._start_vfa_measurement()
        self.monitor._start_offline_flow()
        self.monitor.flow_base.set(12.0)
        self.monitor._apply_manual_flow("B")
        self.monitor.titration_enabled.set(True)
        self.monitor._on_titration_toggle()
        self.monitor._all_off()

        self.assertNotIn("B1", self.sent_cmds)
        self.assertNotIn("VF", self.sent_cmds)
        self.assertNotIn("START", self.sent_cmds)
        self.assertIn("FCAL STOP", self.sent_cmds)
        self.assertFalse(self.monitor.titration_enabled.get())
        self.assertEqual(self.monitor.flow_base.get(), self.monitor.applied_flow_values["B"])

        self.sent_cmds.clear()
        self.monitor.fcal_status.update({"state": "IDLE", "pump": "", "mode": ""})
        self._add_point(window, "B", 10000, 10000, "10.00")
        self.monitor._start_offline_flow()
        self.monitor.flow_base.set(15.0)
        self.monitor._apply_manual_flow("B")
        self.assertNotIn("START", self.sent_cmds)
        self.assertNotIn("FB 15.000000", self.sent_cmds)

    def test_vfa_start_requires_connected_ph_and_non_titrated_raw_sample(self):
        self.monitor.reader = None
        self.monitor.ph_value = 6.2
        self.monitor._start_vfa_measurement()
        self.assertNotIn("VF", self.sent_cmds)

        self.monitor.reader = FakeReader()
        self.monitor.ph_value = None
        self.monitor.ph_text = "--"
        self.monitor._start_vfa_measurement()
        self.assertNotIn("VF", self.sent_cmds)

        self.monitor.ph_value = 5.0
        self.monitor.ph_text = "5.00"
        self.monitor._start_vfa_measurement()
        self.assertNotIn("VF", self.sent_cmds)
        self.assertTrue(any(call[0] == "warning" and "原始样品起始 pH>=5.5" in call[2] for call in self.fake_messagebox.calls))

        self.monitor.ph_value = 6.3
        self.monitor.ph_text = "6.30"
        self.monitor.titration_enabled.set(True)
        self.monitor._start_vfa_measurement()
        self.assertNotIn("VF", self.sent_cmds)
        self.monitor.titration_enabled.set(False)

        self.monitor.titration_state = orp_monitor.TitrationState.WAITING
        self.monitor._start_vfa_measurement()
        self.assertNotIn("VF", self.sent_cmds)
        self.monitor.titration_state = orp_monitor.TitrationState.IDLE

        self.monitor._wait_timer_id = "mixing"
        self.monitor._start_vfa_measurement()
        self.assertNotIn("VF", self.sent_cmds)
        self.monitor._wait_timer_id = None

        self.monitor._start_vfa_measurement()
        self.assertIn("TK 0.005000", self.sent_cmds)
        self.assertIn("TB 4.0000", self.sent_cmds)
        self.assertIn("FN 0.100000", self.sent_cmds)
        self.assertIn("FS 50.000", self.sent_cmds)
        self.assertNotIn("VF", self.sent_cmds)

    def test_orpmv_remains_authoritative_when_mcu_ph_differs(self):
        self.monitor.ph_k.set(0.010454)
        self.monitor.ph_b.set(0.3633)
        self.monitor._parse_line("ORPMV:32")
        expected = 32 * 0.010454 + 0.3633
        self.assertAlmostEqual(self.monitor.ph_value, expected, places=6)
        self.assertEqual(self.monitor.ph_text, f"{expected:.2f}")
        self.assertAlmostEqual(self.monitor.ph_values[-1], expected, places=6)

        self.monitor._parse_line("PH:4.16")
        self.assertAlmostEqual(self.monitor.ph_value, expected, places=6)
        self.assertEqual(self.monitor.ph_text, f"{expected:.2f}")
        self.assertAlmostEqual(self.monitor.ph_values[-1], expected, places=6)
        self.assertAlmostEqual(self.monitor.mcu_ph_value, 4.16, places=2)

    def test_orpmonitor_method_names_are_unique_in_source(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ORPMonitor")
        names = [node.name for node in cls.body if isinstance(node, ast.FunctionDef)]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        self.assertEqual(duplicates, [], f"Duplicate ORPMonitor methods: {duplicates}")

    def test_offline_start_waits_for_all_runtime_param_acks_before_start(self):
        self.monitor.target_ph.set(3.5)
        self.monitor.ph_k.set(0.010454)
        self.monitor.ph_b.set(0.3633)
        self.monitor.trigger_ph.set(3.7)
        self.monitor.tolerance.set(0.2)
        self.monitor.mix_wait.set(5.0)
        self.monitor._start_offline_flow()
        self.assertIn("TT 3.50", self.sent_cmds)
        self.assertIn("TP 3.70", self.sent_cmds)
        self.assertIn("TL 0.200", self.sent_cmds)
        self.assertIn("TM 5.0", self.sent_cmds)
        self.assertIn("TD 0", self.sent_cmds)
        self.assertIn("TK 0.010454", self.sent_cmds)
        self.assertIn("TB 0.3633", self.sent_cmds)
        self.assertNotIn("START", self.sent_cmds)
        self.assertIsNotNone(self.monitor.param_apply_pending)

        for line in ("ACK:TP 3.70", "ACK:TM 5.0", "ACK:TD 0", "ACK:TL 0.200", "ACK:TK 0.010454"):
            self.monitor._parse_line(line)
        self.assertNotIn("START", self.sent_cmds)
        self.assertIsNotNone(self.monitor.param_apply_pending)

        self.monitor._parse_line("ACK:TB 0.3633")
        self.assertNotIn("START", self.sent_cmds)
        self.monitor._parse_line("ACK:TT 3.50")
        self.assertIn("START", self.sent_cmds)
        self.assertIsNone(self.monitor.param_apply_pending)

    def test_target_commit_then_start_upgrades_pending_and_starts_once(self):
        self.monitor.target_ph.set(3.5)
        self.monitor.ph_k.set(0.010454)
        self.monitor.ph_b.set(0.3633)
        self.monitor.trigger_ph.set(3.7)
        self.monitor.tolerance.set(0.2)
        self.monitor.mix_wait.set(5.0)

        self.monitor._on_target_ph_commit()
        self.assertEqual(self.sent_cmds, ["TT 3.50"])
        self.assertEqual(set(self.monitor.param_apply_pending["params"].keys()), {"TT"})

        self.monitor._start_offline_flow()
        self.assertEqual(self.sent_cmds.count("TT 3.50"), 2)
        self.assertIn("TP 3.70", self.sent_cmds)
        self.assertIn("TL 0.200", self.sent_cmds)
        self.assertIn("TM 5.0", self.sent_cmds)
        self.assertIn("TD 0", self.sent_cmds)
        self.assertIn("TK 0.010454", self.sent_cmds)
        self.assertIn("TB 0.3633", self.sent_cmds)
        self.assertNotIn("START", self.sent_cmds)
        self.assertTrue(self.monitor.param_apply_pending["start_after"])

        for line in ("ACK:TT 3.50", "ACK:TP 3.70", "ACK:TM 5.0", "ACK:TD 0", "ACK:TL 0.200", "ACK:TK 0.010454", "ACK:TB 0.3633", "ACK:TT 3.50"):
            self.monitor._parse_line(line)
        self.assertEqual(self.sent_cmds.count("START"), 1)
        self.assertIsNone(self.monitor.param_apply_pending)

    def test_offline_start_missing_ack_or_timeout_does_not_start(self):
        self.monitor.target_ph.set(3.5)
        self.monitor._start_offline_flow()
        for line in ("ACK:TP 3.70", "ACK:TM 5.0", "ACK:TD 0", "ACK:TL 0.200", "ACK:TK 0.005000"):
            self.monitor._parse_line(line)
        self.assertNotIn("START", self.sent_cmds)
        self.assertIsNotNone(self.monitor.param_apply_pending)

        if self.monitor._param_apply_after_id:
            self.monitor.root.after_cancel(self.monitor._param_apply_after_id)
            self.monitor._param_apply_after_id = None
        self.monitor._param_apply_timeout()
        self.assertNotIn("START", self.sent_cmds)
        self.assertIsNone(self.monitor.param_apply_pending)

    def test_target_commit_and_invalid_or_disconnected_start_do_not_fake_start(self):
        self.monitor.target_ph.set(4.2)
        self.monitor._on_target_ph_commit()
        self.assertIn("TT 4.20", self.sent_cmds)
        self.assertNotIn("START", self.sent_cmds)
        self.assertIsNotNone(self.monitor.param_apply_pending)
        self.monitor._parse_line("ACK:TT 4.20")
        self.assertIsNone(self.monitor.param_apply_pending)

        self.sent_cmds.clear()
        self.monitor.reader = None
        self.monitor._start_offline_flow()
        self.assertEqual(self.sent_cmds, [])

        self.monitor.reader = FakeReader()
        self.monitor.target_ph.set(15.0)
        self.monitor._start_offline_flow()
        self.assertEqual(self.sent_cmds, [])

    def test_titration_check_and_enable_use_target_gap_to_choose_pump(self):
        self.monitor.target_ph.set(3.5)
        self.monitor.ph_k.set(0.010454)
        self.monitor.ph_b.set(0.3633)
        self.monitor.tolerance.set(0.2)
        self.monitor.ph_value = 5.0
        self.monitor.ph_text = "5.00"
        self.monitor.titration_enabled.set(True)
        self.monitor.titration_state = orp_monitor.TitrationState.IDLE
        self.monitor._titration_check()
        self.assertIn("A1", self.sent_cmds)
        self.assertNotIn("B1", self.sent_cmds)
        self.assertEqual(self.monitor.titration_dir.get(), orp_monitor.TitrationDir.ADD_ACID.value)

        self.sent_cmds.clear()
        self.monitor._cancel_timers()
        self.monitor.titration_state = orp_monitor.TitrationState.IDLE
        self.monitor.pump_acid = False
        self.monitor.target_ph.set(3.5)
        self.monitor.ph_value = 5.0
        self.monitor._on_titration_toggle()
        self.assertNotIn("A1", self.sent_cmds)
        for line in ("ACK:TP 3.70", "ACK:TM 5.0", "ACK:TD 1", "ACK:TL 0.200", "ACK:TT 3.50", "ACK:TK 0.010454", "ACK:TB 0.3633"):
            self.monitor._parse_line(line)
        self.assertIn("A1", self.sent_cmds)

    def test_target_commit_then_enable_titration_upgrades_pending(self):
        self.monitor.target_ph.set(3.5)
        self.monitor.ph_k.set(0.010454)
        self.monitor.ph_b.set(0.3633)
        self.monitor.tolerance.set(0.2)
        self.monitor.ph_value = 5.0
        self.monitor.ph_text = "5.00"

        self.monitor._on_target_ph_commit()
        self.assertEqual(self.sent_cmds, ["TT 3.50"])

        self.monitor.titration_enabled.set(True)
        self.monitor._on_titration_toggle()
        self.assertEqual(self.sent_cmds.count("TT 3.50"), 2)
        self.assertIn("TP 3.70", self.sent_cmds)
        self.assertIn("TL 0.200", self.sent_cmds)
        self.assertIn("TM 5.0", self.sent_cmds)
        self.assertIn("TD 0", self.sent_cmds)
        self.assertIn("TK 0.010454", self.sent_cmds)
        self.assertIn("TB 0.3633", self.sent_cmds)
        self.assertNotIn("A1", self.sent_cmds)

        for line in ("ACK:TM 5.0", "ACK:TT 3.50", "ACK:TP 3.70", "ACK:TL 0.200", "ACK:TD 0", "ACK:TK 0.010454", "ACK:TB 0.3633"):
            self.monitor._parse_line(line)
        self.assertIn("A1", self.sent_cmds)
        self.assertIsNone(self.monitor.param_apply_pending)

    def test_vfa_waits_for_tk_tb_fn_fs_before_vf(self):
        self._prime_vfa_start_conditions(ph=6.3)
        self.monitor.ph_k.set(0.010454)
        self.monitor.ph_b.set(0.3633)
        self.monitor.acid_N.set(0.12)
        self.monitor.sample_ml.set(45.0)
        self.monitor._start_vfa_measurement()
        self.assertIn("TK 0.010454", self.sent_cmds)
        self.assertIn("TB 0.3633", self.sent_cmds)
        self.assertIn("FN 0.120000", self.sent_cmds)
        self.assertIn("FS 45.000", self.sent_cmds)
        self.assertNotIn("VF", self.sent_cmds)
        for line in ("ACK:FN 0.120000", "ACK:FS 45.000", "ACK:TK 0.010454"):
            self.monitor._parse_line(line)
        self.assertNotIn("VF", self.sent_cmds)
        self.monitor._parse_line("ACK:TB 0.3633")
        self.assertEqual(self.sent_cmds.count("VF"), 1)
        self.assertTrue(self.monitor.vfa_request_pending)

    def test_ph_calibration_commit_and_history_selection_sync_mcu(self):
        self.monitor.ph_k.set(0.010454)
        self.monitor.ph_b.set(0.3633)
        self.monitor._on_ph_calibration_commit()
        self.assertFalse(self.monitor.ph_sync_ok)
        self.assertIn("TK 0.010454", self.sent_cmds)
        self.assertIn("TB 0.3633", self.sent_cmds)
        self.monitor._parse_line("ACK:TK 0.010454")
        self.monitor._parse_line("ACK:TB 0.3633")
        self.assertTrue(self.monitor.ph_sync_ok)
        self.assertAlmostEqual(self.monitor.applied_ph_k, 0.010454, places=6)
        self.assertAlmostEqual(self.monitor.applied_ph_b, 0.3633, places=4)

        self.sent_cmds.clear()
        self.monitor._add_calibration_record("test", 0.020000, 0.5000, 0.99, [])
        self.assertIn("TK 0.020000", self.sent_cmds)
        self.assertIn("TB 0.5000", self.sent_cmds)

    def test_unsynced_connect_sync_blocks_physical_mcu_ph_flows(self):
        self.monitor.ph_value = 6.3
        self.monitor.ph_text = "6.30"
        self.monitor._sync_to_arduino()
        self.assertIsNotNone(self.monitor.param_apply_pending)
        self.assertFalse(self.monitor.ph_sync_ok)

        self.sent_cmds.clear()
        self.monitor._start_offline_flow()
        self.monitor._start_vfa_measurement()
        self.assertEqual(self.sent_cmds, [])

    def test_vfa_request_pending_blocks_until_busy_or_confirmation_and_flow_busy_blocks(self):
        self._prime_vfa_start_conditions()
        self.monitor._start_vfa_measurement()
        self._ack_vfa_preflight()
        self.assertIn("VF", self.sent_cmds)
        self.assertTrue(self.monitor.vfa_request_pending)

        self.sent_cmds.clear()
        self.monitor._base_on()
        self.monitor._start_offline_flow()
        self.monitor.titration_enabled.set(True)
        self.monitor._on_titration_toggle()
        self.monitor._start_vfa_measurement()
        self.assertNotIn("B1", self.sent_cmds)
        self.assertNotIn("START", self.sent_cmds)
        self.assertEqual(self.sent_cmds.count("VF"), 0)
        self.assertFalse(self.monitor.titration_enabled.get())

        self.monitor._parse_line("ACK:VF BUSY")
        self.assertFalse(self.monitor.vfa_request_pending)
        self.assertFalse(self.monitor.vfa_active)
        self.assertTrue(any(call[0] == "warning" and "VFA/ALK 正忙" in call[2] for call in self.fake_messagebox.calls))

        self.fake_messagebox.calls.clear()
        self.sent_cmds.clear()
        self.monitor.flow_state_known = True
        self.monitor.flow_state = "MIXING"
        self.monitor._start_vfa_measurement()
        self.assertNotIn("VF", self.sent_cmds)
        self.assertTrue(any(call[0] == "warning" and "FLOW 状态" in call[2] for call in self.fake_messagebox.calls))

        self.fake_messagebox.calls.clear()
        self.monitor.flow_state = "IDLE"
        self.monitor._start_vfa_measurement()
        self._ack_vfa_preflight()
        self.assertIn("VF", self.sent_cmds)

    def test_vfa_active_blocks_conflicting_actions_and_cancel_is_available(self):
        self.monitor.vfa_active = True
        self.monitor.flow_base.set(12.0)
        self.monitor._base_on()
        self.monitor._start_offline_flow()
        self.monitor.titration_enabled.set(True)
        self.monitor._on_titration_toggle()
        self.assertNotIn("B1", self.sent_cmds)
        self.assertNotIn("START", self.sent_cmds)
        self.assertFalse(self.monitor.titration_enabled.get())

        self.monitor._cancel_vfa_measurement()
        self.assertIn("VC", self.sent_cmds)

        self.sent_cmds.clear()
        self.monitor._all_off()
        self.assertIn("VC", self.sent_cmds)

    def test_vfa_disconnect_and_close_wait_for_cancel_confirmation_or_timeout(self):
        self._prime_vfa_start_conditions()
        self.monitor._start_vfa_measurement()
        self._ack_vfa_preflight()
        self.assertTrue(self.monitor.vfa_request_pending)

        self.monitor._disconnect()
        self.assertIn("VC", self.sent_cmds)
        self.assertIsNotNone(self.monitor.reader)
        self.assertTrue(self.monitor._disconnect_after_vfa_cancel)

        self.monitor._parse_line("ACK:VC OK")
        self.assertIsNone(self.monitor.reader)

        self.monitor.reader = FakeReader()
        self._prime_vfa_start_conditions()
        self.sent_cmds.clear()
        self.monitor._finish_close_called = False
        self.monitor._finish_close = lambda: setattr(self.monitor, "_finish_close_called", True)
        self.monitor._start_vfa_measurement()
        self._ack_vfa_preflight()
        self.monitor.on_close()
        self.assertIn("VC", self.sent_cmds)
        self.assertFalse(self.monitor._finish_close_called)

        self.monitor._parse_line("VFA:CANCELLED")
        self.assertTrue(self.monitor._finish_close_called)

        self.monitor.reader = FakeReader()
        self._prime_vfa_start_conditions()
        self.sent_cmds.clear()
        self.monitor._finish_close_called = False
        self.monitor._finish_close = lambda: setattr(self.monitor, "_finish_close_called", True)
        self.monitor._start_vfa_measurement()
        self._ack_vfa_preflight()
        self.monitor.on_close()
        if self.monitor._vfa_cancel_timeout_id:
            self.monitor.root.after_cancel(self.monitor._vfa_cancel_timeout_id)
            self.monitor._vfa_cancel_timeout_id = None
        self.monitor._vfa_cancel_timeout()
        self.assertFalse(self.monitor._finish_close_called)
        self.assertIsNotNone(self.monitor.reader)
        self.assertTrue(any(call[0] == "warning" and "未确认 VFA/ALK 已取消" in call[2] for call in self.fake_messagebox.calls))

    def test_vfa_reject_messages_and_history_handling(self):
        self.monitor.measurement_results = []
        self.monitor.latest_result = None
        self.monitor.latest_result_valid = False
        self.monitor.vfa_active = True
        self.monitor._parse_line("VFA:REJECT LOW_PH AVG:5.02 MIN:4.99 MAX:5.04")
        self.assertFalse(self.monitor.vfa_active)
        self.assertEqual(len(self.monitor.measurement_results), 0)
        self.assertIn("起始 pH 过低", self.monitor.lbl_titration_note.cget("text"))
        self.assertTrue(any(call[0] == "warning" and "本次无新结果" in call[2] for call in self.fake_messagebox.calls))

        self.fake_messagebox.calls.clear()
        self.monitor.vfa_active = True
        self.monitor._parse_line("VFA:REJECT UNSTABLE AVG:6.20 MIN:6.05 MAX:6.21")
        self.assertFalse(self.monitor.vfa_active)
        self.assertEqual(len(self.monitor.measurement_results), 0)
        self.assertIn("10秒极差", self.monitor.lbl_titration_note.cget("text"))

        self.monitor._parse_line("VFA_RAW:12.5,ALK_RAW:45.3,VFA:13.1,ALK:43.8")
        self.assertEqual(len(self.monitor.measurement_results), 1)

    def test_vfa_reference_formula_matches_appendix_b_example(self):
        result = vfa_reference_calc(
            ph0=6.89,
            stage1_ml=3.4,
            stage2_increment_ml=3.6,
            acid_n=0.12,
            sample_ml=50.0,
            blank_ml=0.25,
        )
        self.assertAlmostEqual(result["total_ml"], 7.0, places=6)
        self.assertAlmostEqual(result["v2_ml"], 6.75, places=6)
        self.assertAlmostEqual(result["vfa_raw"], 11.0195, places=3)
        self.assertAlmostEqual(result["alk_raw"], 6.03167, places=3)
        self.assertGreater(result["vfa_raw"], 0.0)
        self.assertGreater(result["alk_raw"], 0.0)

    def test_vfa_trace_and_result_are_persisted_together(self):
        self.monitor.measurement_results = []
        self.monitor.vfa_active = True
        self.monitor._parse_line("VFA:TRACE PH0:6.89,A1:3.4,A2:3.6,TOTAL:7.0,FN:0.120000,FS:50.000,BLANK:0.25")
        self.monitor._parse_line("VFA_RAW:11.020,ALK_RAW:6.032,VFA:11.020,ALK:6.032")

        self.assertEqual(len(self.monitor.measurement_results), 1)
        stored = self.monitor.measurement_results[0]
        self.assertAlmostEqual(stored["ph0"], 6.89, places=2)
        self.assertAlmostEqual(stored["a1_ml"], 3.4, places=3)
        self.assertAlmostEqual(stored["a2_ml"], 3.6, places=3)
        self.assertAlmostEqual(stored["total_ml"], 7.0, places=3)
        self.assertAlmostEqual(stored["acid_n"], 0.12, places=6)
        self.assertAlmostEqual(stored["sample_ml"], 50.0, places=3)
        self.assertAlmostEqual(stored["blank_ml"], 0.25, places=3)
        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        history = saved["result_calibration"]["measurement_history"]
        self.assertAlmostEqual(history[0]["ph0"], 6.89, places=2)
        self.assertAlmostEqual(history[0]["a2_ml"], 3.6, places=3)

    def test_vfa_calc_error_does_not_write_fake_history_or_clear_last_valid_result(self):
        self.monitor._set_latest_result_from_controller(8.0, 5.0, 8.0, 5.0, measurement_id="prev", timestamp="2026-06-12 16:00:00", append_history=True)
        before = list(self.monitor.measurement_results)
        self.monitor.vfa_active = True
        self.monitor._parse_line("VFA:TRACE PH0:6.89,A1:3.4,A2:3.6,TOTAL:7.0,FN:0.120000,FS:50.000,BLANK:0.25")
        self.monitor._parse_line("VFA:CALC_ERROR INVALID_RESULT")

        self.assertFalse(self.monitor.vfa_active)
        self.assertEqual(self.monitor.measurement_results, before)
        self.assertEqual(self.monitor.latest_result["measurement_id"], "prev")
        self.assertIn("无有效结果", self.monitor.lbl_titration_note.cget("text"))

    def test_old_result_line_stays_compatible_without_trace(self):
        self.monitor.measurement_results = []
        self.monitor._parse_line("VFA_RAW:12.5,ALK_RAW:45.3,VFA:13.1,ALK:43.8")
        self.assertEqual(len(self.monitor.measurement_results), 1)
        stored = self.monitor.measurement_results[0]
        self.assertNotIn("ph0", stored)
        self.assertAlmostEqual(stored["vfa_raw"], 12.5, places=3)

    def test_pump_status_lines_sync_runtime_pump_state_and_ignore_malformed(self):
        updates = []
        self.monitor._update_all_pump_labels = lambda: updates.append(
            (self.monitor.pump_base, self.monitor.pump_acid, self.monitor.pump_water)
        )

        self.monitor._parse_line("PUMP:0,1,0")
        self.assertFalse(self.monitor.pump_base)
        self.assertTrue(self.monitor.pump_acid)
        self.assertFalse(self.monitor.pump_water)
        self.assertEqual(updates[-1], (False, True, False))

        self.monitor._parse_line("PUMP:0,0,0")
        self.assertEqual(updates[-1], (False, False, False))

        before = len(updates)
        self.monitor._parse_line("PUMP:A")
        self.monitor._parse_line("PUMP:1,0")
        self.monitor._parse_line("PUMP:1,0,2")
        self.assertEqual(len(updates), before)
        self.assertFalse(self.monitor.pump_base)
        self.assertFalse(self.monitor.pump_acid)
        self.assertFalse(self.monitor.pump_water)

    def test_vfa_ui_copy_is_clear(self):
        self.assertEqual(self.monitor.btn_vfa_start.cget("text"), "开始VFA/ALK")
        self.assertIn("原样起始pH", self.monitor.btn_vfa_start.master.master.cget("text"))
        self.assertEqual(self.monitor.target_ph_label.cget("text"), "普通调节目标 pH:")
        self.assertIn("独立于VFA", self.monitor.offline_flow_frame.cget("text"))

    def test_disconnect_and_close_wait_for_fcal_stop(self):
        self._set_active_fcal("A", "RUN")
        self.monitor._disconnect()
        self.assertIn("FCAL STOP", self.sent_cmds)
        self.assertIsNotNone(self.monitor.reader)

        self.monitor._parse_line("FCAL:ABORTED PUMP:A MODE:RUN PLAN_MS:10000 ACTUAL_MS:2200 REASON:BUTTON")
        self.assertIsNone(self.monitor.reader)

        self.monitor.reader = FakeReader()
        self.monitor._send_cmd = lambda cmd: self.sent_cmds.append(f"close:{cmd}") or True
        self.monitor._finish_close_called = False
        self.monitor._finish_close = lambda: setattr(self.monitor, "_finish_close_called", True)
        self.monitor.fcal_status.update({"state": "RUN", "pump": "B", "mode": "RUN", "plan_ms": 10000, "elapsed_ms": 1500})
        self.monitor.on_close()
        self.assertIn("close:FCAL STOP", self.sent_cmds)
        self.assertFalse(self.monitor._finish_close_called)
        self.monitor._parse_line("FCAL:ABORTED PUMP:B MODE:RUN PLAN_MS:10000 ACTUAL_MS:1500 REASON:BUTTON")
        self.assertTrue(self.monitor._finish_close_called)

    def test_disconnect_timeout_cancels_close_without_forcing_disconnect(self):
        self._set_active_fcal("B", "RUN")
        self.monitor._disconnect()
        self.assertTrue(self.monitor._disconnect_after_fcal_stop)
        if self.monitor._fcal_stop_timeout_id:
            self.monitor.root.after_cancel(self.monitor._fcal_stop_timeout_id)
            self.monitor._fcal_stop_timeout_id = None

        self.monitor._fcal_stop_timeout()

        self.assertIsNotNone(self.monitor.reader)
        self.assertFalse(self.monitor._disconnect_after_fcal_stop)
        self.assertFalse(self.monitor._close_after_fcal_stop)
        self.assertIn("未确认停泵", self.monitor.lbl_titration_note.cget("text"))
        self.assertTrue(any(call[0] == "warning" and "未确认停泵" in call[2] for call in self.fake_messagebox.calls))

        self.monitor.reader = FakeReader()
        self.monitor._send_cmd = lambda cmd: self.sent_cmds.append(f"close:{cmd}") or True
        self.monitor._finish_close_called = False
        self.monitor._finish_close = lambda: setattr(self.monitor, "_finish_close_called", True)
        self.monitor.fcal_status.update({"state": "RUN", "pump": "B", "mode": "RUN", "plan_ms": 10000, "elapsed_ms": 1500})
        self.monitor.on_close()
        if self.monitor._fcal_stop_timeout_id:
            self.monitor.root.after_cancel(self.monitor._fcal_stop_timeout_id)
            self.monitor._fcal_stop_timeout_id = None
        self.monitor._fcal_stop_timeout()
        self.assertFalse(self.monitor._finish_close_called)
        self.assertIsNotNone(self.monitor.reader)

    def test_unexpected_disconnect_invalidates_run(self):
        window = self._open_window()
        self._set_active_fcal("W", "RUN")
        self.monitor.data_queue.put(("disconnected", ""))
        self.monitor._poll_queue()
        self.assertIn("作废", window.lbl_pending.cget("text"))
        self.assertFalse(self.monitor.fcal_supported)

    def test_flow_apply_ack_timeout_mismatch_err_and_success(self):
        self.monitor.applied_flow_values["B"] = 10.0
        self.monitor.flow_base.set(12.5)
        self.monitor._apply_manual_flow("B")
        self.assertIn("FB 12.500000", self.sent_cmds)
        self.assertIsNotNone(self.monitor.flow_apply_pending)

        self.monitor.flow_base.set(13.0)
        self.monitor._apply_manual_flow("B")
        self.assertNotIn("FB 13.000000", self.sent_cmds)

        self.monitor._parse_line("ACK:FB 12.400000")
        self.assertEqual(self.monitor.applied_flow_values["B"], 10.0)
        self.assertEqual(self.monitor.flow_base.get(), 10.0)

        self.sent_cmds.clear()
        self.monitor.flow_base.set(14.0)
        self.monitor._apply_manual_flow("B")
        self.monitor._parse_line("ERR:FB BUSY")
        self.assertEqual(self.monitor.flow_base.get(), 10.0)

        self.monitor.flow_base.set(15.0)
        self.monitor._apply_manual_flow("B")
        self.monitor._flow_apply_timeout()
        self.assertEqual(self.monitor.flow_base.get(), 10.0)
        self.assertEqual(self.monitor.pump_flow_calibration["B"]["source"], "default")

        self.monitor.flow_base.set(11.5)
        self.monitor._apply_manual_flow("B")
        self.monitor._parse_line("ACK:FB 11.500000")
        self.assertEqual(self.monitor.applied_flow_values["B"], 11.5)
        self.assertEqual(self.monitor.flow_base.get(), 11.5)
        self.assertEqual(self.monitor.pump_flow_calibration["B"]["source"], "manual")

        self.sent_cmds.clear()
        self.monitor.flow_base.set(1.2345674)
        self.monitor._apply_manual_flow("B")
        self.assertIn("FB 1.234567", self.sent_cmds)
        self.monitor._parse_line("ACK:FB 1.234567")
        self.assertAlmostEqual(self.monitor.applied_flow_values["B"], 1.234567, places=6)
        self.assertAlmostEqual(self.monitor.flow_base.get(), 1.234567, places=6)

        self.monitor.flow_base.set(33.3)
        self.monitor._save_config()
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(data["flow_base"], 1.234567)

    def test_history_apply_and_manual_apply_are_blocked_or_confirmed(self):
        window = self._open_window()
        self._add_point(window, "A", 10000, 10000, "10.00")
        window._save_record(False)
        histories = self.monitor.pump_flow_calibration["A"]["histories"]
        self.assertEqual(len(histories), 1)
        window._refresh_history_combo()
        window.cmb_history.current(0)

        self.monitor.fcal_status.update({"state": "RUN", "pump": "A", "mode": "RUN", "plan_ms": 10000, "elapsed_ms": 1200})
        window._apply_selected_history()
        self.assertEqual(self.sent_cmds, [])

        self.monitor.fcal_status.update({"state": "IDLE", "pump": "", "mode": ""})
        self.fake_messagebox.askyesno_result = True
        window._apply_selected_history()
        self.assertTrue(any(cmd.startswith("FA ") for cmd in self.sent_cmds))

    def test_candidate_points_allow_second_and_third_run_but_stop_at_three(self):
        window = self._open_window()
        self.monitor.fcal_supported = True
        self.monitor.fcal_status.update({"state": "IDLE", "pump": "", "mode": ""})

        self._add_point(window, "B", 10000, 10000, "10.00")
        self.assertEqual(len(window.pending_points), 1)
        self.assertEqual(str(window.cmb_pump["state"]), "disabled")
        self.assertEqual(str(window.ent_liquid["state"]), "disabled")
        self.assertEqual(str(window.ent_duration["state"]), "normal")
        self.assertTrue(all(str(btn["state"]) == "normal" for btn in window.quick_duration_buttons))

        self.sent_cmds.clear()
        window.duration_var.set("30")
        window._start_run()
        self.assertIn("FCAL RUN B 30", self.sent_cmds)
        window.pending_run = {
            "pump": "B",
            "mode": "DONE",
            "plan_ms": 30000,
            "actual_ms": 30000,
            "reason": "AUTO",
            "early_stop": False,
        }
        window._refresh_support()
        window._sync_lock_state()
        self.assertEqual(str(window.ent_duration["state"]), "disabled")
        self.assertTrue(all(str(btn["state"]) == "disabled" for btn in window.quick_duration_buttons))
        window.pending_run = None
        window._refresh_support()
        window._sync_lock_state()
        self.assertEqual(str(window.ent_duration["state"]), "normal")

        self._add_point(window, "B", 10000, 9000, "9.00")
        self.assertEqual(len(window.pending_points), 2)

        self.sent_cmds.clear()
        window.duration_var.set("60")
        window._start_run()
        self.assertIn("FCAL RUN B 60", self.sent_cmds)

        self._add_point(window, "B", 10000, 8000, "8.00")
        self.assertEqual(len(window.pending_points), 3)
        self.assertEqual(str(window.ent_duration["state"]), "disabled")
        self.assertTrue(all(str(btn["state"]) == "disabled" for btn in window.quick_duration_buttons))
        self.sent_cmds.clear()
        window._start_run()
        self.assertEqual(self.sent_cmds, [])
        self.assertIn("3/3", window._summary_text())

    def test_point_statistics_temperature_prefill_and_unique_ids(self):
        self.monitor.temp_text = "26.4"
        window = self._open_window()
        self.assertEqual(window.temperature_var.get(), "26.4")

        self._add_point(window, "B", 10000, 10000, "10.00")
        self.assertIn("未验证重复性", window._summary_text())

        self._add_point(window, "B", 10000, 8000, "8.80", reason="USER", mode="STOPPED", early_stop=True)
        summary_two = window._summary_text()
        self.assertIn("两点差值", summary_two)
        self.assertIn("相对差异", summary_two)

        self._add_point(window, "B", 5000, 5000, "7.50")
        record_one = window._build_record()
        record_two = window._build_record()
        self.assertNotEqual(record_one["id"], record_two["id"])
        self.assertGreater(record_one["weighted_flow"], 0)
        self.assertGreater(record_one["mean_flow"], 0)
        self.assertIn("最大偏离均值", window._summary_text())

    def test_old_firmware_without_caps_disables_run_buttons(self):
        window = self._open_window()
        self.monitor._clear_fcal_support_state()
        window._refresh_support()
        self.assertEqual(str(window.btn_run["state"]), "disabled")
        self.assertEqual(str(window.btn_prime["state"]), "disabled")
        self.assertFalse(window._can_start())
        self.assertNotIn("FCAL RUN", self.sent_cmds)

    def test_window_controls_are_accessible(self):
        window = self._open_window()
        window.geometry("980x760")
        self.root.update_idletasks()
        for widget in (window.btn_prime, window.btn_run, window.btn_stop, window.ent_duration, window.ent_liquid):
            self.assertGreater(widget.winfo_width(), 0)
            self.assertGreaterEqual(widget.winfo_x(), 0)

    def test_firmware_source_covers_conflicts_and_non_accumulation(self):
        text = FIRMWARE_PATH.read_text(encoding="utf-8")
        self.assertIn("return fcalSessionActive() || anyPumpRunning() || (rstate!=RS_IDLE);", text)
        self.assertIn('Serial.println(F("ERR:FB BUSY"));', text)
        self.assertIn('Serial.println(F("ACK:VC BUSY"));', text)
        self.assertIn('Serial.println(F("ACK:STOP FCAL"));', text)
        self.assertIn('OL("FLOW CAL DONE");', text)
        self.assertIn('OL("ENTER VOL PC");', text)
        self.assertIn('if(fcalPlanMs && (millis()-fcalStartMs) >= fcalPlanMs){', text)
        self.assertIn('setVfaNotice("START PH<5.5");', text)
        start = text.index("void fcalStart(")
        end = text.index("void fcalStopByReason(")
        self.assertNotIn("ee.vol_", text[start:end])
        self.assertIn('if(isRun && strcmp(reason,"BUTTON")==0){', text)
        self.assertIn("void pumpStateReport()", text)
        self.assertIn("bool stopPumpCounted(uint8_t pump)", text)
        self.assertIn("void stopAllPumpsCounted(bool persist)", text)
        self.assertIn("void stopAllPumpsRaw()", text)
        self.assertIn("void stopAllPumpsUnsaved()", text)
        self.assertIn("bool pumpVolumeDirty=false;", text)
        self.assertIn("bool phFilterPrimed=false;", text)
        self.assertIn("float getPumpDurToTarget(float gap, float endGap)", text)
        self.assertIn("unsigned long vfaPulseMs(float gap)", text)
        self.assertIn("V_S1_DOSE", text)
        self.assertIn("V_S1_MIX", text)
        self.assertIn("V_S2_DOSE", text)
        self.assertIn("V_S2_MIX", text)
        self.assertNotIn("V_TO51", text)
        self.assertNotIn("V_TO35", text)
        self.assertNotIn("V_PAUSE", text)
        self.assertIn('OL("S1 DOSING");', text)
        self.assertIn('OL("S1 MIXING");', text)
        self.assertIn('OL("S2 DOSING");', text)
        self.assertIn('OL("S2 MIXING");', text)
        self.assertIn('Serial.println(F("VFA:CANCELLED"));', text)
        self.assertIn("pumpStateReport();", text)
        self.assertIn("stopAllPumpsRaw();", text)
        self.assertIn("pumpVolumeDirty=true;", text)
        self.assertIn("if(persist && pumpVolumeDirty){", text)
        self.assertIn("pumpVolumeDirty=false;", text)
        stop_pump_start = text.index("bool stopPumpCounted(uint8_t pump)")
        stop_pump_end = text.index("void stopAllPumpsCounted(bool persist)")
        self.assertNotIn("eeSave();", text[stop_pump_start:stop_pump_end])
        stop_all_start = text.index("void stopAllPumpsCounted(bool persist)")
        stop_all_end = text.index("void stopAllPumpsRaw(){", stop_all_start)
        self.assertIn("stopPumpCounted(FCAL_PUMP_ACID);", text[stop_all_start:stop_all_end])
        self.assertIn("stopAllPumpsUnsaved();", text)
        self.assertIn("float VAd=(C2*BB1-C1*BB2)/den, HCO3=(C1*AA2-C2*AA1)/den;", text)
        self.assertIn('Serial.print(F("VFA:TRACE PH0:"));', text)
        self.assertIn('Serial.print(F(",A1:"));', text)
        self.assertIn('Serial.print(F(",A2:"));', text)
        self.assertIn('Serial.print(F(",TOTAL:"));', text)
        self.assertIn('Serial.print(F(",FN:"));', text)
        self.assertIn('Serial.print(F(",FS:"));', text)
        self.assertIn('Serial.print(F(",BLANK:"));', text)
        self.assertIn('Serial.print(F("VFA:CALC_ERROR "));', text)
        self.assertIn("eeExt.result_valid=0;", text)

    def test_old_vfa_stage_and_total_budgets_can_expire_before_1000_seconds(self):
        mix_wait_ms = 1000
        old_stage_budget = 36 * (5000 + mix_wait_ms) + mix_wait_ms + 15000
        old_total_budget = (2 * old_stage_budget) + mix_wait_ms + 30000
        self.assertLess(old_stage_budget, 1_000_000)
        self.assertLess(old_total_budget, 1_000_000)

    def test_firmware_source_uses_single_1000s_vfa_hard_cutoff_and_updated_oled_labels(self):
        text = FIRMWARE_PATH.read_text(encoding="utf-8")
        self.assertIn("const unsigned long VFA_TOTAL_TIMEOUT_MS = 1000000UL;", text)
        self.assertIn('if(vf_totalStart>0 && (millis()-vf_totalStart)>=VFA_TOTAL_TIMEOUT_MS){ vfaAbort("TIMEOUT"); return; }', text)
        self.assertNotIn("VFA_STAGE_MAX_PULSES", text)
        self.assertNotIn("vfaStageTimeoutBudgetMs()", text)
        self.assertNotIn("vfaTotalTimeoutBudgetMs()", text)
        self.assertNotIn("vfaStageTimeout()", text)
        self.assertNotIn("vfaStageLimitReached()", text)
        self.assertIn('ol_cursor(0,2); OL("PH0:");', text)
        self.assertIn('OL(" V1:");', text)
        self.assertIn('OL(" V2:");', text)
        self.assertIn('ol_cursor(0,0); OL("DONE VFA/ALK");', text)
        self.assertIn('ol_cursor(0,2); OL("PH0:"); ol_printF(vf_initPH,2); OL(" V1:");', text)
        self.assertIn('ol_cursor(0,4); OL("V2:"); ol_printF(vf_stage2_ml,1); OL(" VFA:");', text)
        self.assertIn('ol_cursor(0,6); OL("ALK:");', text)
        self.assertIn("stopAllPumps();", text[text.index("void vfaAbort("):text.index("void vfaObserveTick()")])
        stage1_branch_start = text.index("if(vst==V_S1_MIX){")
        stage1_branch_end = text.index("vst=V_S2_MIX;")
        self.assertIn("vf_stage1_ml=vf_acid51-vf_acidB4;", text[stage1_branch_start:stage1_branch_end])
        pulse_start = text.index("unsigned long vfaPulseMs(float gap)")
        pulse_end = text.index("unsigned long vfaMixWaitMs()")
        self.assertNotIn("ee.flow_a", text[pulse_start:pulse_end])
        self.assertNotIn("VFA_MAX_PULSE_MS", text[pulse_start:pulse_end])
        self.assertIn("return (unsigned long)(getPumpDurToTarget(gap, 0.0) * 1000.0);", text[pulse_start:pulse_end])
        self.assertIn("float phInstant = curORP*ee.ph_k+ee.ph_b;", text)
        self.assertIn("if(!phFilterPrimed){", text)
        self.assertIn("curPH=phInstant;", text)
        self.assertIn("phFilterPrimed=true;", text)
        self.assertIn('else if(strncmp(cbuf,"TK ",3)==0){ ee.ph_k=parseF(); phFilterPrimed=false;', text)
        self.assertIn('else if(strncmp(cbuf,"TB ",3)==0){ ee.ph_b=parseF(); phFilterPrimed=false;', text)


if __name__ == "__main__":
    unittest.main()

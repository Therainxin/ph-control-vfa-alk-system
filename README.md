# pH 控制与 VFA/ALK 测量系统

本项目是基于 Arduino UNO R3、ORP/pH 模组、OLED 屏和三路蠕动泵的实验室自动滴定系统。它用于实时监测 pH，控制酸泵、碱泵和水泵，并完成 VFA（挥发性脂肪酸）与 ALK（碳酸氢根/碱度）联合测量。

## 主要内容

- `xy_orp_arduino/xy_orp_arduino.ino`：完整版单片机固件，负责 ORP/pH 采集、OLED 显示、泵控制、脱机 VFA/ALK 测量和串口协议。
- `上位机/orp_monitor.py`：Python 上位机程序，提供实时曲线、参数下发、pH 标定、VFA/ALK 校正、泵流量标定和历史记录。
- `lite/Arduino UNO例程/xy_orp_arduino/xy_orp_arduino.ino`：lite 版固件，可在源码中填写参数后脱离上位机运行。
- `操作手册.md`、`泵流量标定操作卡.md`：面向测试人员的安装、接线、标定和测量操作说明。
- `tests/`：围绕泵流量标定等关键逻辑的 Python 测试。

## 典型用途

1. 通过上位机连接 Arduino，完成 pH 换算参数、泵流速、VFA/ALK 校正系数等配置。
2. 使用上位机实时查看 pH 曲线、手动控制泵，或启动普通 pH 自动滴定。
3. 在已配置参数后，可通过 OLED 和 D4 按键脱机运行 VFA/ALK 测量流程。
4. 使用泵流量标定功能，让单片机按指定时间运行蠕动泵，测试人员回填实际出液体积后计算真实流速。

## 运行环境

- Arduino UNO R3
- Windows PC
- Python 3
- Python 依赖：`pyserial`、`matplotlib`
- Arduino CLI 或 Arduino IDE

详细接线、烧录和测试步骤见 `操作手册.md`。

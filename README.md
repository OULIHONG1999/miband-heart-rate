# MiBand Heart Rate Demo

> For miband 4~7, checkout `miband-4-to-7` tag
>
> 对于小米手环 4~7，请切换到 `miband-4-to-7` 标签

A Demo of reading "Shear heart rate data" of Xiaomi Smart Band 10. Enable the option in official App is required.

接收小米手环10 "运动心率广播" Demo，需在手环设置-心率广播中开启广播功能。

欢迎二次开发。

## Supported Platform

I use `bluest` crate. I copy its words below.

> Bluest is a cross-platform Bluetooth Low Energy (BLE) library for Rust. It currently supports Windows (version 10 and later), MacOS/iOS, and Linux. Android support is planned.

So it supported:

- Windows 10/11
- MacOS/iOS
- Linux

## Supported MiBands

MiBand 10 小米手环 10

Tested on MiBand10/NFC.

## Screenshot

![Alt text](doc/screenshot.png)

## Python version

This project also includes a Python version implemented with `bleak` library. To run the Python version:

1. Install required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   or directly install bleak:
   ```bash
   pip install bleak
   ```

2. Run the Python script:
   ```bash
   python miband_heart_rate.py
   ```

The Python version provides the same functionality as the Rust version but with broader compatibility and easier setup.

## Python GUI version

There's also a GUI version using PyQt6 that displays heart rate in a frameless window:

1. Install required dependencies (including PyQt6):
   ```bash
   pip install -r requirements.txt
   ```

2. Run the GUI version:
   ```bash
   python miband_heart_rate_gui.py
   ```

Features of the GUI version:
- Frameless window that stays on top
- Real-time heart rate display with color coding (green=normal, orange=high, red=very high)
- Sensor contact status indicator
- Draggable window (click and drag anywhere in the window)
- Control buttons appear only when mouse hovers over the window

### GUI版本使用说明

1. 程序启动后会自动在屏幕右下角显示一个半透明黑色的悬浮窗口
2. 窗口默认置顶显示，实时显示心率数值和传感器状态
3. 心率数值根据数值大小显示不同颜色：
   - 绿色：心率正常（< 80）
   - 橙色：心率偏高（80-100）
   - 红色：心率过高（> 100）
4. 窗口控制按钮默认隐藏，将鼠标悬停在窗口上时会显示：
   - 左侧按钮用于切换窗口置顶状态
   - 右侧"×"按钮用于关闭程序
5. 可以在窗口任意位置点击并拖动来移动窗口位置
6. 拖动后窗口会保持在放置的位置，不会自动回位

### 使用前准备

1. 确保电脑蓝牙已开启
2. 在小米运动健康App中开启"运动心率广播"功能：
   - 打开小米运动健康App
   - 进入设备设置
   - 找到"心率广播"选项并开启
3. 确保手环与电脑距离适中（建议在1米以内）
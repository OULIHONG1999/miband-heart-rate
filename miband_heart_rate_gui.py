import sys
import asyncio
import struct
from bleak import BleakClient, BleakScanner
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QPoint
from PyQt6.QtGui import QFont, QPalette, QColor, QCursor

# 蓝牙心率服务和特征 UUID
HRS_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HRM_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

class HeartRateWorker(QThread):
    # 定义信号，用于向主线程发送心率数据
    heart_rate_updated = pyqtSignal(int, bool)
    scanning_status = pyqtSignal(str)
    connection_error = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.device = None
        self.client = None
        self.running = True

    def run(self):
        # 在线程中运行异步任务
        asyncio.run(self._main())

    def stop(self):
        self.running = False

    async def _main(self):
        try:
            # 扫描心率设备
            self.scanning_status.emit("正在扫描心率设备...")
            
            # 扫描已连接的心率设备
            devices = await BleakScanner.discover()
            heart_rate_devices = [device for device in devices if self.is_heart_rate_device(device)]
            
            if heart_rate_devices:
                self.device = heart_rate_devices[0]
                self.scanning_status.emit(f"找到设备: {self.device.name} [{self.device.address}]")
            else:
                self.scanning_status.emit("未找到已连接的心率设备，开始扫描...")
                self.device = await BleakScanner.find_device_by_filter(
                    lambda d, ad: HRS_UUID in (ad.service_uuids or [])
                )
                
                if self.device:
                    self.scanning_status.emit(f"找到设备: {self.device.name} [{self.device.address}]")
                else:
                    self.scanning_status.emit("未找到设备")
                    return
            
            # 连接设备并处理心率数据
            async with BleakClient(self.device) as client:
                self.client = client
                await self.handle_device(client)
                
        except Exception as e:
            self.connection_error.emit(str(e))

    def is_heart_rate_device(self, device):
        """
        检查设备是否是心率设备（简单检查名称）
        """
        if not device.name:
            return False
        name = device.name.lower()
        return "miband" in name or "xiaomi" in name or "mi band" in name

    async def handle_device(self, client):
        """
        处理连接的设备，监听心率数据
        """
        # 开始监听心率测量特征的通知
        await client.start_notify(HRM_UUID, self.notification_handler)
        self.scanning_status.emit("开始监听心率数据...")
        
        # 保持连接直到出错或用户中断
        try:
            while client.is_connected and self.running:
                await asyncio.sleep(1)
        finally:
            await client.stop_notify(HRM_UUID)

    def notification_handler(self, sender, data):
        """
        心率数据通知处理函数
        """
        # 解析心率数据
        flag = data[0]
        
        # 心率值格式
        if flag & 0x01:
            # 16位心率值
            heart_rate_value = struct.unpack('<H', data[1:3])[0]
        else:
            # 8位心率值
            heart_rate_value = data[1]
        
        # 传感器接触状态
        sensor_contact = False
        if flag & 0x04:
            sensor_contact = bool(flag & 0x02)
        
        # 发送信号更新UI
        self.heart_rate_updated.emit(heart_rate_value, sensor_contact)


class HeartRateWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.always_on_top = True  # 默认置顶
        self.drag_position = None
        self.last_position = None  # 记住窗口最后位置
        self.init_ui()
        self.init_worker()
        self.setup_auto_hide()
        
    def init_ui(self):
        # 设置无标题栏窗口
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 设置窗口大小
        self.setFixedSize(300, 200)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        central_widget.setLayout(main_layout)
        
        # 创建心率显示标签
        self.heart_rate_label = QLabel("等待心率数据...")
        self.heart_rate_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.heart_rate_label.setFont(QFont("Arial", 32, QFont.Weight.Bold))
        self.heart_rate_label.setStyleSheet("color: white;")
        
        # 创建状态标签
        self.status_label = QLabel("初始化...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setFont(QFont("Arial", 10))
        self.status_label.setStyleSheet("color: #CCCCCC;")
        
        # 创建传感器接触状态标签
        self.contact_label = QLabel("")
        self.contact_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.contact_label.setFont(QFont("Arial", 9))
        self.contact_label.setStyleSheet("color: #AAAAAA;")
        
        # 创建按钮容器（默认隐藏）
        self.button_container = QWidget()
        self.button_container.setVisible(False)
        button_layout = QHBoxLayout()
        self.button_container.setLayout(button_layout)
        
        # 创建置顶开关按钮
        self.top_button = QPushButton("取消置顶")
        self.top_button.setFont(QFont("Arial", 8))
        self.top_button.setStyleSheet(
            "background-color: #555555; color: white; border: none; padding: 3px;"
        )
        self.top_button.clicked.connect(self.toggle_always_on_top)
        
        # 创建关闭按钮
        close_button = QPushButton("×")
        close_button.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        close_button.setStyleSheet(
            "background-color: #555555; color: white; border: none; padding: 3px;"
        )
        close_button.clicked.connect(self.close)
        
        # 添加按钮到布局
        button_layout.addStretch()
        button_layout.addWidget(self.top_button)
        button_layout.addWidget(close_button)
        
        # 添加部件到主布局
        main_layout.addWidget(self.heart_rate_label)
        main_layout.addWidget(self.status_label)
        main_layout.addWidget(self.contact_label)
        main_layout.addWidget(self.button_container)
        main_layout.addStretch()
        
        # 设置窗口背景
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 200))  # 半透明黑色
        self.setPalette(palette)
        
    def init_worker(self):
        # 初始化工作线程
        self.worker = HeartRateWorker()
        self.worker.heart_rate_updated.connect(self.update_heart_rate)
        self.worker.scanning_status.connect(self.update_status)
        self.worker.connection_error.connect(self.handle_error)
        self.worker.start()
        
    def setup_auto_hide(self):
        # 设置定时器检查鼠标位置
        self.mouse_check_timer = QTimer()
        self.mouse_check_timer.timeout.connect(self.check_mouse_position)
        self.mouse_check_timer.start(300)  # 每300ms检查一次
        
    def check_mouse_position(self):
        # 检查鼠标位置，控制按钮显示/隐藏
        mouse_pos = QCursor.pos()
        window_pos = self.pos()
        window_rect = self.geometry()
        
        # 检查鼠标是否在窗口内
        if (window_pos.x() <= mouse_pos.x() <= window_pos.x() + window_rect.width() and
            window_pos.y() <= mouse_pos.y() <= window_pos.y() + window_rect.height()):
            self.button_container.setVisible(True)
        else:
            self.button_container.setVisible(False)
            
    def update_heart_rate(self, heart_rate, sensor_contact):
        # 更新心率显示
        self.heart_rate_label.setText(f"{heart_rate}")
        self.heart_rate_label.setStyleSheet(
            "color: red;" if heart_rate > 100 else 
            "color: orange;" if heart_rate > 80 else 
            "color: limegreen;"
        )
        
        # 更新传感器接触状态
        if sensor_contact:
            self.contact_label.setText("传感器接触良好")
            self.contact_label.setStyleSheet("color: limegreen;")
        else:
            self.contact_label.setText("传感器接触不良")
            self.contact_label.setStyleSheet("color: orange;")
            
    def update_status(self, status):
        # 更新状态信息
        self.status_label.setText(status)
        
    def handle_error(self, error):
        # 处理连接错误
        self.status_label.setText(f"连接错误: {error}")
        self.heart_rate_label.setText("错误")
        self.heart_rate_label.setStyleSheet("color: red;")
        
    def mousePressEvent(self, event):
        # 实现窗口拖动
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        # 实现窗口拖动
        if event.buttons() & Qt.MouseButton.LeftButton and self.drag_position is not None:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            self.last_position = self.pos()  # 记录当前位置
            event.accept()
            
    def mouseReleaseEvent(self, event):
        # 释放鼠标时清除拖动状态
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = None
            event.accept()
        
    def toggle_always_on_top(self):
        # 切换窗口置顶状态
        self.always_on_top = not self.always_on_top
        
        # 更新窗口标志
        flags = self.windowFlags()
        if self.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
            self.top_button.setText("取消置顶")
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
            self.top_button.setText("置顶窗口")
            
        self.setWindowFlags(flags)
        self.show()  # 重新显示窗口以应用更改
        
    def closeEvent(self, event):
        # 关闭窗口时停止工作线程
        self.worker.stop()
        self.worker.quit()
        self.worker.wait()
        event.accept()


def main():
    app = QApplication(sys.argv)
    
    # 创建并显示主窗口
    window = HeartRateWindow()
    window.show()
    
    # 初始化窗口位置到右下角
    screen = QApplication.primaryScreen().geometry()
    window.move(
        screen.width() - window.width() - 50,
        screen.height() - window.height() - 50
    )
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
import sys
import asyncio
import struct
import logging
import math
from bleak import BleakClient, BleakScanner
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QPoint
from PyQt6.QtGui import QFont, QPalette, QColor, QCursor, QPainter, QPen, QBrush

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("heart_rate.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MiBandHeartRateMonitor")

# 蓝牙心率服务和特征 UUID
HRS_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HRM_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

class HeartRateWorker(QThread):
    # 定义信号，用于向主线程发送心率数据
    heart_rate_updated = pyqtSignal(int, bool)
    scanning_status = pyqtSignal(str)
    connection_error = pyqtSignal(str)
    disconnected = pyqtSignal()
    connection_success = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.device = None
        self.client = None
        self.running = True
        self.retry_count = 0
        self.max_retries = 5
        self.manual_reconnect_requested = False
        self.full_scan_requested = False  # 添加完全扫描请求标志
        self.last_device_address = None  # 记录最后连接的设备地址

    def run(self):
        # 在线程中运行异步任务
        asyncio.run(self._main_loop())

    def stop(self):
        self.running = False

    def request_manual_reconnect(self):
        """请求手动重连设备"""
        logger.info("手动重连请求已发送")
        self.manual_reconnect_requested = True
        self.full_scan_requested = False
        
    def request_full_scan(self):
        """请求完全重新扫描设备"""
        logger.info("完全扫描请求已发送")
        self.full_scan_requested = True
        self.manual_reconnect_requested = False

    async def _main_loop(self):
        """主循环，负责设备扫描、连接和重连逻辑"""
        while self.running:
            try:
                await self._main()
            except Exception as e:
                # 记录异常信息到日志
                logger.error(f"连接异常: {str(e)}")
                
                if self.full_scan_requested:
                    # 完全扫描请求处理
                    self.connection_error.emit("正在重新扫描设备...")
                    self.full_scan_requested = False
                    # 立即重试，不增加重试计数
                elif self.manual_reconnect_requested:
                    # 手动重连请求处理
                    self.connection_error.emit("正在手动重连...")
                    self.manual_reconnect_requested = False
                    # 立即重试，不增加重试计数
                else:
                    # 自动重连逻辑
                    self.retry_count += 1
                    if self.retry_count <= self.max_retries:
                        self.connection_error.emit(f"连接错误: {str(e)}，{5 - self.retry_count}秒后重试...")
                        await asyncio.sleep(5)  # 等待5秒后重试
                    else:
                        self.connection_error.emit(f"连接错误: {str(e)}，已达到最大重试次数")
                        # 重置重试计数，以便后续可能的手动重连
                        self.retry_count = 0
                        break
            else:
                # 如果成功执行，重置重试计数
                self.retry_count = 0
                
        # 循环结束时发送断开连接信号
        self.disconnected.emit()

    async def _main(self):
        """扫描并连接设备"""
        # 扫描心率设备
        self.scanning_status.emit("正在扫描心率设备...")
        logger.info("开始扫描心率设备")
        
        # 如果不是完全扫描请求，则优先尝试重新连接到上次成功连接的设备
        if self.last_device_address and not self.full_scan_requested:
            self.scanning_status.emit(f"尝试重连到上次设备: {self.last_device_address}")
            logger.info(f"尝试重连到上次设备: {self.last_device_address}")
            
            # 尝试直接连接到已知地址
            try:
                device = await BleakScanner.find_device_by_address(self.last_device_address)
                if device and await self._connect_to_device(device):
                    return  # 重连成功，直接返回
            except Exception as e:
                logger.warning(f"重连到上次设备失败: {str(e)}")
        elif self.full_scan_requested:
            # 完全扫描模式，不使用上次设备地址
            logger.info("执行完全扫描模式")
            
        # 扫描所有设备
        devices = await BleakScanner.discover()
        heart_rate_devices = [device for device in devices if self.is_heart_rate_device(device)]
        
        if heart_rate_devices:
            self.device = heart_rate_devices[0]
            self.scanning_status.emit(f"找到设备: {self.device.name} [{self.device.address}]")
            logger.info(f"找到设备: {self.device.name} [{self.device.address}]")
        else:
            self.scanning_status.emit("未找到已连接的心率设备，开始扫描...")
            logger.info("未找到已连接的心率设备，开始深度扫描")
            
            # 使用过滤器查找心率服务设备
            self.device = await BleakScanner.find_device_by_filter(
                lambda d, ad: HRS_UUID in (ad.service_uuids or [])
            )
            
            if self.device:
                self.scanning_status.emit(f"找到设备: {self.device.name} [{self.device.address}]")
                logger.info(f"找到设备: {self.device.name} [{self.device.address}]")
            else:
                self.scanning_status.emit("未找到设备")
                logger.warning("未找到心率设备")
                raise Exception("未找到心率设备")
        
        # 连接设备并处理心率数据
        await self._connect_to_device(self.device)
    
    async def _connect_to_device(self, device):
        """连接到指定设备并处理数据"""
        try:
            async with BleakClient(device) as client:
                self.client = client
                self.last_device_address = device.address  # 记录成功连接的设备地址
                
                # 发送连接成功信号
                self.connection_success.emit()
                logger.info(f"成功连接到设备: {device.address}")
                
                # 处理设备数据
                await self.handle_device(client)
                return True
        except Exception as e:
            logger.error(f"连接设备失败: {str(e)}")
            return False

    def is_heart_rate_device(self, device):
        """检查设备是否是心率设备（简单检查名称）"""
        if not device.name:
            return False
        name = device.name.lower()
        return "miband" in name or "xiaomi" in name or "mi band" in name

    async def handle_device(self, client):
        """处理连接的设备，监听心率数据"""
        try:
            # 开始监听心率测量特征的通知
            await client.start_notify(HRM_UUID, self.notification_handler)
            self.scanning_status.emit("开始监听心率数据...")
            logger.info("开始监听心率数据")
            
            # 保持连接直到出错或用户中断
            while client.is_connected and self.running:
                await asyncio.sleep(1)
        finally:
            # 确保停止通知
            try:
                await client.stop_notify(HRM_UUID)
                logger.info("已停止心率数据监听")
            except Exception as e:
                logger.error(f"停止通知时出错: {str(e)}")
            
        # 如果是主动停止，则不触发断开信号
        if self.running:
            logger.warning("设备连接已断开")
            self.disconnected.emit()

    def notification_handler(self, sender, data):
        """心率数据通知处理函数"""
        try:
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
            
            # 记录心率数据到日志
            logger.debug(f"心率更新: {heart_rate_value}, 传感器接触: {sensor_contact}")
        except Exception as e:
            logger.error(f"处理心率数据时出错: {str(e)}")


class AnimatedHeartWidget(QWidget):
    """心形动画组件"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.heart_size = 100  # 心形初始大小
        self.heart_beat_animation = False  # 是否正在跳动
        self.animation_progress = 0  # 动画进度
        self.beat_timer = None  # 跳动计时器
        self.heart_color = QColor(255, 0, 0)  # 心形颜色
        self.is_connected = False  # 连接状态
        
        # 设置组件大小
        self.setMinimumSize(150, 150)
        
    def set_heart_rate(self, heart_rate):
        """设置心率值并触发跳动动画"""
        # 触发跳动动画
        if self.is_connected and not self.heart_beat_animation:
            self.start_beat_animation()
            
            # 根据心率调整颜色
            if heart_rate > 100:
                self.heart_color = QColor(255, 0, 0)  # 红色
            elif heart_rate > 80:
                self.heart_color = QColor(255, 165, 0)  # 橙色
            else:
                self.heart_color = QColor(0, 255, 0)  # 绿色
        
        self.update()  # 触发重绘
    
    def set_connected(self, connected):
        """设置连接状态"""
        self.is_connected = connected
        if not connected:
            self.heart_color = QColor(100, 100, 100)  # 灰色表示未连接
        self.update()
    
    def start_beat_animation(self):
        """开始跳动动画"""
        self.heart_beat_animation = True
        self.animation_progress = 0
        
        if self.beat_timer is None or not self.beat_timer.isActive():
            self.beat_timer = QTimer(self)
            self.beat_timer.timeout.connect(self.update_beat_animation)
            self.beat_timer.start(20)  # 每20ms更新一次
    
    def update_beat_animation(self):
        """更新跳动动画进度"""
        # 更新动画进度
        self.animation_progress += 0.05
        
        # 计算当前大小（使用正弦函数模拟跳动效果）
        if self.animation_progress < 1.0:
            # 跳动放大阶段
            scale_factor = 1.0 + 0.2 * math.sin(self.animation_progress * math.pi)
        else:
            # 恢复原始大小
            scale_factor = 1.0 - 0.2 * math.sin((self.animation_progress - 1.0) * math.pi)
            
            # 动画结束
            if self.animation_progress >= 2.0:
                self.heart_beat_animation = False
                self.beat_timer.stop()
                scale_factor = 1.0
        
        # 更新心形大小
        self.heart_size = 100 * scale_factor
        
        # 触发重绘
        self.update()
    
    def paintEvent(self, event):
        """绘制心形"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)  # 启用抗锯齿
        
        # 获取窗口中心点
        center_x = self.width() // 2
        center_y = self.height() // 2
        
        # 计算心形顶点坐标
        size = self.heart_size
        points = []
        
        # 使用参数方程绘制心形
        for angle in range(0, 361):
            t = math.radians(angle)
            x = 16 * math.pow(math.sin(t), 3)
            y = 13 * math.cos(t) - 5 * math.cos(2*t) - 2 * math.cos(3*t) - math.cos(4*t)
            
            # 缩放和位移，并转换为整数
            x_coord = int(center_x + x * size / 32)
            y_coord = int(center_y - y * size / 32)
            points.append(QPoint(x_coord, y_coord))
        
        # 绘制心形
        brush = QBrush(self.heart_color)
        painter.setBrush(brush)
        painter.setPen(QPen(self.heart_color, 2))
        painter.drawPolygon(points)


class HeartRateWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.always_on_top = True  # 默认置顶
        self.drag_position = None
        self.last_position = None  # 记住窗口最后位置
        self.heart_rate_history = []  # 存储心率历史数据
        self.max_history_points = 30  # 最大历史数据点数
        self.current_heart_rate = 0  # 当前心率值
        
        self.init_ui()
        self.init_worker()
        self.setup_auto_hide()
        
    def init_ui(self):
        # 设置无标题栏窗口
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 设置窗口大小
        self.setFixedSize(300, 300)  # 增加窗口高度以容纳心形动画
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        central_widget.setLayout(main_layout)
        
        # 创建心形动画组件
        self.heart_widget = AnimatedHeartWidget()
        self.heart_widget.setFixedSize(150, 150)
        main_layout.addWidget(self.heart_widget, alignment=Qt.AlignmentFlag.AlignCenter)
        
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
        
        # 创建重新扫描按钮（原重连按钮，现在更名为重新扫描）
        self.rescan_button = QPushButton("重新扫描")
        self.rescan_button.setFont(QFont("Arial", 8))
        self.rescan_button.setStyleSheet(
            "background-color: #555555; color: white; border: none; padding: 3px;"
        )
        self.rescan_button.clicked.connect(self.manual_rescan)
        self.rescan_button.setVisible(False)  # 默认隐藏重新扫描按钮
        
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
        button_layout.addWidget(self.rescan_button)
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
        self.worker.disconnected.connect(self.handle_disconnected)
        self.worker.connection_success.connect(self.handle_connection_success)
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
        self.current_heart_rate = heart_rate
        self.heart_rate_label.setText(f"{heart_rate}")
        
        # 根据心率值设置不同颜色
        if heart_rate > 100:
            self.heart_rate_label.setStyleSheet("color: red;")
        elif heart_rate > 80:
            self.heart_rate_label.setStyleSheet("color: orange;")
        else:
            self.heart_rate_label.setStyleSheet("color: limegreen;")
        
        # 更新传感器接触状态
        if sensor_contact:
            self.contact_label.setText("传感器接触良好")
            self.contact_label.setStyleSheet("color: limegreen;")
        else:
            self.contact_label.setText("传感器接触不良")
            self.contact_label.setStyleSheet("color: orange;")
        
        # 更新心形动画
        self.heart_widget.set_heart_rate(heart_rate)
        
        # 更新心率历史数据
        self.update_heart_rate_history(heart_rate)
        
    def update_heart_rate_history(self, heart_rate):
        """更新心率历史数据"""
        self.heart_rate_history.append(heart_rate)
        if len(self.heart_rate_history) > self.max_history_points:
            self.heart_rate_history.pop(0)
        
    def update_status(self, status):
        # 更新状态信息
        self.status_label.setText(status)
        
    def handle_error(self, error):
        # 处理连接错误
        self.status_label.setText(error)
        # 心率值保持不变，仅更新颜色表示错误状态
        self.heart_rate_label.setStyleSheet("color: #666666;")
        self.heart_widget.set_connected(False)
        # 显示重新扫描按钮
        self.rescan_button.setVisible(True)
        
    def handle_disconnected(self):
        # 处理设备断开连接
        self.status_label.setText("设备已断开")
        self.heart_rate_label.setStyleSheet("color: #666666;")
        self.contact_label.setText("")
        self.heart_widget.set_connected(False)
        # 显示重新扫描按钮
        self.rescan_button.setVisible(True)
        
    def handle_connection_success(self):
        """处理连接成功事件"""
        self.status_label.setText("已成功连接到设备")
        self.heart_widget.set_connected(True)
        self.rescan_button.setVisible(False)  # 连接成功后隐藏重新扫描按钮
        
    def manual_rescan(self):
        """手动重新扫描设备"""
        self.status_label.setText("正在重新扫描设备...")
        self.rescan_button.setVisible(False)  # 隐藏重新扫描按钮
        self.worker.request_full_scan()
        
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
        logger.info("程序正在关闭")
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
import asyncio
from bleak import BleakClient, BleakScanner
import struct

# 蓝牙心率服务和特征 UUID
HRS_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HRM_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

async def handle_device(client):
    """
    处理连接的设备，监听心率数据
    """
    # 连接设备
    if not client.is_connected:
        await client.connect()
        print(f"Connecting device: {client.address}")
    
    # 开始监听心率测量特征的通知
    await client.start_notify(HRM_UUID, notification_handler)
    print("Started heart rate monitoring...")
    print("Waiting for heart rate data...")
    
    # 保持连接直到出错或用户中断
    try:
        while client.is_connected:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("User interrupt")
    finally:
        await client.stop_notify(HRM_UUID)

def notification_handler(sender, data):
    """
    心率数据通知处理函数
    """
    # 解析心率数据
    flag = data[0]
    
    # 心率值格式
    if flag & 0x01:
        # 16位心率值
        heart_rate_value = struct.unpack('<H', data[1:3])[0]
        index = 3
    else:
        # 8位心率值
        heart_rate_value = data[1]
        index = 2
    
    # 传感器接触状态
    sensor_contact = None
    if flag & 0x04:
        sensor_contact = bool(flag & 0x02)
    
    print(f"HeartRateValue: {heart_rate_value}, SensorContactDetected: {sensor_contact}")

async def main():
    """
    主函数，扫描并连接小米手环设备
    """
    print("Scanning for heart rate devices...")
    
    # 扫描已连接的心率设备
    devices = await BleakScanner.discover()
    heart_rate_devices = [device for device in devices if is_heart_rate_device(device)]
    
    if heart_rate_devices:
        device = heart_rate_devices[0]
        print(f"Found device: {device.name} [{device.address}]")
    else:
        print("No heart rate devices found. Starting scan...")
        device = await BleakScanner.find_device_by_filter(
            lambda d, ad: HRS_UUID in ad.service_uuids if ad.service_uuids else False
        )
        
        if device:
            print(f"Found device: {device.name} [{device.address}]")
        else:
            print("No device found")
            return
    
    # 连接设备并处理心率数据
    async with BleakClient(device) as client:
        try:
            await handle_device(client)
        except Exception as e:
            print(f"Connection error: {e}")

def is_heart_rate_device(device):
    """
    检查设备是否是心率设备（简单检查名称）
    """
    if not device.name:
        return False
    name = device.name.lower()
    return "miband" in name or "xiaomi" in name or "mi band" in name

if __name__ == "__main__":
    asyncio.run(main())
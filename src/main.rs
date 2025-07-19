#![feature(never_type)]

use std::error::Error;

use async_trait::async_trait;
use bluest::{
    btuuid::bluetooth_uuid_from_u16,
    pairing::{IoCapability, PairingAgent, PairingRejected, Passkey},
    Adapter, Device, Uuid,
};
use futures_lite::stream::StreamExt;

const HRS_UUID: Uuid = bluetooth_uuid_from_u16(0x180D);
const HRM_UUID: Uuid = bluetooth_uuid_from_u16(0x2A37);

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    let adapter = Adapter::default()
        .await
        .ok_or("Bluetooth adapter not found")?;
    adapter.wait_available().await?;

    loop {
        let device = {
            let connected_heart_rate_devices =
                adapter.connected_devices_with_services(&[HRS_UUID]).await?;
            if let Some(device) = connected_heart_rate_devices.into_iter().next() {
                device
            } else {
                println!("Starting scan");
                let mut scan = adapter.discover_devices(&[HRS_UUID]).await?;

                println!("Scan started");
                let device = scan.next().await.unwrap()?;

                println!("Found Device: [{}] {:?}", device, device.name_async().await);
                device
            }
        };

        let Err(err) = handle_device(&adapter, &device).await;
        println!("Connection error: {err:?}");
    }
}

async fn handle_device(adapter: &Adapter, device: &Device) -> Result<!, Box<dyn Error>> {
    // Connect
    if !device.is_connected().await {
        println!("Connecting device: {}", device.id());
        adapter.connect_device(&device).await?;
    }
    println!("Connected");

    // Pair
    if !device.is_paired().await? {
        println!("Pairing");
        match device.pair_with_agent(&StdioPairingAgent).await {
            Ok(_) => println!("Pairing success"),
            Err(err) => println!("Failed to pair: {err:?}"),
        }
    }

    // Discover services
    let heart_rate_services = device.discover_services_with_uuid(HRS_UUID).await?;
    println!("Discovered service");
    let heart_rate_service = heart_rate_services
        .first()
        .ok_or("Device should has one heart rate service at least")?;

    // Discover characteristics
    let heart_rate_measurements = heart_rate_service
        .discover_characteristics_with_uuid(HRM_UUID)
        .await?;
    println!("Discovered characteristic");
    let heart_rate_measurement = heart_rate_measurements
        .first()
        .ok_or("HeartRateService should has one heart rate measurement characteristic at least")?;

    let mut updates = heart_rate_measurement.notify().await?;
    println!("Enabled notification");
    while let Some(Ok(heart_rate)) = updates.next().await {
        let flag = *heart_rate.get(0).ok_or("No flag")?;

        // Heart Rate Value Format
        let mut heart_rate_value = *heart_rate.get(1).ok_or("No heart rate u8")? as u16;
        if flag & 0b00001 != 0 {
            heart_rate_value |= (*heart_rate.get(2).ok_or("No heart rate u16")? as u16) << 8;
        }

        // Sensor Contact Supported
        let mut sensor_contact = None;
        if flag & 0b00100 != 0 {
            sensor_contact = Some(flag & 0b00010 != 0)
        }
        println!("HeartRateValue: {heart_rate_value}, SensorContactDetected: {sensor_contact:?}");
    }
    Err("No longer heart rate notify".into())
}

struct StdioPairingAgent;

#[async_trait]
impl PairingAgent for StdioPairingAgent {
    /// The input/output capabilities of this agent
    fn io_capability(&self) -> IoCapability {
        IoCapability::KeyboardDisplay
    }

    async fn confirm(&self, device: &Device) -> Result<(), PairingRejected> {
        tokio::task::block_in_place(move || {
            println!(
                "Do you want to pair with {:?}? (Y/n)",
                device.name().unwrap()
            );
            let mut buf = String::new();
            std::io::stdin()
                .read_line(&mut buf)
                .map_err(|_| PairingRejected::default())?;
            let response = buf.trim();
            if response.is_empty() || response == "y" || response == "Y" {
                Ok(())
            } else {
                Err(PairingRejected::default())
            }
        })
    }

    async fn confirm_passkey(
        &self,
        device: &Device,
        passkey: Passkey,
    ) -> Result<(), PairingRejected> {
        tokio::task::block_in_place(move || {
            println!(
                "Is the passkey \"{}\" displayed on {:?}? (Y/n)",
                passkey,
                device.name().unwrap()
            );
            let mut buf = String::new();
            std::io::stdin()
                .read_line(&mut buf)
                .map_err(|_| PairingRejected::default())?;
            let response = buf.trim();
            if response.is_empty() || response == "y" || response == "Y" {
                Ok(())
            } else {
                Err(PairingRejected::default())
            }
        })
    }

    async fn request_passkey(&self, device: &Device) -> Result<Passkey, PairingRejected> {
        tokio::task::block_in_place(move || {
            println!(
                "Please enter the 6-digit passkey for {:?}: ",
                device.name().unwrap()
            );
            let mut buf = String::new();
            std::io::stdin()
                .read_line(&mut buf)
                .map_err(|_| PairingRejected::default())?;
            buf.trim().parse().map_err(|_| PairingRejected::default())
        })
    }

    fn display_passkey(&self, device: &Device, passkey: Passkey) {
        println!(
            "The passkey is \"{}\" for {:?}.",
            passkey,
            device.name().unwrap()
        );
    }
}

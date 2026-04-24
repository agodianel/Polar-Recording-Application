#!/usr/bin/env python3
"""Diagnostic v3 — test pairing + alternative indicate subscription methods."""

import asyncio
import struct
from bleak import BleakClient, BleakScanner


PMD_CONTROL = "FB005C81-02E7-F387-1CAD-8ACD2D8DF0C8"
PMD_DATA = "FB005C82-02E7-F387-1CAD-8ACD2D8DF0C8"
HR_MEASUREMENT = "00002a37-0000-1000-8000-00805f9b34fb"


async def main():
    print("🔍 Scanning...")
    device = await BleakScanner.find_device_by_filter(
        lambda d, a: d.name and "Polar" in d.name,
        timeout=10,
    )
    if not device:
        print("❌ No Polar device found!")
        return
    print(f"✅ Found: {device.name}\n")

    # ── Approach 1: Connect + Pair, then start_notify ────────────
    print("=" * 60)
    print("APPROACH 1: Pair device, then start_notify")
    print("=" * 60)

    client = BleakClient(device, timeout=15)
    await asyncio.wait_for(client.connect(), timeout=15)
    print(f"✅ Connected")

    # Try pairing
    print("🔐 Pairing device...")
    try:
        result = await asyncio.wait_for(client.pair(), timeout=10)
        print(f"✅ Pair result: {result}")
    except asyncio.TimeoutError:
        print("⚠️  Pair timed out (may already be paired)")
    except Exception as e:
        print(f"⚠️  Pair error: {e}")

    # Now try start_notify on PMD Control
    pmd_responses = []

    def pmd_handler(sender, data):
        pmd_responses.append(data)
        print(f"   ⚡ PMD Control: {data.hex()}")

    print(f"\n⚡ start_notify on PMD Control (indicate)...")
    try:
        await asyncio.wait_for(
            client.start_notify(PMD_CONTROL, pmd_handler),
            timeout=10,
        )
        print("✅ PMD Control subscribed!")

        # Subscribe to PMD Data too
        def data_handler(sender, data):
            print(f"   📊 PMD Data: {len(data)} bytes")

        await asyncio.wait_for(
            client.start_notify(PMD_DATA, data_handler),
            timeout=10,
        )
        print("✅ PMD Data subscribed!")

        # Try reading supported measurement types
        print("\n📖 Reading PMD features...")
        features = await client.read_gatt_char(PMD_CONTROL)
        print(f"   Features: {features.hex()}")

        await asyncio.sleep(3)
        print(f"\n   PMD responses received: {len(pmd_responses)}")
        await client.disconnect()
        print("✅ Approach 1 SUCCEEDED!\n")
        return

    except asyncio.TimeoutError:
        print("❌ start_notify still times out after pairing")
        await client.disconnect()

    # ── Approach 2: Use BluezDBus workaround ─────────────────────
    print("\n" + "=" * 60)
    print("APPROACH 2: Register callback + trigger via read/write")
    print("=" * 60)

    client2 = BleakClient(device, timeout=15)
    await asyncio.wait_for(client2.connect(), timeout=15)
    print(f"✅ Connected")

    # Subscribe PMD Data first (this works)
    pmd_data_received = []

    def data_handler2(sender, data):
        pmd_data_received.append(data)
        print(f"   📊 PMD Data: {len(data)} bytes (type=0x{data[0]:02x})")

    await asyncio.wait_for(
        client2.start_notify(PMD_DATA, data_handler2),
        timeout=10,
    )
    print("✅ PMD Data subscribed")

    # Skip PMD Control subscription entirely — just read features
    print(f"\n📖 Reading PMD Control (skipping indicate subscription)...")
    try:
        features = await client2.read_gatt_char(PMD_CONTROL)
        print(f"   Features byte: {features.hex()}")
        # Parse feature byte
        if len(features) > 1:
            feat_byte = features[1]
            streams = []
            if feat_byte & 0x01:
                streams.append("ECG")
            if feat_byte & 0x02:
                streams.append("PPG")
            if feat_byte & 0x04:
                streams.append("ACC")
            if feat_byte & 0x08:
                streams.append("PPI")
            if feat_byte & 0x10:
                streams.append("Gyro")
            if feat_byte & 0x20:
                streams.append("Mag")
            print(f"   Available streams: {streams}")
    except Exception as e:
        print(f"   Read failed: {e}")

    # Try writing a command to start ECG without subscribing to indications
    print(f"\n⚡ Writing ECG start command to PMD Control...")
    # ECG start command: [0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0E, 0x00]
    ecg_start = bytes([0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0E, 0x00])
    try:
        await client2.write_gatt_char(PMD_CONTROL, ecg_start, response=True)
        print("   ✅ ECG start command written!")
        print("   Waiting 5 seconds for ECG data...")
        await asyncio.sleep(5)
        print(f"   📊 ECG packets received: {len(pmd_data_received)}")
    except Exception as e:
        print(f"   ❌ Write failed: {e}")

    await client2.disconnect()
    print("\n🔌 Disconnected.")


if __name__ == "__main__":
    asyncio.run(main())

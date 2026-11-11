import asyncio

from epaper_studio.gicisky.protocol import Job, ble_error, short_uuid, transfer


def run(job: Job, data: bytes) -> None:
    asyncio.run(transfer(job, data))


def test_upload_reaches_the_tag_intact(fake_ble) -> None:
    data = bytes((i * 7) % 256 for i in range(30000))
    job = Job(fake_ble.ADDRESS, len(data))
    run(job, data)
    assert job.status == "ok", job.error
    assert fake_ble.FakeClient.received["data"] == data
    assert ("lost", 40) in fake_ble.FakeClient.received["events"]
    codes = [e["code"] for e in job.log if e["kind"] == "note"]
    assert "block_repeat" in codes and codes[-1] == "delivered"
    assert job.part == job.blocks == 125


def test_tag_may_end_with_another_code(fake_ble) -> None:
    fake_ble.FakeClient.finish_with_end_code = True
    data = bytes(4800)
    job = Job(fake_ble.ADDRESS, len(data))
    run(job, data)
    assert job.status == "ok"


def test_missing_tag_fails_with_a_code(fake_ble) -> None:
    job = Job("00:00:00:00:00:00", 240)
    asyncio.run(transfer(job, bytes(240), attempts=1))
    assert job.status == "error"
    assert job.error["code"] == "tag_not_seen"


def test_job_view_is_incremental(fake_ble) -> None:
    job = Job(fake_ble.ADDRESS, 480)
    run(job, bytes(480))
    first = job.view(0)
    assert first["log_len"] == len(first["log"]) > 0
    assert job.view(first["log_len"])["log"] == []


def test_ble_error_translation() -> None:
    assert ble_error(FileNotFoundError("no dbus"))[0].code == "ble_service_missing"
    assert ble_error(Exception("No Bluetooth adapters found."))[0].code == "ble_no_adapter"
    err, retry = ble_error(Exception("org.bluez.Error.InProgress"))
    assert err.code == "ble_busy_adapter" and retry
    assert ble_error(Exception("weird"))[0].params == {"detail": "weird"}


def test_short_uuid() -> None:
    assert short_uuid("0000fef1-0000-1000-8000-00805f9b34fb") == "fef1"
    assert short_uuid("FEF2") == "fef2"


def test_ble_error_bleak_not_available() -> None:
    from bleak.exc import BleakBluetoothNotAvailableError
    from bleak.exc import BleakBluetoothNotAvailableReason as R

    err, retry = ble_error(BleakBluetoothNotAvailableError("No Bluetooth adapter found", R.NO_BLUETOOTH))
    assert err.code == "ble_no_adapter" and not retry
    assert ble_error(BleakBluetoothNotAvailableError("off", R.POWERED_OFF))[0].code == "ble_powered_off"
    assert ble_error(BleakBluetoothNotAvailableError("no", R.NO_BLE_CENTRAL_ROLE))[0].code == "ble_no_central"
    assert ble_error(BleakBluetoothNotAvailableError("no", R.DENIED_BY_USER))[0].code == "ble_denied"
    # Unknown reasons keep a readable detail, never the raw args tuple.
    assert ble_error(BleakBluetoothNotAvailableError("odd", R.UNKNOWN))[0].params == {"detail": "odd"}


def test_ble_error_timeout_and_tuple_args() -> None:
    import asyncio

    assert ble_error(asyncio.TimeoutError())[0].code == "ble_timeout"
    assert ble_error(Exception("boom", 42))[0].params == {"detail": "boom"}

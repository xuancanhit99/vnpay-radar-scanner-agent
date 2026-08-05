from radar_agent import device_identity


class FakeDevice:
    def __init__(self, properties: dict[str, str]):
        self._properties = properties

    def shell(self, command: list[str], *, timeout: int) -> str:
        assert command[0] == "getprop"
        assert timeout == 3
        return self._properties.get(command[1], "")


class FakeAdbClient:
    def __init__(self, device: FakeDevice):
        self._device = device
        self.serials: list[str] = []

    def device(self, *, serial: str) -> FakeDevice:
        self.serials.append(serial)
        return self._device


def _install_fake_client(monkeypatch, properties: dict[str, str]) -> FakeAdbClient:
    client = FakeAdbClient(FakeDevice(properties))

    def factory(**kwargs) -> FakeAdbClient:
        assert kwargs == {"host": "127.0.0.1", "port": 5037, "socket_timeout": 3}
        return client

    monkeypatch.setattr(device_identity, "AdbClient", factory)
    return client


def test_query_adb_device_model_prefers_marketing_name(monkeypatch) -> None:
    client = _install_fake_client(
        monkeypatch,
        {
            "ro.product.marketname": "  Xiaomi\n13  ",
            "ro.product.model": "2211133G",
        },
    )

    model = device_identity.query_adb_device_model("314ebbfe")

    assert model == "Xiaomi 13"
    assert client.serials == ["314ebbfe"]


def test_query_adb_device_model_combines_manufacturer_and_model(monkeypatch) -> None:
    _install_fake_client(
        monkeypatch,
        {
            "ro.product.model": "SM-S911B",
            "ro.product.manufacturer": "Samsung",
        },
    )

    assert device_identity.query_adb_device_model("device-001") == "Samsung SM-S911B"


def test_query_adb_device_model_is_best_effort(monkeypatch) -> None:
    def fail(**_kwargs):
        raise OSError("ADB server is unavailable")

    monkeypatch.setattr(device_identity, "AdbClient", fail)

    assert device_identity.query_adb_device_model("device-001") is None


def test_normalize_device_model_removes_control_whitespace_and_nulls() -> None:
    assert device_identity.normalize_device_model("  Xiaomi\x00\n13  ") == "Xiaomi 13"

import asyncio
import logging

from adbutils import AdbClient

DEFAULT_DEVICE_MODEL = "Android Device"
_MARKET_NAME_PROPERTIES = (
    "ro.product.marketname",
    "ro.product.vendor.marketname",
    "ro.product.odm.marketname",
)
_MODEL_PROPERTIES = (
    "ro.product.model",
    "ro.product.vendor.model",
)
_MANUFACTURER_PROPERTIES = (
    "ro.product.manufacturer",
    "ro.product.vendor.manufacturer",
)
_MAX_LABEL_LENGTH = 255
_LOGGER = logging.getLogger(__name__)


def normalize_device_model(value: object) -> str | None:
    """Return a compact, display-safe device label from an external value."""
    label = " ".join(str(value or "").replace("\x00", "").split())
    return label[:_MAX_LABEL_LENGTH] or None


def _first_property(device: object, names: tuple[str, ...]) -> str | None:
    for name in names:
        value = device.shell(["getprop", name], timeout=3)  # type: ignore[attr-defined]
        normalized = normalize_device_model(value)
        if normalized:
            return normalized
    return None


def query_adb_device_model(serial: str) -> str | None:
    """Read the best available marketing/model name from the local ADB server."""
    normalized_serial = normalize_device_model(serial)
    if not normalized_serial:
        return None

    try:
        client = AdbClient(host="127.0.0.1", port=5037, socket_timeout=3)
        device = client.device(serial=normalized_serial)
        market_name = _first_property(device, _MARKET_NAME_PROPERTIES)
        if market_name:
            return market_name

        model = _first_property(device, _MODEL_PROPERTIES)
        if not model:
            return None
        manufacturer = _first_property(device, _MANUFACTURER_PROPERTIES)
        if not manufacturer or model.casefold().startswith(manufacturer.casefold()):
            return model
        return normalize_device_model(f"{manufacturer} {model}")
    except Exception as exc:
        # Device discovery is best-effort and must never break the heartbeat loop.
        _LOGGER.debug("Could not read Android model for ADB serial %s: %s", serial, exc)
        return None


async def resolve_adb_device_model(serial: str) -> str | None:
    return await asyncio.to_thread(query_adb_device_model, serial)

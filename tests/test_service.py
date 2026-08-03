import ssl

from radar_agent.service import _tls_verifier


def test_tls_verifier_uses_system_trust_store() -> None:
    assert isinstance(_tls_verifier(True), ssl.SSLContext)


def test_tls_verifier_can_be_disabled_explicitly() -> None:
    assert _tls_verifier(False) is False

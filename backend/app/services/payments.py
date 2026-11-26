"""Local-only payment option handlers; no external provider or financial transaction."""
from dataclasses import dataclass
import secrets


@dataclass(frozen=True)
class DemoPaymentResult:
    successful: bool
    reference: str
    note: str


def process_demo_payment(*, force_failure: bool = False) -> DemoPaymentResult:
    """Simulate a payment outcome entirely in-process for demonstrations/tests."""
    reference = f"DEMO-{secrets.token_hex(8).upper()}"
    if force_failure:
        return DemoPaymentResult(False, reference, "Demo-only simulated failure; no real payment was attempted.")
    return DemoPaymentResult(True, reference, "Demo-only simulated success; no real payment was attempted.")

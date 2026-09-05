from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional

@dataclass
class Payment:
    payment_id: str
    intent_id: str
    amount: float
    customer_name: str
    created_at: str  # ISO format string: YYYY-MM-DDTHH:MM:SS.fffZ

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Payment":
        return cls(**data)


@dataclass
class Webhook:
    webhook_id: str
    intent_id: str
    received_at: str  # ISO format string: YYYY-MM-DDTHH:MM:SS.fffZ
    amount: Optional[float] = None
    customer_name: Optional[str] = None
    event_type: str = "payment.captured"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Webhook":
        return cls(**data)


@dataclass
class ReconciliationResult:
    intent_id: str
    status: str  # "CLEAN", "DUPLICATE_PREVENTED", "NEEDS_MANUAL_REVIEW", "EXCEPTION"
    confidence: float
    reasoning: str
    amount_at_risk: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReconciliationResult":
        return cls(**data)

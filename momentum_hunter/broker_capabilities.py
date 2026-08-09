from __future__ import annotations

"""Provider-neutral broker capability evidence with fail-closed semantics."""

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class CapabilityState(str, Enum):
    PROVEN = "PROVEN"
    DOCUMENTED_UNPROVEN = "DOCUMENTED_UNPROVEN"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class BrokerCapabilityError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrokerCapability:
    name: str
    state: CapabilityState
    value: str
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("_", "").isalnum():
            raise BrokerCapabilityError("Capability name must be nonempty identifier text.")
        if not self.value:
            raise BrokerCapabilityError("Capability value must be explicit.")
        if not self.evidence or any(not item.strip() for item in self.evidence):
            raise BrokerCapabilityError("Capability evidence must be explicit.")

    @property
    def is_proven(self) -> bool:
        return self.state is CapabilityState.PROVEN


@dataclass(frozen=True)
class BrokerCapabilityRegistry:
    provider: str
    environment: str
    schema_version: int
    capabilities: tuple[BrokerCapability, ...]

    def __post_init__(self) -> None:
        if not self.provider or not self.environment:
            raise BrokerCapabilityError("Provider and environment are required.")
        if self.schema_version < 1:
            raise BrokerCapabilityError("Capability schema version must be positive.")
        names = [capability.name for capability in self.capabilities]
        if len(names) != len(set(names)):
            raise BrokerCapabilityError("Duplicate broker capability names are forbidden.")

    @classmethod
    def build(
        cls,
        *,
        provider: str,
        environment: str,
        capabilities: Iterable[BrokerCapability],
        schema_version: int = 1,
    ) -> BrokerCapabilityRegistry:
        return cls(
            provider=provider,
            environment=environment,
            schema_version=schema_version,
            capabilities=tuple(sorted(capabilities, key=lambda item: item.name)),
        )

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.to_dict(include_fingerprint=False),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest().upper()

    def get(self, name: str) -> BrokerCapability:
        for capability in self.capabilities:
            if capability.name == name:
                return capability
        return BrokerCapability(
            name=name,
            state=CapabilityState.UNKNOWN,
            value="UNKNOWN",
            evidence=("No capability evidence is registered.",),
        )

    def require_proven(self, name: str) -> BrokerCapability:
        capability = self.get(name)
        if not capability.is_proven:
            raise BrokerCapabilityError(
                f"Broker capability {name} is {capability.state.value}; proven support is required."
            )
        return capability

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schemaVersion": self.schema_version,
            "provider": self.provider,
            "environment": self.environment,
            "capabilities": [
                {
                    "name": item.name,
                    "state": item.state.value,
                    "value": item.value,
                    "evidence": list(item.evidence),
                }
                for item in self.capabilities
            ],
        }
        if include_fingerprint:
            payload["fingerprint"] = self.fingerprint
        return payload


CAPABILITY_FRACTIONAL_QUANTITY = "supportsFractionalQuantity"
CAPABILITY_FRACTIONAL_PRECISION = "fractionalQuantityPrecision"
CAPABILITY_FRACTIONAL_MARKET = "supportsFractionalMarket"
CAPABILITY_FRACTIONAL_LIMIT = "supportsFractionalLimit"
CAPABILITY_FRACTIONAL_STOP = "supportsFractionalStop"
CAPABILITY_FRACTIONAL_STOP_LIMIT = "supportsFractionalStopLimit"
CAPABILITY_FRACTIONAL_TAKE_PROFIT = "supportsFractionalTakeProfit"
CAPABILITY_FRACTIONAL_BRACKET = "supportsFractionalBracket"
CAPABILITY_FRACTIONAL_OCO = "supportsFractionalOco"
CAPABILITY_FRACTIONAL_OTO = "supportsFractionalOto"
CAPABILITY_FRACTIONAL_REPLACE = "supportsFractionalReplace"
CAPABILITY_CANCEL = "supportsCancel"
CAPABILITY_CLIENT_ORDER_ID = "supportsClientOrderId"
CAPABILITY_PAPER_ENVIRONMENT = "supportsPaperEnvironment"
CAPABILITY_EXTENDED_HOURS = "supportsExtendedHours"
CAPABILITY_OVERNIGHT = "supportsOvernight"
CAPABILITY_ORDER_STATUS_STREAM = "supportsOrderStatusStream"
CAPABILITY_BROKER_RESIDENT_PROTECTION = "supportsBrokerResidentProtection"
CAPABILITY_WHOLE_QUANTITY = "supportsWholeQuantity"
CAPABILITY_MARKET_ORDER = "supportsMarketOrder"
CAPABILITY_LIMIT_ORDER = "supportsLimitOrder"
CAPABILITY_STOP_ORDER = "supportsStopOrder"
CAPABILITY_STOP_LIMIT_ORDER = "supportsStopLimitOrder"

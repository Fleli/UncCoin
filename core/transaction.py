import json
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
from typing import Any


TRANSACTION_VERSION_LEGACY = 1
TRANSACTION_VERSION_TYPED = 2

TRANSACTION_KIND_TRANSFER = "transfer"
TRANSACTION_KIND_EXECUTE = "execute"
TRANSACTION_KIND_COMMIT = "commit"


def _canonicalize_payload(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): _canonicalize_payload(value[key])
            for key in sorted(value)
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize_payload(item) for item in value]
    return value


@dataclass
class Transaction:
    sender: str
    receiver: str
    amount: Decimal
    fee: Decimal
    timestamp: datetime
    nonce: int = 0
    sender_public_key: tuple[int, int] | None = None
    signature: str | None = None
    kind: str = TRANSACTION_KIND_TRANSFER
    payload: dict[str, Any] = field(default_factory=dict)
    version: int = TRANSACTION_VERSION_TYPED

    def __post_init__(self) -> None:
        self.amount = Decimal(str(self.amount))
        self.fee = Decimal(str(self.fee))
        self.version = int(self.version)
        self.kind = str(self.kind or TRANSACTION_KIND_TRANSFER)
        if self.kind == TRANSACTION_KIND_TRANSFER and not self.payload:
            self.payload = {
                "receiver": self.receiver,
                "amount": str(self.amount),
            }

    @classmethod
    def transfer(
        cls,
        sender: str,
        receiver: str,
        amount: Decimal | str,
        fee: Decimal | str,
        timestamp: datetime,
        nonce: int = 0,
        sender_public_key: tuple[int, int] | None = None,
        signature: str | None = None,
    ) -> "Transaction":
        return cls(
            sender=sender,
            receiver=receiver,
            amount=amount,
            fee=fee,
            timestamp=timestamp,
            nonce=nonce,
            sender_public_key=sender_public_key,
            signature=signature,
            kind=TRANSACTION_KIND_TRANSFER,
            payload={
                "receiver": receiver,
                "amount": str(Decimal(str(amount))),
            },
        )

    @classmethod
    def execute(
        cls,
        sender: str,
        contract_address: str,
        input_data: str,
        fee: Decimal | str,
        timestamp: datetime,
        nonce: int = 0,
        value: Decimal | str = Decimal("0.0"),
        gas_limit: int = 0,
        authorizations: list[dict[str, Any]] | None = None,
        sender_public_key: tuple[int, int] | None = None,
        signature: str | None = None,
    ) -> "Transaction":
        return cls(
            sender=sender,
            receiver=contract_address,
            amount=value,
            fee=fee,
            timestamp=timestamp,
            nonce=nonce,
            sender_public_key=sender_public_key,
            signature=signature,
            kind=TRANSACTION_KIND_EXECUTE,
            payload={
                "contract_address": contract_address,
                "input": input_data,
                "value": str(Decimal(str(value))),
                "gas_limit": int(gas_limit),
                "authorizations": authorizations or [],
            },
        )

    @classmethod
    def commit(
        cls,
        sender: str,
        request_id: str,
        commitment_hash: str,
        fee: Decimal | str,
        timestamp: datetime,
        nonce: int = 0,
        sender_public_key: tuple[int, int] | None = None,
        signature: str | None = None,
    ) -> "Transaction":
        return cls(
            sender=sender,
            receiver="",
            amount=Decimal("0.0"),
            fee=fee,
            timestamp=timestamp,
            nonce=nonce,
            sender_public_key=sender_public_key,
            signature=signature,
            kind=TRANSACTION_KIND_COMMIT,
            payload={
                "request_id": request_id,
                "commitment_hash": commitment_hash,
            },
        )

    def to_dict(self) -> dict:
        return {
            "sender": self.sender,
            "receiver": self.receiver,
            "amount": str(self.amount),
            "fee": str(self.fee),
            "timestamp": self.timestamp.isoformat(),
            "nonce": self.nonce,
            "sender_public_key": (
                {
                    "exponent": str(self.sender_public_key[0]),
                    "modulus": str(self.sender_public_key[1]),
                }
                if self.sender_public_key is not None
                else None
            ),
            "signature": self.signature,
            "kind": self.kind,
            "payload": _canonicalize_payload(self.payload),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, transaction_data: dict) -> "Transaction":
        sender_public_key_data = transaction_data.get("sender_public_key")
        return cls(
            sender=transaction_data["sender"],
            receiver=transaction_data["receiver"],
            amount=Decimal(str(transaction_data["amount"])),
            fee=Decimal(str(transaction_data.get("fee", "0.0"))),
            timestamp=datetime.fromisoformat(transaction_data["timestamp"]),
            nonce=int(transaction_data.get("nonce", 0)),
            sender_public_key=(
                (
                    int(sender_public_key_data["exponent"]),
                    int(sender_public_key_data["modulus"]),
                )
                if sender_public_key_data is not None
                else None
            ),
            signature=transaction_data.get("signature"),
            kind=transaction_data.get("kind", TRANSACTION_KIND_TRANSFER),
            payload=transaction_data.get("payload", {}),
            version=int(transaction_data.get("version", TRANSACTION_VERSION_LEGACY)),
        )

    def signing_payload(self) -> str:
        if self.version == TRANSACTION_VERSION_LEGACY:
            return (
                f"{self.sender}|{self.receiver}|{self.amount}|{self.fee}|{self.nonce}|"
                f"{self.timestamp.isoformat()}"
            )

        return (
            f"{self.version}|{self.kind}|{self.sender}|{self.receiver}|"
            f"{self.amount}|{self.fee}|{self.nonce}|"
            f"{self.timestamp.isoformat()}|{self.canonical_payload()}"
        )

    def canonical_payload(self) -> str:
        return json.dumps(
            _canonicalize_payload(self.payload),
            sort_keys=True,
            separators=(",", ":"),
        )

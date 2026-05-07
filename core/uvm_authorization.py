from dataclasses import dataclass
from typing import Any

from wallet.wallet import Wallet


AUTHORIZATION_VERSION = 1
AUTHORIZATION_DOMAIN = "UVM_AUTH"
MAX_AUTHORIZATION_REQUEST_ID_LENGTH = 128


@dataclass(frozen=True)
class UvmAuthorization:
    wallet: str
    request_id: str
    public_key: tuple[int, int]
    signature: str

    def to_dict(self) -> dict:
        return {
            "wallet": self.wallet,
            "request_id": self.request_id,
            "public_key": {
                "exponent": str(self.public_key[0]),
                "modulus": str(self.public_key[1]),
            },
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, authorization_data: dict[str, Any]) -> "UvmAuthorization":
        public_key_data = authorization_data.get("public_key")
        if not isinstance(public_key_data, dict):
            raise ValueError("authorization public_key must be an object")

        return cls(
            wallet=str(authorization_data.get("wallet", "")),
            request_id=str(authorization_data.get("request_id", "")),
            public_key=(
                int(public_key_data["exponent"]),
                int(public_key_data["modulus"]),
            ),
            signature=str(authorization_data.get("signature", "")),
        )

    def validation_error(self) -> str | None:
        wallet = self.wallet.strip()
        request_id = self.request_id.strip()
        if not wallet:
            return "wallet must be non-empty"
        if not request_id:
            return "request_id must be non-empty"
        if len(request_id) > MAX_AUTHORIZATION_REQUEST_ID_LENGTH:
            return (
                "request_id must be at most "
                f"{MAX_AUTHORIZATION_REQUEST_ID_LENGTH} characters"
            )
        if not self.signature:
            return "signature must be non-empty"

        wallet_from_public_key = Wallet.address_from_public_key(self.public_key)
        if wallet != wallet_from_public_key:
            return "wallet does not match public key"

        signature_is_valid = Wallet.verify_signature_with_public_key(
            message=authorization_signing_payload(wallet, request_id),
            signature=self.signature,
            public_key=self.public_key,
        )
        if not signature_is_valid:
            return "signature verification failed"
        return None


def authorization_signing_payload(wallet: str, request_id: str) -> str:
    return (
        f"{AUTHORIZATION_DOMAIN}|{AUTHORIZATION_VERSION}|"
        f"{wallet.strip()}|{request_id.strip()}"
    )


def create_uvm_authorization(wallet: Wallet, request_id: str) -> UvmAuthorization:
    payload = authorization_signing_payload(wallet.address, request_id)
    return UvmAuthorization(
        wallet=wallet.address,
        request_id=request_id.strip(),
        public_key=wallet.public_key,
        signature=wallet.sign_message(payload),
    )


def build_authorization_index(
    submitted_authorizations: list[dict[str, Any]] | list[UvmAuthorization],
) -> dict[str, list[str]]:
    authorization_sets: dict[str, set[str]] = {}
    for index, submitted_authorization in enumerate(submitted_authorizations):
        try:
            authorization = (
                submitted_authorization
                if isinstance(submitted_authorization, UvmAuthorization)
                else UvmAuthorization.from_dict(submitted_authorization)
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                f"authorization {index} is invalid: {error}"
            ) from error

        validation_error = authorization.validation_error()
        if validation_error is not None:
            raise ValueError(
                f"authorization {index} is invalid: {validation_error}"
            )

        wallet = authorization.wallet.strip()
        request_id = authorization.request_id.strip()
        authorization_sets.setdefault(wallet, set()).add(request_id)

    return {
        wallet: sorted(request_ids)
        for wallet, request_ids in sorted(authorization_sets.items())
    }


def is_request_authorized(
    authorization_index: dict[str, list[str]],
    wallet: str,
    request_id: str,
) -> bool:
    return request_id.strip() in authorization_index.get(wallet.strip(), [])

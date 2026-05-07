import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from wallet.wallet import Wallet


AUTHORIZATION_VERSION = 1
AUTHORIZATION_DOMAIN = "UVM_AUTH"
MAX_AUTHORIZATION_REQUEST_ID_LENGTH = 128


@dataclass(frozen=True)
class UvmAuthorizationScope:
    valid_from_height: int | None = None
    valid_until_height: int | None = None
    max_amount: Decimal | None = None

    def to_dict(self) -> dict[str, Any]:
        scope: dict[str, Any] = {}
        if self.valid_from_height is not None:
            scope["valid_from_height"] = self.valid_from_height
        if self.valid_until_height is not None:
            scope["valid_until_height"] = self.valid_until_height
        if self.max_amount is not None:
            scope["max_amount"] = str(self.max_amount)
        return scope

    @classmethod
    def from_dict(cls, scope_data: dict[str, Any] | None) -> "UvmAuthorizationScope":
        if scope_data is None:
            return cls()
        if not isinstance(scope_data, dict):
            raise ValueError("authorization scope must be an object")

        max_amount = None
        if "max_amount" in scope_data and scope_data["max_amount"] is not None:
            try:
                max_amount = Decimal(str(scope_data["max_amount"]))
            except (InvalidOperation, ValueError) as error:
                raise ValueError("scope.max_amount must be a decimal") from error

        return cls(
            valid_from_height=_parse_optional_height(
                scope_data.get("valid_from_height"),
                "scope.valid_from_height",
            ),
            valid_until_height=_parse_optional_height(
                scope_data.get("valid_until_height"),
                "scope.valid_until_height",
            ),
            max_amount=max_amount,
        )

    def validation_error(self, block_height: int | None = None) -> str | None:
        if (
            self.valid_from_height is not None
            and self.valid_until_height is not None
            and self.valid_until_height < self.valid_from_height
        ):
            return "scope.valid_until_height must be greater than or equal to valid_from_height"
        if self.max_amount is not None:
            try:
                max_amount = Decimal(str(self.max_amount))
            except (InvalidOperation, ValueError):
                return "scope.max_amount must be a decimal"
            if not max_amount.is_finite():
                return "scope.max_amount must be finite"
            if max_amount < Decimal("0.0"):
                return "scope.max_amount must be non-negative"
        if block_height is None:
            return None
        if self.valid_from_height is not None and block_height < self.valid_from_height:
            return (
                "authorization is not valid until block "
                f"{self.valid_from_height}"
            )
        if self.valid_until_height is not None and block_height > self.valid_until_height:
            return f"authorization expired at block {self.valid_until_height}"
        return None


@dataclass(frozen=True)
class UvmAuthorization:
    wallet: str
    request_id: str
    public_key: tuple[int, int]
    signature: str
    scope: UvmAuthorizationScope = field(default_factory=UvmAuthorizationScope)

    def to_dict(self) -> dict:
        authorization = {
            "wallet": self.wallet,
            "request_id": self.request_id,
            "public_key": {
                "exponent": str(self.public_key[0]),
                "modulus": str(self.public_key[1]),
            },
            "signature": self.signature,
        }
        scope = self.scope.to_dict()
        if scope:
            authorization["scope"] = scope
        return authorization

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
            scope=UvmAuthorizationScope.from_dict(
                authorization_data.get("scope", {})
            ),
        )

    def validation_error(self, block_height: int | None = None) -> str | None:
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
        scope_error = self.scope.validation_error(block_height)
        if scope_error is not None:
            return scope_error
        if not self.signature:
            return "signature must be non-empty"

        wallet_from_public_key = Wallet.address_from_public_key(self.public_key)
        if wallet != wallet_from_public_key:
            return "wallet does not match public key"

        signature_is_valid = Wallet.verify_signature_with_public_key(
            message=authorization_signing_payload(wallet, request_id, self.scope),
            signature=self.signature,
            public_key=self.public_key,
        )
        if not signature_is_valid:
            return "signature verification failed"
        return None


def authorization_signing_payload(
    wallet: str,
    request_id: str,
    scope: UvmAuthorizationScope | dict[str, Any] | None = None,
) -> str:
    scope_payload = UvmAuthorizationScope.from_dict(
        scope.to_dict() if isinstance(scope, UvmAuthorizationScope) else scope or {}
    ).to_dict()
    payload = (
        f"{AUTHORIZATION_DOMAIN}|{AUTHORIZATION_VERSION}|"
        f"{wallet.strip()}|{request_id.strip()}"
    )
    if scope_payload:
        payload = f"{payload}|{_canonical_scope_payload(scope_payload)}"
    return payload


def create_uvm_authorization(
    wallet: Wallet,
    request_id: str,
    *,
    valid_from_height: int | None = None,
    valid_until_height: int | None = None,
    valid_for_blocks: int | None = None,
    current_height: int | None = None,
    max_amount: Decimal | str | None = None,
) -> UvmAuthorization:
    if valid_for_blocks is not None:
        valid_for_blocks = _parse_positive_int(
            valid_for_blocks,
            "valid_for_blocks",
        )
        if current_height is None:
            raise ValueError("current_height is required with valid_for_blocks")
        current_height = _parse_optional_height(current_height, "current_height")
        if valid_until_height is not None:
            raise ValueError("valid_until_height cannot be combined with valid_for_blocks")
        if valid_from_height is None:
            valid_from_height = current_height + 1
        valid_until_height = valid_from_height + valid_for_blocks - 1

    scope = UvmAuthorizationScope.from_dict(
        {
            "valid_from_height": valid_from_height,
            "valid_until_height": valid_until_height,
            "max_amount": max_amount,
        }
    )
    scope_error = scope.validation_error()
    if scope_error is not None:
        raise ValueError(scope_error)

    payload = authorization_signing_payload(wallet.address, request_id, scope)
    return UvmAuthorization(
        wallet=wallet.address,
        request_id=request_id.strip(),
        public_key=wallet.public_key,
        signature=wallet.sign_message(payload),
        scope=scope,
    )


def build_authorization_index(
    submitted_authorizations: list[dict[str, Any]] | list[UvmAuthorization],
    block_height: int | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    authorization_index: dict[str, dict[str, dict[str, Any]]] = {}
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

        validation_error = authorization.validation_error(block_height)
        if validation_error is not None:
            raise ValueError(
                f"authorization {index} is invalid: {validation_error}"
            )

        wallet = authorization.wallet.strip()
        request_id = authorization.request_id.strip()
        existing_scope = authorization_index.setdefault(wallet, {}).get(request_id)
        new_scope = authorization.scope.to_dict()
        authorization_index[wallet][request_id] = (
            new_scope
            if existing_scope is None
            else _merge_scope_dicts(existing_scope, new_scope)
        )

    return {
        wallet: {
            request_id: authorization_index[wallet][request_id]
            for request_id in sorted(authorization_index[wallet])
        }
        for wallet in sorted(authorization_index)
    }


def is_request_authorized(
    authorization_index: dict[str, Any],
    wallet: str,
    request_id: str,
) -> bool:
    return get_authorization_scope(authorization_index, wallet, request_id) is not None


def get_authorization_scope(
    authorization_index: dict[str, Any],
    wallet: str,
    request_id: str,
) -> dict[str, Any] | None:
    wallet_authorizations = authorization_index.get(wallet.strip(), {})
    if isinstance(wallet_authorizations, dict):
        scope = wallet_authorizations.get(request_id.strip())
        if scope is None:
            return None
        if isinstance(scope, dict):
            return scope.copy()
        return {}
    if request_id.strip() in wallet_authorizations:
        return {}
    return None


def _parse_optional_height(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    try:
        height = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be an integer") from error
    if height < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return height


def _parse_positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    try:
        parsed_value = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be an integer") from error
    if parsed_value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return parsed_value


def _canonical_scope_payload(scope: dict[str, Any]) -> str:
    return json.dumps(
        scope,
        sort_keys=True,
        separators=(",", ":"),
    )


def _merge_scope_dicts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_scope = UvmAuthorizationScope.from_dict(left)
    right_scope = UvmAuthorizationScope.from_dict(right)
    return UvmAuthorizationScope(
        valid_from_height=_merge_lower_bound(
            left_scope.valid_from_height,
            right_scope.valid_from_height,
        ),
        valid_until_height=_merge_upper_bound(
            left_scope.valid_until_height,
            right_scope.valid_until_height,
        ),
        max_amount=_merge_max_amount(left_scope.max_amount, right_scope.max_amount),
    ).to_dict()


def _merge_lower_bound(left: int | None, right: int | None) -> int | None:
    if left is None or right is None:
        return None
    return min(left, right)


def _merge_upper_bound(left: int | None, right: int | None) -> int | None:
    if left is None or right is None:
        return None
    return max(left, right)


def _merge_max_amount(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return max(left, right)

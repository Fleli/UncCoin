from dataclasses import dataclass
from typing import Any


MAX_AUTHORIZATION_REQUEST_ID_LENGTH = 128


@dataclass(frozen=True)
class UvmAuthorizationScope:
    valid_from_height: int | None = None
    valid_until_height: int | None = None

    def to_dict(self) -> dict[str, Any]:
        scope: dict[str, Any] = {}
        if self.valid_from_height is not None:
            scope["valid_from_height"] = self.valid_from_height
        if self.valid_until_height is not None:
            scope["valid_until_height"] = self.valid_until_height
        return scope

    @classmethod
    def from_dict(cls, scope_data: dict[str, Any] | None) -> "UvmAuthorizationScope":
        if scope_data is None:
            return cls()
        if not isinstance(scope_data, dict):
            raise ValueError("authorization scope must be an object")

        return cls(
            valid_from_height=_parse_optional_height(
                scope_data.get("valid_from_height"),
                "scope.valid_from_height",
            ),
            valid_until_height=_parse_optional_height(
                scope_data.get("valid_until_height"),
                "scope.valid_until_height",
            ),
        )

    def validation_error(self, block_height: int | None = None) -> str | None:
        if (
            self.valid_from_height is not None
            and self.valid_until_height is not None
            and self.valid_until_height < self.valid_from_height
        ):
            return "scope.valid_until_height must be greater than or equal to valid_from_height"
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

import hashlib
from dataclasses import dataclass


DEFAULT_PREFERRED_PORT = 9000


@dataclass
class Wallet:
    public_key: tuple[int, int]
    private_key: tuple[int, int]
    name: str | None = None
    preferred_port: int = DEFAULT_PREFERRED_PORT

    def __post_init__(self) -> None:
        self.preferred_port = _normalize_preferred_port(self.preferred_port)

    @property
    def address(self) -> str:
        public_exponent, modulus = self.public_key
        key_material = f"{public_exponent}:{modulus}".encode("utf-8")
        return hashlib.sha256(key_material).hexdigest()

    def sign_message(self, message: str) -> str:
        digest = self._message_digest(message)
        private_exponent, modulus = self.private_key
        signature = pow(digest, private_exponent, modulus)
        return format(signature, "x")

    def verify_signature(self, message: str, signature: str) -> bool:
        return self.verify_signature_with_public_key(
            message=message,
            signature=signature,
            public_key=self.public_key,
        )

    def key_pair_is_valid(self) -> bool:
        probe_message = "UNCCOIN_WALLET_KEYPAIR_SELF_TEST"
        try:
            return self.verify_signature(
                message=probe_message,
                signature=self.sign_message(probe_message),
            )
        except (TypeError, ValueError):
            return False

    @staticmethod
    def verify_signature_with_public_key(
        message: str,
        signature: str,
        public_key: tuple[int, int],
    ) -> bool:
        digest = Wallet._message_digest(message)
        public_exponent, modulus = public_key
        signature_value = int(signature, 16)
        verified_digest = pow(signature_value, public_exponent, modulus)
        return digest == verified_digest

    @staticmethod
    def address_from_public_key(public_key: tuple[int, int]) -> str:
        public_exponent, modulus = public_key
        key_material = f"{public_exponent}:{modulus}".encode("utf-8")
        return hashlib.sha256(key_material).hexdigest()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "address": self.address,
            "preferred_port": self.preferred_port,
            "public_key": {
                "exponent": str(self.public_key[0]),
                "modulus": str(self.public_key[1]),
            },
            "private_key": {
                "exponent": str(self.private_key[0]),
                "modulus": str(self.private_key[1]),
            },
        }

    @classmethod
    def from_dict(cls, wallet_data: dict) -> "Wallet":
        return cls(
            public_key=(
                int(wallet_data["public_key"]["exponent"]),
                int(wallet_data["public_key"]["modulus"]),
            ),
            private_key=(
                int(wallet_data["private_key"]["exponent"]),
                int(wallet_data["private_key"]["modulus"]),
            ),
            name=wallet_data.get("name"),
            preferred_port=_normalize_preferred_port(
                wallet_data.get("preferred_port", DEFAULT_PREFERRED_PORT)
            ),
        )

    @staticmethod
    def _message_digest(message: str) -> int:
        return int(hashlib.sha256(message.encode("utf-8")).hexdigest(), 16)


def _normalize_preferred_port(preferred_port: object) -> int:
    try:
        port = int(preferred_port)
    except (TypeError, ValueError):
        return DEFAULT_PREFERRED_PORT
    if 0 < port < 65536:
        return port
    return DEFAULT_PREFERRED_PORT

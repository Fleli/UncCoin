import unittest
from pathlib import Path

from wallet import create_wallet
from wallet.storage import normalize_wallet_name
from wallet.storage import wallet_path
from wallet.wallet import Wallet


class WalletModelTests(unittest.TestCase):
    def test_wallet_serializes_preferred_port(self) -> None:
        wallet = create_wallet(name="miner", preferred_port=9012)

        wallet_data = wallet.to_dict()
        restored_wallet = Wallet.from_dict(wallet_data)

        self.assertEqual(wallet_data["preferred_port"], 9012)
        self.assertEqual(restored_wallet.preferred_port, 9012)

    def test_missing_preferred_port_defaults_to_9000(self) -> None:
        wallet_data = create_wallet(name="legacy").to_dict()
        wallet_data.pop("preferred_port")

        restored_wallet = Wallet.from_dict(wallet_data)

        self.assertEqual(restored_wallet.preferred_port, 9000)

    def test_wallet_name_rejects_path_traversal(self) -> None:
        invalid_names = (
            "../alice",
            "..\\alice",
            "/tmp/alice",
            "nested/alice",
            "nested\\alice",
            ".",
            "..",
            "",
        )

        for name in invalid_names:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    normalize_wallet_name(name)

    def test_wallet_path_stays_inside_wallet_directory(self) -> None:
        path = wallet_path("alice-01.main")

        self.assertEqual(path.name, "alice-01.main.json")
        self.assertEqual(path.parent.name, "wallets")
        self.assertFalse(Path("alice-01.main").is_absolute())


if __name__ == "__main__":
    unittest.main()

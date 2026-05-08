import unittest
import json
import tempfile
from pathlib import Path
from unittest import mock

from wallet import create_wallet
from wallet.storage import load_wallet
from wallet.storage import normalize_wallet_name
from wallet.storage import save_wallet
from wallet.storage import update_wallet_preferred_port
from wallet.storage import wallet_path
from wallet.wallet import Wallet


class WalletModelTests(unittest.TestCase):
    def test_wallet_serializes_preferred_port(self) -> None:
        wallet = create_wallet(name="miner", preferred_port=9012)

        wallet_data = wallet.to_dict()
        restored_wallet = Wallet.from_dict(wallet_data)

        self.assertEqual(wallet_data["preferred_port"], 9012)
        self.assertEqual(restored_wallet.preferred_port, 9012)

    def test_wallet_serializes_large_key_numbers_as_strings(self) -> None:
        wallet = create_wallet(name="miner", preferred_port=9012)

        wallet_data = wallet.to_dict()

        self.assertIsInstance(wallet_data["public_key"]["exponent"], str)
        self.assertIsInstance(wallet_data["public_key"]["modulus"], str)
        self.assertIsInstance(wallet_data["private_key"]["exponent"], str)
        self.assertIsInstance(wallet_data["private_key"]["modulus"], str)

    def test_missing_preferred_port_defaults_to_9000(self) -> None:
        wallet_data = create_wallet(name="legacy").to_dict()
        wallet_data.pop("preferred_port")

        restored_wallet = Wallet.from_dict(wallet_data)

        self.assertEqual(restored_wallet.preferred_port, 9000)

    def test_update_preferred_port_preserves_wallet_key_material(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            wallets_dir = Path(temp_dir) / "wallets"
            with mock.patch("wallet.storage.WALLETS_DIR", wallets_dir):
                wallet = create_wallet(name="miner", preferred_port=9000)
                path = save_wallet(wallet)
                original_wallet_data = json.loads(path.read_text(encoding="utf-8"))

                updated_wallet = update_wallet_preferred_port("miner", 9011)
                updated_wallet_data = json.loads(path.read_text(encoding="utf-8"))

                self.assertEqual(updated_wallet.preferred_port, 9011)
                self.assertEqual(load_wallet("miner").preferred_port, 9011)
                self.assertEqual(
                    updated_wallet_data["public_key"],
                    original_wallet_data["public_key"],
                )
                self.assertEqual(
                    updated_wallet_data["private_key"],
                    original_wallet_data["private_key"],
                )

    def test_load_wallet_rejects_mismatched_stored_address(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            wallets_dir = Path(temp_dir) / "wallets"
            with mock.patch("wallet.storage.WALLETS_DIR", wallets_dir):
                wallet = create_wallet(name="miner")
                path = save_wallet(wallet)
                wallet_data = json.loads(path.read_text(encoding="utf-8"))
                wallet_data["address"] = "not-the-derived-address"
                path.write_text(json.dumps(wallet_data, indent=2), encoding="utf-8")

                with self.assertRaisesRegex(ValueError, "does not match its stored address"):
                    load_wallet("miner")

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

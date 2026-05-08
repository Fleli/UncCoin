import unittest

from wallet import create_wallet
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


if __name__ == "__main__":
    unittest.main()

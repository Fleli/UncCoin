import json
import unittest
from decimal import Decimal
from pathlib import Path

from core.uvm import UvmExecutionContext
from core.uvm import execute_uvm_program


PLAYER_A = "fe269f427a5ad619ce480192db583a29a7ce4098b22111d9b7216e2fee6bc964"
PLAYER_B = "7153252bebd059f5210023029130e39a91a656edc334d611800b75245a080630"
REQUEST_ID = "coinflip"
CONTRACT_ADDRESS = "coinflip-contract"


def load_coinflip_program():
    contract_path = Path(__file__).resolve().parent.parent / "state/contracts/coinflip.uvm"
    return json.loads(contract_path.read_text(encoding="utf-8"))


def reveal(seed: int) -> dict[str, str]:
    return {
        "seed": str(seed),
        "salt": "",
        "commitment_hash": "a" * 64,
    }


def authorization_index(*wallets: str) -> dict[str, dict[str, dict]]:
    return {
        wallet: {REQUEST_ID: {}}
        for wallet in wallets
    }


class CoinflipContractTests(unittest.TestCase):
    def test_coinflip_noops_before_deadline_when_reveal_is_missing(self) -> None:
        result = execute_uvm_program(
            load_coinflip_program(),
            UvmExecutionContext(
                tx_sender="caller",
                contract_address=CONTRACT_ADDRESS,
                gas_limit=2_000,
                block_height=10,
                reveals={
                    REQUEST_ID: {
                        PLAYER_A: reveal(1),
                    }
                },
                balances={PLAYER_B: Decimal("100")},
                authorization_index=authorization_index(PLAYER_B),
            ),
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.storage, {})
        self.assertEqual(result.balance_changes, {})

    def test_coinflip_punishes_missing_revealer_after_deadline(self) -> None:
        result = execute_uvm_program(
            load_coinflip_program(),
            UvmExecutionContext(
                tx_sender="caller",
                contract_address=CONTRACT_ADDRESS,
                gas_limit=2_000,
                block_height=11,
                reveals={
                    REQUEST_ID: {
                        PLAYER_A: reveal(1),
                    }
                },
                balances={PLAYER_B: Decimal("100")},
                authorization_index=authorization_index(PLAYER_B),
            ),
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.storage, {"settled": 1})
        self.assertEqual(
            result.balance_changes,
            {
                PLAYER_B: Decimal("-100"),
                PLAYER_A: Decimal("100"),
            },
        )

    def test_coinflip_settles_normal_flip_once(self) -> None:
        result = execute_uvm_program(
            load_coinflip_program(),
            UvmExecutionContext(
                tx_sender="caller",
                contract_address=CONTRACT_ADDRESS,
                gas_limit=2_000,
                block_height=10,
                reveals={
                    REQUEST_ID: {
                        PLAYER_A: reveal(1),
                        PLAYER_B: reveal(2),
                    }
                },
                balances={
                    PLAYER_A: Decimal("100"),
                    PLAYER_B: Decimal("100"),
                    CONTRACT_ADDRESS: Decimal("0"),
                },
                authorization_index=authorization_index(PLAYER_A, PLAYER_B),
            ),
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.storage, {"settled": 1})
        self.assertEqual(
            result.balance_changes,
            {
                PLAYER_A: Decimal("100"),
                PLAYER_B: Decimal("-100"),
            },
        )

    def test_coinflip_replay_noops_after_settlement(self) -> None:
        result = execute_uvm_program(
            load_coinflip_program(),
            UvmExecutionContext(
                tx_sender="caller",
                contract_address=CONTRACT_ADDRESS,
                gas_limit=2_000,
                storage={"settled": 1},
                block_height=11,
            ),
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.storage, {"settled": 1})
        self.assertEqual(result.balance_changes, {})


if __name__ == "__main__":
    unittest.main()

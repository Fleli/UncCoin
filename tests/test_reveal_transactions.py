import unittest
from datetime import datetime
from decimal import Decimal

from core.blockchain import Blockchain
from core.genesis import create_genesis_block
from core.hashing import sha256_block_hash
from core.randomness import create_reveal_commitment_hash
from core.randomness import parse_randomness_seed
from core.transaction import Transaction
from node.node import Node
from wallet import create_wallet


def create_blockchain() -> Blockchain:
    blockchain = Blockchain(
        difficulty_bits=0,
        hash_function=sha256_block_hash,
    )
    blockchain.add_block(create_genesis_block(sha256_block_hash))
    return blockchain


def sign_transaction(wallet, transaction: Transaction) -> Transaction:
    transaction.signature = wallet.sign_message(transaction.signing_payload())
    return transaction


def create_signed_commit(wallet, request_id: str, seed: str, salt: str = "") -> Transaction:
    return sign_transaction(
        wallet,
        Transaction.commit(
            sender=wallet.address,
            request_id=request_id,
            commitment_hash=create_reveal_commitment_hash(
                wallet.address,
                request_id,
                seed,
                salt,
            ),
            fee=Decimal("0"),
            timestamp=datetime.now(),
            nonce=0,
            sender_public_key=wallet.public_key,
        ),
    )


class RevealTransactionTests(unittest.TestCase):
    def test_reveal_transaction_records_seed_for_prior_commitment(self) -> None:
        blockchain = create_blockchain()
        wallet = create_wallet(name="revealer")
        request_id = "casino-play-1"
        seed = "123456"
        salt = "table-7"
        blockchain.add_transaction(create_signed_commit(wallet, request_id, seed, salt))
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="include commitment",
        )
        reveal_transaction = sign_transaction(
            wallet,
            Transaction.reveal(
                sender=wallet.address,
                request_id=request_id,
                seed=seed,
                salt=salt,
                fee=Decimal("0"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(wallet.address),
                sender_public_key=wallet.public_key,
            ),
        )

        blockchain.add_transaction(reveal_transaction)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="include reveal",
        )

        self.assertEqual(
            blockchain.get_reveal(request_id, wallet.address),
            {
                "seed": seed,
                "salt": salt,
                "commitment_hash": create_reveal_commitment_hash(
                    wallet.address,
                    request_id,
                    seed,
                    salt,
                ),
            },
        )
        self.assertEqual(
            blockchain.get_reveals(request_id),
            {
                wallet.address: {
                    "seed": seed,
                    "salt": salt,
                    "commitment_hash": create_reveal_commitment_hash(
                        wallet.address,
                        request_id,
                        seed,
                        salt,
                    ),
                }
            },
        )

    def test_reveal_rejects_wrong_seed(self) -> None:
        blockchain = create_blockchain()
        wallet = create_wallet(name="revealer")
        request_id = "casino-play-1"
        blockchain.add_transaction(create_signed_commit(wallet, request_id, "123"))
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="include commitment",
        )
        reveal_transaction = sign_transaction(
            wallet,
            Transaction.reveal(
                sender=wallet.address,
                request_id=request_id,
                seed="456",
                fee=Decimal("0"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(wallet.address),
                sender_public_key=wallet.public_key,
            ),
        )

        with self.assertRaisesRegex(ValueError, "does not match prior commitment"):
            blockchain.add_transaction(reveal_transaction)

    def test_reveal_requires_prior_commitment(self) -> None:
        blockchain = create_blockchain()
        wallet = create_wallet(name="revealer")
        reveal_transaction = sign_transaction(
            wallet,
            Transaction.reveal(
                sender=wallet.address,
                request_id="casino-play-1",
                seed="123",
                fee=Decimal("0"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(wallet.address),
                sender_public_key=wallet.public_key,
            ),
        )

        with self.assertRaisesRegex(ValueError, "no prior commitment"):
            blockchain.add_transaction(reveal_transaction)

    def test_duplicate_reveal_is_rejected(self) -> None:
        blockchain = create_blockchain()
        wallet = create_wallet(name="revealer")
        request_id = "casino-play-1"
        seed = "123"
        blockchain.add_transaction(create_signed_commit(wallet, request_id, seed))
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="include commitment",
        )
        first_reveal = sign_transaction(
            wallet,
            Transaction.reveal(
                sender=wallet.address,
                request_id=request_id,
                seed=seed,
                fee=Decimal("0"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(wallet.address),
                sender_public_key=wallet.public_key,
            ),
        )
        blockchain.add_transaction(first_reveal)

        duplicate_reveal = sign_transaction(
            wallet,
            Transaction.reveal(
                sender=wallet.address,
                request_id=request_id,
                seed=seed,
                fee=Decimal("0"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(wallet.address),
                sender_public_key=wallet.public_key,
            ),
        )

        with self.assertRaisesRegex(ValueError, "reveal already exists"):
            blockchain.add_transaction(duplicate_reveal)

    def test_reveal_seed_accepts_hex_but_stores_canonical_decimal(self) -> None:
        blockchain = create_blockchain()
        wallet = create_wallet(name="revealer")
        request_id = "casino-play-1"
        seed = "0x2a"
        blockchain.add_transaction(create_signed_commit(wallet, request_id, seed))
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="include commitment",
        )
        reveal_transaction = sign_transaction(
            wallet,
            Transaction.reveal(
                sender=wallet.address,
                request_id=request_id,
                seed=seed,
                fee=Decimal("0"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(wallet.address),
                sender_public_key=wallet.public_key,
            ),
        )

        blockchain.add_transaction(reveal_transaction)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="include reveal",
        )

        reveal = blockchain.get_reveal(request_id, wallet.address)
        self.assertIsNotNone(reveal)
        assert reveal is not None
        self.assertEqual(reveal["seed"], "42")
        self.assertEqual(parse_randomness_seed(seed), 42)

    def test_execute_can_read_revealed_seed(self) -> None:
        blockchain = create_blockchain()
        revealer = create_wallet(name="revealer")
        caller = create_wallet(name="caller")
        request_id = "casino-play-1"
        seed = "98765"
        blockchain.add_transaction(create_signed_commit(revealer, request_id, seed))
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="include commitment",
        )
        reveal_transaction = sign_transaction(
            revealer,
            Transaction.reveal(
                sender=revealer.address,
                request_id=request_id,
                seed=seed,
                fee=Decimal("0"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(revealer.address),
                sender_public_key=revealer.public_key,
            ),
        )
        blockchain.add_transaction(reveal_transaction)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="include reveal",
        )
        execute_transaction = sign_transaction(
            caller,
            Transaction.execute(
                sender=caller.address,
                contract_address="randomness-contract",
                input_data=[
                    ["READ_REVEAL", revealer.address, request_id],
                    ["STORE", "seed"],
                    ["HALT"],
                ],
                value=Decimal("0"),
                fee=Decimal("0"),
                gas_limit=200,
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(caller.address),
                sender_public_key=caller.public_key,
            ),
        )

        blockchain.add_transaction(execute_transaction)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="read reveal",
        )

        self.assertEqual(
            blockchain.get_contract_storage("randomness-contract"),
            {"seed": int(seed)},
        )


class NodeRevealTransactionTests(unittest.TestCase):
    def test_node_creates_signed_reveal_transaction(self) -> None:
        blockchain = create_blockchain()
        wallet = create_wallet(name="revealer")
        request_id = "casino-play-1"
        seed = "777"
        blockchain.add_transaction(create_signed_commit(wallet, request_id, seed))
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="include commitment",
        )
        node = Node(
            host="127.0.0.1",
            port=9400,
            wallet=wallet,
            blockchain=blockchain,
        )

        reveal_transaction = node.create_signed_reveal(
            request_id=request_id,
            seed=seed,
            fee="0",
        )

        accepted, reason = node._handle_incoming_transaction(reveal_transaction)
        self.assertTrue(accepted, reason)


if __name__ == "__main__":
    unittest.main()

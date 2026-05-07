import unittest
from datetime import datetime
from decimal import Decimal

from core.blockchain import Blockchain
from core.genesis import create_genesis_block
from core.hashing import sha256_block_hash
from core.transaction import Transaction
from core.uvm_authorization import create_uvm_authorization
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


class CommitTransactionTests(unittest.TestCase):
    def test_commit_transaction_is_recorded_by_request_id_and_sender(self) -> None:
        blockchain = create_blockchain()
        wallet = create_wallet(name="committer")
        blockchain.mine_pending_transactions(
            miner_address=wallet.address,
            description="fund committer",
        )
        transaction = sign_transaction(
            wallet,
            Transaction.commit(
                sender=wallet.address,
                request_id="randomness:round:1",
                commitment_hash="A" * 64,
                fee=Decimal("0.25"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(wallet.address),
                sender_public_key=wallet.public_key,
            ),
        )

        blockchain.add_transaction(transaction)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="include commitment",
        )

        self.assertEqual(
            blockchain.get_commitment("randomness:round:1", wallet.address),
            "a" * 64,
        )
        self.assertEqual(
            blockchain.get_commitments("randomness:round:1"),
            {wallet.address: "a" * 64},
        )
        self.assertEqual(blockchain.get_balance(wallet.address), Decimal("9.75"))

    def test_duplicate_commit_for_same_request_and_sender_is_rejected(self) -> None:
        blockchain = create_blockchain()
        wallet = create_wallet(name="committer")
        blockchain.mine_pending_transactions(
            miner_address=wallet.address,
            description="fund committer",
        )
        first = sign_transaction(
            wallet,
            Transaction.commit(
                sender=wallet.address,
                request_id="randomness:round:1",
                commitment_hash="a" * 64,
                fee=Decimal("0"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(wallet.address),
                sender_public_key=wallet.public_key,
            ),
        )
        blockchain.add_transaction(first)

        second = sign_transaction(
            wallet,
            Transaction.commit(
                sender=wallet.address,
                request_id="randomness:round:1",
                commitment_hash="b" * 64,
                fee=Decimal("0"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(wallet.address),
                sender_public_key=wallet.public_key,
            ),
        )

        with self.assertRaisesRegex(ValueError, "commitment already exists"):
            blockchain.add_transaction(second)

    def test_commit_rejects_invalid_commitment_hash(self) -> None:
        blockchain = create_blockchain()
        wallet = create_wallet(name="committer")
        blockchain.mine_pending_transactions(
            miner_address=wallet.address,
            description="fund committer",
        )
        transaction = sign_transaction(
            wallet,
            Transaction.commit(
                sender=wallet.address,
                request_id="randomness:round:1",
                commitment_hash="not-a-sha256",
                fee=Decimal("0"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(wallet.address),
                sender_public_key=wallet.public_key,
            ),
        )

        with self.assertRaisesRegex(ValueError, "64-character hex"):
            blockchain.add_transaction(transaction)

    def test_execute_transactions_are_modeled_but_not_accepted_without_uvm(self) -> None:
        blockchain = create_blockchain()
        wallet = create_wallet(name="caller")
        authorizer = create_wallet(name="authorizer")
        blockchain.mine_pending_transactions(
            miner_address=wallet.address,
            description="fund caller",
        )
        transaction = sign_transaction(
            wallet,
            Transaction.execute(
                sender=wallet.address,
                contract_address="contract-address",
                input_data="00",
                value=Decimal("0"),
                fee=Decimal("0"),
                gas_limit=10_000,
                authorizations=[
                    create_uvm_authorization(authorizer, "casino-play-1").to_dict()
                ],
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(wallet.address),
                sender_public_key=wallet.public_key,
            ),
        )

        with self.assertRaisesRegex(ValueError, "UVM execution engine"):
            blockchain.add_transaction(transaction)

    def test_execute_rejects_invalid_authorization_before_uvm_execution(self) -> None:
        blockchain = create_blockchain()
        wallet = create_wallet(name="caller")
        authorizer = create_wallet(name="authorizer")
        blockchain.mine_pending_transactions(
            miner_address=wallet.address,
            description="fund caller",
        )
        invalid_authorization = create_uvm_authorization(
            authorizer,
            "casino-play-1",
        ).to_dict()
        invalid_authorization["request_id"] = "casino-play-2"
        transaction = sign_transaction(
            wallet,
            Transaction.execute(
                sender=wallet.address,
                contract_address="contract-address",
                input_data="00",
                value=Decimal("0"),
                fee=Decimal("0"),
                gas_limit=10_000,
                authorizations=[invalid_authorization],
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(wallet.address),
                sender_public_key=wallet.public_key,
            ),
        )

        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            blockchain.add_transaction(transaction)


class NodeCommitTransactionTests(unittest.TestCase):
    def test_node_creates_signed_commitment_transaction(self) -> None:
        blockchain = create_blockchain()
        wallet = create_wallet(name="committer")
        blockchain.mine_pending_transactions(
            miner_address=wallet.address,
            description="fund committer",
        )
        node = Node(
            host="127.0.0.1",
            port=9300,
            wallet=wallet,
            blockchain=blockchain,
        )

        transaction = node.create_signed_commitment(
            request_id="randomness:round:1",
            commitment_hash="c" * 64,
            fee="0.1",
        )

        accepted, reason = node._handle_incoming_transaction(transaction)
        self.assertTrue(accepted, reason)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="include node commitment",
        )
        self.assertEqual(
            blockchain.get_commitment("randomness:round:1", wallet.address),
            "c" * 64,
        )


if __name__ == "__main__":
    unittest.main()

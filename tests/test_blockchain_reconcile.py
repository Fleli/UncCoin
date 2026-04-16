import unittest
from datetime import datetime
from decimal import Decimal

from core.blockchain import Blockchain
from core.genesis import create_genesis_block
from core.hashing import sha256_block_hash
from core.transaction import Transaction
from wallet import create_wallet


def create_blockchain() -> Blockchain:
    blockchain = Blockchain(
        difficulty_bits=0,
        hash_function=sha256_block_hash,
    )
    blockchain.add_block(create_genesis_block(sha256_block_hash))
    return blockchain


class BlockchainReconcileTests(unittest.TestCase):
    def test_reorg_resurrects_transactions_from_replaced_branch(self) -> None:
        blockchain = create_blockchain()
        sender = create_wallet(name="sender")
        receiver = create_wallet(name="receiver")

        funding_block = blockchain.mine_pending_transactions(
            miner_address=sender.address,
            description="fund sender",
        )

        transaction = Transaction(
            sender=sender.address,
            receiver=receiver.address,
            amount=Decimal("5"),
            fee=Decimal("0"),
            timestamp=datetime.now(),
            nonce=blockchain.get_next_nonce(sender.address),
            sender_public_key=sender.public_key,
        )
        transaction.signature = sender.sign_message(transaction.signing_payload())
        blockchain.add_transaction(transaction)

        main_block = blockchain.mine_pending_transactions(
            miner_address="main-miner",
            description="main branch includes tx",
        )
        self.assertEqual(blockchain.pending_transactions, [])

        fork_block = blockchain.mine_pending_transactions(
            miner_address="fork-miner",
            description="fork branch misses tx",
            tip_hash=funding_block.block_hash,
        )
        blockchain.mine_pending_transactions(
            miner_address="fork-miner",
            description="fork becomes canonical",
            tip_hash=fork_block.block_hash,
        )

        self.assertEqual(blockchain.main_tip_hash, blockchain.blocks[-1].block_hash)
        self.assertEqual(len(blockchain.pending_transactions), 1)
        self.assertEqual(
            blockchain.pending_transactions[0].signing_payload(),
            transaction.signing_payload(),
        )
        self.assertNotEqual(main_block.block_hash, blockchain.main_tip_hash)

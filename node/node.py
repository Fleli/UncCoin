import asyncio
import functools
import json
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from config import DEFAULT_DIFFICULTY_BITS
from config import DEFAULT_DIFFICULTY_GROWTH_FACTOR
from config import DEFAULT_DIFFICULTY_GROWTH_BITS
from config import DEFAULT_DIFFICULTY_GROWTH_START_HEIGHT
from config import DEFAULT_GENESIS_DIFFICULTY_BITS
from core.block import Block
from core.block import ProofOfWorkCancelled
from core.block import get_block_verification_error
from core.block import proof_of_work
from core.blockchain import Blockchain
from core.contracts import NFT_TRANSFER_GAS_LIMIT
from core.contracts import build_nft_contract
from core.contracts import compute_contract_code_hash
from core.contracts import normalize_wallet_address
from core.genesis import create_genesis_block
from core.hashing import sha256_block_hash
from core.hashing import sha256_transaction_hash
from core.cloud_native_automine import CloudNativeAutomineConfig
from core.cloud_native_automine import CloudNativeAutomineEvent
from core.cloud_native_automine import CloudNativeDifficultySchedule
from core.cloud_native_automine import mine_reward_only_blocks
from core.mining_backend import build_mining_backend as build_pow_backend
from core.mining_backend import mining_backend_capabilities
from core.mining_backend import normalize_mining_backend
from core.mining_backend import selected_mining_backend
from core.native_pow import gpu_device_ids
from core.native_pow import request_pow_cancel
from core.native_pow import reset_pow_cancel
from core.randomness import create_reveal_commitment_hash
from core.transaction import Transaction
from core.uvm_authorization import UvmAuthorizationScope
from core.utils.constants import MINING_REWARD_AMOUNT, MINING_REWARD_SENDER
from core.utils.mining import get_mining_reward_amount_validation_error
from core.utils.mining import get_mining_reward_structure_error
from core.utils.mining import is_mining_reward_transaction
from node.alias_store import load_aliases, save_aliases
from network.p2p_server import P2PServer
from node.message_store import load_messages, save_messages
from node.storage import load_blockchain_state, save_blockchain_state, write_blockchain_state
from wallet import Wallet


class CloudNativeAutomineStaleTip(Exception):
    pass


def _read_positive_int_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return value if value > 0 else default


def _read_positive_float_env(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass
class Node:
    host: str
    port: int
    wallet: Wallet | None = None
    blockchain: Blockchain | None = None
    private_automine: bool = False
    mining_only: bool = False
    cloud_native_automine: bool = False
    mined_block_persist_interval: int = 1
    difficulty_bits: int = DEFAULT_DIFFICULTY_BITS
    genesis_difficulty_bits: int = DEFAULT_GENESIS_DIFFICULTY_BITS
    difficulty_growth_factor: int = DEFAULT_DIFFICULTY_GROWTH_FACTOR
    difficulty_growth_start_height: int = DEFAULT_DIFFICULTY_GROWTH_START_HEIGHT
    difficulty_growth_bits: int = DEFAULT_DIFFICULTY_GROWTH_BITS
    p2p_server: P2PServer = field(init=False)
    automine_task: asyncio.Task | None = field(default=None, init=False)
    automine_description: str = field(default="", init=False)
    mining_active: bool = field(default=False, init=False)
    mining_mode: str | None = field(default=None, init=False)
    mining_description: str = field(default="", init=False)
    mining_started_at: datetime | None = field(default=None, init=False)
    mining_last_update_at: datetime | None = field(default=None, init=False)
    mining_last_nonce: int = field(default=0, init=False)
    mining_difficulty_bits: int | None = field(default=None, init=False)
    mining_tip_hash: str | None = field(default=None, init=False)
    mining_last_block_hash: str | None = field(default=None, init=False)
    mining_last_block_height: int | None = field(default=None, init=False)
    mining_last_block_nonces_checked: int | None = field(default=None, init=False)
    mining_backend: str = field(default_factory=selected_mining_backend, init=False)
    miner_warmup_task: asyncio.Task | None = field(default=None, init=False)
    miner_warmup_status: dict[str, Any] = field(default_factory=dict, init=False)
    _automine_stop_requested: bool = field(default=False, init=False)
    _current_automine_tip_hash: str | None = field(default=None, init=False)
    _private_automine_tip_hash: str | None = field(default=None, init=False)
    orphan_blocks_by_parent_hash: dict[str, list[Block]] = field(default_factory=dict, init=False)
    orphan_block_hashes: set[str] = field(default_factory=set, init=False)
    message_history: list[dict] = field(default_factory=list, init=False)
    message_ids: set[str] = field(default_factory=set, init=False)
    wallet_aliases: dict[str, str] = field(default_factory=dict, init=False)
    network_notifications_muted: bool = field(default=False, init=False)
    autosend_target: str | None = field(default=None, init=False)
    autosend_last_seen_balance: Decimal = field(default=Decimal("0.0"), init=False)
    autosend_task: asyncio.Task | None = field(default=None, init=False)
    _persist_blockchain_state: bool = field(default=False, init=False)
    _deferred_chain_sync_save_pending: bool = field(default=False, init=False)
    _mined_blocks_since_persist: int = field(default=0, init=False)
    _cloud_native_fast_blocks_since_verify: int = field(default=0, init=False)

    REPO_ROOT = Path(__file__).resolve().parent.parent
    CONTRACTS_DIR = REPO_ROOT / "state" / "contracts"

    def __post_init__(self) -> None:
        self._persist_blockchain_state = self.blockchain is None
        if self.mined_block_persist_interval < 0:
            raise ValueError("mined_block_persist_interval must be non-negative.")
        if self.cloud_native_automine and not self.mining_only:
            raise ValueError("cloud_native_automine requires mining_only.")
        if self.blockchain is None:
            self.blockchain = Blockchain(
                difficulty_bits=self.difficulty_bits,
                hash_function=sha256_block_hash,
                genesis_difficulty_bits=self.genesis_difficulty_bits,
                difficulty_growth_factor=self.difficulty_growth_factor,
                difficulty_growth_start_height=self.difficulty_growth_start_height,
                difficulty_growth_bits=self.difficulty_growth_bits,
            )
        self.p2p_server = P2PServer(
            host=self.host,
            port=self.port,
            on_transaction=self._handle_incoming_transaction,
            on_block=self._handle_incoming_block,
            on_wallet_message=self._handle_wallet_message,
            on_chain_summary=self._handle_chain_summary,
            on_chain_request=self._handle_chain_request,
            on_chain_response=self._handle_chain_response,
            on_chain_sync_complete=self._handle_chain_sync_complete,
            on_pending_transactions=self._handle_pending_transactions,
            on_notification=self._print_network_notification,
            transaction_relay=not self.mining_only,
            log_block_broadcasts=not self.cloud_native_automine,
        )
        self.miner_warmup_status = self._default_miner_warmup_status()

    async def start(self) -> None:
        self._load_persisted_aliases()
        self._load_persisted_messages()
        self._load_persisted_blockchain()
        self._ensure_genesis_block()
        await self.p2p_server.start()
        available_gpu_device_ids = gpu_device_ids()
        print(
            "GPU devices available: "
            f"{len(available_gpu_device_ids)}"
            + (
                f" (ids: {', '.join(str(device_id) for device_id in available_gpu_device_ids)})"
                if available_gpu_device_ids
                else ""
            ),
            flush=True,
        )
        if self.wallet is not None:
            wallet_name = self.wallet.name or "unnamed"
            print(f"Loaded wallet '{wallet_name}' with address {self.wallet.address}")
        if self.private_automine:
            print(
                "Private automine mode enabled. Mining keeps a preferred branch tip.",
                flush=True,
            )
        if self.mining_only:
            print(
                "Mining-only mode enabled. Transaction relay is disabled.",
                flush=True,
            )
        if self.cloud_native_automine:
            print(
                "Cloud native automine enabled. Mining reward-only blocks in a burst worker.",
                flush=True,
            )
        if self.mined_block_persist_interval == 0:
            print(
                "Mined block persistence deferred until shutdown.",
                flush=True,
            )
        elif self.mined_block_persist_interval > 1:
            print(
                "Mined block persistence interval: "
                f"{self.mined_block_persist_interval} block(s).",
                flush=True,
            )
        self._reset_autosend_balance_baseline()

    async def serve_forever(self) -> None:
        await self.p2p_server.serve_forever()

    async def stop(self) -> None:
        await self.stop_automine(wait=True)
        self._save_persisted_blockchain("shutdown")
        self._save_persisted_aliases()
        await self.p2p_server.stop()

    async def connect_to_peer(self, host: str, port: int) -> None:
        try:
            await self.p2p_server.connect_to_peer(host, port)
        except TimeoutError as error:
            raise ValueError(f"Timed out connecting to peer {host}:{port}") from error
        except OSError as error:
            raise ValueError(f"Could not connect to peer {host}:{port}: {error.strerror or error}") from error

    async def disconnect_peer(self, host: str, port: int) -> None:
        await self.p2p_server.disconnect_peer(host, port)

    async def broadcast(self, message: dict) -> None:
        await self.p2p_server.broadcast(message)

    async def broadcast_transaction(self, transaction: Transaction) -> None:
        await self.p2p_server.broadcast_transaction(transaction)

    async def rebroadcast_pending_transactions(self) -> int:
        return await self.p2p_server.broadcast_pending_transactions()

    async def broadcast_block(self, block: Block) -> None:
        await self.p2p_server.broadcast_block(block)

    async def broadcast_wallet_message(self, wallet_message: dict) -> None:
        await self.p2p_server.broadcast_wallet_message(wallet_message)

    async def discover_peers(self) -> None:
        await self.p2p_server.discover_peers()

    async def sync_chain(self, fast: bool = True) -> int:
        return await self.p2p_server.request_chain_sync(fast=fast)

    async def send_to_peer(self, host: str, port: int, message: dict) -> None:
        await self.p2p_server.send_to_peer(host, port, message)

    def list_peers(self) -> list[str]:
        return self.p2p_server.list_peers()

    def list_known_peers(self) -> list[str]:
        return self.p2p_server.list_known_peers()

    def network_stats(self) -> dict:
        return self.p2p_server.network_traffic_stats()

    def get_next_nonce(self, address: str) -> int:
        if self.blockchain is None:
            return 0
        return self.blockchain.get_next_nonce(
            address,
            tip_hash=self._state_tip_hash(),
        )

    def create_signed_transaction(
        self,
        receiver: str,
        amount: str,
        fee: str,
    ) -> Transaction:
        if self.wallet is None:
            raise ValueError("A loaded wallet is required to create signed transactions.")

        try:
            parsed_amount = Decimal(str(amount))
            parsed_fee = Decimal(str(fee))
        except InvalidOperation as error:
            raise ValueError("Amount and fee must be valid decimal numbers.") from error

        transaction = Transaction.transfer(
            sender=self.wallet.address,
            receiver=receiver,
            amount=parsed_amount,
            fee=parsed_fee,
            timestamp=datetime.now(),
            nonce=self.get_next_nonce(self.wallet.address),
            sender_public_key=self.wallet.public_key,
        )
        transaction.signature = self.wallet.sign_message(transaction.signing_payload())
        return transaction

    def create_signed_commitment(
        self,
        request_id: str,
        commitment_hash: str,
        fee: str,
    ) -> Transaction:
        if self.wallet is None:
            raise ValueError("A loaded wallet is required to create signed commitments.")

        try:
            parsed_fee = Decimal(str(fee))
        except InvalidOperation as error:
            raise ValueError("Fee must be a valid decimal number.") from error

        transaction = Transaction.commit(
            sender=self.wallet.address,
            request_id=request_id,
            commitment_hash=commitment_hash,
            fee=parsed_fee,
            timestamp=datetime.now(),
            nonce=self.get_next_nonce(self.wallet.address),
            sender_public_key=self.wallet.public_key,
        )
        transaction.signature = self.wallet.sign_message(transaction.signing_payload())
        return transaction

    def create_signed_reveal(
        self,
        request_id: str,
        seed: str,
        fee: str,
        salt: str = "",
    ) -> Transaction:
        if self.wallet is None:
            raise ValueError("A loaded wallet is required to reveal randomness seeds.")

        try:
            parsed_fee = Decimal(str(fee))
        except InvalidOperation as error:
            raise ValueError("Fee must be a valid decimal number.") from error

        transaction = Transaction.reveal(
            sender=self.wallet.address,
            request_id=request_id,
            seed=seed,
            salt=salt,
            fee=parsed_fee,
            timestamp=datetime.now(),
            nonce=self.get_next_nonce(self.wallet.address),
            sender_public_key=self.wallet.public_key,
        )
        transaction.signature = self.wallet.sign_message(transaction.signing_payload())
        return transaction

    def create_signed_deploy(
        self,
        program,
        fee: str,
        metadata: dict | None = None,
        contract_address: str | None = None,
    ) -> Transaction:
        if self.wallet is None:
            raise ValueError("A loaded wallet is required to deploy contracts.")

        try:
            parsed_fee = Decimal(str(fee))
        except InvalidOperation as error:
            raise ValueError("Fee must be a valid decimal number.") from error

        transaction = Transaction.deploy(
            sender=self.wallet.address,
            program=program,
            metadata=metadata or {},
            fee=parsed_fee,
            timestamp=datetime.now(),
            nonce=self.get_next_nonce(self.wallet.address),
            contract_address=contract_address,
            sender_public_key=self.wallet.public_key,
        )
        transaction.signature = self.wallet.sign_message(transaction.signing_payload())
        return transaction

    def create_signed_deploy_from_source(
        self,
        contract_source: str,
        fee: str,
        contract_address: str | None = None,
    ) -> Transaction:
        program, metadata = self.load_contract_deploy_source(contract_source)
        return self.create_signed_deploy(
            program=program,
            metadata=metadata,
            fee=fee,
            contract_address=contract_address,
        )

    def load_contract_deploy_source(self, contract_source: str) -> tuple[object, dict]:
        deploy_payload = self._load_contract_deploy_payload(contract_source)
        if isinstance(deploy_payload, dict) and "program" in deploy_payload:
            program = deploy_payload["program"]
            metadata = deploy_payload.get("metadata", {})
        else:
            program = deploy_payload
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValueError("Deploy metadata must be a JSON object.")
        return program, metadata

    def create_signed_nft_mint(
        self,
        *,
        name: str,
        description: str,
        image_data_uri: str,
        fee: str,
    ) -> Transaction:
        if self.wallet is None:
            raise ValueError("A loaded wallet is required to mint NFTs.")

        program, metadata = build_nft_contract(
            name=name,
            description=description,
            image_data_uri=image_data_uri,
            initial_owner=self.wallet.address,
        )
        return self.create_signed_deploy(
            program=program,
            metadata=metadata,
            fee=fee,
        )

    def create_signed_nft_transfer(
        self,
        *,
        contract_address: str,
        recipient: str,
        fee: str,
        gas_limit: str = str(NFT_TRANSFER_GAS_LIMIT),
        gas_price: str = "0",
    ) -> Transaction:
        recipient_address = normalize_wallet_address(recipient, "recipient")
        return self.create_signed_execute(
            contract_address=contract_address,
            input_data={"recipient": recipient_address},
            gas_limit=gas_limit,
            gas_price=gas_price,
            value="0",
            fee=fee,
        )

    def create_signed_execute(
        self,
        contract_address: str,
        input_data,
        gas_limit: str,
        gas_price: str,
        value: str,
        fee: str,
    ) -> Transaction:
        if self.wallet is None:
            raise ValueError("A loaded wallet is required to execute contracts.")

        try:
            parsed_gas_limit = int(gas_limit)
            parsed_gas_price = Decimal(str(gas_price))
            parsed_value = Decimal(str(value))
            parsed_fee = Decimal(str(fee))
        except (InvalidOperation, ValueError) as error:
            raise ValueError(
                "Gas limit must be an integer; gas price, value, and fee "
                "must be valid decimal numbers."
            ) from error

        transaction = Transaction.execute(
            sender=self.wallet.address,
            contract_address=contract_address,
            input_data=input_data,
            value=parsed_value,
            fee=parsed_fee,
            gas_limit=parsed_gas_limit,
            gas_price=parsed_gas_price,
            timestamp=datetime.now(),
            nonce=self.get_next_nonce(self.wallet.address),
            sender_public_key=self.wallet.public_key,
        )
        transaction.signature = self.wallet.sign_message(transaction.signing_payload())
        return transaction

    def create_signed_authorization(
        self,
        contract_address: str,
        request_id: str,
        fee: str,
        valid_for_blocks: str | None = None,
    ) -> Transaction:
        if self.wallet is None:
            raise ValueError("A loaded wallet is required to authorize contracts.")
        if self.blockchain is None:
            raise ValueError("A blockchain is required to authorize contracts.")

        contract = self.blockchain.get_contract(
            contract_address,
            tip_hash=self._state_tip_hash(),
        )
        if contract is None:
            raise ValueError(f"Contract {contract_address} is not deployed locally.")
        code_hash = str(
            contract.get(
                "code_hash",
                compute_contract_code_hash(
                    contract.get("program", []),
                    contract.get("metadata", {}),
                ),
            )
        ).strip()
        if not code_hash:
            raise ValueError(f"Contract {contract_address} does not have a code_hash.")

        try:
            parsed_fee = Decimal(str(fee))
        except InvalidOperation as error:
            raise ValueError("Fee must be a valid decimal number.") from error

        scope = {}
        if valid_for_blocks is not None:
            try:
                parsed_valid_for_blocks = int(valid_for_blocks)
            except ValueError as error:
                raise ValueError("valid-blocks must be an integer.") from error
            if parsed_valid_for_blocks <= 0:
                raise ValueError("valid-blocks must be positive.")
            current_height = (
                self.blockchain._get_state_for_tip(self._state_tip_hash()).height
            )
            scope = UvmAuthorizationScope.from_dict(
                {
                    "valid_from_height": current_height + 1,
                    "valid_until_height": current_height + parsed_valid_for_blocks,
                }
            ).to_dict()

        transaction = Transaction.authorize(
            sender=self.wallet.address,
            contract_address=contract_address,
            code_hash=code_hash,
            request_id=request_id,
            scope=scope,
            fee=parsed_fee,
            timestamp=datetime.now(),
            nonce=self.get_next_nonce(self.wallet.address),
            sender_public_key=self.wallet.public_key,
        )
        transaction.signature = self.wallet.sign_message(transaction.signing_payload())
        return transaction

    def create_signed_wallet_message(self, receiver: str, content: str) -> dict:
        if self.wallet is None:
            raise ValueError("A loaded wallet is required to send messages.")

        timestamp = datetime.now().isoformat()
        message_id = str(uuid.uuid4())
        payload = (
            f"{self.wallet.address}|{receiver}|{content}|{timestamp}|{message_id}"
        )
        signature = self.wallet.sign_message(payload)
        return {
            "message_id": message_id,
            "sender": self.wallet.address,
            "receiver": receiver,
            "content": content,
            "timestamp": timestamp,
            "sender_public_key": {
                "exponent": str(self.wallet.public_key[0]),
                "modulus": str(self.wallet.public_key[1]),
            },
            "signature": signature,
        }

    def default_block_description(self, prefix: str) -> str:
        if self.wallet is None or not self.wallet.name:
            return prefix
        return f"{prefix} ({self.wallet.name})"

    def _next_mining_difficulty_bits(self) -> int:
        if self.blockchain is None:
            raise ValueError("A blockchain is required to mine.")
        return self.blockchain.get_next_block_difficulty_bits(
            self._mining_tip_hash(),
        )

    def _mining_tip_hash(self) -> str | None:
        if self.blockchain is None:
            return None
        if not self.private_automine:
            return self.blockchain.main_tip_hash

        if (
            self._private_automine_tip_hash is not None
            and self._private_automine_tip_hash in self.blockchain.block_states
        ):
            return self._private_automine_tip_hash

        self._private_automine_tip_hash = self.blockchain.main_tip_hash
        return self._private_automine_tip_hash

    def _mining_status_text(self) -> str:
        difficulty_bits = self._next_mining_difficulty_bits()
        if not self.private_automine:
            return f"N={difficulty_bits}"

        tip_hash = self._mining_tip_hash()
        if tip_hash is None:
            return f"N={difficulty_bits}, private tip=unset"
        return f"N={difficulty_bits}, private tip={tip_hash[:12]}"

    def _state_tip_hash(self) -> str | None:
        return self._mining_tip_hash()

    def _record_local_mining_tip(self, block_hash: str) -> None:
        if self.private_automine:
            self._private_automine_tip_hash = block_hash

    def _advance_private_automine_tip(self, block_hash: str) -> bool:
        if (
            not self.private_automine
            or self.blockchain is None
            or self._private_automine_tip_hash is None
            or block_hash == self._private_automine_tip_hash
        ):
            return False

        if not self.blockchain.is_ancestor(self._private_automine_tip_hash, block_hash):
            return False

        self._private_automine_tip_hash = block_hash
        return True

    def _handle_accepted_block_for_automine(self, block: Block) -> None:
        if self.blockchain is None:
            return

        if self.private_automine:
            private_tip_advanced = self._advance_private_automine_tip(block.block_hash)
            if (
                private_tip_advanced
                and self.automine_task is not None
                and not self.automine_task.done()
                and self._current_automine_tip_hash is not None
                and self._private_automine_tip_hash is not None
                and self.blockchain.is_ancestor(
                    self._current_automine_tip_hash,
                    self._private_automine_tip_hash,
                )
            ):
                request_pow_cancel()
            return

        self._cancel_stale_automine_if_needed()

    def _reconcile_pending_transactions_for_state_tip(
        self,
        previous_state_tip_hash: str | None,
    ) -> None:
        if self.blockchain is None or not self.private_automine:
            return

        self.blockchain.reconcile_pending_transactions(
            previous_state_tip_hash,
            self._state_tip_hash(),
        )

    async def mine_pending_transactions(self, description: str) -> Block:
        if self.wallet is None:
            raise ValueError("A loaded wallet is required to mine.")
        if self.blockchain is None:
            raise ValueError("A blockchain is required to mine.")

        previous_state_tip_hash = self._state_tip_hash()
        block = self.blockchain.mine_pending_transactions(
            miner_address=self.wallet.address,
            description=description,
            tip_hash=self._mining_tip_hash(),
            reconcile_pending_transactions=not self.private_automine,
            mining_backend=self.mining_backend,
        )
        self._record_mined_block_progress(block)
        self._record_local_mining_tip(block.block_hash)
        self._reconcile_pending_transactions_for_state_tip(previous_state_tip_hash)
        self._save_mined_block_progress()
        await self.broadcast_block(block)
        self._maybe_schedule_autosend()
        return block

    async def mine_pending_transactions_with_progress(self, description: str) -> Block:
        if self.wallet is None:
            raise ValueError("A loaded wallet is required to mine.")
        if self.blockchain is None:
            raise ValueError("A blockchain is required to mine.")

        tip_hash = self._mining_tip_hash()
        difficulty_bits = self.blockchain.get_next_block_difficulty_bits(tip_hash)
        self._start_mining_progress(
            mode="manual",
            description=description,
            difficulty_bits=difficulty_bits,
            tip_hash=tip_hash,
        )
        print(f"Mining... ({self._mining_status_text()})", flush=True)
        previous_state_tip_hash = self._state_tip_hash()
        block = await asyncio.to_thread(
            functools.partial(
                self.blockchain.mine_pending_transactions,
                miner_address=self.wallet.address,
                description=description,
                progress_callback=self._report_mining_progress,
                tip_hash=tip_hash,
                reconcile_pending_transactions=not self.private_automine,
                mining_backend=self.mining_backend,
            )
        )
        self._clear_mining_progress()
        self._record_mined_block_progress(block)
        self._record_local_mining_tip(block.block_hash)
        self._reconcile_pending_transactions_for_state_tip(previous_state_tip_hash)
        self._save_mined_block_progress()
        await self.broadcast_block(block)
        self._maybe_schedule_autosend()
        return block

    async def start_automine(self, description: str) -> None:
        if self.automine_task is not None and not self.automine_task.done():
            raise ValueError("Automine is already running.")
        if self.wallet is None:
            raise ValueError("A loaded wallet is required to mine.")
        if self.blockchain is None:
            raise ValueError("A blockchain is required to mine.")

        self._mining_tip_hash()
        self.automine_description = description
        self._automine_stop_requested = False
        if self.cloud_native_automine:
            self.automine_task = asyncio.create_task(self._cloud_native_automine_loop())
        else:
            self.automine_task = asyncio.create_task(self._automine_loop())

    async def stop_automine(self, wait: bool = False) -> None:
        if self.automine_task is None or self.automine_task.done():
            self.automine_task = None
            return

        self._automine_stop_requested = True
        request_pow_cancel()
        if wait:
            await self.automine_task
            reset_pow_cancel()

    async def _automine_loop(self) -> None:
        assert self.wallet is not None
        assert self.blockchain is not None

        try:
            while not self._automine_stop_requested:
                self._current_automine_tip_hash = self._mining_tip_hash()
                difficulty_bits = self.blockchain.get_next_block_difficulty_bits(
                    self._current_automine_tip_hash,
                )
                self._start_mining_progress(
                    mode="automine",
                    description=self.automine_description,
                    difficulty_bits=difficulty_bits,
                    tip_hash=self._current_automine_tip_hash,
                )
                previous_state_tip_hash = self._state_tip_hash()
                print(
                    f"Automining... ({self._mining_status_text()})",
                    flush=True,
                )
                block = await asyncio.to_thread(
                    functools.partial(
                        self.blockchain.mine_pending_transactions,
                        miner_address=self.wallet.address,
                        description=self.automine_description,
                        progress_callback=self._report_mining_progress,
                        tip_hash=self._current_automine_tip_hash,
                        reconcile_pending_transactions=not self.private_automine,
                        mining_backend=self.mining_backend,
                    )
                )
                self._clear_mining_progress()
                self._record_mined_block_progress(block)
                self._record_local_mining_tip(block.block_hash)
                self._reconcile_pending_transactions_for_state_tip(previous_state_tip_hash)
                self._save_mined_block_progress()
                await self.broadcast_block(block)
                self._maybe_schedule_autosend()
                print(
                    f"\nAuto-mined block {block.block_hash[:12]} at height {block.block_id}",
                    flush=True,
                )
        except ProofOfWorkCancelled:
            self._clear_mining_progress()
            if not self._automine_stop_requested:
                print("\nRestarting automine on newer preferred tip.", flush=True)
                self.automine_task = asyncio.create_task(self._automine_loop())
                return
        except ValueError as error:
            self._clear_mining_progress()
            print(f"\nAutomine stopped: {error}", flush=True)
        finally:
            reset_pow_cancel()
            self._current_automine_tip_hash = None
            if self.automine_task is asyncio.current_task():
                self.automine_task = None
            self._automine_stop_requested = False

    async def _cloud_native_automine_loop(self) -> None:
        assert self.wallet is not None
        assert self.blockchain is not None

        try:
            while not self._automine_stop_requested:
                tip_hash = self._mining_tip_hash()
                if tip_hash is None:
                    raise ValueError("Genesis block must be created before mining.")
                if tip_hash not in self.blockchain.block_states:
                    raise ValueError(f"Unknown mining tip {tip_hash[:12]}.")

                start_height = self.blockchain.block_states[tip_hash].height
                self._current_automine_tip_hash = tip_hash
                self._start_mining_progress(
                    mode="cloud-native-automine",
                    description=self.automine_description,
                    difficulty_bits=self.blockchain.get_difficulty_bits_for_height(
                        start_height + 1,
                    ),
                    tip_hash=tip_hash,
                )
                print(
                    f"Cloud native automining... ({self._mining_status_text()})",
                    flush=True,
                )

                restart_requested = await self._run_cloud_native_automine_worker(
                    tip_hash,
                    start_height,
                )
                if self._automine_stop_requested:
                    break
                if restart_requested:
                    print(
                        "\nRestarting cloud native automine on newer preferred tip.",
                        flush=True,
                    )
                    continue
                break
        except Exception as error:
            print(f"\nCloud native automine stopped: {error}", flush=True)
        finally:
            self._clear_mining_progress()
            reset_pow_cancel()
            self._current_automine_tip_hash = None
            if self.automine_task is asyncio.current_task():
                self.automine_task = None
            self._automine_stop_requested = False

    async def _run_cloud_native_automine_worker(
        self,
        tip_hash: str,
        start_height: int,
    ) -> bool:
        assert self.wallet is not None
        assert self.blockchain is not None

        result_queue: queue.Queue[CloudNativeAutomineEvent] = queue.Queue(maxsize=2)
        stop_event = threading.Event()
        worker = threading.Thread(
            target=mine_reward_only_blocks,
            args=(
                CloudNativeAutomineConfig(
                    miner_address=self.wallet.address,
                    description=self.automine_description,
                    start_tip_hash=tip_hash,
                    start_height=start_height,
                    difficulty_schedule=self._cloud_native_difficulty_schedule(),
                    mining_backend=self.mining_backend,
                ),
                result_queue,
                stop_event,
            ),
            daemon=True,
        )
        worker.start()
        restart_requested = False
        accepted_blocks = 0
        stale_restarts = 0
        started_at = time.perf_counter()
        last_summary_at = started_at

        try:
            while worker.is_alive() or not result_queue.empty():
                if self._automine_stop_requested:
                    stop_event.set()
                    request_pow_cancel()

                try:
                    event = await asyncio.to_thread(result_queue.get, True, 0.25)
                except queue.Empty:
                    continue

                if event.kind == "block":
                    assert event.block is not None
                    try:
                        await self._accept_cloud_native_mined_block(event.block)
                        accepted_blocks += 1
                        last_summary_at = self._maybe_print_cloud_native_summary(
                            block=event.block,
                            accepted_blocks=accepted_blocks,
                            stale_restarts=stale_restarts,
                            started_at=started_at,
                            last_summary_at=last_summary_at,
                        )
                    except CloudNativeAutomineStaleTip:
                        stale_restarts += 1
                        restart_requested = True
                        stop_event.set()
                        request_pow_cancel()
                        break
                elif event.kind == "cancelled":
                    restart_requested = not self._automine_stop_requested
                    break
                elif event.kind == "error":
                    if event.error is not None:
                        raise event.error
                    raise RuntimeError("Cloud native automine worker failed.")
        finally:
            stop_event.set()
            if worker.is_alive():
                request_pow_cancel()
                await asyncio.to_thread(worker.join, 5.0)
            reset_pow_cancel()

        return restart_requested

    def _maybe_print_cloud_native_summary(
        self,
        *,
        block: Block,
        accepted_blocks: int,
        stale_restarts: int,
        started_at: float,
        last_summary_at: float,
    ) -> float:
        block_interval = _read_positive_int_env(
            "UNCCOIN_CLOUD_NATIVE_SUMMARY_BLOCKS",
            10,
        )
        seconds_interval = _read_positive_float_env(
            "UNCCOIN_CLOUD_NATIVE_SUMMARY_SECONDS",
            15.0,
        )
        now = time.perf_counter()
        if (
            accepted_blocks % block_interval != 0
            and now - last_summary_at < seconds_interval
        ):
            return last_summary_at

        elapsed = max(now - started_at, 0.001)
        blocks_per_minute = accepted_blocks * 60.0 / elapsed
        print(
            "Cloud-native summary: "
            f"height={block.block_id} "
            f"accepted={accepted_blocks} "
            f"rate={blocks_per_minute:.1f}/min "
            f"stale_restarts={stale_restarts}",
            flush=True,
        )
        return now

    def _cloud_native_difficulty_schedule(self) -> CloudNativeDifficultySchedule:
        assert self.blockchain is not None
        return CloudNativeDifficultySchedule(
            difficulty_bits=self.blockchain.difficulty_bits,
            genesis_difficulty_bits=self.blockchain.genesis_difficulty_bits,
            difficulty_growth_factor=self.blockchain.difficulty_growth_factor,
            difficulty_growth_start_height=self.blockchain.difficulty_growth_start_height,
            difficulty_growth_bits=self.blockchain.difficulty_growth_bits,
            difficulty_schedule_activation_height=(
                self.blockchain.difficulty_schedule_activation_height
            ),
        )

    async def _accept_cloud_native_mined_block(self, block: Block) -> None:
        assert self.blockchain is not None

        expected_tip_hash = self._mining_tip_hash()
        if block.previous_hash != expected_tip_hash:
            raise CloudNativeAutomineStaleTip(
                f"mined block extends {block.previous_hash[:12]}, "
                f"current preferred tip is {expected_tip_hash[:12] if expected_tip_hash else 'unset'}",
            )

        previous_state_tip_hash = self._state_tip_hash()
        if self._can_fast_accept_cloud_native_block():
            self._fast_accept_cloud_native_mined_block(block)
        else:
            result = self.blockchain.add_block_result(
                block,
                reconcile_pending_transactions=not self.private_automine,
            )
            if result.status != "accepted":
                if result.status in {"duplicate", "missing_parent"}:
                    raise CloudNativeAutomineStaleTip(result.reason or result.status)
                raise ValueError(
                    "native mined block failed consensus validation: "
                    f"{result.reason or result.status}"
                )

        self._record_mined_block_progress(block)
        self._record_local_mining_tip(block.block_hash)
        self._current_automine_tip_hash = block.block_hash
        self._reconcile_pending_transactions_for_state_tip(previous_state_tip_hash)
        self._save_mined_block_progress()
        await self.broadcast_block(block)
        self._maybe_schedule_autosend()
        self.mining_tip_hash = self._mining_tip_hash()
        self.mining_difficulty_bits = self.blockchain.get_next_block_difficulty_bits(
            self.mining_tip_hash,
        )

    def _can_fast_accept_cloud_native_block(self) -> bool:
        assert self.blockchain is not None
        return (
            self.cloud_native_automine
            and self.mining_only
            and not self.blockchain.pending_transactions
        )

    def _fast_accept_cloud_native_mined_block(self, block: Block) -> None:
        assert self.blockchain is not None

        if block.block_hash in self.blockchain.blocks_by_hash:
            raise CloudNativeAutomineStaleTip("block already exists")

        parent_state = self.blockchain.block_states.get(block.previous_hash)
        if parent_state is None:
            raise CloudNativeAutomineStaleTip(
                f"missing parent state for block {block.previous_hash[:12]}"
            )

        if block.block_id != parent_state.height + 1:
            raise ValueError(
                "native mined block failed fast consensus validation: "
                f"block_id {block.block_id} does not extend parent height "
                f"{parent_state.height}"
            )

        validation_error = self._cloud_native_reward_only_validation_error(block)
        if validation_error is not None:
            raise ValueError(
                "native mined block failed fast consensus validation: "
                f"{validation_error}"
            )

        previous_head = self.blockchain.main_tip_hash
        previous_parent_children = list(
            self.blockchain.children_by_hash.get(block.previous_hash, [])
        )
        previous_block_children = self.blockchain.children_by_hash.get(block.block_hash)
        previous_fast_blocks_since_verify = self._cloud_native_fast_blocks_since_verify
        child_state = parent_state.copy()
        reward_transaction = block.transactions[0]
        child_state.height = block.block_id
        child_state.balances[reward_transaction.receiver] = (
            child_state.balances.get(reward_transaction.receiver, Decimal("0.0"))
            + reward_transaction.amount
        )

        try:
            self.blockchain.blocks_by_hash[block.block_hash] = block
            self.blockchain.block_states[block.block_hash] = child_state
            self.blockchain.children_by_hash.setdefault(block.block_hash, [])
            self.blockchain.children_by_hash.setdefault(block.previous_hash, []).append(
                block.block_hash
            )
            if self.blockchain._should_update_main_tip(block.block_hash):
                self.blockchain.main_tip_hash = block.block_hash

            self._cloud_native_fast_blocks_since_verify += 1
            verify_interval = _read_positive_int_env(
                "UNCCOIN_CLOUD_NATIVE_FULL_VERIFY_BLOCKS",
                100,
            )
            if self._cloud_native_fast_blocks_since_verify >= verify_interval:
                self._cloud_native_fast_blocks_since_verify = 0
                if not self.blockchain.verify_chain():
                    raise ValueError("full chain verification failed")
        except Exception:
            self.blockchain.blocks_by_hash.pop(block.block_hash, None)
            self.blockchain.block_states.pop(block.block_hash, None)
            if previous_block_children is None:
                self.blockchain.children_by_hash.pop(block.block_hash, None)
            else:
                self.blockchain.children_by_hash[block.block_hash] = previous_block_children
            self.blockchain.children_by_hash[block.previous_hash] = previous_parent_children
            self.blockchain.main_tip_hash = previous_head
            self._cloud_native_fast_blocks_since_verify = previous_fast_blocks_since_verify
            raise

    def _cloud_native_reward_only_validation_error(self, block: Block) -> str | None:
        assert self.blockchain is not None

        if len(block.transactions) != 1:
            return "cloud native fast path requires exactly one reward transaction"

        reward_transaction = block.transactions[0]
        if not is_mining_reward_transaction(reward_transaction):
            return "cloud native fast path block is missing a mining reward transaction"

        structure_error = get_mining_reward_structure_error(block)
        if structure_error is not None:
            return structure_error

        if (
            reward_transaction.sender_public_key is not None
            or reward_transaction.signature is not None
        ):
            return "mining reward transaction must not include signature data"

        if reward_transaction.fee != Decimal("0.0"):
            return "mining reward transaction fee must be 0.0"

        if reward_transaction.amount != MINING_REWARD_AMOUNT:
            return (
                f"mining reward amount {reward_transaction.amount} does not match "
                f"expected reward {MINING_REWARD_AMOUNT}"
            )

        reward_amount_error = get_mining_reward_amount_validation_error(
            block,
            Decimal("0.0"),
        )
        if reward_amount_error is not None:
            return reward_amount_error

        return get_block_verification_error(
            block,
            self.blockchain.get_difficulty_bits_for_height(block.block_id),
        )

    def mining_status(self) -> dict[str, Any]:
        next_difficulty_bits = None
        state_tip_hash = None
        if self.blockchain is not None:
            try:
                state_tip_hash = self._state_tip_hash()
                next_difficulty_bits = self.blockchain.get_next_block_difficulty_bits(
                    state_tip_hash,
                )
            except ValueError:
                pass

        return {
            "active": self.mining_active,
            "mode": self.mining_mode,
            "description": self.mining_description,
            "started_at": (
                self.mining_started_at.isoformat()
                if self.mining_started_at is not None
                else None
            ),
            "last_update_at": (
                self.mining_last_update_at.isoformat()
                if self.mining_last_update_at is not None
                else None
            ),
            "nonce": self.mining_last_nonce,
            "difficulty_bits": (
                self.mining_difficulty_bits
                if self.mining_difficulty_bits is not None
                else next_difficulty_bits
            ),
            "next_difficulty_bits": next_difficulty_bits,
            "state_tip_hash": state_tip_hash,
            "tip_hash": self.mining_tip_hash or state_tip_hash,
            "automine": {
                "running": (
                    self.automine_task is not None
                    and not self.automine_task.done()
                ),
                "description": self.automine_description,
            },
            "backend": self.mining_backend,
            "warmup": self.miner_warmup_status.copy(),
            "last_block": {
                "height": self.mining_last_block_height,
                "block_hash": self.mining_last_block_hash,
                "nonces_checked": self.mining_last_block_nonces_checked,
            },
        }

    def mining_backend_status(self) -> dict[str, Any]:
        return {
            **mining_backend_capabilities(self.mining_backend),
            "warmup": self.miner_warmup_status.copy(),
        }

    def set_mining_backend(self, backend: str) -> dict[str, Any]:
        if self.mining_active or (
            self.automine_task is not None
            and not self.automine_task.done()
        ):
            raise ValueError("Stop mining before changing the mining backend.")
        self.mining_backend = normalize_mining_backend(backend)
        if not self.miner_warmup_status.get("active", False):
            self.miner_warmup_status = self._default_miner_warmup_status()
        return self.mining_backend_status()

    def build_mining_backend(self, backend: str) -> dict[str, Any]:
        result = build_pow_backend(backend)
        result["capabilities"] = self.mining_backend_status()
        return result

    async def start_miner_warmup(self) -> dict[str, Any]:
        if (
            self.miner_warmup_task is not None
            and not self.miner_warmup_task.done()
        ):
            return self.miner_warmup_status.copy()

        now = datetime.now().isoformat()
        self.miner_warmup_status = {
            "active": True,
            "status": "running",
            "backend": self.mining_backend,
            "started_at": now,
            "finished_at": None,
            "error": None,
            "detail": "Warming selected miner backend.",
        }
        self.miner_warmup_task = asyncio.create_task(self._run_miner_warmup())
        return self.miner_warmup_status.copy()

    async def _run_miner_warmup(self) -> None:
        backend = self.mining_backend
        try:
            warmup_result = await asyncio.to_thread(self._warm_miner_backend, backend)
        except Exception as error:
            self.miner_warmup_status = {
                **self.miner_warmup_status,
                "active": False,
                "status": "failed",
                "finished_at": datetime.now().isoformat(),
                "error": str(error),
                "detail": "Miner warmup failed.",
            }
        else:
            self.miner_warmup_status = {
                **self.miner_warmup_status,
                "active": False,
                "status": "ready",
                "finished_at": datetime.now().isoformat(),
                "error": None,
                "detail": warmup_result,
            }

    def _warm_miner_backend(self, backend: str) -> dict[str, Any]:
        warmup_block = Block(
            block_id=0,
            transactions=[],
            hash_function=sha256_block_hash,
            description="miner warmup",
            previous_hash="0",
        )
        proof_of_work(
            warmup_block,
            difficulty_bits=0,
            mining_backend=backend,
        )
        return {
            "backend": backend,
            "nonce": warmup_block.nonce,
            "block_hash": warmup_block.block_hash,
            "nonces_checked": warmup_block.nonces_checked,
        }

    def _default_miner_warmup_status(self) -> dict[str, Any]:
        return {
            "active": False,
            "status": "idle",
            "backend": self.mining_backend,
            "started_at": None,
            "finished_at": None,
            "error": None,
            "detail": None,
        }

    def _start_mining_progress(
        self,
        mode: str,
        description: str,
        difficulty_bits: int,
        tip_hash: str | None,
    ) -> None:
        now = datetime.now()
        self.mining_active = True
        self.mining_mode = mode
        self.mining_description = description
        self.mining_started_at = now
        self.mining_last_update_at = now
        self.mining_last_nonce = 0
        self.mining_difficulty_bits = difficulty_bits
        self.mining_tip_hash = tip_hash

    def _record_mined_block_progress(self, block: Block) -> None:
        self.mining_last_nonce = block.nonce
        self.mining_last_update_at = datetime.now()
        self.mining_last_block_height = block.block_id
        self.mining_last_block_hash = block.block_hash
        self.mining_last_block_nonces_checked = block.nonces_checked

    def _report_mining_progress(self, nonce: int) -> None:
        self.mining_last_nonce = int(nonce)
        self.mining_last_update_at = datetime.now()
        print(f"\rTried {nonce:,} nonces...", end="", flush=True)

    def _clear_mining_progress(self) -> None:
        self.mining_active = False
        print("\r" + (" " * 40) + "\r", end="", flush=True)

    @staticmethod
    def _interactive_help_text() -> str:
        return """\
Commands:
  Network
    peers                         List connected peers
    known-peers                   List discovered peers
    discover                      Ask peers for more peers
    sync                          Request fast chain sync
    fastsync                      Request fast chain sync manually
    add-peer <host:port>          Connect to a peer
    localself                     Print this node's local address
    send <host:port> <json>       Send a direct JSON message
    <raw json>                    Broadcast raw JSON to connected peers

  Wallets and transactions
    alias <wallet-id> <alias>     Store a local wallet alias
    tx <receiver> <amount> <fee>  Broadcast a signed transaction
    commit <request-id> <hash> <fee>
                                  Commit a randomness hash for a request
    reveal <request-id> <seed> <fee> [salt]
                                  Reveal a seed for a prior commitment
    rebroadcast-pending           Rebroadcast local pending transactions
    deploy <fee> <json-or-file>   Deploy UVM code from JSON or state/contracts
    view-contract <contract>      Show deployed UVM contract details
    authorize <contract> <request-id> <fee> [valid-blocks]
                                  Broadcast an on-chain UVM consent transaction
    execute <contract> <gas-limit> <gas-price> <value> <max-fee> <json>
                                  Execute UVM code with on-chain authorizations
    receipt <txid-prefix>          Show a UVM execution receipt
    balance [address]             Print one balance
    balances [>amount|<amount]    Print balances, optionally filtered
    autosend <wallet-id>          Forward future balance increases
    autosend off                  Disable autosend

  Messages
    msg <wallet> <content>        Send a signed wallet message
    messages                      Print local message history

  Mining
    mine [description]            Mine one block
    automine [description]        Mine continuously
    stop                          Stop automining after the current block
    blockchain                    Print the canonical chain

  Output and console
    txtbalances <relative-path>   Write balances to a text file
    txtblockchain <relative-path> Write blockchain state JSON to a file
    mute                          Hide incoming network notifications
    unmute                        Show incoming network notifications
    help                          Show this help text
    clear                         Clear the screen
    quit                          Exit

Wallet commands accept either a wallet address or a local alias."""

    async def interactive_console(self) -> None:
        print("Interactive mode enabled.")
        print(self._interactive_help_text())

        while True:
            try:
                raw_input_line = await asyncio.to_thread(input, "p2p> ")
            except EOFError:
                return

            line = raw_input_line.strip()
            if not line:
                continue

            if line == "quit":
                return

            if line == "help":
                print(self._interactive_help_text())
                continue

            if line == "clear":
                print("\033[H\033[2J\033[3J", end="", flush=True)
                continue

            if line == "peers":
                peers = self.list_peers()
                print("Connected peers:" if peers else "No connected peers.")
                for peer in peers:
                    print(peer)
                continue

            if line == "known-peers":
                peers = self.list_known_peers()
                print("Known peers:" if peers else "No known peers.")
                for peer in peers:
                    print(peer)
                continue

            if line == "discover":
                await self.discover_peers()
                print("Peer discovery request sent.")
                continue

            if line == "sync":
                peer_count = await self.sync_chain()
                print(f"Requested fast chain sync from {peer_count} peer(s).")
                continue

            if line == "fastsync":
                peer_count = await self.sync_chain(fast=True)
                print(f"Requested fast chain sync from {peer_count} peer(s).")
                continue

            if line == "mute":
                self.network_notifications_muted = True
                print("Incoming network notifications muted.")
                continue

            if line == "unmute":
                self.network_notifications_muted = False
                print("Incoming network notifications unmuted.")
                continue

            if line.startswith("autosend"):
                try:
                    autosend_target = line[len("autosend"):].strip()
                    if not autosend_target:
                        print(self.format_autosend_status())
                    elif autosend_target.lower() == "off":
                        self.disable_autosend()
                        print("Autosend disabled.")
                    else:
                        resolved_target = self.enable_autosend(autosend_target)
                        print(
                            "Autosend enabled to "
                            f"{self.format_wallet_reference(resolved_target)}."
                        )
                except ValueError as error:
                    print(f"Invalid autosend command: {error}")
                continue

            if line == "localself":
                print(self.self_peer_address())
                continue

            if line.startswith("alias "):
                try:
                    wallet_reference, alias = line[len("alias "):].split(" ", maxsplit=1)
                    wallet_address = self.set_wallet_alias(wallet_reference, alias.strip())
                    print(
                        f"Stored alias {self.alias_for_wallet(wallet_address)} "
                        f"for {wallet_address}"
                    )
                except ValueError as error:
                    print(f"Invalid alias command: {error}")
                continue

            if line.startswith("add-peer "):
                try:
                    host, port = line[len("add-peer "):].split(":", maxsplit=1)
                    await self.connect_to_peer(host, int(port))
                    print(f"Connected to peer {host}:{port}")
                except ValueError as error:
                    print(f"Invalid add-peer command: {error}")
                continue

            if line == "stop":
                if self.automine_task is None or self.automine_task.done():
                    print("Automine is not running.")
                    continue
                print("Stopping automine after the current block...")
                await self.stop_automine(wait=True)
                print("Automine stopped.")
                continue

            if line == "blockchain":
                print(self.format_canonical_blockchain())
                continue

            if line.startswith("receipt "):
                try:
                    print(self.format_uvm_receipt(line[len("receipt "):].strip()))
                except ValueError as error:
                    print(f"Invalid receipt command: {error}")
                continue

            if line == "messages":
                print(self.format_message_history())
                continue

            if line.startswith("balances"):
                try:
                    print(self.format_all_balances(line[len("balances"):].strip()))
                except ValueError as error:
                    print(f"Invalid balances command: {error}")
                continue

            if line.startswith("txtbalances"):
                try:
                    path = self.write_all_balances_to_file(
                        line[len("txtbalances"):].strip()
                    )
                    print(f"Balances written to {path}")
                except ValueError as error:
                    print(f"Invalid txtbalances command: {error}")
                continue

            if line.startswith("txtblockchain"):
                try:
                    path = self.write_blockchain_state_to_file(
                        line[len("txtblockchain"):].strip()
                    )
                    print(f"Blockchain state written to {path}")
                except ValueError as error:
                    print(f"Invalid txtblockchain command: {error}")
                continue

            if line.startswith("balance"):
                address = self.resolve_wallet_reference(
                    line[len("balance"):].strip()
                ) or (
                    self.wallet.address if self.wallet is not None else ""
                )
                if not address:
                    print("Balance command requires an address when no wallet is loaded.")
                    continue
                print(
                    f"Balance for {self.format_wallet_reference(address)}: "
                    f"{self.get_balance(address)}"
                )
                continue

            if line.startswith("tx "):
                try:
                    receiver, amount, fee = line[len("tx "):].split(" ", maxsplit=2)
                    transaction = self.create_signed_transaction(
                        receiver=self.resolve_wallet_reference(receiver),
                        amount=amount,
                        fee=fee,
                    )
                    await self.broadcast_transaction(transaction)
                except ValueError as error:
                    print(f"Invalid tx command: {error}")
                continue

            if line.startswith("commit "):
                try:
                    request_id, commitment_hash, fee = line[len("commit "):].split(
                        " ",
                        maxsplit=2,
                    )
                    transaction = self.create_signed_commitment(
                        request_id=request_id,
                        commitment_hash=commitment_hash,
                        fee=fee,
                    )
                    await self.broadcast_transaction(transaction)
                except ValueError as error:
                    print(f"Invalid commit command: {error}")
                continue

            if line.startswith("reveal "):
                try:
                    reveal_args = line[len("reveal "):].split(" ", maxsplit=3)
                    if len(reveal_args) not in {3, 4}:
                        raise ValueError("Use reveal <request-id> <seed> <fee> [salt].")
                    request_id, seed, fee = reveal_args[:3]
                    salt = reveal_args[3] if len(reveal_args) == 4 else ""
                    transaction = self.create_signed_reveal(
                        request_id=request_id,
                        seed=seed,
                        fee=fee,
                        salt=salt,
                    )
                    expected_commitment_hash = create_reveal_commitment_hash(
                        self.wallet.address if self.wallet is not None else "",
                        request_id,
                        seed,
                        salt,
                    )
                    await self.broadcast_transaction(transaction)
                    print(f"Reveal matches commitment hash {expected_commitment_hash}")
                except ValueError as error:
                    print(f"Invalid reveal command: {error}")
                continue

            if line == "rebroadcast-pending":
                count = await self.rebroadcast_pending_transactions()
                print(f"Rebroadcast {count} pending transaction(s).")
                continue

            if line.startswith("deploy "):
                try:
                    deploy_args = line[len("deploy "):].split(" ", maxsplit=1)
                    if len(deploy_args) != 2:
                        raise ValueError("Use deploy <fee> <json-or-file>.")
                    fee, deploy_json = deploy_args
                    transaction = self.create_signed_deploy_from_source(
                        contract_source=deploy_json,
                        fee=fee,
                    )
                    await self.broadcast_transaction(transaction)
                    print(
                        "Deploy transaction broadcast: "
                        f"{sha256_transaction_hash(transaction)}"
                    )
                    print(f"Contract address: {transaction.receiver}")
                    print(f"Code hash: {transaction.payload['code_hash']}")
                except ValueError as error:
                    print(f"Invalid deploy command: {error}")
                continue

            if line.startswith("view-contract "):
                try:
                    print(
                        self.format_contract_view(
                            line[len("view-contract "):].strip()
                        )
                    )
                except ValueError as error:
                    print(f"Invalid view-contract command: {error}")
                continue

            if line.startswith("authorize "):
                try:
                    authorize_args = line[len("authorize "):].split(" ", maxsplit=3)
                    if len(authorize_args) not in {3, 4}:
                        raise ValueError(
                            "Use authorize <contract> <request-id> <fee> "
                            "[valid-blocks]."
                        )
                    contract_address, request_id, fee = authorize_args[:3]
                    valid_for_blocks = (
                        authorize_args[3] if len(authorize_args) == 4 else None
                    )
                    transaction = self.create_signed_authorization(
                        contract_address=contract_address,
                        request_id=request_id,
                        fee=fee,
                        valid_for_blocks=valid_for_blocks,
                    )
                    await self.broadcast_transaction(transaction)
                    print(
                        "Authorize transaction broadcast: "
                        f"{sha256_transaction_hash(transaction)}"
                    )
                except ValueError as error:
                    print(f"Invalid authorize command: {error}")
                continue

            if line.startswith("execute "):
                try:
                    execute_args = line[len("execute "):].split(" ", maxsplit=5)
                    if len(execute_args) != 6:
                        raise ValueError(
                            "Use execute <contract> <gas-limit> <gas-price> "
                            "<value> <max-fee> <json>."
                        )
                    (
                        contract_address,
                        gas_limit,
                        gas_price,
                        value,
                        fee,
                        execute_json,
                    ) = execute_args
                    execute_payload = json.loads(execute_json)
                    if isinstance(execute_payload, dict):
                        input_data = execute_payload.get("input")
                        if execute_payload.get("authorizations"):
                            raise ValueError(
                                "Execute authorizations are on-chain now; "
                                "submit authorize transactions before execution."
                            )
                    else:
                        input_data = execute_payload
                    transaction = self.create_signed_execute(
                        contract_address=contract_address,
                        input_data=input_data,
                        gas_limit=gas_limit,
                        gas_price=gas_price,
                        value=value,
                        fee=fee,
                    )
                    await self.broadcast_transaction(transaction)
                    print(
                        "Execute transaction broadcast: "
                        f"{sha256_transaction_hash(transaction)}"
                    )
                except (ValueError, json.JSONDecodeError) as error:
                    print(f"Invalid execute command: {error}")
                continue

            if line.startswith("msg "):
                try:
                    receiver, content = line[len("msg "):].split(" ", maxsplit=1)
                    wallet_message = self.create_signed_wallet_message(
                        self.resolve_wallet_reference(receiver),
                        content,
                    )
                    await self.broadcast_wallet_message(wallet_message)
                except ValueError as error:
                    print(f"Invalid msg command: {error}")
                continue

            if line.startswith("mine"):
                description = (
                    line[len("mine"):].strip()
                    or self.default_block_description("Mined block")
                )
                try:
                    block = await self.mine_pending_transactions_with_progress(description)
                    print(f"Mined and broadcast block {block.block_hash[:12]} at height {block.block_id}")
                except ValueError as error:
                    print(f"Mining failed: {error}")
                continue

            if line.startswith("automine"):
                description = (
                    line[len("automine"):].strip()
                    or self.default_block_description("Auto-mined block")
                )
                try:
                    await self.start_automine(description)
                    print("Automine started.")
                except ValueError as error:
                    print(f"Automine failed: {error}")
                continue

            if line.startswith("send "):
                try:
                    peer_part, message_part = line[len("send "):].split(" ", maxsplit=1)
                    host, port = peer_part.split(":", maxsplit=1)
                    message = json.loads(message_part)
                    await self.send_to_peer(host, int(port), message)
                    print(f"Sent direct message to {host}:{port}")
                except (ValueError, json.JSONDecodeError) as error:
                    print(f"Invalid send command: {error}")
                continue

            try:
                message = json.loads(line)
            except json.JSONDecodeError as error:
                print(f"Invalid JSON: {error}")
                continue

            await self.broadcast(message)
            print("Broadcast message sent.")

    def _handle_incoming_transaction(self, transaction: Transaction) -> tuple[bool, str | None]:
        if self.blockchain is None:
            return False, "no blockchain is loaded"

        try:
            self.blockchain.add_transaction(
                transaction,
                tip_hash=self._state_tip_hash(),
            )
        except ValueError as error:
            return False, str(error)

        self._save_persisted_blockchain("accepted transaction")
        return True, None

    def _handle_incoming_block(self, block: Block) -> tuple[str, str | None]:
        if self.blockchain is None:
            return "rejected", "no blockchain is loaded"

        return self._accept_or_store_block(block)

    def _handle_chain_request(self) -> list[Block]:
        if self.blockchain is None:
            return []
        return self.blockchain.blocks

    def _handle_pending_transactions(self) -> list[Transaction]:
        if self.blockchain is None:
            return []
        return list(self.blockchain.pending_transactions)

    def _handle_chain_summary(self) -> tuple[str | None, int]:
        if self.blockchain is None or self.blockchain.main_tip_hash is None:
            return None, -1
        return self.blockchain.main_tip_hash, self.blockchain.blocks[-1].block_id

    def _handle_chain_response(self, blocks: list[Block]) -> dict[str, int]:
        if self.blockchain is None:
            return {
                "accepted": 0,
                "duplicates": 0,
                "orphans": 0,
                "rejected": 0,
            }

        accepted_blocks = 0
        duplicate_blocks = 0
        orphaned_blocks = 0
        rejected_blocks = 0
        previous_head = self.blockchain.main_tip_hash
        previous_state_tip_hash = self._state_tip_hash()
        active_fast_sync = any(
            state.active
            for state in self.p2p_server.fast_sync_states.values()
        )
        for block in blocks:
            if block.block_hash in self.blockchain.blocks_by_hash:
                duplicate_blocks += 1
                continue
            status, reason = self._accept_or_store_sync_block(block)
            if status == "accepted":
                accepted_blocks += 1
            elif status == "orphaned":
                orphaned_blocks += 1
                self._print_network_notification(
                    f"Deferred synced block {block.block_hash[:12]}: "
                    f"{reason or 'waiting for parent'}"
                )
            elif status == "duplicate":
                duplicate_blocks += 1
            else:
                rejected_blocks += 1
                self._print_network_notification(
                    f"Rejected synced block {block.block_hash[:12]}: "
                    f"{reason or 'unknown reason'}"
                )

        if accepted_blocks > 0:
            self._reconcile_pending_transactions_after_sync(
                previous_head,
                previous_state_tip_hash,
            )
            if active_fast_sync:
                self._deferred_chain_sync_save_pending = True
            else:
                self._save_persisted_blockchain("chain sync")
            self._maybe_schedule_autosend()

        sync_label = (
            "Fast sync chunk processed"
            if active_fast_sync
            else "Chain sync chunk processed"
        )
        self._print_network_notification(
            f"{sync_label}: "
            f"accepted {accepted_blocks}, duplicates {duplicate_blocks}, "
            f"orphans {orphaned_blocks}, rejected {rejected_blocks}."
        )
        self._maybe_schedule_autosend()
        return {
            "accepted": accepted_blocks,
            "duplicates": duplicate_blocks,
            "orphans": orphaned_blocks,
            "rejected": rejected_blocks,
        }

    def _handle_chain_sync_complete(self) -> None:
        if not self._deferred_chain_sync_save_pending:
            return

        self._deferred_chain_sync_save_pending = False
        self._save_persisted_blockchain("chain sync")

    def _handle_wallet_message(self, wallet_message: dict) -> bool:
        sender_public_key_data = wallet_message.get("sender_public_key")
        signature = wallet_message.get("signature")
        sender = wallet_message.get("sender", "")
        receiver = wallet_message.get("receiver", "")
        content = wallet_message.get("content", "")
        timestamp = wallet_message.get("timestamp", "")
        message_id = wallet_message.get("message_id", "")

        if (
            not sender_public_key_data
            or signature is None
            or not sender
            or not receiver
            or not content
            or not timestamp
            or not message_id
        ):
            return False

        sender_public_key = (
            int(sender_public_key_data["exponent"]),
            int(sender_public_key_data["modulus"]),
        )
        if sender != Wallet.address_from_public_key(sender_public_key):
            return False

        payload = f"{sender}|{receiver}|{content}|{timestamp}|{message_id}"
        if not Wallet.verify_signature_with_public_key(
            message=payload,
            signature=signature,
            public_key=sender_public_key,
        ):
            return False

        if self.wallet is not None and sender == self.wallet.address:
            self._store_wallet_message(
                {
                    "direction": "sent",
                    "message_id": message_id,
                    "sender": sender,
                    "receiver": receiver,
                    "content": content,
                    "timestamp": timestamp,
                }
            )
        elif self.wallet is not None and receiver == self.wallet.address:
            self._store_wallet_message(
                {
                    "direction": "received",
                    "message_id": message_id,
                    "sender": sender,
                    "receiver": receiver,
                    "content": content,
                    "timestamp": timestamp,
                }
            )
            self._print_network_notification(
                f"\nMessage from {self.format_wallet_reference(sender)}: {content}",
                force=True,
            )

        return True

    def _ensure_genesis_block(self) -> None:
        if self.blockchain is None or self.blockchain.blocks_by_hash:
            return

        genesis_block = create_genesis_block(sha256_block_hash)
        self.blockchain.add_block(genesis_block)

    def _load_persisted_blockchain(self) -> None:
        if self.wallet is None:
            return

        try:
            persisted_blockchain = load_blockchain_state(
                self.wallet.address,
                hash_function=sha256_block_hash,
            )
        except ValueError as error:
            print(
                f"Ignoring persisted blockchain for {self.wallet.address}: {error}",
                flush=True,
            )
            return
        if persisted_blockchain is None:
            return

        self.blockchain = persisted_blockchain
        print(
            f"Loaded persisted blockchain for {self.wallet.address} "
            f"({len(self.blockchain.blocks)} blocks)",
            flush=True,
        )

    def _save_persisted_blockchain(self, reason: str | None = None) -> None:
        if (
            not self._persist_blockchain_state
            or self.wallet is None
            or self.blockchain is None
        ):
            return

        try:
            path = save_blockchain_state(self.wallet.address, self.blockchain)
        except OSError as error:
            print(f"Failed to save blockchain state: {error}", flush=True)
            return

        reason_suffix = f" ({reason})" if reason else ""
        print(f"Saved blockchain state to {path}{reason_suffix}", flush=True)

    def _save_mined_block_progress(self) -> None:
        if self.mined_block_persist_interval == 0:
            self._mined_blocks_since_persist += 1
            return

        self._mined_blocks_since_persist += 1
        if self._mined_blocks_since_persist < self.mined_block_persist_interval:
            return

        self._mined_blocks_since_persist = 0
        self._save_persisted_blockchain("mined block")

    def _load_contract_deploy_payload(self, contract_source: str):
        try:
            return json.loads(contract_source)
        except json.JSONDecodeError:
            contract_path = self._resolve_contract_source_path(contract_source)

        try:
            return json.loads(contract_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Contract file {contract_path.relative_to(self.REPO_ROOT)} "
                f"does not contain valid JSON: {error}"
            ) from error

    def _resolve_contract_source_path(self, contract_source: str) -> Path:
        cleaned_source = contract_source.strip()
        if not cleaned_source:
            raise ValueError("Contract source must not be empty.")

        source_path = Path(cleaned_source)
        candidates: list[Path] = []
        if source_path.is_absolute():
            candidates.append(source_path)
            if source_path.suffix == "":
                candidates.append(source_path.with_suffix(".uvm"))
        else:
            candidates.append(self.CONTRACTS_DIR / source_path)
            if source_path.suffix == "":
                candidates.append((self.CONTRACTS_DIR / source_path).with_suffix(".uvm"))
            candidates.append(self.REPO_ROOT / source_path)
            if source_path.suffix == "":
                candidates.append((self.REPO_ROOT / source_path).with_suffix(".uvm"))

        for candidate in candidates:
            resolved_candidate = candidate.resolve()
            try:
                resolved_candidate.relative_to(self.REPO_ROOT.resolve())
            except ValueError:
                continue
            if resolved_candidate.is_file():
                return resolved_candidate

        searched_paths = ", ".join(
            self._format_contract_source_candidate(candidate)
            for candidate in candidates
        )
        raise ValueError(
            f"Contract source {cleaned_source} is neither inline JSON nor a readable "
            f"contract file. Searched: {searched_paths}"
        )

    def _format_contract_source_candidate(self, candidate: Path) -> str:
        if candidate.is_absolute() and self.REPO_ROOT in candidate.parents:
            return str(candidate.relative_to(self.REPO_ROOT))
        return str(candidate)

    def format_canonical_blockchain(self) -> str:
        if self.blockchain is None or not self.blockchain.blocks:
            return "Canonical blockchain is empty."

        lines = ["Canonical blockchain:"]
        for block in self.blockchain.blocks:
            lines.append(
                f"#{block.block_id} {block.block_hash[:12]} "
                f"prev={block.previous_hash[:12]} txs={len(block.transactions)} "
                f'"{block.description}"'
            )
        return "\n".join(lines)

    def format_contract_view(self, contract_reference: str) -> str:
        if self.blockchain is None:
            return "No blockchain is loaded."

        contract_reference = contract_reference.strip()
        if not contract_reference:
            raise ValueError("view-contract requires a contract address or prefix.")

        state = self.blockchain._get_state_for_tip(self._state_tip_hash())
        matches = [
            (contract_address, contract)
            for contract_address, contract in state.contracts.items()
            if contract_address.startswith(contract_reference)
        ]
        if not matches:
            return f"No contract found for {contract_reference}."
        if len(matches) > 1:
            return (
                f"Contract prefix {contract_reference} is ambiguous: "
                + ", ".join(contract_address[:12] for contract_address, _ in matches)
            )

        contract_address, contract = matches[0]
        metadata = contract.get("metadata", {})
        program = contract.get("program", [])
        code_hash = str(
            contract.get(
                "code_hash",
                compute_contract_code_hash(program, metadata),
            )
        )
        lines = [
            f"Contract {contract_address}:",
            f"  deployer: {self.format_wallet_reference(contract.get('deployer', ''))}",
            f"  code_hash: {code_hash}",
            f"  metadata: {json.dumps(metadata, sort_keys=True)}",
            "  program:",
        ]
        program_json = json.dumps(program, indent=2, sort_keys=True)
        lines.extend(f"    {line}" for line in program_json.splitlines())
        return "\n".join(lines)

    def format_uvm_receipt(self, transaction_reference: str) -> str:
        if self.blockchain is None:
            return "No blockchain is loaded."

        transaction_reference = transaction_reference.strip()
        if not transaction_reference:
            raise ValueError("Receipt command requires a transaction id or prefix.")

        state = self.blockchain._get_state_for_tip(self._state_tip_hash())
        matches = [
            (transaction_id, receipt)
            for transaction_id, receipt in state.uvm_receipts.items()
            if transaction_id.startswith(transaction_reference)
        ]
        if not matches:
            return f"No UVM receipt found for {transaction_reference}."
        if len(matches) > 1:
            return (
                f"Receipt prefix {transaction_reference} is ambiguous: "
                + ", ".join(transaction_id[:12] for transaction_id, _ in matches)
            )

        transaction_id, receipt = matches[0]
        status = "success" if receipt.get("success") else "failed"
        lines = [
            f"UVM receipt {transaction_id}:",
            f"  status: {status}",
            f"  gas_used: {receipt.get('gas_used')}",
            f"  gas_remaining: {receipt.get('gas_remaining')}",
            f"  gas_exhausted: {receipt.get('gas_exhausted')}",
        ]
        if "fee_paid" in receipt:
            lines.extend(
                [
                    f"  fee_escrowed: {receipt.get('fee_escrowed')}",
                    f"  fee_paid: {receipt.get('fee_paid')}",
                    f"  fee_refunded: {receipt.get('fee_refunded')}",
                ]
            )
        if receipt.get("error"):
            lines.append(f"  error: {receipt['error']}")

        lines.append(f"  stack: {json.dumps(receipt.get('stack', []))}")
        lines.append(f"  memory: {json.dumps(receipt.get('memory', {}), sort_keys=True)}")
        lines.append(f"  storage: {json.dumps(receipt.get('storage', {}), sort_keys=True)}")

        balance_changes = receipt.get("balance_changes", {})
        if balance_changes:
            lines.append("  balance_changes:")
            for address, change in sorted(balance_changes.items()):
                lines.append(f"    {self.format_wallet_reference(address)}: {change}")

        transfers = receipt.get("transfers", [])
        if transfers:
            lines.append("  transfers:")
            for transfer in transfers:
                lines.append(
                    "    "
                    f"{self.format_wallet_reference(transfer.get('source', ''))} -> "
                    f"{self.format_wallet_reference(transfer.get('receiver', ''))}: "
                    f"{transfer.get('amount')} "
                    f"(request_id={transfer.get('request_id')})"
                )

        return "\n".join(lines)

    def get_balance(self, address: str) -> str:
        if self.blockchain is None:
            return "0.0"
        return str(
            self.blockchain.get_balance(
                address,
                tip_hash=self._state_tip_hash(),
            )
        )

    def format_all_balances(self, filter_expression: str = "") -> str:
        if self.blockchain is None or not self.blockchain.blocks:
            return "No balances available."

        addresses: set[str] = set()
        for block in self.blockchain.get_chain(self._state_tip_hash()):
            for transaction in block.transactions:
                if (
                    transaction.sender
                    and transaction.sender != MINING_REWARD_SENDER
                ):
                    addresses.add(transaction.sender)
                if transaction.receiver:
                    addresses.add(transaction.receiver)

        if not addresses:
            return "No wallet balances found."

        comparison = self._parse_balance_filter(filter_expression)
        lines = ["Balances:"]
        for address in sorted(addresses, key=self._wallet_balance_sort_key):
            balance = self.blockchain.get_balance(
                address,
                tip_hash=self._state_tip_hash(),
            )
            if comparison is not None and not comparison(balance):
                continue
            lines.append(f"{self.format_wallet_reference(address)}: {balance}")
        if len(lines) == 1:
            return "No wallet balances matched the filter."
        return "\n".join(lines)

    def write_all_balances_to_file(self, relative_path: str) -> Path:
        resolved_path = self._resolve_repo_relative_output_path(
            relative_path=relative_path,
            command_name="txtbalances",
        )

        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(
            f"{self.format_all_balances()}\n",
            encoding="utf-8",
        )
        return resolved_path.relative_to(self.REPO_ROOT.resolve())

    def write_blockchain_state_to_file(self, relative_path: str) -> Path:
        if self.wallet is None or self.blockchain is None:
            raise ValueError("No wallet-backed blockchain is loaded.")

        resolved_path = self._resolve_repo_relative_output_path(
            relative_path=relative_path,
            command_name="txtblockchain",
        )
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        write_blockchain_state(
            resolved_path,
            self.wallet.address,
            self.blockchain,
        )
        return resolved_path.relative_to(self.REPO_ROOT.resolve())

    def _resolve_repo_relative_output_path(
        self,
        relative_path: str,
        command_name: str,
    ) -> Path:
        if not relative_path:
            raise ValueError(f"Use {command_name} <relative-path>.")

        output_path = Path(relative_path)
        if output_path.is_absolute():
            raise ValueError(f"{command_name} requires a relative path.")

        resolved_repo_root = self.REPO_ROOT.resolve()
        resolved_path = (resolved_repo_root / output_path).resolve()
        if not resolved_path.is_relative_to(resolved_repo_root):
            raise ValueError(f"{command_name} path must stay within the project root.")

        return resolved_path

    def self_peer_address(self) -> str:
        return f"{self.host}:{self.port}"

    def format_message_history(self) -> str:
        if not self.message_history:
            return "No stored messages."

        lines = ["Message history:"]
        for message in self.message_history:
            peer = (
                message["receiver"]
                if message["direction"] == "sent"
                else message["sender"]
            )
            lines.append(
                f"[{message['timestamp']}] {message['direction']} "
                f"{self.format_wallet_reference(peer)}: {message['content']}"
            )
        return "\n".join(lines)

    def format_autosend_status(self) -> str:
        if self.autosend_target is None:
            return "Autosend is disabled."
        return (
            "Autosend is enabled to "
            f"{self.format_wallet_reference(self.autosend_target)}."
        )

    def resolve_wallet_reference(self, wallet_reference: str) -> str:
        stripped_reference = wallet_reference.strip()
        if not stripped_reference:
            return ""
        return self.wallet_aliases.get(stripped_reference, stripped_reference)

    def alias_for_wallet(self, wallet_address: str) -> str | None:
        for alias, address in self.wallet_aliases.items():
            if address == wallet_address:
                return alias
        return None

    def format_wallet_reference(self, wallet_address: str) -> str:
        alias = self.alias_for_wallet(wallet_address)
        if alias is None:
            return wallet_address
        return f"{alias} ({wallet_address[:10]})"

    def set_wallet_alias(self, wallet_reference: str, alias: str) -> str:
        cleaned_alias = alias.strip()
        if not cleaned_alias:
            raise ValueError("Alias must not be empty.")

        wallet_address = self.resolve_wallet_reference(wallet_reference)
        if not wallet_address:
            raise ValueError("Wallet id must not be empty.")

        aliases_to_remove = [
            existing_alias
            for existing_alias, existing_address in self.wallet_aliases.items()
            if existing_alias == cleaned_alias or existing_address == wallet_address
        ]
        for existing_alias in aliases_to_remove:
            self.wallet_aliases.pop(existing_alias, None)

        self.wallet_aliases[cleaned_alias] = wallet_address
        self._save_persisted_aliases()
        return wallet_address

    def enable_autosend(self, wallet_reference: str) -> str:
        if self.wallet is None or self.blockchain is None:
            raise ValueError("A loaded wallet is required to enable autosend.")

        wallet_address = self.resolve_wallet_reference(wallet_reference)
        if not wallet_address:
            raise ValueError("Autosend target must not be empty.")
        if wallet_address == self.wallet.address:
            raise ValueError("Autosend target must be different from the loaded wallet.")

        self.autosend_target = wallet_address
        self._reset_autosend_balance_baseline()
        return wallet_address

    def disable_autosend(self) -> None:
        self.autosend_target = None
        self._reset_autosend_balance_baseline()

    def _wallet_sort_key(self, wallet_address: str) -> tuple[str, str]:
        alias = self.alias_for_wallet(wallet_address)
        return (
            alias.lower() if alias is not None else wallet_address.lower(),
            wallet_address,
        )

    def _wallet_balance_sort_key(self, wallet_address: str) -> tuple[Decimal, str, str]:
        assert self.blockchain is not None
        return (
            self.blockchain.get_balance(
                wallet_address,
                tip_hash=self._state_tip_hash(),
            ),
            *self._wallet_sort_key(wallet_address),
        )

    def _parse_balance_filter(
        self,
        filter_expression: str,
    ) -> Callable[[Decimal], bool] | None:
        if not filter_expression:
            return None

        if filter_expression[0] not in {">", "<"}:
            raise ValueError("Use balances, balances >amount, or balances <amount.")

        threshold_text = filter_expression[1:].strip()
        if not threshold_text:
            raise ValueError("Balance filter requires an amount.")

        try:
            threshold = Decimal(threshold_text)
        except InvalidOperation as error:
            raise ValueError("Balance filter amount must be a valid decimal.") from error

        if filter_expression[0] == ">":
            return lambda balance: balance > threshold
        return lambda balance: balance < threshold

    def _accept_or_store_block(self, block: Block) -> tuple[str, str | None]:
        assert self.blockchain is not None

        previous_state_tip_hash = self._state_tip_hash()
        result = self.blockchain.add_block_result(
            block,
            reconcile_pending_transactions=not self.private_automine,
        )
        status = result.status
        if status == "accepted":
            self.orphan_block_hashes.discard(block.block_hash)
            self._handle_accepted_block_for_automine(block)
            self._reconcile_pending_transactions_for_state_tip(previous_state_tip_hash)
            self._resolve_orphan_descendants(block.block_hash)
            self._maybe_schedule_autosend()
            self._save_persisted_blockchain("accepted block")
            return "accepted", None

        if status == "duplicate":
            self.orphan_block_hashes.discard(block.block_hash)
            return "duplicate", result.reason

        if status == "missing_parent":
            self._store_orphan_block(block)
            return "orphaned", result.reason

        self.orphan_block_hashes.discard(block.block_hash)
        return "rejected", result.reason

    def _accept_or_store_sync_block(self, block: Block) -> tuple[str, str | None]:
        assert self.blockchain is not None

        result = self.blockchain.add_block_result(
            block,
            reconcile_pending_transactions=False,
        )
        status = result.status
        if status == "accepted":
            self.orphan_block_hashes.discard(block.block_hash)
            self._handle_accepted_block_for_automine(block)
            self._resolve_synced_orphan_descendants(block.block_hash)
            return "accepted", None

        if status == "duplicate":
            self.orphan_block_hashes.discard(block.block_hash)
            return "duplicate", result.reason

        if status == "missing_parent":
            self._store_orphan_block(block)
            return "orphaned", result.reason

        self.orphan_block_hashes.discard(block.block_hash)
        return "rejected", result.reason

    def _store_orphan_block(self, block: Block) -> None:
        if block.block_hash in self.orphan_block_hashes:
            return

        self.orphan_block_hashes.add(block.block_hash)
        self.orphan_blocks_by_parent_hash.setdefault(block.previous_hash, []).append(block)

    def _resolve_orphan_descendants(self, parent_hash: str) -> None:
        pending_parent_hashes = [parent_hash]

        while pending_parent_hashes:
            current_parent_hash = pending_parent_hashes.pop()
            orphan_blocks = self.orphan_blocks_by_parent_hash.pop(current_parent_hash, [])

            for orphan_block in orphan_blocks:
                previous_state_tip_hash = self._state_tip_hash()
                result = self.blockchain.add_block_result(
                    orphan_block,
                    reconcile_pending_transactions=not self.private_automine,
                )
                status = result.status
                if status == "accepted":
                    self.orphan_block_hashes.discard(orphan_block.block_hash)
                    self._handle_accepted_block_for_automine(orphan_block)
                    self._reconcile_pending_transactions_for_state_tip(previous_state_tip_hash)
                    self._print_network_notification(
                        f"Accepted orphan block {orphan_block.block_hash[:12]} "
                        f"at height {orphan_block.block_id}"
                    )
                    pending_parent_hashes.append(orphan_block.block_hash)
                elif status == "missing_parent":
                    self._store_orphan_block(orphan_block)
                elif status == "duplicate":
                    self.orphan_block_hashes.discard(orphan_block.block_hash)
                else:
                    self.orphan_block_hashes.discard(orphan_block.block_hash)
                    self._print_network_notification(
                        f"Rejected orphan block {orphan_block.block_hash[:12]}: "
                        f"{result.reason or 'unknown reason'}"
                    )

    def _resolve_synced_orphan_descendants(self, parent_hash: str) -> None:
        pending_parent_hashes = [parent_hash]

        while pending_parent_hashes:
            current_parent_hash = pending_parent_hashes.pop()
            orphan_blocks = self.orphan_blocks_by_parent_hash.pop(current_parent_hash, [])

            for orphan_block in orphan_blocks:
                result = self.blockchain.add_block_result(
                    orphan_block,
                    reconcile_pending_transactions=False,
                )
                status = result.status
                if status == "accepted":
                    self.orphan_block_hashes.discard(orphan_block.block_hash)
                    self._handle_accepted_block_for_automine(orphan_block)
                    pending_parent_hashes.append(orphan_block.block_hash)
                elif status == "missing_parent":
                    self._store_orphan_block(orphan_block)
                elif status == "duplicate":
                    self.orphan_block_hashes.discard(orphan_block.block_hash)
                else:
                    self.orphan_block_hashes.discard(orphan_block.block_hash)

    def _reconcile_pending_transactions_after_sync(
        self,
        previous_head: str | None,
        previous_state_tip_hash: str | None,
    ) -> None:
        assert self.blockchain is not None

        if self.private_automine:
            self._reconcile_pending_transactions_for_state_tip(previous_state_tip_hash)
            return

        self.blockchain.reconcile_pending_transactions(previous_head)

    def _cancel_stale_automine_if_needed(self) -> None:
        if (
            self.automine_task is None
            or self.automine_task.done()
            or self._current_automine_tip_hash is None
            or self.blockchain is None
            or self.blockchain.main_tip_hash == self._current_automine_tip_hash
        ):
            return

        request_pow_cancel()

    def _load_persisted_messages(self) -> None:
        if self.wallet is None:
            return

        self.message_history = load_messages(self.wallet.address)
        self.message_ids = {
            message["message_id"]
            for message in self.message_history
        }

    def _store_wallet_message(self, message_entry: dict) -> None:
        if self.wallet is None:
            return

        message_id = message_entry["message_id"]
        if message_id in self.message_ids:
            return

        self.message_history.append(message_entry)
        self.message_ids.add(message_id)
        save_messages(self.wallet.address, self.message_history)

    def _load_persisted_aliases(self) -> None:
        owner_key = self._alias_owner_key()
        if owner_key is None:
            return

        self.wallet_aliases = load_aliases(owner_key)

    def _save_persisted_aliases(self) -> None:
        owner_key = self._alias_owner_key()
        if owner_key is None:
            return

        save_aliases(owner_key, self.wallet_aliases)

    def _alias_owner_key(self) -> str | None:
        if self.wallet is None:
            return None
        return self.wallet.address

    def _print_network_notification(self, message: str, force: bool = False) -> None:
        if self.network_notifications_muted and not force:
            return
        print(message, flush=True)

    def _maybe_schedule_autosend(self) -> None:
        if (
            self.autosend_target is None
            or self.wallet is None
            or self.blockchain is None
        ):
            self._reset_autosend_balance_baseline()
            return

        current_balance = self.blockchain.get_available_balance(
            self.wallet.address,
            tip_hash=self._state_tip_hash(),
        )
        if current_balance < self.autosend_last_seen_balance:
            self.autosend_last_seen_balance = current_balance

        if current_balance <= self.autosend_last_seen_balance or current_balance <= Decimal("0.0"):
            return

        if self.autosend_task is not None and not self.autosend_task.done():
            return

        self.autosend_task = asyncio.create_task(self._autosend_available_balance())

    async def _autosend_available_balance(self) -> None:
        try:
            if (
                self.autosend_target is None
                or self.wallet is None
                or self.blockchain is None
            ):
                return

            balance = self.blockchain.get_available_balance(
                self.wallet.address,
                tip_hash=self._state_tip_hash(),
            )
            if balance <= Decimal("0.0"):
                return

            transaction = self.create_signed_transaction(
                receiver=self.autosend_target,
                amount=str(balance),
                fee="0",
            )
            await self.broadcast_transaction(transaction)
            print(
                "Autosend queued "
                f"{balance} to {self.format_wallet_reference(self.autosend_target)}."
            )
        except ValueError as error:
            print(f"Autosend failed: {error}")
        finally:
            self._reset_autosend_balance_baseline()
            self.autosend_task = None

    def _reset_autosend_balance_baseline(self) -> None:
        if self.wallet is None or self.blockchain is None:
            self.autosend_last_seen_balance = Decimal("0.0")
            return
        self.autosend_last_seen_balance = self.blockchain.get_available_balance(
            self.wallet.address,
            tip_hash=self._state_tip_hash(),
        )

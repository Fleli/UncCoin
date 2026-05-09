from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from core.block import Block, get_block_verification_error, proof_of_work
from core.contracts import compute_contract_address
from core.contracts import compute_contract_code_hash
from core.genesis import get_genesis_block_validation_error
from core.hashing import sha256_transaction_hash
from core.randomness import MAX_RANDOMNESS_REQUEST_ID_LENGTH
from core.randomness import MAX_REVEAL_SALT_LENGTH
from core.randomness import create_reveal_commitment_hash
from core.randomness import parse_randomness_seed
from core.transaction import TRANSACTION_KIND_AUTHORIZE
from core.transaction import TRANSACTION_KIND_COMMIT
from core.transaction import TRANSACTION_KIND_DEPLOY
from core.transaction import TRANSACTION_KIND_EXECUTE
from core.transaction import TRANSACTION_KIND_REVEAL
from core.transaction import TRANSACTION_KIND_TRANSFER
from core.transaction import Transaction
from core.uvm import UvmExecutionContext
from core.uvm import execute_uvm_program
from core.uvm import parse_uvm_program
from core.uvm_authorization import MAX_AUTHORIZATION_REQUEST_ID_LENGTH
from core.uvm_authorization import UvmAuthorizationScope
from core.utils.constants import GENESIS_PREVIOUS_HASH, MAX_TRANSACTIONS_PER_BLOCK
from core.utils.mining import (
    create_mining_reward_transaction,
    get_mining_reward_amount_validation_error,
    get_mining_reward_structure_error,
    is_mining_reward_transaction,
)
from wallet.wallet import Wallet


@dataclass
class ChainState:
    balances: dict[str, Decimal] = field(default_factory=dict)
    nonces: dict[str, int] = field(default_factory=dict)
    commitments: dict[str, dict[str, str]] = field(default_factory=dict)
    reveals: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)
    authorizations: list[dict] = field(default_factory=list)
    contracts: dict[str, dict] = field(default_factory=dict)
    contract_storage: dict[str, dict[str, int]] = field(default_factory=dict)
    uvm_receipts: dict[str, dict] = field(default_factory=dict)
    height: int = -1

    def copy(self) -> "ChainState":
        return ChainState(
            balances=self.balances.copy(),
            nonces=self.nonces.copy(),
            commitments={
                request_id: commitments_by_sender.copy()
                for request_id, commitments_by_sender in self.commitments.items()
            },
            reveals={
                request_id: {
                    sender: reveal.copy()
                    for sender, reveal in reveals_by_sender.items()
                }
                for request_id, reveals_by_sender in self.reveals.items()
            },
            authorizations=deepcopy(self.authorizations),
            contracts={
                contract_address: deepcopy(contract)
                for contract_address, contract in self.contracts.items()
            },
            contract_storage={
                contract_address: storage.copy()
                for contract_address, storage in self.contract_storage.items()
            },
            uvm_receipts={
                transaction_id: receipt.copy()
                for transaction_id, receipt in self.uvm_receipts.items()
            },
            height=self.height,
        )


@dataclass(frozen=True)
class BlockAcceptanceResult:
    status: str
    reason: str | None = None


@dataclass
class Blockchain:
    difficulty_bits: int
    hash_function: Callable[[Block], str]
    genesis_difficulty_bits: int | None = None
    difficulty_growth_factor: int = 10
    difficulty_growth_start_height: int = 100
    difficulty_growth_bits: int = 1
    difficulty_schedule_activation_height: int = 0
    blocks_by_hash: dict[str, Block] = field(default_factory=dict)
    children_by_hash: dict[str, list[str]] = field(default_factory=dict)
    block_states: dict[str, ChainState] = field(default_factory=dict)
    pending_transactions: list[Transaction] = field(default_factory=list)
    main_tip_hash: str | None = None

    @property
    def blocks(self) -> list[Block]:
        return self.get_chain()

    def get_difficulty_bits_for_height(self, block_height: int) -> int:
        if block_height < 0:
            raise ValueError("block_height must be non-negative.")
        if self.genesis_difficulty_bits is not None and self.genesis_difficulty_bits < 0:
            raise ValueError("genesis_difficulty_bits must be non-negative.")
        if self.difficulty_growth_factor < 2:
            raise ValueError("difficulty_growth_factor must be at least 2.")
        if self.difficulty_growth_start_height < 1:
            raise ValueError("difficulty_growth_start_height must be at least 1.")
        if self.difficulty_growth_bits < 1:
            raise ValueError("difficulty_growth_bits must be at least 1.")

        if block_height == 0:
            return (
                self.genesis_difficulty_bits
                if self.genesis_difficulty_bits is not None
                else self.difficulty_bits
            )

        if block_height < self.difficulty_schedule_activation_height:
            return self.difficulty_bits

        if block_height < self.difficulty_growth_start_height:
            return self.difficulty_bits

        growth_steps = 0
        threshold = self.difficulty_growth_start_height
        while block_height >= threshold:
            growth_steps += 1
            threshold *= self.difficulty_growth_factor

        return self.difficulty_bits + (growth_steps * self.difficulty_growth_bits)

    def get_next_block_difficulty_bits(self, tip_hash: str | None = None) -> int:
        return self.get_difficulty_bits_for_height(
            self._get_state_for_tip(tip_hash).height + 1
        )

    def get_chain(self, tip_hash: str | None = None) -> list[Block]:
        chain: list[Block] = []
        current_hash = self.main_tip_hash if tip_hash is None else tip_hash

        while current_hash is not None:
            block = self.blocks_by_hash.get(current_hash)
            if block is None:
                break

            chain.append(block)
            if block.previous_hash == GENESIS_PREVIOUS_HASH:
                break

            current_hash = block.previous_hash

        chain.reverse()
        return chain

    def get_balance(self, address: str, tip_hash: str | None = None) -> Decimal:
        return self._get_state_for_tip(tip_hash).balances.get(address, Decimal("0.0"))

    def get_available_balance(self, address: str, tip_hash: str | None = None) -> Decimal:
        state = self._get_state_for_tip(tip_hash).copy()

        for transaction in self.pending_transactions:
            if (
                self._apply_transaction_to_state_error(
                    transaction,
                    state,
                    execution_block_height=state.height + 1,
                )
                is not None
            ):
                return Decimal("0.0")

        return state.balances.get(address, Decimal("0.0"))

    def get_next_nonce(self, address: str, tip_hash: str | None = None) -> int:
        state = self._get_state_for_tip(tip_hash).copy()

        for transaction in self.pending_transactions:
            if (
                self._apply_transaction_to_state_error(
                    transaction,
                    state,
                    execution_block_height=state.height + 1,
                )
                is not None
            ):
                raise ValueError("Existing pending transactions are invalid.")

        return state.nonces.get(address, 0)

    def get_commitment(
        self,
        request_id: str,
        sender: str,
        tip_hash: str | None = None,
    ) -> str | None:
        return (
            self._get_state_for_tip(tip_hash)
            .commitments.get(request_id, {})
            .get(sender)
        )

    def get_commitments(
        self,
        request_id: str,
        tip_hash: str | None = None,
    ) -> dict[str, str]:
        return (
            self._get_state_for_tip(tip_hash)
            .commitments.get(request_id, {})
            .copy()
        )

    def get_reveal(
        self,
        request_id: str,
        sender: str,
        tip_hash: str | None = None,
    ) -> dict[str, str] | None:
        reveal = (
            self._get_state_for_tip(tip_hash)
            .reveals.get(request_id, {})
            .get(sender)
        )
        return None if reveal is None else reveal.copy()

    def get_reveals(
        self,
        request_id: str,
        tip_hash: str | None = None,
    ) -> dict[str, dict[str, str]]:
        return {
            sender: reveal.copy()
            for sender, reveal in (
                self._get_state_for_tip(tip_hash)
                .reveals.get(request_id, {})
                .items()
            )
        }

    def get_authorizations(
        self,
        *,
        contract_address: str | None = None,
        request_id: str | None = None,
        wallet: str | None = None,
        tip_hash: str | None = None,
    ) -> list[dict]:
        authorizations = self._get_state_for_tip(tip_hash).authorizations
        return [
            deepcopy(authorization)
            for authorization in authorizations
            if (
                contract_address is None
                or authorization.get("contract_address") == contract_address
            )
            and (
                request_id is None
                or authorization.get("request_id") == request_id
            )
            and (
                wallet is None
                or authorization.get("wallet") == wallet
            )
        ]

    def get_contract_storage(
        self,
        contract_address: str,
        tip_hash: str | None = None,
    ) -> dict[str, int]:
        return (
            self._get_state_for_tip(tip_hash)
            .contract_storage.get(contract_address, {})
            .copy()
        )

    def get_contract(
        self,
        contract_address: str,
        tip_hash: str | None = None,
    ) -> dict | None:
        contract = self._get_state_for_tip(tip_hash).contracts.get(contract_address)
        return None if contract is None else deepcopy(contract)

    def get_uvm_receipt(
        self,
        transaction_id: str,
        tip_hash: str | None = None,
    ) -> dict | None:
        receipt = self._get_state_for_tip(tip_hash).uvm_receipts.get(transaction_id)
        return None if receipt is None else receipt.copy()

    def add_transaction(self, transaction: Transaction, tip_hash: str | None = None) -> None:
        if is_mining_reward_transaction(transaction):
            raise ValueError("Mining reward transactions can only be created by the blockchain.")

        state = self._get_state_for_tip(tip_hash).copy()
        for index, pending_transaction in enumerate(self.pending_transactions):
            pending_error = self._apply_transaction_to_state_error(
                pending_transaction,
                state,
                execution_block_height=state.height + 1,
            )
            if pending_error is not None:
                raise ValueError(
                    f"Existing pending transaction {index} is invalid: "
                    f"{pending_error}"
                )

        transaction_error = self._apply_transaction_to_state_error(
            transaction,
            state,
            execution_block_height=state.height + 1,
        )
        if transaction_error is not None:
            raise ValueError(transaction_error)

        self.pending_transactions.append(transaction)

    def mine_pending_transactions(
        self,
        miner_address: str,
        description: str,
        progress_callback: Callable[[int], None] | None = None,
        tip_hash: str | None = None,
        reconcile_pending_transactions: bool = True,
        mining_backend: str | None = None,
    ) -> Block:
        base_tip_hash = self.main_tip_hash if tip_hash is None else tip_hash
        if base_tip_hash is None:
            raise ValueError("Genesis block must be created before mining.")

        base_state = self._get_state_for_tip(base_tip_hash)
        selected_transactions = self._select_transactions_for_block(base_tip_hash)
        total_fees = self._calculate_transaction_fees_for_block(
            selected_transactions,
            base_state,
        )
        reward_transaction = create_mining_reward_transaction(
            miner_address,
            total_fees=total_fees,
        )
        block_transactions = [reward_transaction, *selected_transactions]

        block = Block(
            block_id=base_state.height + 1,
            transactions=block_transactions,
            hash_function=self.hash_function,
            description=description,
            previous_hash=base_tip_hash,
        )
        proof_of_work(
            block,
            self.get_difficulty_bits_for_height(block.block_id),
            progress_callback=progress_callback,
            mining_backend=mining_backend,
        )

        add_result = self.add_block_result(
            block,
            reconcile_pending_transactions=reconcile_pending_transactions,
        )
        if add_result.status != "accepted":
            raise ValueError(
                "Mined block failed validation: "
                f"{add_result.reason or add_result.status}"
            )

        return block

    def add_block(
        self,
        block: Block,
        reconcile_pending_transactions: bool = True,
    ) -> bool:
        return (
            self.add_block_result(
                block,
                reconcile_pending_transactions=reconcile_pending_transactions,
            ).status
            == "accepted"
        )

    def add_block_with_status(
        self,
        block: Block,
        reconcile_pending_transactions: bool = True,
    ) -> str:
        return self.add_block_result(
            block,
            reconcile_pending_transactions=reconcile_pending_transactions,
        ).status

    def add_block_result(
        self,
        block: Block,
        reconcile_pending_transactions: bool = True,
    ) -> BlockAcceptanceResult:
        block_hash = block.block_hash
        if block_hash in self.blocks_by_hash:
            return BlockAcceptanceResult("duplicate", "block already exists")

        if (
            block.previous_hash != GENESIS_PREVIOUS_HASH
            and block.previous_hash not in self.block_states
        ):
            return BlockAcceptanceResult(
                "missing_parent",
                f"missing parent block {block.previous_hash[:12]}",
            )

        parent_state, parent_error = self._get_parent_state_for_block(block)
        if parent_state is None:
            return BlockAcceptanceResult("invalid", parent_error)

        child_state, child_error = self._build_child_state(block, parent_state)
        if child_state is None:
            return BlockAcceptanceResult("invalid", child_error)

        previous_head = self.main_tip_hash
        self.blocks_by_hash[block_hash] = block
        self.block_states[block_hash] = child_state
        self.children_by_hash.setdefault(block_hash, [])
        if block.previous_hash != GENESIS_PREVIOUS_HASH:
            self.children_by_hash.setdefault(block.previous_hash, []).append(block_hash)

        if self._should_update_main_tip(block_hash):
            self.main_tip_hash = block_hash

        if reconcile_pending_transactions:
            self._reconcile_pending_transactions(previous_head)
        return BlockAcceptanceResult("accepted")

    def verify_chain(self) -> bool:
        temp_states: dict[str, ChainState] = {}
        temp_children: dict[str, list[str]] = {
            block_hash: []
            for block_hash in self.blocks_by_hash
        }

        def compute_state(block_hash: str) -> ChainState | None:
            if block_hash in temp_states:
                return temp_states[block_hash]

            block = self.blocks_by_hash[block_hash]
            if block.previous_hash == GENESIS_PREVIOUS_HASH:
                parent_state, _ = self._get_parent_state_for_block(block, states=temp_states)
                if parent_state is None:
                    return None
            else:
                if block.previous_hash not in self.blocks_by_hash:
                    return None
                parent_state = compute_state(block.previous_hash)
                if parent_state is None:
                    return None

            child_state, _ = self._build_child_state(block, parent_state)
            if child_state is None:
                return None

            temp_states[block_hash] = child_state
            return child_state

        genesis_blocks = 0
        for block_hash, block in self.blocks_by_hash.items():
            if block.previous_hash == GENESIS_PREVIOUS_HASH:
                genesis_blocks += 1
            else:
                temp_children.setdefault(block.previous_hash, []).append(block_hash)

            if compute_state(block_hash) is None:
                return False

        if genesis_blocks > 1:
            return False

        previous_head = self.main_tip_hash
        self.block_states = temp_states
        self.children_by_hash = temp_children
        self.main_tip_hash = self._select_best_tip(temp_states, temp_children)
        self._reconcile_pending_transactions(previous_head)
        return True

    def _build_child_state(
        self,
        block: Block,
        parent_state: ChainState,
    ) -> tuple[ChainState | None, str | None]:
        if len(block.transactions) > MAX_TRANSACTIONS_PER_BLOCK:
            return (
                None,
                f"block has {len(block.transactions)} transactions, "
                f"max is {MAX_TRANSACTIONS_PER_BLOCK}",
            )

        mining_reward_error = get_mining_reward_structure_error(block)
        if mining_reward_error is not None:
            return None, mining_reward_error

        block_verification_error = get_block_verification_error(
            block,
            self.get_difficulty_bits_for_height(block.block_id),
        )
        if block_verification_error is not None:
            return None, block_verification_error

        state = parent_state.copy()
        state.height = block.block_id
        fee_collector: list[Decimal] = []

        for index, transaction in enumerate(block.transactions):
            transaction_error = self._apply_transaction_to_state_error(
                transaction,
                state,
                execution_block_height=block.block_id,
                fee_collector=fee_collector,
            )
            if transaction_error is not None:
                transaction_id = sha256_transaction_hash(transaction)[:12]
                return (
                    None,
                    f"transaction {index} ({transaction_id}) is invalid: "
                    f"{transaction_error}",
                )

        reward_amount_error = get_mining_reward_amount_validation_error(
            block,
            sum(fee_collector, start=Decimal("0.0")),
        )
        if reward_amount_error is not None:
            return None, reward_amount_error

        return state, None

    def _get_parent_state_for_block(
        self,
        block: Block,
        states: dict[str, ChainState] | None = None,
    ) -> tuple[ChainState | None, str | None]:
        block_states = self.block_states if states is None else states

        if block.previous_hash == GENESIS_PREVIOUS_HASH:
            genesis_error = get_genesis_block_validation_error(block)
            if genesis_error is not None:
                return None, genesis_error
            if any(
                existing_block.previous_hash == GENESIS_PREVIOUS_HASH
                and existing_hash != block.block_hash
                for existing_hash, existing_block in self.blocks_by_hash.items()
            ):
                return None, "a different genesis block already exists"
            return ChainState(), None

        parent_state = block_states.get(block.previous_hash)
        if parent_state is None:
            return None, f"missing parent state for block {block.previous_hash[:12]}"

        if block.block_id != parent_state.height + 1:
            return (
                None,
                f"block_id {block.block_id} does not extend parent height "
                f"{parent_state.height}",
            )

        return parent_state, None

    def _get_canonical_state(self) -> ChainState:
        if self.main_tip_hash is None:
            return ChainState()
        return self.block_states[self.main_tip_hash]

    def _get_state_for_tip(self, tip_hash: str | None = None) -> ChainState:
        resolved_tip_hash = self.main_tip_hash if tip_hash is None else tip_hash
        if resolved_tip_hash is None:
            return ChainState()

        state = self.block_states.get(resolved_tip_hash)
        if state is None:
            raise ValueError(f"Unknown tip hash {resolved_tip_hash[:12]}")
        return state

    def is_ancestor(self, ancestor_hash: str, descendant_hash: str | None) -> bool:
        if (
            not ancestor_hash
            or descendant_hash is None
            or ancestor_hash not in self.block_states
            or descendant_hash not in self.block_states
        ):
            return False

        current_hash = descendant_hash
        while True:
            if current_hash == ancestor_hash:
                return True

            current_block = self.blocks_by_hash.get(current_hash)
            if current_block is None or current_block.previous_hash == GENESIS_PREVIOUS_HASH:
                return False

            current_hash = current_block.previous_hash

    def _should_update_main_tip(self, block_hash: str) -> bool:
        if self.main_tip_hash is None:
            return True

        new_height = self.block_states[block_hash].height
        current_height = self.block_states[self.main_tip_hash].height
        return new_height > current_height

    def _select_best_tip(
        self,
        states: dict[str, ChainState],
        children: dict[str, list[str]],
    ) -> str | None:
        if not states:
            return None

        tip_hashes = [
            block_hash
            for block_hash in states
            if not children.get(block_hash)
        ]

        if not tip_hashes:
            return None

        max_height = max(states[block_hash].height for block_hash in tip_hashes)
        candidates = [
            block_hash
            for block_hash in tip_hashes
            if states[block_hash].height == max_height
        ]

        if self.main_tip_hash in candidates:
            return self.main_tip_hash

        return sorted(candidates)[0]

    def _select_transactions_for_block(self, tip_hash: str | None = None) -> list[Transaction]:
        remaining_transactions = sorted(
            self.pending_transactions,
            key=lambda transaction: transaction.fee,
            reverse=True,
        )
        state = self._get_state_for_tip(tip_hash).copy()
        selected_transactions: list[Transaction] = []

        while remaining_transactions and len(selected_transactions) < MAX_TRANSACTIONS_PER_BLOCK - 1:
            progress = False
            next_round: list[Transaction] = []

            for transaction in remaining_transactions:
                if len(selected_transactions) >= MAX_TRANSACTIONS_PER_BLOCK - 1:
                    next_round.append(transaction)
                    continue

                test_state = state.copy()
                if (
                    self._apply_transaction_to_state_error(
                        transaction,
                        test_state,
                        execution_block_height=state.height + 1,
                    )
                    is None
                ):
                    state = test_state
                    selected_transactions.append(transaction)
                    progress = True
                else:
                    next_round.append(transaction)

            if not progress:
                break

            remaining_transactions = next_round

        return selected_transactions

    def _calculate_transaction_fees_for_block(
        self,
        transactions: list[Transaction],
        base_state: ChainState,
    ) -> Decimal:
        state = base_state.copy()
        fee_collector: list[Decimal] = []
        execution_block_height = base_state.height + 1

        for transaction in transactions:
            transaction_error = self._apply_transaction_to_state_error(
                transaction,
                state,
                execution_block_height=execution_block_height,
                fee_collector=fee_collector,
            )
            if transaction_error is not None:
                raise ValueError(
                    "Selected transaction became invalid while calculating fees: "
                    f"{transaction_error}"
                )

        return sum(fee_collector, start=Decimal("0.0"))

    def reconcile_pending_transactions(
        self,
        previous_head: str | None,
        current_head: str | None = None,
    ) -> None:
        self._reconcile_pending_transactions(previous_head, current_head)

    def _reconcile_pending_transactions(
        self,
        previous_head: str | None,
        current_head: str | None = None,
    ) -> None:
        resolved_current_head = self.main_tip_hash if current_head is None else current_head
        common_ancestor_hash = self._find_common_ancestor_hash(
            previous_head,
            resolved_current_head,
        )
        previous_transactions = self._collect_branch_transactions(
            previous_head,
            stop_hash=common_ancestor_hash,
        )
        current_transactions = self._collect_branch_transactions(
            resolved_current_head,
            stop_hash=common_ancestor_hash,
        )
        current_transaction_ids = {
            sha256_transaction_hash(transaction)
            for transaction in current_transactions
        }

        resurrected_transactions = [
            transaction
            for transaction in previous_transactions
            if not is_mining_reward_transaction(transaction)
            and sha256_transaction_hash(transaction) not in current_transaction_ids
        ]

        candidate_transactions = [*resurrected_transactions, *self.pending_transactions]
        state = self._get_canonical_state().copy()
        seen_transaction_ids: set[str] = set()
        valid_pending_transactions: list[Transaction] = []

        for transaction in candidate_transactions:
            transaction_id = sha256_transaction_hash(transaction)
            if transaction_id in seen_transaction_ids or transaction_id in current_transaction_ids:
                continue

            test_state = state.copy()
            if (
                self._apply_transaction_to_state_error(
                    transaction,
                    test_state,
                    execution_block_height=state.height + 1,
                )
                is None
            ):
                state = test_state
                valid_pending_transactions.append(transaction)
                seen_transaction_ids.add(transaction_id)

        self.pending_transactions = valid_pending_transactions

    def _find_common_ancestor_hash(
        self,
        left_head: str | None,
        right_head: str | None,
    ) -> str | None:
        if left_head is None or right_head is None:
            return None
        if left_head not in self.block_states or right_head not in self.block_states:
            return None

        left_hash = left_head
        right_hash = right_head
        left_height = self.block_states[left_hash].height
        right_height = self.block_states[right_hash].height

        while left_height > right_height:
            left_hash = self._parent_hash(left_hash)
            if left_hash is None:
                return None
            left_height -= 1

        while right_height > left_height:
            right_hash = self._parent_hash(right_hash)
            if right_hash is None:
                return None
            right_height -= 1

        while left_hash != right_hash:
            left_hash = self._parent_hash(left_hash)
            right_hash = self._parent_hash(right_hash)
            if left_hash is None or right_hash is None:
                return None

        return left_hash

    def _collect_branch_transactions(
        self,
        head_hash: str | None,
        *,
        stop_hash: str | None,
    ) -> list[Transaction]:
        if head_hash is None or head_hash == stop_hash:
            return []

        branch_blocks: list[Block] = []
        current_hash = head_hash
        while current_hash is not None and current_hash != stop_hash:
            block = self.blocks_by_hash[current_hash]
            branch_blocks.append(block)
            current_hash = self._parent_hash(current_hash)

        branch_blocks.reverse()
        transactions: list[Transaction] = []
        for block in branch_blocks:
            transactions.extend(block.transactions)
        return transactions

    def _parent_hash(self, block_hash: str) -> str | None:
        block = self.blocks_by_hash[block_hash]
        if block.previous_hash == GENESIS_PREVIOUS_HASH:
            return None
        return block.previous_hash

    def _collect_transactions(self, tip_hash: str | None) -> list[Transaction]:
        if tip_hash is None:
            return []

        transactions: list[Transaction] = []
        for block in self.get_chain(tip_hash):
            transactions.extend(block.transactions)
        return transactions

    def _apply_transaction_to_state_error(
        self,
        transaction: Transaction,
        state: ChainState,
        execution_block_height: int | None = None,
        fee_collector: list[Decimal] | None = None,
    ) -> str | None:
        def collect_fee(fee_paid: Decimal) -> None:
            if fee_collector is not None and not is_mining_reward_transaction(transaction):
                fee_collector.append(fee_paid)

        authenticity_error = self._validate_transaction_authenticity_error(transaction)
        if authenticity_error is not None:
            return authenticity_error

        if transaction.fee < Decimal("0.0"):
            return f"transaction fee must be non-negative, got {transaction.fee}"

        if is_mining_reward_transaction(transaction):
            if not transaction.receiver:
                return "mining reward transaction receiver is empty"
            if transaction.amount <= Decimal("0.0"):
                return f"mining reward amount must be positive, got {transaction.amount}"
            state.balances[transaction.receiver] = (
                state.balances.get(transaction.receiver, Decimal("0.0")) + transaction.amount
            )
            return None

        if not transaction.sender:
            return "transaction sender is empty"

        expected_nonce = state.nonces.get(transaction.sender, 0)
        if transaction.nonce != expected_nonce:
            return (
                f"transaction nonce {transaction.nonce} does not match "
                f"expected nonce {expected_nonce}"
            )

        sender_balance = state.balances.get(transaction.sender, Decimal("0.0"))

        if transaction.kind == TRANSACTION_KIND_TRANSFER:
            if not transaction.receiver:
                return "transfer transaction receiver is empty"
            if transaction.amount <= Decimal("0.0"):
                return f"transfer transaction amount must be positive, got {transaction.amount}"

            total_cost = transaction.amount + transaction.fee
            if sender_balance < total_cost:
                return (
                    f"sender balance {sender_balance} is below total transaction "
                    f"cost {total_cost}"
                )

            state.nonces[transaction.sender] = expected_nonce + 1
            state.balances[transaction.sender] = sender_balance - total_cost
            state.balances[transaction.receiver] = (
                state.balances.get(transaction.receiver, Decimal("0.0")) + transaction.amount
            )
            collect_fee(transaction.fee)
            return None

        if transaction.kind == TRANSACTION_KIND_COMMIT:
            commit_error = self._validate_commit_transaction_error(transaction, state)
            if commit_error is not None:
                return commit_error

            total_cost = transaction.fee
            if sender_balance < total_cost:
                return (
                    f"sender balance {sender_balance} is below total transaction "
                    f"cost {total_cost}"
                )

            request_id = transaction.payload["request_id"].strip()
            commitment_hash = transaction.payload["commitment_hash"].strip().lower()
            state.nonces[transaction.sender] = expected_nonce + 1
            state.balances[transaction.sender] = sender_balance - total_cost
            state.commitments.setdefault(request_id, {})[transaction.sender] = commitment_hash
            collect_fee(transaction.fee)
            return None

        if transaction.kind == TRANSACTION_KIND_REVEAL:
            reveal_error = self._validate_reveal_transaction_error(transaction, state)
            if reveal_error is not None:
                return reveal_error

            total_cost = transaction.fee
            if sender_balance < total_cost:
                return (
                    f"sender balance {sender_balance} is below total transaction "
                    f"cost {total_cost}"
                )

            request_id = transaction.payload["request_id"].strip()
            seed_value = parse_randomness_seed(transaction.payload["seed"])
            salt = transaction.payload.get("salt", "").strip()
            commitment_hash = state.commitments[request_id][transaction.sender]
            state.nonces[transaction.sender] = expected_nonce + 1
            state.balances[transaction.sender] = sender_balance - total_cost
            state.reveals.setdefault(request_id, {})[transaction.sender] = {
                "seed": str(seed_value),
                "salt": salt,
                "commitment_hash": commitment_hash,
            }
            collect_fee(transaction.fee)
            return None

        if transaction.kind == TRANSACTION_KIND_AUTHORIZE:
            authorize_error = self._validate_authorize_transaction_error(transaction, state)
            if authorize_error is not None:
                return authorize_error

            total_cost = transaction.fee
            if sender_balance < total_cost:
                return (
                    f"sender balance {sender_balance} is below total transaction "
                    f"cost {total_cost}"
                )

            scope = UvmAuthorizationScope.from_dict(
                transaction.payload.get("scope", {}),
            ).to_dict()
            state.nonces[transaction.sender] = expected_nonce + 1
            state.balances[transaction.sender] = sender_balance - total_cost
            state.authorizations.append(
                {
                    "wallet": transaction.sender,
                    "contract_address": transaction.payload["contract_address"].strip(),
                    "code_hash": transaction.payload["code_hash"].strip().lower(),
                    "request_id": transaction.payload["request_id"].strip(),
                    "scope": scope,
                    "authorized_at_height": execution_block_height,
                }
            )
            collect_fee(transaction.fee)
            return None

        if transaction.kind == TRANSACTION_KIND_DEPLOY:
            deploy_error = self._validate_deploy_transaction_error(transaction, state)
            if deploy_error is not None:
                return deploy_error

            total_cost = transaction.fee
            if sender_balance < total_cost:
                return (
                    f"sender balance {sender_balance} is below total transaction "
                    f"cost {total_cost}"
                )

            contract_address = transaction.payload["contract_address"].strip()
            state.nonces[transaction.sender] = expected_nonce + 1
            state.balances[transaction.sender] = sender_balance - total_cost
            state.contracts[contract_address] = {
                "deployer": transaction.sender,
                "code_hash": transaction.payload["code_hash"],
                "program": deepcopy(transaction.payload["program"]),
                "metadata": deepcopy(transaction.payload.get("metadata", {})),
            }
            state.contract_storage.setdefault(contract_address, {})
            collect_fee(transaction.fee)
            return None

        if transaction.kind == TRANSACTION_KIND_EXECUTE:
            return self._apply_execute_transaction_to_state_error(
                transaction,
                state,
                sender_balance,
                expected_nonce,
                execution_block_height,
                fee_collector,
            )

        return f"unsupported transaction kind {transaction.kind}"

    def _apply_execute_transaction_to_state_error(
        self,
        transaction: Transaction,
        state: ChainState,
        sender_balance: Decimal,
        expected_nonce: int,
        execution_block_height: int | None,
        fee_collector: list[Decimal] | None,
    ) -> str | None:
        if not transaction.receiver:
            return "execute transaction contract address is empty"
        if transaction.amount < Decimal("0.0"):
            return f"execute transaction value must be non-negative, got {transaction.amount}"

        contract_address = str(
            transaction.payload.get("contract_address", transaction.receiver)
        ).strip()
        if not contract_address:
            return "execute transaction contract_address must be non-empty"
        if contract_address != transaction.receiver:
            return "execute transaction receiver must match contract_address"

        raw_gas_limit = transaction.payload.get("gas_limit")
        try:
            gas_limit = int(raw_gas_limit)
        except (TypeError, ValueError) as error:
            return f"execute transaction gas_limit must be an integer: {error}"
        if gas_limit < 0:
            return "execute transaction gas_limit must be non-negative"
        try:
            gas_price = Decimal(str(transaction.payload.get("gas_price", "0.0")))
        except InvalidOperation as error:
            return f"execute transaction gas_price must be a decimal: {error}"
        if gas_price < Decimal("0.0"):
            return "execute transaction gas_price must be non-negative"

        maximum_fuel_fee = Decimal(gas_limit) * gas_price
        if gas_price > Decimal("0.0") and transaction.fee < maximum_fuel_fee:
            return (
                f"execute transaction fee {transaction.fee} is below maximum "
                f"fuel cost gas_limit {gas_limit} * gas_price {gas_price} "
                f"= {maximum_fuel_fee}"
            )

        total_cost = transaction.amount + transaction.fee
        if sender_balance < total_cost:
            return (
                f"sender balance {sender_balance} is below total transaction "
                f"cost {total_cost}"
            )

        execution_balances = state.balances.copy()
        execution_balances[transaction.sender] = sender_balance - total_cost
        if transaction.amount > Decimal("0.0"):
            execution_balances[contract_address] = (
                execution_balances.get(contract_address, Decimal("0.0"))
                + transaction.amount
            )

        program = transaction.payload.get("input")
        input_data: dict[str, Any] = {}
        metadata = {}
        contract = state.contracts.get(contract_address)
        if contract is not None:
            program = contract["program"]
            raw_input_data = transaction.payload.get("input")
            input_data = raw_input_data if isinstance(raw_input_data, dict) else {}
            metadata = contract.get("metadata", {})
            code_hash = str(
                contract.get(
                    "code_hash",
                    compute_contract_code_hash(
                        contract["program"],
                        metadata,
                    ),
                )
            )
        elif program is None:
            return f"execute transaction references undeployed contract {contract_address}"
        else:
            code_hash = compute_contract_code_hash(program, {})

        raw_authorizations = transaction.payload.get("authorizations", [])
        if raw_authorizations:
            return (
                "execute transaction inline authorizations are not supported; "
                "submit authorize transactions before execution"
            )
        authorization_index = self._build_chain_authorization_index(
            state,
            contract_address=contract_address,
            code_hash=code_hash,
            block_height=execution_block_height,
        )

        execution_result = execute_uvm_program(
            program,
            UvmExecutionContext(
                tx_sender=transaction.sender,
                contract_address=contract_address,
                gas_limit=gas_limit,
                storage=state.contract_storage.get(contract_address, {}),
                balances=execution_balances,
                commitments=state.commitments,
                reveals=state.reveals,
                authorization_index=authorization_index,
                metadata=metadata,
                input_data=input_data,
                block_height=execution_block_height or 0,
            ),
        )

        fee_paid = (
            Decimal(execution_result.gas_used) * gas_price
            if gas_price > Decimal("0.0")
            else transaction.fee
        )

        state.nonces[transaction.sender] = expected_nonce + 1
        state.balances[transaction.sender] = sender_balance - fee_paid
        if execution_result.success:
            state.balances[transaction.sender] -= transaction.amount
            if transaction.amount > Decimal("0.0"):
                state.balances[contract_address] = (
                    state.balances.get(contract_address, Decimal("0.0"))
                    + transaction.amount
                )
            for address, balance_change in execution_result.balance_changes.items():
                state.balances[address] = (
                    state.balances.get(address, Decimal("0.0")) + balance_change
                )
            state.contract_storage[contract_address] = execution_result.storage
        receipt = execution_result.to_dict()
        receipt["fee_escrowed"] = str(transaction.fee)
        receipt["fee_paid"] = str(fee_paid)
        receipt["fee_refunded"] = str(transaction.fee - fee_paid)
        state.uvm_receipts[sha256_transaction_hash(transaction)] = receipt
        if fee_collector is not None:
            fee_collector.append(fee_paid)
        return None

    @staticmethod
    def _validate_deploy_transaction_error(
        transaction: Transaction,
        state: ChainState,
    ) -> str | None:
        if not transaction.receiver:
            return "deploy transaction contract address is empty"
        if transaction.amount != Decimal("0.0"):
            return f"deploy transaction amount must be 0.0, got {transaction.amount}"

        raw_contract_address = transaction.payload.get("contract_address")
        if not isinstance(raw_contract_address, str) or not raw_contract_address.strip():
            return "deploy transaction contract_address must be a non-empty string"
        contract_address = raw_contract_address.strip()
        if contract_address != transaction.receiver:
            return "deploy transaction receiver must match contract_address"
        if contract_address in state.contracts:
            return f"contract {contract_address} is already deployed"

        if "program" not in transaction.payload:
            return "deploy transaction program is required"
        try:
            parse_uvm_program(transaction.payload["program"])
        except ValueError as error:
            return f"deploy transaction program is invalid: {error}"

        metadata = transaction.payload.get("metadata", {})
        if not isinstance(metadata, dict):
            return "deploy transaction metadata must be an object"

        expected_code_hash = compute_contract_code_hash(
            transaction.payload["program"],
            metadata,
        )
        code_hash = str(transaction.payload.get("code_hash", "")).strip().lower()
        if code_hash != expected_code_hash:
            return "deploy transaction code_hash does not match program and metadata"

        expected_contract_address = compute_contract_address(
            transaction.sender,
            transaction.nonce,
            expected_code_hash,
        )
        if contract_address != expected_contract_address:
            return (
                "deploy transaction contract_address must be deterministic address "
                "derived from sender, nonce, and code_hash"
            )

        request_ids = metadata.get("request_ids", [])
        if request_ids is None:
            return None
        if not isinstance(request_ids, list):
            return "deploy transaction metadata.request_ids must be a list"
        for index, request_id in enumerate(request_ids):
            if not isinstance(request_id, str) or not request_id.strip():
                return (
                    "deploy transaction metadata.request_ids "
                    f"item {index} must be a non-empty string"
                )
            if len(request_id.strip()) > MAX_RANDOMNESS_REQUEST_ID_LENGTH:
                return (
                    "deploy transaction metadata.request_ids "
                    f"item {index} must be at most "
                    f"{MAX_RANDOMNESS_REQUEST_ID_LENGTH} characters"
                )

        return None

    @staticmethod
    def _validate_authorize_transaction_error(
        transaction: Transaction,
        state: ChainState,
    ) -> str | None:
        if not transaction.receiver:
            return "authorize transaction contract address is empty"
        if transaction.amount != Decimal("0.0"):
            return f"authorize transaction amount must be 0.0, got {transaction.amount}"

        raw_contract_address = transaction.payload.get("contract_address")
        if not isinstance(raw_contract_address, str) or not raw_contract_address.strip():
            return "authorize transaction contract_address must be a non-empty string"
        contract_address = raw_contract_address.strip()
        if contract_address != transaction.receiver:
            return "authorize transaction receiver must match contract_address"

        raw_code_hash = transaction.payload.get("code_hash")
        if not isinstance(raw_code_hash, str) or not _is_hex_hash(raw_code_hash.strip()):
            return "authorize transaction code_hash must be a 64-character hex string"
        code_hash = raw_code_hash.strip().lower()

        contract = state.contracts.get(contract_address)
        if contract is not None:
            expected_code_hash = str(
                contract.get(
                    "code_hash",
                    compute_contract_code_hash(
                        contract.get("program", []),
                        contract.get("metadata", {}),
                    ),
                )
            ).strip().lower()
            if code_hash != expected_code_hash:
                return "authorize transaction code_hash does not match deployed contract"

        raw_request_id = transaction.payload.get("request_id")
        if not isinstance(raw_request_id, str) or not raw_request_id.strip():
            return "authorize transaction request_id must be a non-empty string"
        if len(raw_request_id.strip()) > MAX_AUTHORIZATION_REQUEST_ID_LENGTH:
            return (
                "authorize transaction request_id must be at most "
                f"{MAX_AUTHORIZATION_REQUEST_ID_LENGTH} characters"
            )

        try:
            UvmAuthorizationScope.from_dict(transaction.payload.get("scope", {}))
        except ValueError as error:
            return f"authorize transaction scope is invalid: {error}"

        return None

    @staticmethod
    def _build_chain_authorization_index(
        state: ChainState,
        *,
        contract_address: str,
        code_hash: str,
        block_height: int | None,
    ) -> dict[str, dict[str, dict]]:
        authorization_index: dict[str, dict[str, dict]] = {}
        for authorization in state.authorizations:
            if authorization.get("contract_address") != contract_address:
                continue
            if str(authorization.get("code_hash", "")).strip().lower() != code_hash:
                continue

            try:
                scope = UvmAuthorizationScope.from_dict(
                    authorization.get("scope", {}),
                )
            except ValueError:
                continue
            if scope.validation_error(block_height) is not None:
                continue

            wallet = str(authorization.get("wallet", "")).strip()
            request_id = str(authorization.get("request_id", "")).strip()
            if not wallet or not request_id:
                continue
            authorization_index.setdefault(wallet, {})[request_id] = scope.to_dict()

        return {
            wallet: {
                request_id: authorization_index[wallet][request_id]
                for request_id in sorted(authorization_index[wallet])
            }
            for wallet in sorted(authorization_index)
        }

    @staticmethod
    def _validate_commit_transaction_error(
        transaction: Transaction,
        state: ChainState,
    ) -> str | None:
        if transaction.receiver:
            return "commit transaction receiver must be empty"
        if transaction.amount != Decimal("0.0"):
            return f"commit transaction amount must be 0.0, got {transaction.amount}"

        raw_request_id = transaction.payload.get("request_id")
        raw_commitment_hash = transaction.payload.get("commitment_hash")
        if not isinstance(raw_request_id, str) or not raw_request_id.strip():
            return "commit transaction request_id must be a non-empty string"
        if len(raw_request_id.strip()) > MAX_RANDOMNESS_REQUEST_ID_LENGTH:
            return (
                "commit transaction request_id must be at most "
                f"{MAX_RANDOMNESS_REQUEST_ID_LENGTH} characters"
            )
        if not isinstance(raw_commitment_hash, str) or not raw_commitment_hash.strip():
            return "commit transaction commitment_hash must be a non-empty string"

        commitment_hash = raw_commitment_hash.strip()
        if len(commitment_hash) != 64 or any(
            character not in "0123456789abcdefABCDEF"
            for character in commitment_hash
        ):
            return "commit transaction commitment_hash must be a 64-character hex string"

        request_id = raw_request_id.strip()
        if transaction.sender in state.commitments.get(request_id, {}):
            return (
                "commitment already exists for sender "
                f"{transaction.sender} and request_id {request_id}"
            )

        return None

    @staticmethod
    def _validate_reveal_transaction_error(
        transaction: Transaction,
        state: ChainState,
    ) -> str | None:
        if transaction.receiver:
            return "reveal transaction receiver must be empty"
        if transaction.amount != Decimal("0.0"):
            return f"reveal transaction amount must be 0.0, got {transaction.amount}"

        raw_request_id = transaction.payload.get("request_id")
        if not isinstance(raw_request_id, str) or not raw_request_id.strip():
            return "reveal transaction request_id must be a non-empty string"
        request_id = raw_request_id.strip()
        if len(request_id) > MAX_RANDOMNESS_REQUEST_ID_LENGTH:
            return (
                "reveal transaction request_id must be at most "
                f"{MAX_RANDOMNESS_REQUEST_ID_LENGTH} characters"
            )

        if "seed" not in transaction.payload:
            return "reveal transaction seed is required"
        try:
            seed_value = parse_randomness_seed(transaction.payload["seed"])
        except ValueError as error:
            return f"reveal transaction seed is invalid: {error}"

        raw_salt = transaction.payload.get("salt", "")
        if not isinstance(raw_salt, str):
            return "reveal transaction salt must be a string"
        salt = raw_salt.strip()
        if len(salt) > MAX_REVEAL_SALT_LENGTH:
            return f"reveal transaction salt must be at most {MAX_REVEAL_SALT_LENGTH} characters"

        commitment_hash = state.commitments.get(request_id, {}).get(transaction.sender)
        if commitment_hash is None:
            return (
                "reveal transaction has no prior commitment for sender "
                f"{transaction.sender} and request_id {request_id}"
            )
        if transaction.sender in state.reveals.get(request_id, {}):
            return (
                "reveal already exists for sender "
                f"{transaction.sender} and request_id {request_id}"
            )

        expected_commitment_hash = create_reveal_commitment_hash(
            transaction.sender,
            request_id,
            seed_value,
            salt,
        )
        if expected_commitment_hash != commitment_hash:
            return "reveal transaction seed does not match prior commitment"

        return None

    def _validate_transaction_authenticity_error(
        self,
        transaction: Transaction,
    ) -> str | None:
        if is_mining_reward_transaction(transaction):
            if transaction.sender_public_key is not None or transaction.signature is not None:
                return "mining reward transaction must not include signature data"
            return None

        if transaction.sender_public_key is None or transaction.signature is None:
            return "transaction is missing sender public key or signature"

        sender_address = Wallet.address_from_public_key(transaction.sender_public_key)
        if transaction.sender != sender_address:
            return "transaction sender does not match sender public key"

        signature_is_valid = Wallet.verify_signature_with_public_key(
            message=transaction.signing_payload(),
            signature=transaction.signature,
            public_key=transaction.sender_public_key,
        )
        if not signature_is_valid:
            return "transaction signature verification failed"
        return None


def _is_hex_hash(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True

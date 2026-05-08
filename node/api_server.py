import asyncio
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, TYPE_CHECKING

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from core.block import Block
from core.hashing import sha256_transaction_hash
from core.transaction import Transaction

if TYPE_CHECKING:
    from core.blockchain import Blockchain, ChainState
    from node.node import Node


API_PREFIX = "/api/v1"
PEER_CONNECT_TIMEOUT_SECONDS = 3.0


class PeerRequest(BaseModel):
    peer: str


class SyncRequest(BaseModel):
    fast: bool = True


class TransactionRequest(BaseModel):
    receiver: str
    amount: str
    fee: str = "0"


class MineRequest(BaseModel):
    description: str | None = None


class MessageRequest(BaseModel):
    receiver: str
    content: str


class AliasRequest(BaseModel):
    wallet: str
    alias: str


class AutosendRequest(BaseModel):
    target: str | None = None


class CommitmentRequest(BaseModel):
    request_id: str
    commitment_hash: str
    fee: str = "0"


class RevealRequest(BaseModel):
    request_id: str
    seed: str
    fee: str = "0"
    salt: str = ""


class DeployRequest(BaseModel):
    fee: str = "0"
    source: str | None = None
    program: Any | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecuteRequest(BaseModel):
    contract_address: str
    gas_limit: str = "1000"
    gas_price: str = "0"
    value: str = "0"
    fee: str = "0"
    input: Any | None = None


class AuthorizationRequest(BaseModel):
    contract_address: str
    request_id: str
    fee: str = "0"
    valid_for_blocks: str | None = None


def create_api_app(node: "Node") -> FastAPI:
    app = FastAPI(
        title="UncCoin Node API",
        version="1.0.0",
        description="Read-only HTTP API for local UncCoin node state.",
    )

    @app.get("/")
    def root() -> dict[str, Any]:
        return {
            "name": "UncCoin Node API",
            "version": "1.0.0",
            "api_prefix": API_PREFIX,
            "openapi": "/openapi.json",
            "docs": "/docs",
        }

    @app.get(f"{API_PREFIX}/health")
    def health() -> dict[str, Any]:
        blockchain = _require_blockchain(node)
        return {
            "status": "ok",
            "node": {
                "host": node.host,
                "port": node.port,
                "private_automine": bool(node.private_automine),
            },
            "wallet": _wallet_payload(node),
            "chain": _chain_head_payload(node, blockchain),
            "peers": {
                "connected": len(node.list_peers()),
                "known": len(node.list_known_peers()),
            },
            "sync": _sync_status_payload(node),
        }

    @app.get(f"{API_PREFIX}/node")
    def node_info() -> dict[str, Any]:
        return {
            "host": node.host,
            "port": node.port,
            "private_automine": bool(node.private_automine),
            "wallet": _wallet_payload(node),
            "peers": {
                "connected": node.list_peers(),
                "known": node.list_known_peers(),
            },
            "autosend": {
                "target": node.autosend_target,
                "enabled": node.autosend_target is not None,
            },
            "sync": _sync_status_payload(node),
        }

    @app.get(f"{API_PREFIX}/peers")
    def peers() -> dict[str, Any]:
        return {
            "connected": node.list_peers(),
            "known": node.list_known_peers(),
        }

    @app.get(f"{API_PREFIX}/sync/status")
    def sync_status() -> dict[str, Any]:
        return _sync_status_payload(node)

    @app.get(f"{API_PREFIX}/chain/head")
    def chain_head() -> dict[str, Any]:
        blockchain = _require_blockchain(node)
        return _chain_head_payload(node, blockchain)

    @app.get(f"{API_PREFIX}/chain/blocks")
    def chain_blocks(
        from_height: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=500),
    ) -> dict[str, Any]:
        chain = _current_chain(node)
        selected_blocks = [
            block
            for block in chain
            if block.block_id >= from_height
        ][:limit]
        next_from_height = None
        if selected_blocks and selected_blocks[-1].block_id < chain[-1].block_id:
            next_from_height = selected_blocks[-1].block_id + 1

        return {
            "from_height": from_height,
            "limit": limit,
            "count": len(selected_blocks),
            "next_from_height": next_from_height,
            "tip_hash": _state_tip_hash(node),
            "height": chain[-1].block_id if chain else -1,
            "blocks": [_block_payload(block) for block in selected_blocks],
        }

    @app.get(f"{API_PREFIX}/chain/block/{{block_reference}}")
    def chain_block(block_reference: str) -> dict[str, Any]:
        block = _find_current_chain_block(node, block_reference)
        return _block_payload(block)

    @app.get(f"{API_PREFIX}/balances")
    def balances() -> dict[str, Any]:
        state = _current_state(node)
        return {
            "tip_hash": _state_tip_hash(node),
            "height": state.height,
            "balances": [
                _balance_payload(node, address, balance)
                for address, balance in sorted(state.balances.items())
            ],
        }

    @app.get(f"{API_PREFIX}/balances/{{address}}")
    def balance(address: str) -> dict[str, Any]:
        blockchain = _require_blockchain(node)
        balance_value = blockchain.get_balance(address, tip_hash=_state_tip_hash(node))
        return {
            "tip_hash": _state_tip_hash(node),
            "height": _current_state(node).height,
            **_balance_payload(node, address, balance_value),
        }

    @app.get(f"{API_PREFIX}/transactions/pending")
    def pending_transactions() -> dict[str, Any]:
        blockchain = _require_blockchain(node)
        return {
            "tip_hash": _state_tip_hash(node),
            "count": len(blockchain.pending_transactions),
            "transactions": [
                _transaction_payload(transaction)
                for transaction in blockchain.pending_transactions
            ],
        }

    @app.get(f"{API_PREFIX}/messages")
    def messages() -> dict[str, Any]:
        return {
            "count": len(node.message_history),
            "messages": [message.copy() for message in node.message_history],
        }

    @app.get(f"{API_PREFIX}/contracts")
    def contracts() -> dict[str, Any]:
        state = _current_state(node)
        return {
            "tip_hash": _state_tip_hash(node),
            "height": state.height,
            "contracts": [
                {
                    "address": contract_address,
                    "contract": _jsonable(contract),
                    "storage": state.contract_storage.get(contract_address, {}).copy(),
                }
                for contract_address, contract in sorted(state.contracts.items())
            ],
        }

    @app.get(f"{API_PREFIX}/contracts/{{contract_address}}")
    def contract(contract_address: str) -> dict[str, Any]:
        blockchain = _require_blockchain(node)
        contract_data = blockchain.get_contract(contract_address, tip_hash=_state_tip_hash(node))
        if contract_data is None:
            raise HTTPException(status_code=404, detail="contract not found")
        return {
            "address": contract_address,
            "tip_hash": _state_tip_hash(node),
            "height": _current_state(node).height,
            "contract": contract_data,
        }

    @app.get(f"{API_PREFIX}/contracts/{{contract_address}}/storage")
    def contract_storage(contract_address: str) -> dict[str, Any]:
        blockchain = _require_blockchain(node)
        return {
            "address": contract_address,
            "tip_hash": _state_tip_hash(node),
            "height": _current_state(node).height,
            "storage": blockchain.get_contract_storage(
                contract_address,
                tip_hash=_state_tip_hash(node),
            ),
        }

    @app.get(f"{API_PREFIX}/receipts")
    def receipts() -> dict[str, Any]:
        state = _current_state(node)
        return {
            "tip_hash": _state_tip_hash(node),
            "height": state.height,
            "receipts": [
                {
                    "transaction_id": transaction_id,
                    "receipt": receipt.copy(),
                }
                for transaction_id, receipt in sorted(state.uvm_receipts.items())
            ],
        }

    @app.get(f"{API_PREFIX}/receipts/{{transaction_reference}}")
    def receipt(transaction_reference: str) -> dict[str, Any]:
        transaction_id, receipt_data = _find_receipt(node, transaction_reference)
        return {
            "transaction_id": transaction_id,
            "tip_hash": _state_tip_hash(node),
            "height": _current_state(node).height,
            "receipt": receipt_data,
        }

    @app.get(f"{API_PREFIX}/commitments/{{request_id}}")
    def commitments(request_id: str) -> dict[str, Any]:
        blockchain = _require_blockchain(node)
        return {
            "request_id": request_id,
            "tip_hash": _state_tip_hash(node),
            "height": _current_state(node).height,
            "commitments": blockchain.get_commitments(
                request_id,
                tip_hash=_state_tip_hash(node),
            ),
        }

    @app.get(f"{API_PREFIX}/reveals/{{request_id}}")
    def reveals(request_id: str) -> dict[str, Any]:
        blockchain = _require_blockchain(node)
        return {
            "request_id": request_id,
            "tip_hash": _state_tip_hash(node),
            "height": _current_state(node).height,
            "reveals": blockchain.get_reveals(
                request_id,
                tip_hash=_state_tip_hash(node),
            ),
        }

    @app.get(f"{API_PREFIX}/authorizations")
    def authorizations() -> dict[str, Any]:
        state = _current_state(node)
        return {
            "tip_hash": _state_tip_hash(node),
            "height": state.height,
            "count": len(state.authorizations),
            "authorizations": [
                _jsonable(authorization)
                for authorization in state.authorizations
            ],
        }

    @app.post(f"{API_PREFIX}/control/peers/connect")
    async def connect_peer(request: PeerRequest) -> dict[str, Any]:
        host, port = _parse_peer(request.peer)
        try:
            await asyncio.wait_for(
                node.connect_to_peer(host, port),
                timeout=PEER_CONNECT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as error:
            raise HTTPException(
                status_code=504,
                detail=f"Timed out connecting to peer {host}:{port}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"connected": node.list_peers(), "known": node.list_known_peers()}

    @app.post(f"{API_PREFIX}/control/peers/discover")
    async def discover_peers() -> dict[str, Any]:
        await node.discover_peers()
        return {"connected": node.list_peers(), "known": node.list_known_peers()}

    @app.post(f"{API_PREFIX}/control/sync")
    async def sync(request: SyncRequest) -> dict[str, Any]:
        peer_count = await node.sync_chain(fast=request.fast)
        return {"requested_peers": peer_count, "fast": request.fast}

    @app.post(f"{API_PREFIX}/control/transactions")
    async def create_transaction(request: TransactionRequest) -> dict[str, Any]:
        try:
            transaction = node.create_signed_transaction(
                receiver=node.resolve_wallet_reference(request.receiver),
                amount=request.amount,
                fee=request.fee,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return await _broadcast_transaction(node, transaction)

    @app.post(f"{API_PREFIX}/control/messages")
    async def create_message(request: MessageRequest) -> dict[str, Any]:
        try:
            message = node.create_signed_wallet_message(
                node.resolve_wallet_reference(request.receiver),
                request.content,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        accepted, reason = await node.p2p_server.broadcast_wallet_message(message)
        if not accepted:
            raise HTTPException(status_code=400, detail=reason or "message rejected")
        return {"message": message}

    @app.post(f"{API_PREFIX}/control/mine")
    async def mine(request: MineRequest) -> dict[str, Any]:
        description = request.description or node.default_block_description("Mined block")
        try:
            block = await node.mine_pending_transactions(description)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"block": _block_payload(block)}

    @app.post(f"{API_PREFIX}/control/automine/start")
    async def automine_start(request: MineRequest) -> dict[str, Any]:
        description = request.description or node.default_block_description("Auto-mined block")
        try:
            await node.start_automine(description)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"running": True, "description": description}

    @app.post(f"{API_PREFIX}/control/automine/stop")
    async def automine_stop() -> dict[str, Any]:
        await node.stop_automine(wait=False)
        return {"running": False}

    @app.post(f"{API_PREFIX}/control/aliases")
    def create_alias(request: AliasRequest) -> dict[str, Any]:
        try:
            wallet_address = node.set_wallet_alias(request.wallet, request.alias)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "wallet": wallet_address,
            "alias": node.alias_for_wallet(wallet_address),
        }

    @app.post(f"{API_PREFIX}/control/autosend")
    def autosend(request: AutosendRequest) -> dict[str, Any]:
        try:
            if request.target is None or not request.target.strip():
                node.disable_autosend()
                return {"enabled": False, "target": None}
            target = node.enable_autosend(request.target)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"enabled": True, "target": target}

    @app.post(f"{API_PREFIX}/control/commitments")
    async def create_commitment(request: CommitmentRequest) -> dict[str, Any]:
        try:
            transaction = node.create_signed_commitment(
                request_id=request.request_id,
                commitment_hash=request.commitment_hash,
                fee=request.fee,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return await _broadcast_transaction(node, transaction)

    @app.post(f"{API_PREFIX}/control/reveals")
    async def create_reveal(request: RevealRequest) -> dict[str, Any]:
        try:
            transaction = node.create_signed_reveal(
                request_id=request.request_id,
                seed=request.seed,
                fee=request.fee,
                salt=request.salt,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return await _broadcast_transaction(node, transaction)

    @app.post(f"{API_PREFIX}/control/contracts/deploy")
    async def deploy_contract(request: DeployRequest) -> dict[str, Any]:
        try:
            if request.source is not None and request.source.strip():
                transaction = node.create_signed_deploy_from_source(
                    contract_source=request.source,
                    fee=request.fee,
                )
            elif request.program is not None:
                transaction = node.create_signed_deploy(
                    program=request.program,
                    metadata=request.metadata,
                    fee=request.fee,
                )
            else:
                raise ValueError("Deploy requires source or program.")
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        result = await _broadcast_transaction(node, transaction)
        result["contract_address"] = transaction.receiver
        result["code_hash"] = transaction.payload.get("code_hash")
        return result

    @app.post(f"{API_PREFIX}/control/contracts/execute")
    async def execute_contract(request: ExecuteRequest) -> dict[str, Any]:
        try:
            transaction = node.create_signed_execute(
                contract_address=request.contract_address,
                input_data=request.input,
                gas_limit=request.gas_limit,
                gas_price=request.gas_price,
                value=request.value,
                fee=request.fee,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        result = await _broadcast_transaction(node, transaction)
        result["contract_address"] = transaction.receiver
        return result

    @app.post(f"{API_PREFIX}/control/contracts/authorize")
    async def authorize_contract(request: AuthorizationRequest) -> dict[str, Any]:
        try:
            transaction = node.create_signed_authorization(
                contract_address=request.contract_address,
                request_id=request.request_id,
                fee=request.fee,
                valid_for_blocks=request.valid_for_blocks,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        result = await _broadcast_transaction(node, transaction)
        result["contract_address"] = transaction.receiver
        result["request_id"] = request.request_id
        return result

    return app


@dataclass
class NodeAPIServer:
    node: "Node"
    host: str
    port: int
    log_level: str = "warning"
    app: FastAPI = field(init=False)
    _server: uvicorn.Server | None = field(default=None, init=False)
    _task: asyncio.Task | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.app = create_api_app(self.node)

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return

        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level=self.log_level,
        )
        self._server = uvicorn.Server(config)
        self._task = asyncio.create_task(self._server.serve())
        while not self._server.started:
            if self._task.done():
                await self._task
                return
            await asyncio.sleep(0.01)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            await self._task
        self._server = None
        self._task = None


def _require_blockchain(node: "Node") -> "Blockchain":
    if node.blockchain is None:
        raise HTTPException(status_code=503, detail="blockchain is not loaded")
    return node.blockchain


def _state_tip_hash(node: "Node") -> str | None:
    state_tip_hash = getattr(node, "_state_tip_hash", None)
    if callable(state_tip_hash):
        return state_tip_hash()
    blockchain = _require_blockchain(node)
    return blockchain.main_tip_hash


def _current_state(node: "Node") -> "ChainState":
    blockchain = _require_blockchain(node)
    return blockchain._get_state_for_tip(_state_tip_hash(node))


def _current_chain(node: "Node") -> list[Block]:
    blockchain = _require_blockchain(node)
    return blockchain.get_chain(_state_tip_hash(node))


def _chain_head_payload(node: "Node", blockchain: "Blockchain") -> dict[str, Any]:
    chain = blockchain.get_chain(_state_tip_hash(node))
    head = chain[-1] if chain else None
    state_tip_hash = _state_tip_hash(node)
    next_difficulty_bits = None
    try:
        next_difficulty_bits = blockchain.get_next_block_difficulty_bits(state_tip_hash)
    except ValueError:
        pass

    return {
        "height": head.block_id if head is not None else -1,
        "tip_hash": head.block_hash if head is not None else None,
        "state_tip_hash": state_tip_hash,
        "canonical_tip_hash": blockchain.main_tip_hash,
        "block_count": len(chain),
        "difficulty_bits": blockchain.difficulty_bits,
        "next_difficulty_bits": next_difficulty_bits,
        "pending_transaction_count": len(blockchain.pending_transactions),
    }


def _sync_status_payload(node: "Node") -> dict[str, Any]:
    active_fast_syncs = []
    fast_sync_states = getattr(node.p2p_server, "fast_sync_states", {})
    for peer, state in sorted(
        fast_sync_states.items(),
        key=lambda item: f"{item[0].host}:{item[0].port}",
    ):
        if not getattr(state, "active", False):
            continue
        active_fast_syncs.append(
            {
                "peer": f"{peer.host}:{peer.port}",
                "expected_start_height": getattr(state, "expected_start_height", 0),
                "pending_chunks": len(getattr(state, "pending_chunks", {})),
            }
        )

    return {
        "phase": "fastsync" if active_fast_syncs else "ready",
        "fastsync": {
            "active": bool(active_fast_syncs),
            "peers": active_fast_syncs,
        },
    }


def _find_current_chain_block(node: "Node", block_reference: str) -> Block:
    reference = block_reference.strip()
    if not reference:
        raise HTTPException(status_code=404, detail="block not found")

    chain = _current_chain(node)
    if reference.isdecimal():
        height = int(reference)
        for block in chain:
            if block.block_id == height:
                return block
        raise HTTPException(status_code=404, detail="block not found")

    matches = [
        block
        for block in chain
        if block.block_hash == reference or block.block_hash.startswith(reference)
    ]
    if not matches:
        raise HTTPException(status_code=404, detail="block not found")
    if len(matches) > 1:
        raise HTTPException(status_code=400, detail="block hash prefix is ambiguous")
    return matches[0]


def _find_receipt(node: "Node", transaction_reference: str) -> tuple[str, dict]:
    reference = transaction_reference.strip()
    if not reference:
        raise HTTPException(status_code=404, detail="receipt not found")

    state = _current_state(node)
    matches = [
        (transaction_id, receipt.copy())
        for transaction_id, receipt in state.uvm_receipts.items()
        if transaction_id == reference or transaction_id.startswith(reference)
    ]
    if not matches:
        raise HTTPException(status_code=404, detail="receipt not found")
    if len(matches) > 1:
        raise HTTPException(status_code=400, detail="transaction id prefix is ambiguous")
    return matches[0]


def _parse_peer(peer: str) -> tuple[str, int]:
    try:
        host, raw_port = peer.strip().split(":", maxsplit=1)
        port = int(raw_port)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="peer must be host:port") from error
    if not host or port <= 0 or port > 65535:
        raise HTTPException(status_code=400, detail="peer must be host:port")
    return host, port


async def _broadcast_transaction(node: "Node", transaction: Transaction) -> dict[str, Any]:
    accepted, reason = await node.p2p_server.broadcast_transaction(transaction)
    if not accepted:
        raise HTTPException(status_code=400, detail=reason or "transaction rejected")
    return {
        "transaction_id": sha256_transaction_hash(transaction),
        "transaction": _transaction_payload(transaction),
    }


def _wallet_payload(node: "Node") -> dict[str, Any] | None:
    if node.wallet is None:
        return None
    return {
        "name": node.wallet.name,
        "address": node.wallet.address,
    }


def _balance_payload(node: "Node", address: str, balance: Decimal) -> dict[str, Any]:
    alias = node.alias_for_wallet(address)
    return {
        "address": address,
        "alias": alias,
        "balance": str(balance),
    }


def _block_payload(block: Block) -> dict[str, Any]:
    block_data = block.to_dict()
    block_data["height"] = block.block_id
    block_data["transaction_count"] = len(block.transactions)
    block_data["transactions"] = [
        _transaction_payload(transaction)
        for transaction in block.transactions
    ]
    return block_data


def _transaction_payload(transaction: Transaction) -> dict[str, Any]:
    transaction_data = transaction.to_dict()
    transaction_data["transaction_id"] = sha256_transaction_hash(transaction)
    return transaction_data


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value

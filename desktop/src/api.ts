export type ChainHead = {
  height: number;
  tip_hash: string | null;
  state_tip_hash: string | null;
  canonical_tip_hash: string | null;
  block_count: number;
  difficulty_bits: number;
  next_difficulty_bits: number | null;
  pending_transaction_count: number;
};

export type WalletInfo = {
  name: string | null;
  address: string;
};

export type NodeInfo = {
  host: string;
  port: number;
  private_automine: boolean;
  wallet: WalletInfo | null;
  peers: PeersResponse;
  autosend: {
    target: string | null;
    enabled: boolean;
  };
  sync?: SyncStatus;
};

export type BalanceRow = {
  address: string;
  alias: string | null;
  balance: string;
};

export type BalancesResponse = {
  tip_hash: string | null;
  height: number;
  balances: BalanceRow[];
};

export type PeersResponse = {
  connected: string[];
  known: string[];
};

export type SyncStatus = {
  phase: "ready" | "fastsync" | string;
  fastsync: {
    active: boolean;
    peers: Array<{
      peer: string;
      expected_start_height: number;
      pending_chunks: number;
    }>;
  };
};

export type MinerStat = {
  address: string;
  alias: string | null;
  blocks: number;
};

export type MiningStatus = {
  active: boolean;
  mode: "manual" | "automine" | string | null;
  description: string;
  started_at: string | null;
  last_update_at: string | null;
  nonce: number;
  difficulty_bits: number | null;
  next_difficulty_bits: number | null;
  state_tip_hash?: string | null;
  tip_hash: string | null;
  automine: {
    running: boolean;
    description: string;
  };
  last_block: {
    height: number | null;
    block_hash: string | null;
    nonces_checked: number | null;
  };
  recent_miners: MinerStat[];
};

export type TransactionPayload = {
  transaction_id: string;
  sender: string;
  receiver: string;
  amount: string;
  fee: string;
  nonce: number;
  timestamp: string;
  kind?: string;
  payload?: Record<string, unknown>;
};

export type PendingTransactionsResponse = {
  tip_hash: string | null;
  count: number;
  transactions: TransactionPayload[];
};

export type BlockPayload = {
  height: number;
  block_hash: string;
  previous_hash: string;
  nonce: number;
  timestamp: string;
  description: string;
  transaction_count: number;
  transactions: TransactionPayload[];
};

export type BlocksResponse = {
  count: number;
  height: number;
  tip_hash: string | null;
  blocks: BlockPayload[];
};

export type MessageEntry = {
  direction?: string;
  peer?: string;
  sender?: string;
  receiver?: string;
  content?: string;
  timestamp?: string;
  message_id?: string;
};

export type MessagesResponse = {
  count: number;
  messages: MessageEntry[];
};

export type ContractEntry = {
  address: string;
  contract: Record<string, unknown>;
  storage: Record<string, unknown>;
};

export type ContractsResponse = {
  tip_hash: string | null;
  height: number;
  contracts: ContractEntry[];
};

export type ReceiptEntry = {
  transaction_id: string;
  receipt: Record<string, unknown>;
};

export type ReceiptsResponse = {
  tip_hash: string | null;
  height: number;
  receipts: ReceiptEntry[];
};

export type AuthorizationsResponse = {
  count: number;
  authorizations: Record<string, unknown>[];
};

export type BroadcastTransactionResponse = {
  transaction_id: string;
  transaction: TransactionPayload;
  contract_address?: string;
  code_hash?: string;
};

export type MineResponse = {
  block: BlockPayload;
};

export type AuthorizationResponse = {
  authorization: Record<string, unknown>;
};

async function requestApi<T>(
  apiPort: number,
  path: string,
  method: "GET" | "POST" = "GET",
  body?: unknown,
): Promise<T> {
  return window.unccoinDesktop.fetchApi(apiPort, path, { method, body }) as Promise<T>;
}

export function readChainHead(apiPort: number): Promise<ChainHead> {
  return requestApi<ChainHead>(apiPort, "/chain/head");
}

export function readNodeInfo(apiPort: number): Promise<NodeInfo> {
  return requestApi<NodeInfo>(apiPort, "/node");
}

export function readSyncStatus(apiPort: number): Promise<SyncStatus> {
  return requestApi<SyncStatus>(apiPort, "/sync/status");
}

export function readMiningStatus(apiPort: number): Promise<MiningStatus> {
  return requestApi<MiningStatus>(apiPort, "/mining/status");
}

export function readBalances(apiPort: number): Promise<BalancesResponse> {
  return requestApi<BalancesResponse>(apiPort, "/balances");
}

export function readPeers(apiPort: number): Promise<PeersResponse> {
  return requestApi<PeersResponse>(apiPort, "/peers");
}

export function readPendingTransactions(apiPort: number): Promise<PendingTransactionsResponse> {
  return requestApi<PendingTransactionsResponse>(apiPort, "/transactions/pending");
}

export function readBlocks(apiPort: number, limit = 12): Promise<BlocksResponse> {
  return requestApi<BlocksResponse>(apiPort, `/chain/blocks?limit=${limit}`);
}

export function readMessages(apiPort: number): Promise<MessagesResponse> {
  return requestApi<MessagesResponse>(apiPort, "/messages");
}

export function readContracts(apiPort: number): Promise<ContractsResponse> {
  return requestApi<ContractsResponse>(apiPort, "/contracts");
}

export function readReceipts(apiPort: number): Promise<ReceiptsResponse> {
  return requestApi<ReceiptsResponse>(apiPort, "/receipts");
}

export function readAuthorizations(apiPort: number): Promise<AuthorizationsResponse> {
  return requestApi<AuthorizationsResponse>(apiPort, "/authorizations");
}

export function connectPeer(apiPort: number, peer: string): Promise<PeersResponse> {
  return requestApi<PeersResponse>(apiPort, "/control/peers/connect", "POST", { peer });
}

export function discoverPeers(apiPort: number): Promise<PeersResponse> {
  return requestApi<PeersResponse>(apiPort, "/control/peers/discover", "POST", {});
}

export function syncChain(apiPort: number, fast = true): Promise<{ requested_peers: number }> {
  return requestApi(apiPort, "/control/sync", "POST", { fast });
}

export function sendTransaction(
  apiPort: number,
  payload: { receiver: string; amount: string; fee: string },
): Promise<BroadcastTransactionResponse> {
  return requestApi(apiPort, "/control/transactions", "POST", payload);
}

export function sendMessage(
  apiPort: number,
  payload: { receiver: string; content: string },
): Promise<{ message: MessageEntry }> {
  return requestApi(apiPort, "/control/messages", "POST", payload);
}

export function mineBlock(apiPort: number, description?: string): Promise<MineResponse> {
  return requestApi(apiPort, "/control/mine", "POST", { description });
}

export function startAutomine(
  apiPort: number,
  description?: string,
): Promise<{ running: boolean; description: string }> {
  return requestApi(apiPort, "/control/automine/start", "POST", { description });
}

export function stopAutomine(apiPort: number): Promise<{ running: boolean }> {
  return requestApi(apiPort, "/control/automine/stop", "POST", {});
}

export function setAlias(
  apiPort: number,
  payload: { wallet: string; alias: string },
): Promise<{ wallet: string; alias: string | null }> {
  return requestApi(apiPort, "/control/aliases", "POST", payload);
}

export function setAutosend(
  apiPort: number,
  target: string | null,
): Promise<{ enabled: boolean; target: string | null }> {
  return requestApi(apiPort, "/control/autosend", "POST", { target });
}

export function createCommitment(
  apiPort: number,
  payload: { request_id: string; commitment_hash: string; fee: string },
): Promise<BroadcastTransactionResponse> {
  return requestApi(apiPort, "/control/commitments", "POST", payload);
}

export function revealCommitment(
  apiPort: number,
  payload: { request_id: string; seed: string; fee: string; salt: string },
): Promise<BroadcastTransactionResponse> {
  return requestApi(apiPort, "/control/reveals", "POST", payload);
}

export function deployContract(
  apiPort: number,
  payload: { fee: string; source?: string; program?: unknown; metadata?: Record<string, unknown> },
): Promise<BroadcastTransactionResponse> {
  return requestApi(apiPort, "/control/contracts/deploy", "POST", payload);
}

export function executeContract(
  apiPort: number,
  payload: {
    contract_address: string;
    gas_limit: string;
    gas_price: string;
    value: string;
    fee: string;
    input: unknown;
    authorizations: Record<string, unknown>[];
  },
): Promise<BroadcastTransactionResponse> {
  return requestApi(apiPort, "/control/contracts/execute", "POST", payload);
}

export function authorizeContract(
  apiPort: number,
  payload: { contract_address: string; request_id: string; valid_for_blocks?: string | null },
): Promise<AuthorizationResponse> {
  return requestApi(apiPort, "/control/contracts/authorize", "POST", payload);
}

export function storeAuthorization(
  apiPort: number,
  authorization: Record<string, unknown>,
): Promise<{ stored: boolean }> {
  return requestApi(apiPort, "/control/authorizations/store", "POST", { authorization });
}

export function sendAuthorization(
  apiPort: number,
  payload: {
    receiver: string;
    contract_address: string;
    request_id: string;
    valid_for_blocks?: string | null;
  },
): Promise<{ message: MessageEntry }> {
  return requestApi(apiPort, "/control/authorizations/send", "POST", payload);
}

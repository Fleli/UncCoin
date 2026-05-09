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

export type TrafficStats = {
  bytes: number;
  messages: number;
};

export type NetworkPeerStats = {
  peer: string;
  connected: boolean;
  ingress: TrafficStats;
  egress: TrafficStats;
};

export type NetworkStatsResponse = {
  ingress: TrafficStats;
  egress: TrafficStats;
  peers: NetworkPeerStats[];
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

export type MiningBackendId = "auto" | "gpu" | "native" | "python" | string;

export type MiningWarmupStatus = {
  active: boolean;
  status: "idle" | "running" | "ready" | "failed" | string;
  backend: MiningBackendId;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  detail: unknown;
};

export type MiningBackendOption = {
  id: MiningBackendId;
  label: string;
  available: boolean;
  can_build: boolean;
  description: string;
};

export type MiningBackendsResponse = {
  selected: MiningBackendId;
  native: {
    path: string;
    built: boolean;
    needs_rebuild: boolean;
  };
  warmup: MiningWarmupStatus;
  backends: MiningBackendOption[];
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
  backend: MiningBackendId;
  warmup: MiningWarmupStatus;
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
  nonces_checked?: number;
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
  transaction?: TransactionPayload;
  contract_address?: string;
  contract_name?: string | null;
  contract_description?: string | null;
  block_height?: number;
  block_hash?: string;
  block_description?: string;
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

export type CommitmentsResponse = {
  request_id: string;
  tip_hash: string | null;
  height: number;
  commitments: Record<string, string>;
};

export type RevealEntry = {
  seed?: string;
  salt?: string;
  commitment_hash?: string;
};

export type RevealsResponse = {
  request_id: string;
  tip_hash: string | null;
  height: number;
  reveals: Record<string, RevealEntry>;
};

export type BroadcastTransactionResponse = {
  transaction_id: string;
  transaction: TransactionPayload;
  contract_address?: string;
  code_hash?: string;
  request_id?: string;
};

export type MineResponse = {
  block: BlockPayload;
};

type RequestOptions = {
  timeoutMs?: number;
};

async function requestApi<T>(
  apiPort: number,
  path: string,
  method: "GET" | "POST" = "GET",
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  return window.unccoinDesktop.fetchApi(
    apiPort,
    path,
    { method, body, timeoutMs: options.timeoutMs },
  ) as Promise<T>;
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

export function readMiningBackends(apiPort: number): Promise<MiningBackendsResponse> {
  return requestApi<MiningBackendsResponse>(apiPort, "/mining/backends");
}

export function readMiningWarmup(apiPort: number): Promise<MiningWarmupStatus> {
  return requestApi<MiningWarmupStatus>(apiPort, "/mining/warmup");
}

export function readBalances(apiPort: number): Promise<BalancesResponse> {
  return requestApi<BalancesResponse>(apiPort, "/balances");
}

export function readPeers(apiPort: number): Promise<PeersResponse> {
  return requestApi<PeersResponse>(apiPort, "/peers");
}

export function readNetworkStats(apiPort: number): Promise<NetworkStatsResponse> {
  return requestApi<NetworkStatsResponse>(apiPort, "/network/stats");
}

export function readPendingTransactions(apiPort: number): Promise<PendingTransactionsResponse> {
  return requestApi<PendingTransactionsResponse>(apiPort, "/transactions/pending");
}

export function readBlocks(apiPort: number, limit = 12, fromHeight = 0): Promise<BlocksResponse> {
  return requestApi<BlocksResponse>(apiPort, `/chain/blocks?from_height=${fromHeight}&limit=${limit}`);
}

export function readBlock(apiPort: number, reference: string): Promise<BlockPayload> {
  return requestApi<BlockPayload>(apiPort, `/chain/block/${encodeURIComponent(reference)}`);
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

export function readCommitments(apiPort: number, requestId: string): Promise<CommitmentsResponse> {
  return requestApi<CommitmentsResponse>(apiPort, `/commitments/${encodeURIComponent(requestId)}`);
}

export function readReveals(apiPort: number, requestId: string): Promise<RevealsResponse> {
  return requestApi<RevealsResponse>(apiPort, `/reveals/${encodeURIComponent(requestId)}`);
}

export function connectPeer(apiPort: number, peer: string): Promise<PeersResponse> {
  return requestApi<PeersResponse>(
    apiPort,
    "/control/peers/connect",
    "POST",
    { peer },
    { timeoutMs: 25000 },
  );
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

export function rebroadcastPendingTransactions(
  apiPort: number,
): Promise<{ rebroadcast: number }> {
  return requestApi(apiPort, "/control/transactions/rebroadcast", "POST", {});
}

export function sendMessage(
  apiPort: number,
  payload: { receiver: string; content: string },
): Promise<{ message: MessageEntry }> {
  return requestApi(apiPort, "/control/messages", "POST", payload);
}

export function mineBlock(apiPort: number, description?: string): Promise<MineResponse> {
  return requestApi(apiPort, "/control/mine", "POST", { description }, { timeoutMs: 0 });
}

export function setMiningBackend(
  apiPort: number,
  backend: MiningBackendId,
): Promise<MiningBackendsResponse> {
  return requestApi(apiPort, "/control/mining/backend", "POST", { backend });
}

export function buildMiningBackend(
  apiPort: number,
  backend: MiningBackendId,
): Promise<{ built: boolean; path: string; capabilities: MiningBackendsResponse }> {
  return requestApi(
    apiPort,
    "/control/mining/backend/build",
    "POST",
    { backend },
    { timeoutMs: 120000 },
  );
}

export function startMiningWarmup(apiPort: number): Promise<MiningWarmupStatus> {
  return requestApi(apiPort, "/control/mining/warmup", "POST", {});
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
  },
): Promise<BroadcastTransactionResponse> {
  return requestApi(apiPort, "/control/contracts/execute", "POST", payload);
}

export function authorizeContract(
  apiPort: number,
  payload: { contract_address: string; request_id: string; valid_for_blocks?: string | null },
): Promise<BroadcastTransactionResponse> {
  return requestApi(apiPort, "/control/contracts/authorize", "POST", payload);
}

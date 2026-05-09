import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  authorizeContract,
  buildMiningBackend,
  connectPeer,
  createCommitment,
  deployContract,
  disconnectPeer,
  discoverPeers,
  executeContract,
  mineBlock,
  readAuthorizations,
  readBalances,
  readBlock,
  readBlocks,
  readChainHead,
  readCommitments,
  readContracts,
  readMiningBackends,
  readMiningStatus,
  readMessages,
  readNetworkStats,
  readNodeInfo,
  readPeers,
  readPendingTransactions,
  readReceipts,
  readReveals,
  readSyncStatus,
  rebroadcastPendingTransactions,
  revealCommitment,
  sendMessage,
  sendTransaction,
  setAlias,
  setAutosend,
  setMiningBackend,
  startAutomine,
  startMiningWarmup,
  stopAutomine,
  syncChain,
  type BalanceRow,
  type BlockPayload,
  type ChainHead,
  type ContractEntry,
  type MessageEntry,
  type MiningBackendId,
  type MiningBackendOption,
  type MiningBackendsResponse,
  type MiningWarmupStatus,
  type MiningStatus,
  type NetworkStatsResponse,
  type NodeInfo,
  type PeersResponse,
  type ReceiptEntry,
  type SyncStatus,
  type TransactionPayload,
} from "./api";
import "./styles.css";

const DEFAULT_PORT = 9000;
const BOOTSTRAP_PEERS = [
  "localhost:9000",
  "100.98.249.35:9000",
  "100.98.249.35:9001",
  "100.71.105.5:4040",
  "100.119.242.7:6000",
];
const DEFAULT_DEPLOY_JSON = `{
  "program": [["HALT"]],
  "metadata": {"name": "noop"}
}`;
const DEFAULT_EXECUTE_JSON = "null";
const RECENT_BLOCK_LIMIT = 12;
const BLOCKCHAIN_CONTEXT_BLOCKS = 3;
const MINING_REWARD_SENDER = "SYSTEM";
const RANDOMNESS_SEED_MODULUS = 1n << 256n;
const COINFLIP_REVEAL_DEADLINE_BLOCKS = 20;

type TabId = "blockchain" | "balances" | "transfer" | "mining" | "wallet" | "network" | "messages" | "contracts" | "logs";
type TabIconName = "blocks" | "balances" | "transfer" | "pickaxe" | "wallet" | "network" | "messages" | "contracts" | "logs";
type ContractSubTab = "deploy" | "execute" | "authorization" | "randomness" | "contracts" | "receipts";
type DeploySubTab = "raw" | "templates";
type ContractTemplateId = "coinflip";

type Snapshot = {
  nodeInfo: NodeInfo | null;
  chainHead: ChainHead | null;
  balances: BalanceRow[];
  peers: PeersResponse;
  networkStats: NetworkStatsResponse;
  pendingTransactions: TransactionPayload[];
  blocks: BlockPayload[];
  messages: MessageEntry[];
  contracts: ContractEntry[];
  receipts: ReceiptEntry[];
  authorizations: Record<string, unknown>[];
};

type ActionResult = {
  label: string;
  detail?: string;
};

type NodeActionRefreshMode = "snapshot" | "mining" | "none";

type BlockchainWindow = {
  reference: string;
  targetHash: string;
  targetHeight: number;
  blocks: BlockPayload[];
};

type BootstrapAttempt = {
  peer: string;
  status: "pending" | "connected" | "failed" | "skipped";
  detail?: string;
  rawDetail?: string;
};

type NetworkEvent = {
  id: string;
  type: "connected" | "disconnected";
  peer: string;
  timestamp: string;
};

type StartupPhase = "idle" | "starting-node" | "waiting-api" | "warming-miner" | "connecting-bootstrap" | "fastsync" | "ready";

const tabs: Array<{ id: TabId; label: string; icon: TabIconName }> = [
  { id: "blockchain", label: "Blockchain", icon: "blocks" },
  { id: "balances", label: "Balances", icon: "balances" },
  { id: "transfer", label: "Transfer", icon: "transfer" },
  { id: "mining", label: "Mining", icon: "pickaxe" },
  { id: "wallet", label: "Wallet", icon: "wallet" },
  { id: "network", label: "Network", icon: "network" },
  { id: "messages", label: "Messages", icon: "messages" },
  { id: "contracts", label: "Contracts", icon: "contracts" },
  { id: "logs", label: "Logs", icon: "logs" },
];

const contractSubTabs: Array<{ id: ContractSubTab; label: string }> = [
  { id: "deploy", label: "Deploy" },
  { id: "execute", label: "Execute" },
  { id: "authorization", label: "Authorization" },
  { id: "randomness", label: "Randomness" },
  { id: "contracts", label: "Contracts" },
  { id: "receipts", label: "Receipts" },
];

const contractTemplates: Array<{ id: ContractTemplateId; label: string; description: string }> = [
  {
    id: "coinflip",
    label: "Coinflip",
    description: "Two-wallet commit-reveal coinflip.",
  },
];

function TabIcon({ name }: { name: TabIconName }) {
  switch (name) {
    case "balances":
      return (
        <svg className="tab-icon" viewBox="0 0 20 20" aria-hidden="true">
          <path d="M4 6.5c0-1.1 2.7-2 6-2s6 .9 6 2-2.7 2-6 2-6-.9-6-2Z" />
          <path d="M4 6.5v3c0 1.1 2.7 2 6 2s6-.9 6-2v-3" />
          <path d="M4 9.5v3c0 1.1 2.7 2 6 2s6-.9 6-2v-3" />
        </svg>
      );
    case "blocks":
      return (
        <svg className="tab-icon" viewBox="0 0 20 20" aria-hidden="true">
          <path d="M3.5 4.5h5v5h-5z" />
          <path d="M11.5 10.5h5v5h-5z" />
          <path d="M8.5 7h3" />
          <path d="M11.5 13h-3" />
        </svg>
      );
    case "transfer":
      return (
        <svg className="tab-icon" viewBox="0 0 20 20" aria-hidden="true">
          <path d="M4 10h11" />
          <path d="m11.5 6.5 3.5 3.5-3.5 3.5" />
        </svg>
      );
    case "pickaxe":
      return (
        <svg className="tab-icon" viewBox="0 0 20 20" aria-hidden="true">
          <path d="M12.5 4.5c2 .3 3.3 1 4 2" />
          <path d="M8 6.5c2.5-1.9 5.3-2.4 8.5-1.5" />
          <path d="m9.5 8.5-5 6" />
          <path d="m4 14 2 2" />
        </svg>
      );
    case "wallet":
      return (
        <svg className="tab-icon" viewBox="0 0 20 20" aria-hidden="true">
          <path d="M4 6h11.5a1.5 1.5 0 0 1 1.5 1.5v7A1.5 1.5 0 0 1 15.5 16h-10A1.5 1.5 0 0 1 4 14.5z" />
          <path d="M4 6.5V5a1.5 1.5 0 0 1 1.8-1.5L14 5" />
          <path d="M14.5 11h.5" />
        </svg>
      );
    case "network":
      return (
        <svg className="tab-icon" viewBox="0 0 20 20" aria-hidden="true">
          <path d="M6 7.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z" />
          <path d="M14 16.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z" />
          <path d="M15 7.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z" />
          <path d="m7.8 6.2 4.4 1.1" />
          <path d="m7.4 7.2 5.2 5.6" />
        </svg>
      );
    case "messages":
      return (
        <svg className="tab-icon" viewBox="0 0 20 20" aria-hidden="true">
          <path d="M4 5.5h12v8H9l-3.5 2v-2H4z" />
        </svg>
      );
    case "contracts":
      return (
        <svg className="tab-icon" viewBox="0 0 20 20" aria-hidden="true">
          <path d="M6 3.5h6l3 3V16H6z" />
          <path d="M12 3.5V7h3" />
          <path d="m9 10-1.5 1.5L9 13" />
          <path d="m12 10 1.5 1.5L12 13" />
        </svg>
      );
    case "logs":
      return (
        <svg className="tab-icon" viewBox="0 0 20 20" aria-hidden="true">
          <path d="M4.5 5.5h11" />
          <path d="M4.5 10h11" />
          <path d="M4.5 14.5h7" />
        </svg>
      );
  }
}

function WarningIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" aria-hidden="true">
      <path d="M10 3.5 17 16H3z" />
      <path d="M10 7.5v4" />
      <path d="M10 14h.01" />
    </svg>
  );
}

function TrafficDirectionIcon({ direction }: { direction: "ingress" | "egress" }) {
  return (
    <span className={`traffic-direction-icon ${direction}`} aria-hidden="true">
      <svg viewBox="0 0 20 20">
        {direction === "ingress" ? (
          <>
            <path d="M14.5 5.5 5.5 14.5" />
            <path d="M5.5 8.5v6h6" />
          </>
        ) : (
          <>
            <path d="M5.5 14.5 14.5 5.5" />
            <path d="M8.5 5.5h6v6" />
          </>
        )}
      </svg>
    </span>
  );
}

function BlockchainHashConnector({ active }: { active: boolean }) {
  return (
    <div
      className={`block-connector ${active ? "" : "muted"}`}
      aria-label="Block hash links to the next block previous hash"
    >
      <svg viewBox="0 0 58 128" aria-hidden="true">
        <circle cx="4" cy="24" r="2.5" />
        <path d="M6 24 H31 V60 H52" />
        <path d="M46 54 53 60 46 66" />
        <circle cx="54" cy="60" r="2.5" />
      </svg>
    </div>
  );
}

function emptySnapshot(): Snapshot {
  return {
    nodeInfo: null,
    chainHead: null,
    balances: [],
    peers: { connected: [], known: [] },
    networkStats: {
      ingress: { bytes: 0, messages: 0 },
      egress: { bytes: 0, messages: 0 },
      peers: [],
    },
    pendingTransactions: [],
    blocks: [],
    messages: [],
    contracts: [],
    receipts: [],
    authorizations: [],
  };
}

function formatAmount(value: string | null | undefined): string {
  return value ?? "0";
}

function balanceSortValue(balance: BalanceRow): number {
  const value = Number.parseFloat(balance.balance);
  return Number.isFinite(value) ? value : Number.NEGATIVE_INFINITY;
}

function sortBalancesDescending(balances: BalanceRow[]): BalanceRow[] {
  return [...balances].sort((left, right) => {
    const balanceDelta = balanceSortValue(right) - balanceSortValue(left);
    if (balanceDelta !== 0) {
      return balanceDelta;
    }
    return (left.alias ?? left.address).localeCompare(right.alias ?? right.address);
  });
}

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function randomHex(bytes: number): string {
  const fallback = () => Array.from({ length: bytes }, () => (
    Math.floor(Math.random() * 256).toString(16).padStart(2, "0")
  )).join("");

  if (globalThis.crypto?.getRandomValues === undefined) {
    return fallback();
  }

  const buffer = new Uint8Array(bytes);
  globalThis.crypto.getRandomValues(buffer);
  return Array.from(buffer, (value) => value.toString(16).padStart(2, "0")).join("");
}

function createCoinflipRequestId(): string {
  const suffix = typeof globalThis.crypto?.randomUUID === "function"
    ? globalThis.crypto.randomUUID().replace(/-/g, "").slice(0, 16)
    : randomHex(8);
  return `coinflip-${suffix}`;
}

function parsePositiveIntegerField(value: string, label: string): number {
  const trimmedValue = value.trim();
  if (!/^[0-9]+$/.test(trimmedValue)) {
    throw new Error(`${label} must be a positive whole number.`);
  }
  const parsedValue = Number(trimmedValue);
  if (!Number.isSafeInteger(parsedValue) || parsedValue <= 0) {
    throw new Error(`${label} must be a positive whole number below ${Number.MAX_SAFE_INTEGER}.`);
  }
  return parsedValue;
}

function parseWholeNumberField(value: string, label: string): number {
  const trimmedValue = value.trim();
  if (!/^[0-9]+$/.test(trimmedValue)) {
    throw new Error(`${label} must be a whole number.`);
  }
  const parsedValue = Number(trimmedValue);
  if (!Number.isSafeInteger(parsedValue)) {
    throw new Error(`${label} must be a whole number below ${Number.MAX_SAFE_INTEGER}.`);
  }
  return parsedValue;
}

function buildCoinflipContract({
  walletOne,
  walletTwo,
  amount,
  revealDeadline,
  requestId,
}: {
  walletOne: string;
  walletTwo: string;
  amount: number;
  revealDeadline: number;
  requestId: string;
}): { program: unknown[]; metadata: Record<string, unknown> } {
  const payout = amount * 2;
  return {
    program: [
      ["LOAD", "settled"],
      ["JUMPI", 51],
      ["HAS_REVEAL", walletOne, requestId],
      ["MEM_STORE", "a_revealed"],
      ["HAS_REVEAL", walletTwo, requestId],
      ["MEM_STORE", "b_revealed"],
      ["MEM_LOAD", "a_revealed"],
      ["MEM_LOAD", "b_revealed"],
      ["AND"],
      ["JUMPI", 32],
      ["BLOCK_HEIGHT"],
      ["READ_METADATA", "reveal_deadline"],
      ["GT"],
      ["JUMPI", 15],
      ["HALT"],
      ["MEM_LOAD", "a_revealed"],
      ["JUMPI", 22],
      ["MEM_LOAD", "b_revealed"],
      ["JUMPI", 27],
      ["PUSH", 1],
      ["STORE", "settled"],
      ["HALT"],
      ["PUSH", 1],
      ["STORE", "settled"],
      ["PUSH", amount],
      ["TRANSFER_FROM", walletTwo, walletOne, requestId],
      ["HALT"],
      ["PUSH", 1],
      ["STORE", "settled"],
      ["PUSH", amount],
      ["TRANSFER_FROM", walletOne, walletTwo, requestId],
      ["HALT"],
      ["PUSH", 1],
      ["STORE", "settled"],
      ["PUSH", amount],
      ["TRANSFER_FROM", walletOne, "$CONTRACT", requestId],
      ["PUSH", amount],
      ["TRANSFER_FROM", walletTwo, "$CONTRACT", requestId],
      ["READ_REVEAL", walletOne, requestId],
      ["READ_REVEAL", walletTwo, requestId],
      ["XOR"],
      ["SHA256"],
      ["PUSH", 2],
      ["MOD"],
      ["JUMPI", 48],
      ["PUSH", payout],
      ["TRANSFER_FROM", "$CONTRACT", walletOne, "coinflip:payout"],
      ["HALT"],
      ["PUSH", payout],
      ["TRANSFER_FROM", "$CONTRACT", walletTwo, "coinflip:payout"],
      ["HALT"],
      ["HALT"],
    ],
    metadata: {
      name: "coinflip",
      description: `Coinflip between ${walletOne} and ${walletTwo}.`,
      template: "coinflip",
      request_id: requestId,
      request_ids: [requestId],
      participants: [walletOne, walletTwo],
      amount,
      stake: amount,
      reveal_deadline: revealDeadline,
    },
  };
}

function normalizeRandomnessSeed(seed: string): string {
  const trimmedSeed = seed.trim();
  if (!trimmedSeed) {
    throw new Error("Seed is required.");
  }
  const seedValue = trimmedSeed.startsWith("0x") || trimmedSeed.startsWith("0X")
    ? BigInt(trimmedSeed)
    : BigInt(trimmedSeed);
  if (seedValue < 0n || seedValue >= RANDOMNESS_SEED_MODULUS) {
    throw new Error("Seed must be between 0 and 2^256 - 1.");
  }
  return seedValue.toString(10);
}

async function sha256Hex(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await window.crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function createRevealCommitmentHash(
  walletAddress: string,
  requestId: string,
  seed: string,
  salt: string,
): Promise<string> {
  const payload = [
    "UVM_REVEAL",
    "1",
    walletAddress.trim(),
    requestId.trim(),
    normalizeRandomnessSeed(seed),
    salt.trim(),
  ].join("|");
  return sha256Hex(payload);
}

function formatWalletKey(key: WalletKeyDetails["publicKey"]): string {
  return JSON.stringify({
    exponent: key.exponent,
    modulus: key.modulus,
  }, null, 2);
}

function formatNumber(value: number | null | undefined): string {
  return typeof value === "number" ? value.toLocaleString() : "-";
}

function formatBytes(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "-";
  }
  const units = ["B", "KB", "MB", "GB"];
  let unitIndex = 0;
  let scaledValue = value;
  while (scaledValue >= 1024 && unitIndex < units.length - 1) {
    scaledValue /= 1024;
    unitIndex += 1;
  }
  if (unitIndex === 0) {
    return `${scaledValue.toLocaleString()} ${units[unitIndex]}`;
  }
  return `${scaledValue.toLocaleString(undefined, { maximumFractionDigits: 1 })} ${units[unitIndex]}`;
}

function formatElapsed(startedAt: string | null | undefined): string {
  if (!startedAt) {
    return "-";
  }
  const started = Date.parse(startedAt);
  if (!Number.isFinite(started)) {
    return "-";
  }
  const seconds = Math.max(0, Math.floor((Date.now() - started) / 1000));
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return minutes > 0 ? `${minutes}m ${remainder}s` : `${remainder}s`;
}

function miningBackendButtonLabel(
  option: MiningBackendOption,
  selected: MiningBackendId,
  needsWarmup: boolean,
  isWarming: boolean,
): string {
  if (isWarming) {
    return "Warming";
  }
  if (option.available) {
    if (option.id === selected) {
      return needsWarmup ? "Warm up" : "Selected";
    }
    return needsWarmup ? `Use & warm ${option.label}` : `Use ${option.label}`;
  }
  if (option.can_build) {
    return `Build ${option.label}`;
  }
  return "Unavailable";
}

function miningBackendIsWarmed(
  option: MiningBackendOption,
  warmup: MiningWarmupStatus | null,
): boolean {
  if (!option.available) {
    return false;
  }
  if (option.id === "python") {
    return true;
  }
  return (
    warmup?.status === "ready"
    && warmup.error === null
    && warmup.backend === option.id
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function recordString(record: Record<string, unknown>, key: string): string | null {
  const value = record[key];
  if (value === undefined || value === null || value === "") {
    return null;
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function contractMetadata(contract: ContractEntry): Record<string, unknown> {
  const metadata = contract.contract.metadata;
  return isRecord(metadata) ? metadata : {};
}

function contractDisplayName(contract: ContractEntry): string {
  return recordString(contractMetadata(contract), "name") ?? "Contract";
}

function contractCodeHash(contract: ContractEntry): string | null {
  return recordString(contract.contract, "code_hash");
}

function contractDescription(contract: ContractEntry): string | null {
  return recordString(contractMetadata(contract), "description");
}

function truthyStorageValue(value: unknown): boolean {
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    return value !== 0;
  }
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    return normalized !== "" && normalized !== "0" && normalized !== "false";
  }
  return value !== undefined && value !== null;
}

function contractUsesSettledState(contract: ContractEntry): boolean {
  const metadata = contractMetadata(contract);
  return (
    Object.prototype.hasOwnProperty.call(contract.storage, "settled")
    || Object.prototype.hasOwnProperty.call(metadata, "request_ids")
    || Object.prototype.hasOwnProperty.call(metadata, "reveal_deadline")
    || Object.prototype.hasOwnProperty.call(metadata, "stake")
  );
}

function receiptBelongsToContract(receipt: ReceiptEntry, contract: ContractEntry): boolean {
  return (
    receipt.contract_address === contract.address
    || receipt.transaction?.receiver === contract.address
    || (
      receipt.transaction !== undefined
      && payloadValue(receipt.transaction, "contract_address") === contract.address
    )
  );
}

function contractHasExecutionReceipt(contract: ContractEntry, receipts: ReceiptEntry[]): boolean {
  return receipts.some((receipt) => receiptBelongsToContract(receipt, contract));
}

function contractIsDone(contract: ContractEntry, receipts: ReceiptEntry[]): boolean {
  if (contractUsesSettledState(contract)) {
    return truthyStorageValue(contract.storage.settled);
  }
  return contractHasExecutionReceipt(contract, receipts);
}

function contractExecutionStatus(contract: ContractEntry, receipts: ReceiptEntry[]): string {
  if (contractIsDone(contract, receipts)) {
    return "done";
  }
  return contractHasExecutionReceipt(contract, receipts) ? "open" : "not executed";
}

function authorizationScopeLabel(authorization: Record<string, unknown>): string {
  const scope = authorization.scope;
  if (!isRecord(scope) || Object.keys(scope).length === 0) {
    return "open";
  }

  const from = recordString(scope, "valid_from_height");
  const until = recordString(scope, "valid_until_height");
  if (from !== null && until !== null) {
    return `blocks ${from}-${until}`;
  }
  if (until !== null) {
    return `until ${until}`;
  }
  if (from !== null) {
    return `from ${from}`;
  }
  return "scoped";
}

function parseJsonField(value: string, label: string): unknown {
  try {
    return JSON.parse(value);
  } catch (error) {
    throw new Error(`${label} must be valid JSON: ${(error as Error).message}`);
  }
}

function actionText(result: ActionResult): string {
  return result.detail ? `${result.label}: ${result.detail}` : result.label;
}

function transactionKind(transaction: TransactionPayload): string {
  const kind = transaction.kind;
  if (typeof kind === "string" && kind) {
    return kind;
  }
  return "transfer";
}

function transactionSummary(transaction: TransactionPayload): string {
  const kind = transactionKind(transaction);
  if (kind === "transfer") {
    return `${transaction.sender} -> ${transaction.receiver} (${transaction.amount})`;
  }
  return `${kind} ${transaction.receiver}`;
}

function outgoingTransactionSummary(transaction: TransactionPayload): string {
  const kind = transactionKind(transaction);
  const kindPrefix = kind === "transfer" ? "" : `${kind} `;
  return `-> ${kindPrefix}${transaction.receiver} (${transaction.amount})`;
}

function newestFirst<T extends { timestamp?: string }>(items: T[]): T[] {
  return [...items].sort((left, right) => String(right.timestamp ?? "").localeCompare(String(left.timestamp ?? "")));
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) {
    return value;
  }
  return new Date(timestamp).toLocaleString();
}

function payloadValue(transaction: TransactionPayload, key: string): string | null {
  const value = transaction.payload?.[key];
  if (value === undefined || value === null || value === "") {
    return null;
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function receiptSuccess(receipt: ReceiptEntry): boolean | null {
  const success = receipt.receipt.success;
  return typeof success === "boolean" ? success : null;
}

function receiptBlockSortValue(receipt: ReceiptEntry): number {
  return typeof receipt.block_height === "number" ? receipt.block_height : -1;
}

function pendingTransactionMatchesCommit(
  transaction: TransactionPayload,
  record: RandomnessCommitRecord,
  walletAddress: string,
): boolean {
  return (
    transaction.sender === walletAddress
    && payloadValue(transaction, "request_id") === record.requestId
    && payloadValue(transaction, "commitment_hash")?.toLowerCase() === record.commitmentHash.toLowerCase()
  );
}

function pendingTransactionMatchesReveal(
  transaction: TransactionPayload,
  record: RandomnessCommitRecord,
  walletAddress: string,
): boolean {
  return (
    transaction.sender === walletAddress
    && payloadValue(transaction, "request_id") === record.requestId
    && payloadValue(transaction, "seed") === record.seed
    && (payloadValue(transaction, "salt") ?? "") === record.salt
  );
}

function randomnessRecordsChanged(
  previousRecords: RandomnessCommitRecord[],
  nextRecords: RandomnessCommitRecord[],
): boolean {
  return JSON.stringify(previousRecords) !== JSON.stringify(nextRecords);
}

function markRandomnessRecordPending(record: RandomnessCommitRecord): RandomnessCommitRecord {
  return {
    ...record,
    status: "pending",
    staleReason: undefined,
  };
}

function markRandomnessRecordRevealed(record: RandomnessCommitRecord): RandomnessCommitRecord {
  return {
    ...record,
    status: "revealed",
    revealedAt: record.revealedAt ?? new Date().toISOString(),
    staleReason: undefined,
  };
}

function markRandomnessRecordStale(record: RandomnessCommitRecord, staleReason: string): RandomnessCommitRecord {
  return {
    ...record,
    status: "stale",
    staleReason,
  };
}

async function reconcileRandomnessCommitRecords(
  apiPort: number,
  records: RandomnessCommitRecord[],
  walletAddress: string | null | undefined,
  pendingTransactions: TransactionPayload[],
): Promise<RandomnessCommitRecord[]> {
  if (!walletAddress || records.length === 0) {
    return records;
  }

  const requestIds = [...new Set(records.map((record) => record.requestId).filter(Boolean))];
  if (requestIds.length === 0) {
    return records;
  }

  const chainStateEntries = await Promise.all(
    requestIds.map(async (requestId) => {
      const [commitments, reveals] = await Promise.all([
        readCommitments(apiPort, requestId),
        readReveals(apiPort, requestId),
      ]);
      return [requestId, { commitments: commitments.commitments, reveals: reveals.reveals }] as const;
    }),
  );
  const chainStateByRequestId = new Map(chainStateEntries);

  return records.map((record) => {
    const chainState = chainStateByRequestId.get(record.requestId);
    const canonicalCommitmentHash = chainState?.commitments[walletAddress]?.toLowerCase();
    const canonicalReveal = chainState?.reveals[walletAddress];
    const canonicalRevealCommitmentHash = canonicalReveal?.commitment_hash?.toLowerCase();
    const localCommitmentHash = record.commitmentHash.toLowerCase();

    if (canonicalReveal !== undefined) {
      if (canonicalRevealCommitmentHash === undefined || canonicalRevealCommitmentHash === localCommitmentHash) {
        return markRandomnessRecordRevealed(record);
      }
      return markRandomnessRecordStale(record, "On-chain reveal exists for a different commitment.");
    }

    if (pendingTransactions.some((transaction) => pendingTransactionMatchesReveal(transaction, record, walletAddress))) {
      return markRandomnessRecordRevealed(record);
    }

    if (canonicalCommitmentHash === localCommitmentHash) {
      return markRandomnessRecordPending(record);
    }

    if (pendingTransactions.some((transaction) => pendingTransactionMatchesCommit(transaction, record, walletAddress))) {
      return markRandomnessRecordPending(record);
    }

    if (canonicalCommitmentHash === undefined) {
      return markRandomnessRecordStale(record, "Commitment is not on the canonical chain.");
    }

    return markRandomnessRecordStale(record, "Canonical commitment hash differs from this local record.");
  });
}

function isRandomnessChainStateError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return (
    /reveal already exists/i.test(message)
    || /no prior commitment/i.test(message)
    || /seed does not match prior commitment/i.test(message)
  );
}

function displayReference(value: string | null | undefined, _length = 16): { value: string; title?: string } {
  if (!value) {
    return { value: "-" };
  }
  return {
    value,
    title: value,
  };
}

function referenceDisplay(
  value: string | number | null | undefined,
  prefix = "",
  suffix = "",
): string {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return `${prefix}${String(value)}${suffix}`;
}

function referenceTitle(value: string | number | null | undefined, title?: string): string | undefined {
  if (title !== undefined) {
    return title;
  }
  if (value === null || value === undefined || value === "") {
    return undefined;
  }
  return String(value);
}

function ReferenceText({
  value,
  title,
  prefix,
  suffix,
}: {
  value: string | number | null | undefined;
  title?: string;
  prefix?: string;
  suffix?: string;
}) {
  return (
    <span className="reference-text" title={referenceTitle(value, title)}>
      {referenceDisplay(value, prefix, suffix)}
    </span>
  );
}

function ReferenceCode({
  value,
  title,
  prefix,
  suffix,
}: {
  value: string | number | null | undefined;
  title?: string;
  prefix?: string;
  suffix?: string;
}) {
  return (
    <code className="reference-text" title={referenceTitle(value, title)}>
      {referenceDisplay(value, prefix, suffix)}
    </code>
  );
}

function ReferenceStrong({
  value,
  title,
  prefix,
  suffix,
}: {
  value: string | number | null | undefined;
  title?: string;
  prefix?: string;
  suffix?: string;
}) {
  return (
    <strong className="reference-text" title={referenceTitle(value, title)}>
      {referenceDisplay(value, prefix, suffix)}
    </strong>
  );
}

function isMiningRewardTransaction(transaction: TransactionPayload): boolean {
  return transaction.sender === MINING_REWARD_SENDER;
}

function transactionKindLabel(transaction: TransactionPayload): string {
  if (isMiningRewardTransaction(transaction)) {
    return "Mining Reward";
  }
  const kind = transactionKind(transaction);
  if (kind === "deploy") {
    return "Contract Deploy";
  }
  if (kind === "execute") {
    return "Contract Execute";
  }
  if (kind === "authorize") {
    return "Authorization";
  }
  if (kind === "commit") {
    return "Commit";
  }
  if (kind === "reveal") {
    return "Reveal";
  }
  return kind === "transfer" ? "Transfer" : kind;
}

function transactionRows(transaction: TransactionPayload): Array<{ label: string; value: string; title?: string }> {
  const kind = transactionKind(transaction);
  const rows: Array<{ label: string; value: string; title?: string }> = [];
  const pushReference = (label: string, value: string | null | undefined, length = 16) => {
    rows.push({ label, ...displayReference(value, length) });
  };
  const pushValue = (label: string, value: string | null | undefined) => {
    if (value) {
      rows.push({ label, value });
    }
  };

  if (isMiningRewardTransaction(transaction)) {
    pushReference("Miner", transaction.receiver, 18);
    pushValue("Reward", transaction.amount);
  } else if (kind === "deploy") {
    pushReference("Deployer", transaction.sender, 14);
    pushReference("Contract", payloadValue(transaction, "contract_address") ?? transaction.receiver, 14);
    pushReference("Code Hash", payloadValue(transaction, "code_hash"), 14);
    pushValue("Fee", transaction.fee);
  } else if (kind === "execute") {
    pushReference("Caller", transaction.sender, 14);
    pushReference("Contract", payloadValue(transaction, "contract_address") ?? transaction.receiver, 14);
    pushValue("Value", payloadValue(transaction, "value") ?? transaction.amount);
    pushValue("Gas", payloadValue(transaction, "gas_limit"));
    pushValue("Fee", transaction.fee);
  } else if (kind === "authorize") {
    pushReference("Wallet", transaction.sender, 14);
    pushReference("Contract", payloadValue(transaction, "contract_address") ?? transaction.receiver, 14);
    pushValue("Request", payloadValue(transaction, "request_id"));
    pushValue("Fee", transaction.fee);
  } else if (kind === "commit" || kind === "reveal") {
    pushReference("Wallet", transaction.sender, 14);
    pushValue("Request", payloadValue(transaction, "request_id"));
    pushValue("Fee", transaction.fee);
  } else {
    pushReference("From", transaction.sender, 14);
    pushReference("To", transaction.receiver, 14);
    pushValue("Amount", transaction.amount);
    pushValue("Fee", transaction.fee);
  }

  rows.push({ label: "Nonce", value: String(transaction.nonce) });
  rows.push({ label: "Tx", ...displayReference(transaction.transaction_id, 14) });
  return rows;
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
}

function miningStatusNeedsSnapshotRefresh(status: MiningStatus, snapshot: Snapshot): boolean {
  const snapshotTipHash = snapshot.chainHead?.state_tip_hash ?? snapshot.chainHead?.tip_hash ?? null;
  const statusTipHash = status.state_tip_hash ?? status.tip_hash;
  if (statusTipHash != null && statusTipHash !== snapshotTipHash) {
    return true;
  }

  const lastMinedBlockHash = status.last_block.block_hash;
  if (lastMinedBlockHash === null) {
    return false;
  }
  return !snapshot.blocks.some((block) => block.block_hash === lastMinedBlockHash);
}

function parsePeerAddress(peer: string): { host: string; port: number } | null {
  const [host, rawPort] = peer.split(":");
  const port = Number(rawPort);
  if (!host || !Number.isInteger(port)) {
    return null;
  }
  return { host, port };
}

function isLocalBootstrapPeer(
  peer: string,
  nodeConfig: NodeRuntimeState["config"],
  localAddresses: string[],
): boolean {
  const parsedPeer = parsePeerAddress(peer);
  if (parsedPeer === null || nodeConfig === null || parsedPeer.port !== nodeConfig.port) {
    return false;
  }

  const localAddressSet = new Set([
    ...localAddresses,
    nodeConfig.host,
  ].map((address) => address.toLowerCase()));
  return localAddressSet.has(parsedPeer.host.toLowerCase());
}

function peerConnectErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function readablePeerConnectError(error: unknown): Pick<BootstrapAttempt, "detail" | "rawDetail"> {
  const rawDetail = peerConnectErrorMessage(error);
  const cleaned = rawDetail
    .replace(/^Error invoking remote method 'node-api:fetch':\s*/i, "")
    .replace(/^Error:\s*/i, "")
    .trim();

  if (/timed out connecting to peer/i.test(cleaned)) {
    return { detail: "Timed out", rawDetail };
  }
  if (/failed to fetch|fetch failed|node api unavailable/i.test(cleaned)) {
    return { detail: "Node API unavailable", rawDetail };
  }
  if (/connection refused|could not connect|not reachable|network is unreachable/i.test(cleaned)) {
    return { detail: "Not reachable", rawDetail };
  }
  if (/invalid peer|invalid address/i.test(cleaned)) {
    return { detail: "Invalid address", rawDetail };
  }
  if (/rejected|unauthorized|forbidden/i.test(cleaned)) {
    return { detail: "Rejected", rawDetail };
  }

  return { detail: "Failed", rawDetail };
}

function bootstrapAttemptLabel(attempt: BootstrapAttempt): string {
  if (attempt.detail) {
    return attempt.detail;
  }
  if (attempt.status === "pending") {
    return "waiting";
  }
  return attempt.status;
}

function normalizePreferredPort(value: unknown): number {
  const port = Number(value);
  if (Number.isInteger(port) && port > 0 && port < 65536) {
    return port;
  }
  return DEFAULT_PORT;
}

function requireUiPort(value: string, label: string): number {
  const port = Number(value);
  if (Number.isInteger(port) && port > 0 && port < 65536) {
    return port;
  }
  throw new Error(`${label} must be between 1 and 65535.`);
}

function apiPortForNodePort(port: number): number {
  const apiPort = port + 10000;
  if (apiPort > 65535) {
    throw new Error("P2P port must be at most 55535 when the API port is derived as P2P + 10000.");
  }
  return apiPort;
}

function App() {
  if (!window.unccoinDesktop) {
    return (
      <main className="bridge-fallback">
        <section>
          <h1>UncCoin Desktop</h1>
          <p>Desktop bridge unavailable. Launch the app with ./scripts/desktop.sh.</p>
        </section>
      </main>
    );
  }

  const [activeTab, setActiveTab] = useState<TabId>("blockchain");
  const [wallets, setWallets] = useState<WalletSummary[]>([]);
  const [walletName, setWalletName] = useState("");
  const [walletSearch, setWalletSearch] = useState("");
  const [newWalletName, setNewWalletName] = useState("");
  const [newWalletPreferredPort, setNewWalletPreferredPort] = useState(String(DEFAULT_PORT));
  const [walletDeleteCandidate, setWalletDeleteCandidate] = useState("");
  const [walletKeysVisible, setWalletKeysVisible] = useState(false);
  const [walletKeys, setWalletKeys] = useState<WalletKeyDetails | null>(null);
  const [host, setHost] = useState("127.0.0.1");
  const [port, setPort] = useState(String(DEFAULT_PORT));
  const [apiPort, setApiPort] = useState(String(DEFAULT_PORT + 10000));
  const [launchPeers, setLaunchPeers] = useState("");
  const [nodeState, setNodeState] = useState<NodeRuntimeState>({
    running: false,
    pid: null,
    config: null,
  });
  const [logs, setLogs] = useState<NodeLogEntry[]>([]);
  const [snapshot, setSnapshot] = useState<Snapshot>(() => emptySnapshot());
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [apiStatus, setApiStatus] = useState("offline");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [startupPhase, setStartupPhase] = useState<StartupPhase>("idle");
  const [startupComplete, setStartupComplete] = useState(false);
  const [bootstrapAttempts, setBootstrapAttempts] = useState<BootstrapAttempt[]>([]);
  const [networkBootstrapAttempts, setNetworkBootstrapAttempts] = useState<BootstrapAttempt[]>([]);
  const [networkEvents, setNetworkEvents] = useState<NetworkEvent[]>([]);
  const [unreadNetworkEventCount, setUnreadNetworkEventCount] = useState(0);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [miningStatus, setMiningStatus] = useState<MiningStatus | null>(null);
  const [miningBackends, setMiningBackends] = useState<MiningBackendsResponse | null>(null);
  const [miningBackendsLoading, setMiningBackendsLoading] = useState(false);
  const [miningBackendsError, setMiningBackendsError] = useState<string | null>(null);
  const [warmMinerOnStartup, setWarmMinerOnStartup] = useState(true);
  const [blockchainSearch, setBlockchainSearch] = useState("");
  const [blockchainWindow, setBlockchainWindow] = useState<BlockchainWindow | null>(null);
  const [blockchainSearchError, setBlockchainSearchError] = useState<string | null>(null);
  const [activeContractSubTab, setActiveContractSubTab] = useState<ContractSubTab>("deploy");
  const [activeDeploySubTab, setActiveDeploySubTab] = useState<DeploySubTab>("raw");
  const [seenReceivedMessageCount, setSeenReceivedMessageCount] = useState(0);
  const [seenBlockHeight, setSeenBlockHeight] = useState<number | null>(null);
  const [randomnessCommits, setRandomnessCommits] = useState<RandomnessCommitRecord[]>([]);
  const [localAddresses, setLocalAddresses] = useState<string[]>([]);
  const [disabledBootstrapPeers, setDisabledBootstrapPeers] = useState<string[]>([]);
  const latestSnapshotRef = useRef<Snapshot>(snapshot);
  const randomnessCommitsRef = useRef<RandomnessCommitRecord[]>([]);
  const lastRandomnessReconcileKeyRef = useRef("");
  const previousConnectedPeersRef = useRef<string[] | null>(null);
  const snapshotRefreshRef = useRef<Promise<void> | null>(null);
  const snapshotRefreshQueuedRef = useRef(false);
  const coinflipDeadlineInitializedRef = useRef(false);
  const previousCoinflipWalletRef = useRef<string | null>(null);

  const [txReceiver, setTxReceiver] = useState("");
  const [txAmount, setTxAmount] = useState("1");
  const [txFee, setTxFee] = useState("0");
  const [mineDescription, setMineDescription] = useState("");
  const [peerAddress, setPeerAddress] = useState("");
  const [messageReceiver, setMessageReceiver] = useState("");
  const [messageContent, setMessageContent] = useState("");
  const [aliasWallet, setAliasWallet] = useState("");
  const [aliasName, setAliasName] = useState("");
  const [autosendTarget, setAutosendTarget] = useState("");
  const [commitRequestId, setCommitRequestId] = useState("");
  const [commitSeed, setCommitSeed] = useState("");
  const [commitSalt, setCommitSalt] = useState("");
  const [commitFee, setCommitFee] = useState("0");
  const [revealRequestId, setRevealRequestId] = useState("");
  const [revealSeed, setRevealSeed] = useState("");
  const [revealSalt, setRevealSalt] = useState("");
  const [revealFee, setRevealFee] = useState("0");
  const [deployFee, setDeployFee] = useState("0");
  const [deployJson, setDeployJson] = useState(DEFAULT_DEPLOY_JSON);
  const [selectedContractTemplate, setSelectedContractTemplate] = useState<ContractTemplateId>("coinflip");
  const [coinflipWalletOne, setCoinflipWalletOne] = useState("");
  const [coinflipWalletTwo, setCoinflipWalletTwo] = useState("");
  const [coinflipAmount, setCoinflipAmount] = useState("100");
  const [coinflipRevealDeadline, setCoinflipRevealDeadline] = useState("");
  const [coinflipRequestId, setCoinflipRequestId] = useState(createCoinflipRequestId);
  const [executeContractAddress, setExecuteContractAddress] = useState("");
  const [executeGasLimit, setExecuteGasLimit] = useState("1000");
  const [executeGasPrice, setExecuteGasPrice] = useState("0");
  const [executeValue, setExecuteValue] = useState("0");
  const [executeFee, setExecuteFee] = useState("0");
  const [executeInputJson, setExecuteInputJson] = useState(DEFAULT_EXECUTE_JSON);
  const [showExecuteInputJson, setShowExecuteInputJson] = useState(false);
  const [authContractAddress, setAuthContractAddress] = useState("");
  const [authRequestId, setAuthRequestId] = useState("");
  const [authValidBlocks, setAuthValidBlocks] = useState("");

  const activeApiPort = nodeState.config?.apiPort ?? Number(apiPort);
  const isApiAvailable = nodeState.running && Number.isInteger(activeApiPort);
  const launchPeerList = useMemo(
    () => launchPeers.split(",").map((peer) => peer.trim()).filter(Boolean),
    [launchPeers],
  );
  const coinflipTemplatePreview = useMemo(() => {
    const walletOne = coinflipWalletOne.trim();
    const walletTwo = coinflipWalletTwo.trim();
    const requestId = coinflipRequestId.trim();
    if (!walletOne || !walletTwo || !coinflipAmount.trim() || !coinflipRevealDeadline.trim() || !requestId) {
      return null;
    }
    try {
      return formatJson(buildCoinflipContract({
        walletOne,
        walletTwo,
        amount: parsePositiveIntegerField(coinflipAmount, "Amount"),
        revealDeadline: parseWholeNumberField(coinflipRevealDeadline, "Reveal deadline"),
        requestId,
      }));
    } catch {
      return null;
    }
  }, [coinflipWalletOne, coinflipWalletTwo, coinflipAmount, coinflipRevealDeadline, coinflipRequestId]);
  const filteredWallets = useMemo(() => {
    const query = walletSearch.trim().toLowerCase();
    if (!query) {
      return wallets;
    }
    return wallets.filter((wallet) => (
      wallet.name.toLowerCase().includes(query)
      || wallet.address.toLowerCase().includes(query)
      || String(wallet.preferredPort).includes(query)
    ));
  }, [walletSearch, wallets]);
  const selectedWallet = useMemo(
    () => wallets.find((wallet) => wallet.name === walletName),
    [walletName, wallets],
  );
  const desktopStateKey = useMemo(
    () => snapshot.nodeInfo?.wallet?.address || selectedWallet?.address || "",
    [selectedWallet?.address, snapshot.nodeInfo?.wallet?.address],
  );
  const receivedMessageCount = useMemo(
    () => snapshot.messages.filter((message) => message.direction === "received").length,
    [snapshot.messages],
  );
  const currentConnectedPeers = snapshot.peers.connected;
  const connectedPeerKey = currentConnectedPeers.slice().sort().join("\n");
  const unreadMessageCount = Math.max(0, receivedMessageCount - seenReceivedMessageCount);
  const blockchainCurrentHeight = snapshot.chainHead?.height ?? null;
  const unreadBlockCount = (
    blockchainCurrentHeight !== null
    && blockchainCurrentHeight >= 0
    && seenBlockHeight !== null
      ? Math.max(0, blockchainCurrentHeight - seenBlockHeight)
      : 0
  );
  const pendingRandomnessCommits = useMemo(
    () => randomnessCommits.filter((record) => record.status === "pending").reverse(),
    [randomnessCommits],
  );
  const finishedRandomnessCommits = useMemo(
    () => randomnessCommits.filter((record) => record.status === "revealed").reverse(),
    [randomnessCommits],
  );
  const staleRandomnessCommits = useMemo(
    () => randomnessCommits.filter((record) => record.status === "stale").reverse(),
    [randomnessCommits],
  );
  const isPreferredPortDirty = (
    selectedWallet !== undefined
    && Number(port) !== selectedWallet.preferredPort
  );
  const newWalletApiPort = useMemo(() => {
    const preferredPort = Number(newWalletPreferredPort);
    if (!Number.isInteger(preferredPort) || preferredPort <= 0 || preferredPort > 55535) {
      return "-";
    }
    return String(apiPortForNodePort(preferredPort));
  }, [newWalletPreferredPort]);
  const enabledBootstrapPeers = useMemo(
    () => BOOTSTRAP_PEERS.filter((peer) => !disabledBootstrapPeers.includes(peer)),
    [disabledBootstrapPeers],
  );

  const refreshWallets = useCallback(async () => {
    const nextWallets = await window.unccoinDesktop.listWallets();
    setWallets(nextWallets);
    setWalletName((current) => (
      nextWallets.some((wallet) => wallet.name === current) ? current : ""
    ));
  }, []);

  const markReceivedMessagesSeen = useCallback(async (messageCount: number) => {
    if (!desktopStateKey) {
      return;
    }
    const normalizedMessageCount = Math.max(0, messageCount);
    setSeenReceivedMessageCount(normalizedMessageCount);
    await window.unccoinDesktop.updateDesktopState(desktopStateKey, {
      seenReceivedMessageCount: normalizedMessageCount,
    });
  }, [desktopStateKey]);

  const markBlockchainSeen = useCallback(async (blockHeight: number) => {
    if (!desktopStateKey) {
      return;
    }
    const normalizedBlockHeight = Math.max(-1, blockHeight);
    setSeenBlockHeight(normalizedBlockHeight);
    await window.unccoinDesktop.updateDesktopState(desktopStateKey, {
      seenBlockHeight: normalizedBlockHeight,
    });
  }, [desktopStateKey]);

  const saveRandomnessCommits = useCallback(async (records: RandomnessCommitRecord[]) => {
    randomnessCommitsRef.current = records;
    setRandomnessCommits(records);
    if (!desktopStateKey) {
      return;
    }
    const nextState = await window.unccoinDesktop.updateDesktopState(desktopStateKey, {
      randomnessCommits: records,
    });
    randomnessCommitsRef.current = nextState.randomnessCommits;
    setRandomnessCommits(nextState.randomnessCommits);
  }, [desktopStateKey]);

  const reconcileRandomnessCommits = useCallback(async (
    apiPortToUse: number,
    walletAddress: string | null | undefined,
    pendingTransactions: TransactionPayload[],
    chainReference: string | number | null | undefined,
    force = false,
  ) => {
    const currentRecords = randomnessCommitsRef.current;
    if (!walletAddress || currentRecords.length === 0) {
      return currentRecords;
    }

    const reconcileKey = JSON.stringify({
      walletAddress,
      records: currentRecords.map((record) => ({
        id: record.id,
        requestId: record.requestId,
        commitmentHash: record.commitmentHash,
        status: record.status,
      })),
      pending: pendingTransactions.map((transaction) => transaction.transaction_id),
      chainReference,
      apiPortToUse,
    });
    if (!force && reconcileKey === lastRandomnessReconcileKeyRef.current) {
      return currentRecords;
    }

    const nextRecords = await reconcileRandomnessCommitRecords(
      apiPortToUse,
      currentRecords,
      walletAddress,
      pendingTransactions,
    );
    lastRandomnessReconcileKeyRef.current = reconcileKey;
    if (randomnessRecordsChanged(currentRecords, nextRecords)) {
      await saveRandomnessCommits(nextRecords);
    }
    return nextRecords;
  }, [saveRandomnessCommits]);

  const loadSnapshot = useCallback(async (apiPortToUse: number) => {
    const chainHead = await readChainHead(apiPortToUse);
    const recentBlockStartHeight = Math.max(0, chainHead.height - RECENT_BLOCK_LIMIT + 1);
    const [
      nodeInfo,
      balances,
      peers,
      networkStats,
      pendingTransactions,
      blocks,
      messages,
      contracts,
      receipts,
      authorizations,
      mining,
    ] = await Promise.all([
      readNodeInfo(apiPortToUse),
      readBalances(apiPortToUse),
      readPeers(apiPortToUse),
      readNetworkStats(apiPortToUse),
      readPendingTransactions(apiPortToUse),
      readBlocks(apiPortToUse, RECENT_BLOCK_LIMIT, recentBlockStartHeight),
      readMessages(apiPortToUse),
      readContracts(apiPortToUse),
      readReceipts(apiPortToUse),
      readAuthorizations(apiPortToUse),
      readMiningStatus(apiPortToUse),
    ]);

    const nextSnapshot = {
      nodeInfo,
      chainHead,
      balances: balances.balances,
      peers,
      networkStats,
      pendingTransactions: pendingTransactions.transactions,
      blocks: blocks.blocks,
      messages: messages.messages,
      contracts: contracts.contracts,
      receipts: receipts.receipts,
      authorizations: authorizations.authorizations,
    };
    latestSnapshotRef.current = nextSnapshot;
    setSnapshot(nextSnapshot);
    setMiningStatus(mining);
    setMiningBackends((currentBackends) => (
      currentBackends === null
        ? currentBackends
        : {
          ...currentBackends,
          selected: mining.backend,
          warmup: mining.warmup,
        }
    ));
    if (nodeInfo.sync) {
      setSyncStatus(nodeInfo.sync);
    }
    setApiStatus("live");
    try {
      await reconcileRandomnessCommits(
        apiPortToUse,
        nodeInfo.wallet?.address,
        pendingTransactions.transactions,
        chainHead.state_tip_hash ?? chainHead.tip_hash ?? chainHead.height,
      );
    } catch (reconcileError) {
      console.warn("Failed to reconcile randomness records", reconcileError);
    }
  }, [reconcileRandomnessCommits]);

  const refreshSnapshot = useCallback(async () => {
    if (!isApiAvailable) {
      setApiStatus("offline");
      return;
    }

    if (snapshotRefreshRef.current !== null) {
      snapshotRefreshQueuedRef.current = true;
      await snapshotRefreshRef.current;
      return;
    }

    const apiPortToUse = activeApiPort;
    const refreshPromise = (async () => {
      try {
        do {
          snapshotRefreshQueuedRef.current = false;
          await loadSnapshot(apiPortToUse);
        } while (snapshotRefreshQueuedRef.current);
      } finally {
        snapshotRefreshRef.current = null;
      }
    })();
    snapshotRefreshRef.current = refreshPromise;
    await refreshPromise;
  }, [activeApiPort, isApiAvailable, loadSnapshot]);

  const refreshMiningBackends = useCallback(async (apiPortToUse = activeApiPort) => {
    setMiningBackendsLoading(true);
    setMiningBackendsError(null);
    try {
      const response = await readMiningBackends(apiPortToUse);
      setMiningBackends(response);
      return response;
    } catch (backendError) {
      const message = backendError instanceof Error ? backendError.message : String(backendError);
      setMiningBackendsError(message);
      throw backendError;
    } finally {
      setMiningBackendsLoading(false);
    }
  }, [activeApiPort]);

  function applyWalletSelection(walletNameToSelect: string, availableWallets = wallets) {
    setWalletName(walletNameToSelect);
    setWalletDeleteCandidate("");
    const selectedWallet = availableWallets.find((wallet) => wallet.name === walletNameToSelect);
    if (selectedWallet === undefined) {
      return;
    }
    const preferredPort = normalizePreferredPort(selectedWallet.preferredPort);
    setPort(String(preferredPort));
    setApiPort(String(preferredPort + 10000));
  }

  function toggleBootstrapPeer(peer: string) {
    setDisabledBootstrapPeers((currentPeers) => (
      currentPeers.includes(peer)
        ? currentPeers.filter((currentPeer) => currentPeer !== peer)
        : [...currentPeers, peer]
    ));
  }

  const resetSnapshot = useCallback(() => {
    const nextSnapshot = emptySnapshot();
    latestSnapshotRef.current = nextSnapshot;
    setSnapshot(nextSnapshot);
  }, []);

  useEffect(() => {
    randomnessCommitsRef.current = randomnessCommits;
  }, [randomnessCommits]);

  useEffect(() => {
    const walletAddress = snapshot.nodeInfo?.wallet?.address;
    if (walletAddress && previousCoinflipWalletRef.current !== walletAddress) {
      setCoinflipWalletOne(walletAddress);
      previousCoinflipWalletRef.current = walletAddress;
    }
  }, [snapshot.nodeInfo?.wallet?.address]);

  useEffect(() => {
    if (coinflipDeadlineInitializedRef.current || coinflipRevealDeadline.trim()) {
      return;
    }
    if (typeof snapshot.chainHead?.height !== "number" || snapshot.chainHead.height < 0) {
      return;
    }
    setCoinflipRevealDeadline(String(snapshot.chainHead.height + COINFLIP_REVEAL_DEADLINE_BLOCKS));
    coinflipDeadlineInitializedRef.current = true;
  }, [coinflipRevealDeadline, snapshot.chainHead?.height]);

  useEffect(() => {
    if (!desktopStateKey) {
      setSeenReceivedMessageCount(0);
      setSeenBlockHeight(null);
      randomnessCommitsRef.current = [];
      setRandomnessCommits([]);
      return undefined;
    }

    let cancelled = false;
    window.unccoinDesktop.readDesktopState(desktopStateKey)
      .then((state) => {
        if (!cancelled) {
          setSeenReceivedMessageCount(state.seenReceivedMessageCount);
          setSeenBlockHeight(state.seenBlockHeight);
          randomnessCommitsRef.current = state.randomnessCommits;
          setRandomnessCommits(state.randomnessCommits);
        }
      })
      .catch((stateError) => {
        if (!cancelled) {
          setError(String(stateError));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [desktopStateKey]);

  useEffect(() => {
    setWalletKeysVisible(false);
    setWalletKeys(null);
  }, [walletName]);

  useEffect(() => {
    if (
      activeTab !== "messages"
      || !desktopStateKey
      || receivedMessageCount <= seenReceivedMessageCount
    ) {
      return;
    }

    void markReceivedMessagesSeen(receivedMessageCount).catch((stateError) => {
      setError(String(stateError));
    });
  }, [
    activeTab,
    desktopStateKey,
    markReceivedMessagesSeen,
    receivedMessageCount,
    seenReceivedMessageCount,
  ]);

  useEffect(() => {
    if (
      !desktopStateKey
      || blockchainCurrentHeight === null
      || blockchainCurrentHeight < 0
    ) {
      return;
    }

    if (seenBlockHeight === null) {
      void markBlockchainSeen(blockchainCurrentHeight).catch((stateError) => {
        setError(String(stateError));
      });
      return;
    }

    if (activeTab !== "blockchain" || blockchainCurrentHeight <= seenBlockHeight) {
      return;
    }

    void markBlockchainSeen(blockchainCurrentHeight).catch((stateError) => {
      setError(String(stateError));
    });
  }, [
    activeTab,
    blockchainCurrentHeight,
    desktopStateKey,
    markBlockchainSeen,
    seenBlockHeight,
  ]);

  useEffect(() => {
    if (!nodeState.running || !isApiAvailable) {
      previousConnectedPeersRef.current = null;
      return;
    }

    const nextConnectedPeers = connectedPeerKey ? connectedPeerKey.split("\n") : [];
    const previousConnectedPeers = previousConnectedPeersRef.current;
    previousConnectedPeersRef.current = nextConnectedPeers;

    if (previousConnectedPeers === null) {
      return;
    }

    const nextConnectedSet = new Set(nextConnectedPeers);
    const previousConnectedSet = new Set(previousConnectedPeers);
    const connectedPeers = nextConnectedPeers.filter((peer) => !previousConnectedSet.has(peer));
    const disconnectedPeers = previousConnectedPeers.filter((peer) => !nextConnectedSet.has(peer));
    if (connectedPeers.length === 0 && disconnectedPeers.length === 0) {
      return;
    }

    const timestamp = new Date().toISOString();
    const connectedEvents = connectedPeers.map((peer, index): NetworkEvent => ({
      id: `${timestamp}-connected-${index}-${peer}`,
      type: "connected",
      peer,
      timestamp,
    }));
    const disconnectedEvents = disconnectedPeers.map((peer, index): NetworkEvent => ({
      id: `${timestamp}-disconnected-${index}-${peer}`,
      type: "disconnected",
      peer,
      timestamp,
    }));
    const nextEvents = [...connectedEvents, ...disconnectedEvents];

    setNetworkEvents((currentEvents) => [...nextEvents, ...currentEvents].slice(0, 30));
    if (activeTab !== "network") {
      setUnreadNetworkEventCount((currentCount) => currentCount + nextEvents.length);
    }
    if (nextEvents.length === 1) {
      setNotice(nextEvents[0].type === "connected"
        ? `Peer connected: ${nextEvents[0].peer}`
        : `Peer disconnected: ${nextEvents[0].peer}`);
      return;
    }
    setNotice(`${connectedEvents.length} connected, ${disconnectedEvents.length} disconnected`);
  }, [activeTab, connectedPeerKey, isApiAvailable, nodeState.running]);

  useEffect(() => {
    if (activeTab === "network" && unreadNetworkEventCount > 0) {
      setUnreadNetworkEventCount(0);
    }
  }, [activeTab, unreadNetworkEventCount]);

  useEffect(() => {
    void refreshWallets().catch((walletError) => {
      setError(String(walletError));
    });
    window.unccoinDesktop.getLocalAddresses().then(setLocalAddresses).catch((addressError) => {
      setError(String(addressError));
    });
    window.unccoinDesktop.getNodeState().then(setNodeState).catch((stateError) => {
      setError(String(stateError));
    });
    const removeLogListener = window.unccoinDesktop.onNodeLog((entry) => {
      setLogs((currentLogs) => [...currentLogs.slice(-500), entry]);
    });
    const removeStateListener = window.unccoinDesktop.onNodeState(setNodeState);
    return () => {
      removeLogListener();
      removeStateListener();
    };
  }, [refreshWallets]);

  useEffect(() => {
    if (!isApiAvailable) {
      resetSnapshot();
      setApiStatus("offline");
      setMiningStatus(null);
      setMiningBackends(null);
      setMiningBackendsLoading(false);
      setMiningBackendsError(null);
      return undefined;
    }
    if (!startupComplete) {
      setApiStatus("starting");
      return undefined;
    }

    let cancelled = false;
    const poll = async () => {
      try {
        await refreshSnapshot();
      } catch {
        if (!cancelled) {
          setApiStatus(
            miningStatus?.active === true || miningStatus?.automine.running === true
              ? "busy"
              : "starting",
          );
        }
      }
    };

    void poll();
    const interval = window.setInterval(() => {
      void poll();
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [
    isApiAvailable,
    miningStatus?.active,
    miningStatus?.automine.running,
    refreshSnapshot,
    resetSnapshot,
    startupComplete,
  ]);

  useEffect(() => {
    if (
      !nodeState.running
      || startupComplete
      || busyAction === "start-node"
      || busyAction === "create-wallet"
    ) {
      return undefined;
    }

    const apiPortToUse = nodeState.config?.apiPort ?? Number(apiPort);
    if (!Number.isInteger(apiPortToUse)) {
      return undefined;
    }

    let cancelled = false;
    const reattachRunningNode = async () => {
      setStartupPhase("waiting-api");
      setApiStatus("starting");

      while (!cancelled) {
        try {
          await waitForNodeApi(apiPortToUse);
          if (cancelled) {
            return;
          }
          await loadSnapshot(apiPortToUse);
          if (cancelled) {
            return;
          }
          setStartupPhase("ready");
          setStartupComplete(true);
          return;
        } catch {
          if (!cancelled) {
            setApiStatus("busy");
            await delay(1500);
          }
        }
      }
    };

    void reattachRunningNode();
    return () => {
      cancelled = true;
    };
  }, [
    apiPort,
    busyAction,
    loadSnapshot,
    nodeState.config?.apiPort,
    nodeState.running,
    startupComplete,
  ]);

  useEffect(() => {
    const shouldPollMiningFast = (
      isApiAvailable
      && (
        busyAction === "mine-block"
        || busyAction === "warm-miner"
        || miningStatus?.active === true
        || miningStatus?.automine.running === true
        || miningStatus?.warmup.active === true
      )
    );
    if (!shouldPollMiningFast) {
      return undefined;
    }

    let cancelled = false;
    const pollMining = async () => {
      try {
        const status = await readMiningStatus(activeApiPort);
        if (!cancelled) {
          setMiningStatus(status);
          setMiningBackends((currentBackends) => (
            currentBackends === null
              ? currentBackends
              : {
                ...currentBackends,
                selected: status.backend,
                warmup: status.warmup,
              }
          ));
          if (miningStatusNeedsSnapshotRefresh(status, latestSnapshotRef.current)) {
            await refreshSnapshot();
          }
        }
      } catch {
        if (!cancelled) {
          setApiStatus("busy");
        }
      }
    };

    void pollMining();
    const interval = window.setInterval(() => {
      void pollMining();
    }, 500);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [
    activeApiPort,
    busyAction,
    isApiAvailable,
    miningStatus?.active,
    miningStatus?.automine.running,
    miningStatus?.warmup.active,
    refreshSnapshot,
  ]);

  useEffect(() => {
    if (!isApiAvailable || !startupComplete) {
      return;
    }

    void refreshMiningBackends().catch(() => {
      setMiningBackends(null);
    });
  }, [isApiAvailable, refreshMiningBackends, startupComplete]);

  async function waitForNodeApi(apiPortToCheck: number) {
    setStartupPhase("waiting-api");
    setApiStatus("starting");
    for (let attempt = 0; attempt < 60; attempt += 1) {
      try {
        const nodeInfo = await readNodeInfo(apiPortToCheck);
        setSnapshot((currentSnapshot) => {
          const nextSnapshot = {
            ...currentSnapshot,
            nodeInfo,
          };
          latestSnapshotRef.current = nextSnapshot;
          return nextSnapshot;
        });
        if (nodeInfo.sync) {
          setSyncStatus(nodeInfo.sync);
        }
        setApiStatus("live");
        return;
      } catch {
        await delay(500);
      }
    }
    throw new Error(`Node API did not become available on port ${apiPortToCheck}.`);
  }

  async function warmMinerForStartup(apiPortToUse: number) {
    if (!warmMinerOnStartup) {
      return;
    }

    setStartupPhase("warming-miner");
    try {
      const warmup = await startMiningWarmup(apiPortToUse);
      setMiningStatus((currentStatus) => (
        currentStatus === null
          ? currentStatus
          : {
            ...currentStatus,
            warmup,
            backend: warmup.backend,
          }
      ));

      for (let attempt = 0; attempt < 240; attempt += 1) {
        const status = await readMiningStatus(apiPortToUse);
        setMiningStatus(status);
        setMiningBackends((currentBackends) => (
          currentBackends === null
            ? currentBackends
            : {
              ...currentBackends,
              selected: status.backend,
              warmup: status.warmup,
            }
        ));
        if (!status.warmup.active) {
          if (status.warmup.status === "failed") {
            setNotice(`Miner warmup failed; continuing startup. ${status.warmup.error || ""}`.trim());
          }
          return;
        }
        await delay(500);
      }
      setNotice("Miner warmup is still running; continuing startup.");
    } catch (warmupError) {
      setNotice(`Miner warmup skipped after API error: ${warmupError instanceof Error ? warmupError.message : String(warmupError)}`);
    }
  }

  async function connectBootstrapPeers(
    apiPortToUse: number,
    nodeConfig: NodeRuntimeState["config"],
  ): Promise<BootstrapAttempt[]> {
    setStartupPhase("connecting-bootstrap");
    const initialAttempts = BOOTSTRAP_PEERS.map((peer): BootstrapAttempt => (
      disabledBootstrapPeers.includes(peer)
        ? { peer, status: "skipped", detail: "disabled" }
        : isLocalBootstrapPeer(peer, nodeConfig, localAddresses)
        ? { peer, status: "skipped", detail: "local node" }
        : { peer, status: "pending" }
    ));
    setBootstrapAttempts(initialAttempts);

    const attempts = await Promise.all(
      initialAttempts.map(async (attempt): Promise<BootstrapAttempt> => {
        if (attempt.status === "skipped") {
          return attempt;
        }
        try {
          const peer = attempt.peer;
          await connectPeer(apiPortToUse, peer);
          return { peer, status: "connected" };
        } catch (connectError) {
          return {
            peer: attempt.peer,
            status: "failed",
            ...readablePeerConnectError(connectError),
          };
        }
      }),
    );

    setBootstrapAttempts(attempts);
    return attempts;
  }

  async function waitForFastSyncToFinish(apiPortToUse: number) {
    setStartupPhase("fastsync");
    let sawActiveFastSync = false;

    for (let attempt = 0; attempt < 240; attempt += 1) {
      const status = await readSyncStatus(apiPortToUse);
      setSyncStatus(status);

      if (status.fastsync.active) {
        sawActiveFastSync = true;
      } else if (sawActiveFastSync || attempt >= 2) {
        return;
      }

      await delay(1000);
    }

    throw new Error("Fastsync did not finish within 4 minutes.");
  }

  async function finishStartup(
    apiPortToUse: number,
    nodeConfig: NodeRuntimeState["config"],
  ) {
    await waitForNodeApi(apiPortToUse);
    const attempts = await connectBootstrapPeers(apiPortToUse, nodeConfig);
    const connectedBootstrapPeers = attempts.filter((attempt) => attempt.status === "connected");
    const skippedBootstrapPeers = attempts.filter((attempt) => attempt.status === "skipped");

    if (connectedBootstrapPeers.length > 0) {
      const syncResponse = await syncChain(apiPortToUse, true);
      setNotice(`Connected ${connectedBootstrapPeers.length} bootstrap peer(s); fastsync requested from ${syncResponse.requested_peers} peer(s).`);
      await waitForFastSyncToFinish(apiPortToUse);
    } else {
      setNotice(
        enabledBootstrapPeers.length === 0
          ? "All bootstrap peers were disabled for this launch; continuing with the local chain."
          : skippedBootstrapPeers.length > 0
          ? "Skipped this node's bootstrap address; no other bootstrap peers were reachable."
          : "No bootstrap peers were reachable; continuing with the local chain.",
      );
    }

    await warmMinerForStartup(apiPortToUse);
    await loadSnapshot(apiPortToUse);
    setStartupPhase("ready");
    setStartupComplete(true);
  }

  async function runNodeAction(
    label: string,
    action: () => Promise<ActionResult | void>,
    refreshMode: NodeActionRefreshMode = "snapshot",
  ) {
    if (!isApiAvailable) {
      setError("Start the node before running node actions.");
      return;
    }
    setBusyAction(label);
    setError(null);
    setNotice(null);
    try {
      const result = await action();
      setNotice(result ? actionText(result) : label);
      if (refreshMode === "snapshot") {
        await refreshSnapshot();
      } else if (refreshMode === "mining") {
        try {
          const status = await readMiningStatus(activeApiPort);
          setMiningStatus(status);
          setApiStatus("live");
        } catch {
          setApiStatus("busy");
        }
      }
    } catch (actionError) {
      setError(String(actionError));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleCreateWallet(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = newWalletName.trim();
    if (!name) {
      setError("Wallet name is required.");
      return;
    }
    setBusyAction("create-wallet");
    setError(null);
    setNotice(null);
    try {
      const preferredPort = requireUiPort(newWalletPreferredPort, "Preferred port");
      const preferredApiPort = apiPortForNodePort(preferredPort);
      const wallet = await window.unccoinDesktop.createWallet(name, undefined, preferredPort);
      const nextWallets = await window.unccoinDesktop.listWallets();
      setWallets(nextWallets);
      applyWalletSelection(wallet.name, nextWallets);
      setPort(String(preferredPort));
      setApiPort(String(preferredApiPort));
      setWalletSearch("");
      setNewWalletName("");
      await launchWalletNode(
        wallet.name,
        "create-wallet",
        String(preferredPort),
        String(preferredApiPort),
      );
    } catch (walletError) {
      setError(String(walletError));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleSavePreferredPort() {
    if (!walletName) {
      setError("Choose a wallet before saving a preferred port.");
      return;
    }
    setBusyAction("save-preferred-port");
    setError(null);
    setNotice(null);
    try {
      const preferredPort = requireUiPort(port, "P2P port");
      const wallet = await window.unccoinDesktop.updateWalletPreferredPort(walletName, preferredPort);
      const nextWallets = await window.unccoinDesktop.listWallets();
      setWallets(nextWallets);
      applyWalletSelection(wallet.name, nextWallets);
      setNotice(`Saved ${wallet.name} preferred port ${wallet.preferredPort}`);
    } catch (walletError) {
      setError(String(walletError));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleDeleteWallet() {
    if (!walletDeleteCandidate) {
      return;
    }
    setBusyAction("delete-wallet");
    setError(null);
    setNotice(null);
    try {
      const deletedWallet = await window.unccoinDesktop.deleteWallet(walletDeleteCandidate);
      const nextWallets = await window.unccoinDesktop.listWallets();
      setWallets(nextWallets);
      setWalletName("");
      setWalletDeleteCandidate("");
      setNotice(`Moved ${deletedWallet.name} to state/deleted`);
    } catch (walletError) {
      setError(String(walletError));
    } finally {
      setBusyAction(null);
    }
  }

  async function launchWalletNode(
    walletNameToLaunch: string,
    busyLabel: string,
    nodePortValue = port,
    nodeApiPortValue = apiPort,
  ) {
    const nodePort = requireUiPort(nodePortValue, "P2P port");
    const nodeApiPort = requireUiPort(nodeApiPortValue, "API port");

    setWalletName(walletNameToLaunch);
    setBusyAction(busyLabel);
    setStartupPhase("starting-node");
    setStartupComplete(false);
    setBootstrapAttempts([]);
    setNetworkEvents([]);
    setUnreadNetworkEventCount(0);
    previousConnectedPeersRef.current = null;
    setSyncStatus(null);
    setError(null);
    setNotice(null);

    const nextState = await window.unccoinDesktop.startNode({
      walletName: walletNameToLaunch,
      host,
      port: nodePort,
      apiPort: nodeApiPort,
      peers: launchPeerList,
    });
    setNodeState(nextState);
    const startupApiPort = nextState.config?.apiPort ?? nodeApiPort;
    await finishStartup(startupApiPort, nextState.config);
  }

  async function handleStart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await launchWalletNode(walletName, "start-node");
    } catch (startError) {
      setError(String(startError));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleWalletDoubleClick(wallet: WalletSummary) {
    if (busyAction !== null) {
      return;
    }

    const walletWasAlreadySelected = walletName === wallet.name;
    const walletPreferredPort = normalizePreferredPort(wallet.preferredPort);
    const nodePortValue = walletWasAlreadySelected ? port : String(walletPreferredPort);
    const nodeApiPortValue = walletWasAlreadySelected ? apiPort : String(apiPortForNodePort(walletPreferredPort));

    applyWalletSelection(wallet.name);
    try {
      await launchWalletNode(wallet.name, "start-node", nodePortValue, nodeApiPortValue);
    } catch (startError) {
      setError(String(startError));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleStop() {
    setBusyAction("stop-node");
    setError(null);
    setNotice(null);
    try {
      const nextState = await window.unccoinDesktop.stopNode();
      setNodeState(nextState);
      resetSnapshot();
      setApiStatus("offline");
      setStartupPhase("idle");
      setStartupComplete(false);
      setBootstrapAttempts([]);
      setNetworkEvents([]);
      setUnreadNetworkEventCount(0);
      previousConnectedPeersRef.current = null;
      setSyncStatus(null);
      setMiningStatus(null);
      setNotice("Stopped node");
    } catch (stopError) {
      setError(String(stopError));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleRefresh() {
    setError(null);
    try {
      await refreshSnapshot();
    } catch (refreshError) {
      setError(String(refreshError));
    }
  }

  async function focusBlockchainBlock(reference: string, updateSearch = false) {
    if (!isApiAvailable) {
      setBlockchainSearchError("Start the node before searching blocks.");
      return null;
    }

    const targetBlock = await readBlock(activeApiPort, reference);
    const fromHeight = targetBlock.height === 0 ? 0 : targetBlock.height - 1;
    const response = await readBlocks(activeApiPort, BLOCKCHAIN_CONTEXT_BLOCKS, fromHeight);
    const blocks = response.blocks.some((block) => block.block_hash === targetBlock.block_hash)
      ? response.blocks
      : [targetBlock];
    setBlockchainWindow({
      reference,
      targetHash: targetBlock.block_hash,
      targetHeight: targetBlock.height,
      blocks,
    });
    setBlockchainSearchError(null);
    if (updateSearch) {
      setBlockchainSearch(String(targetBlock.height));
    }
    return targetBlock;
  }

  async function handleBlockchainSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const reference = blockchainSearch.trim();
    if (!reference) {
      setBlockchainWindow(null);
      setBlockchainSearchError(null);
      return;
    }
    if (!isApiAvailable) {
      setBlockchainSearchError("Start the node before searching blocks.");
      return;
    }

    setBusyAction("blockchain-search");
    setBlockchainSearchError(null);
    setNotice(null);
    try {
      let resolvedReference = reference;
      let movedToTip = false;
      if (/^\d+$/.test(reference)) {
        const requestedHeight = Number(reference);
        const chainHead = await readChainHead(activeApiPort);
        if (requestedHeight > chainHead.height) {
          if (chainHead.height < 0) {
            setBlockchainSearchError("No blocks are available.");
            return;
          }
          resolvedReference = String(chainHead.height);
          movedToTip = true;
        }
      }
      const targetBlock = await focusBlockchainBlock(resolvedReference);
      if (movedToTip) {
        setBlockchainSearch(String(targetBlock?.height ?? resolvedReference));
        setNotice(`Moved to tip with hash ${targetBlock?.block_hash.slice(0, 8) ?? resolvedReference}`);
      }
    } catch (searchError) {
      setBlockchainSearchError(searchError instanceof Error ? searchError.message : String(searchError));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleBlockchainStep(direction: -1 | 1) {
    if (!isApiAvailable) {
      setBlockchainSearchError("Start the node before navigating blocks.");
      return;
    }

    const currentHeight = blockchainWindow?.targetHeight
      ?? snapshot.chainHead?.height
      ?? (snapshot.blocks.length > 0 ? snapshot.blocks[snapshot.blocks.length - 1].height : null)
      ?? null;
    if (currentHeight === null || currentHeight < 0) {
      setBlockchainSearchError("No blocks are available.");
      return;
    }

    setBusyAction("blockchain-nav");
    setBlockchainSearchError(null);
    setNotice(null);
    try {
      const chainHead = direction > 0 || snapshot.chainHead === null
        ? await readChainHead(activeApiPort)
        : snapshot.chainHead;
      const nextHeight = direction > 0
        ? Math.min(chainHead.height, currentHeight + 1)
        : Math.max(0, currentHeight - 1);
      if (nextHeight === currentHeight) {
        return;
      }
      await focusBlockchainBlock(String(nextHeight), true);
    } catch (stepError) {
      setBlockchainSearchError(stepError instanceof Error ? stepError.message : String(stepError));
    } finally {
      setBusyAction(null);
    }
  }

  function clearBlockchainSearch() {
    setBlockchainSearch("");
    setBlockchainWindow(null);
    setBlockchainSearchError(null);
  }

  async function handleTransaction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("send-transaction", async () => {
      const response = await sendTransaction(activeApiPort, {
        receiver: txReceiver,
        amount: txAmount,
        fee: txFee,
      });
      return { label: "Broadcast transaction", detail: response.transaction_id };
    });
  }

  async function handleMine(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("mine-block", async () => {
      const response = await mineBlock(activeApiPort, mineDescription || undefined);
      return { label: "Mined block", detail: `${response.block.height} ${response.block.block_hash}` };
    });
  }

  async function handleUseMiningBackend(backend: MiningBackendId) {
    await runNodeAction("warm-miner", async () => {
      let backendStatus = miningBackends;
      if (backend !== selectedMiningBackend) {
        backendStatus = await setMiningBackend(activeApiPort, backend);
        setMiningBackends(backendStatus);
      }
      const warmup = await startMiningWarmup(activeApiPort);
      setMiningStatus((currentStatus) => (
        currentStatus === null
          ? currentStatus
          : { ...currentStatus, warmup, backend: warmup.backend }
      ));
      setMiningBackends((currentBackends) => {
        const baseBackends = backendStatus ?? currentBackends;
        return baseBackends === null
          ? baseBackends
          : { ...baseBackends, warmup, selected: warmup.backend };
      });
      return { label: "Miner warmup started", detail: warmup.backend };
    }, "mining");
  }

  async function handleBuildMiningBackend(backend: MiningBackendId) {
    await runNodeAction("build-mining-backend", async () => {
      const response = await buildMiningBackend(activeApiPort, backend);
      setMiningBackends(response.capabilities);
      return { label: "Built miner", detail: response.path };
    }, "none");
  }

  async function handleConnectPeer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("connect-peer", async () => {
      const response = await connectPeer(activeApiPort, peerAddress);
      return { label: "Connected peers", detail: String(response.connected.length) };
    });
  }

  async function handleDisconnectPeer(peer: string) {
    await runNodeAction("disconnect-peer", async () => {
      const response = await disconnectPeer(activeApiPort, peer);
      return { label: "Disconnected peer", detail: peer || String(response.connected.length) };
    });
  }

  async function handleConnectBootstrapPeers() {
    if (!isApiAvailable) {
      setError("Start the node before connecting bootstrap peers.");
      return;
    }

    setBusyAction("connect-bootstrap-peers");
    setError(null);
    setNotice(null);
    const initialAttempts = BOOTSTRAP_PEERS.map((peer): BootstrapAttempt => (
      isLocalBootstrapPeer(peer, nodeState.config, localAddresses)
        ? { peer, status: "skipped", detail: "local node" }
        : { peer, status: "pending" }
    ));
    setNetworkBootstrapAttempts(initialAttempts);

    try {
      const attempts = await Promise.all(
        initialAttempts.map(async (attempt): Promise<BootstrapAttempt> => {
          if (attempt.status === "skipped") {
            return attempt;
          }
          try {
            await connectPeer(activeApiPort, attempt.peer);
            return { peer: attempt.peer, status: "connected" };
          } catch (connectError) {
            return {
              peer: attempt.peer,
              status: "failed",
              ...readablePeerConnectError(connectError),
            };
          }
        }),
      );
      setNetworkBootstrapAttempts(attempts);

      const connectedCount = attempts.filter((attempt) => attempt.status === "connected").length;
      const failedCount = attempts.filter((attempt) => attempt.status === "failed").length;
      const skippedCount = attempts.filter((attempt) => attempt.status === "skipped").length;
      setNotice(
        connectedCount > 0
          ? `Connected ${connectedCount} bootstrap peer(s).`
          : failedCount > 0
          ? "No bootstrap peers were reachable."
          : `Skipped ${skippedCount} local bootstrap peer(s).`,
      );
      await refreshSnapshot();
    } catch (actionError) {
      setError(String(actionError));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("send-message", async () => {
      const response = await sendMessage(activeApiPort, {
        receiver: messageReceiver,
        content: messageContent,
      });
      setMessageContent("");
      return { label: "Sent message", detail: response.message.message_id };
    });
  }

  async function handleAlias(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("set-alias", async () => {
      const response = await setAlias(activeApiPort, {
        wallet: aliasWallet,
        alias: aliasName,
      });
      return { label: "Saved alias", detail: response.alias ?? response.wallet };
    });
  }

  async function handleAutosend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("set-autosend", async () => {
      const response = await setAutosend(activeApiPort, autosendTarget || null);
      return {
        label: response.enabled ? "Autosend enabled" : "Autosend disabled",
        detail: response.target || undefined,
      };
    });
  }

  async function handleCommit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("commit-randomness", async () => {
      const walletAddress = snapshot.nodeInfo?.wallet?.address;
      if (!walletAddress) {
        throw new Error("A loaded wallet is required to commit randomness.");
      }
      const requestId = commitRequestId.trim();
      const seed = normalizeRandomnessSeed(commitSeed);
      const salt = commitSalt.trim();
      const commitmentHash = await createRevealCommitmentHash(
        walletAddress,
        requestId,
        seed,
        salt,
      );
      setRevealRequestId(requestId);
      setRevealSeed(seed);
      setRevealSalt(salt);
      const response = await createCommitment(activeApiPort, {
        request_id: requestId,
        commitment_hash: commitmentHash,
        fee: commitFee,
      });
      const nextRecord: RandomnessCommitRecord = {
        id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        requestId,
        seed,
        salt,
        commitmentHash,
        transactionId: response.transaction_id,
        createdAt: new Date().toISOString(),
        status: "pending",
      };
      await saveRandomnessCommits([...randomnessCommitsRef.current, nextRecord]);
      return { label: "Broadcast commitment", detail: response.transaction_id };
    });
  }

  async function handleRevealSavedCommit(record: RandomnessCommitRecord) {
    await runNodeAction("reveal-randomness", async () => {
      let response;
      try {
        response = await revealCommitment(activeApiPort, {
          request_id: record.requestId,
          seed: record.seed,
          fee: revealFee,
          salt: record.salt,
        });
      } catch (revealError) {
        if (isRandomnessChainStateError(revealError)) {
          const latestSnapshot = latestSnapshotRef.current;
          const reconciledRecords = await reconcileRandomnessCommits(
            activeApiPort,
            latestSnapshot.nodeInfo?.wallet?.address,
            latestSnapshot.pendingTransactions,
            latestSnapshot.chainHead?.state_tip_hash ?? latestSnapshot.chainHead?.tip_hash ?? latestSnapshot.chainHead?.height,
            true,
          );
          const reconciledRecord = reconciledRecords.find((currentRecord) => currentRecord.id === record.id);
          if (reconciledRecord?.status === "revealed") {
            return { label: "Reveal already on chain", detail: record.requestId };
          }
          if (reconciledRecord?.status === "stale") {
            return { label: "Randomness record stale", detail: reconciledRecord.staleReason };
          }
        }
        throw revealError;
      }
      const revealedRecord: RandomnessCommitRecord = {
        ...record,
        status: "revealed",
        revealTransactionId: response.transaction_id,
        revealedAt: new Date().toISOString(),
      };
      await saveRandomnessCommits(
        randomnessCommitsRef.current.map((currentRecord) => (
          currentRecord.id === record.id ? revealedRecord : currentRecord
        )),
      );
      return { label: "Broadcast reveal", detail: response.transaction_id };
    });
  }

  async function handleReveal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("reveal-randomness", async () => {
      const response = await revealCommitment(activeApiPort, {
        request_id: revealRequestId,
        seed: revealSeed,
        fee: revealFee,
        salt: revealSalt,
      });
      return { label: "Broadcast reveal", detail: response.transaction_id };
    });
  }

  async function handleDeploy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("deploy-contract", async () => {
      const parsedDeploy = parseJsonField(deployJson, "Deploy JSON");
      const payload: {
        fee: string;
        program?: unknown;
        metadata?: Record<string, unknown>;
      } = { fee: deployFee };

      if (isRecord(parsedDeploy) && "program" in parsedDeploy) {
        payload.program = parsedDeploy.program;
        payload.metadata = isRecord(parsedDeploy.metadata) ? parsedDeploy.metadata : {};
      } else {
        payload.program = parsedDeploy;
        payload.metadata = {};
      }

      const response = await deployContract(activeApiPort, payload);
      setExecuteContractAddress(response.contract_address ?? "");
      setAuthContractAddress(response.contract_address ?? "");
      return { label: "Broadcast deploy", detail: response.contract_address };
    });
  }

  async function handleDeployTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("deploy-contract", async () => {
      if (selectedContractTemplate !== "coinflip") {
        throw new Error("Choose a contract template.");
      }

      const walletOne = coinflipWalletOne.trim();
      const walletTwo = coinflipWalletTwo.trim();
      const requestId = coinflipRequestId.trim() || createCoinflipRequestId();
      if (!walletOne || !walletTwo) {
        throw new Error("Wallet 1 and wallet 2 are required.");
      }
      if (walletOne === walletTwo) {
        throw new Error("Wallet 1 and wallet 2 must be different.");
      }

      const amount = parsePositiveIntegerField(coinflipAmount, "Amount");
      const revealDeadline = parseWholeNumberField(coinflipRevealDeadline, "Reveal deadline");
      const currentHeight = snapshot.chainHead?.height;
      if (typeof currentHeight === "number" && revealDeadline <= currentHeight) {
        throw new Error(`Reveal deadline must be after current block #${currentHeight}.`);
      }

      const contract = buildCoinflipContract({
        walletOne,
        walletTwo,
        amount,
        revealDeadline,
        requestId,
      });
      const response = await deployContract(activeApiPort, {
        fee: deployFee,
        program: contract.program,
        metadata: contract.metadata,
      });
      setCoinflipRequestId(requestId);
      setExecuteContractAddress(response.contract_address ?? "");
      setAuthContractAddress(response.contract_address ?? "");
      setAuthRequestId(requestId);
      setCommitRequestId(requestId);
      setRevealRequestId(requestId);
      return {
        label: "Broadcast coinflip deploy",
        detail: `${response.contract_address ?? "pending"} request ${requestId}`,
      };
    });
  }

  async function handleExecute(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("execute-contract", async () => {
      const parsedInput = showExecuteInputJson
        ? parseJsonField(executeInputJson, "Execute input JSON")
        : null;
      const response = await executeContract(activeApiPort, {
        contract_address: executeContractAddress,
        gas_limit: executeGasLimit,
        gas_price: executeGasPrice,
        value: executeValue,
        fee: executeFee,
        input: parsedInput,
      });
      return { label: "Broadcast execute", detail: response.transaction_id };
    });
  }

  async function handleAuthorize(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("authorize-contract", async () => {
      const response = await authorizeContract(activeApiPort, {
        contract_address: authContractAddress,
        request_id: authRequestId,
        valid_for_blocks: authValidBlocks || null,
      });
      return { label: "Broadcast authorization", detail: response.transaction_id };
    });
  }

  const isStartingNode = (
    busyAction === "start-node"
    || (busyAction === "create-wallet" && startupPhase !== "idle")
    || (nodeState.running && !startupComplete)
  );
  const launchLogs = logs.slice(-5);
  const activeSyncPeers = syncStatus?.fastsync.peers ?? [];
  const startupStatusLabel = startupPhase.replace("-", " ");
  const startupPhases: StartupPhase[] = [
    "starting-node",
    "waiting-api",
    "connecting-bootstrap",
    "fastsync",
    "warming-miner",
    "ready",
  ];
  const startupPhaseLabels: Record<StartupPhase, string> = {
    idle: "Preparing",
    "starting-node": "Starting Node",
    "waiting-api": "Opening API",
    "warming-miner": "Warming Miner",
    "connecting-bootstrap": "Connecting Peers",
    fastsync: "Syncing Chain",
    ready: "Ready",
  };
  const startupPhaseText: Record<StartupPhase, string> = {
    idle: "Preparing the node process.",
    "starting-node": "Launching the local Python node process.",
    "waiting-api": "The node is running and the local API is warming up.",
    "warming-miner": "Benchmarking the selected miner so the first mined block starts smoothly.",
    "connecting-bootstrap": "Trying the selected bootstrap peers.",
    fastsync: "A bootstrap peer answered; downloading current chain state.",
    ready: "Node is ready.",
  };
  const startupPhaseIndex = Math.max(0, startupPhases.indexOf(startupPhase));
  const previewNodeConfig = {
    walletName,
    host,
    port: Number(port),
    apiPort: Number(apiPort),
    peers: launchPeerList,
  };

  if (!nodeState.running || isStartingNode) {
    return (
      <main className="launch-shell">
        <section className="launch-card">
          {isStartingNode ? (
            <>
              <div className="launch-header startup-hero">
                <div>
                  <h1>{startupPhaseLabels[startupPhase]}</h1>
                  <p>{nodeState.config?.walletName || walletName || "Selected wallet"}</p>
                </div>
                <span className="spinner" aria-label="Starting" />
              </div>
              <div className="startup-progress">
                {startupPhases.map((phase, index) => (
                  <div
                    className={[
                      "startup-step",
                      index < startupPhaseIndex ? "done" : "",
                      index === startupPhaseIndex ? "active" : "",
                    ].filter(Boolean).join(" ")}
                    key={phase}
                  >
                    <span>{index + 1}</span>
                    <strong>{startupPhaseLabels[phase]}</strong>
                  </div>
                ))}
              </div>
              <p className="startup-note">{startupPhaseText[startupPhase]}</p>
              <dl className="launch-details">
                <div>
                  <dt>P2P</dt>
                  <dd>{nodeState.config?.host || host}:{nodeState.config?.port || port}</dd>
                </div>
                <div>
                  <dt>API</dt>
                  <dd>{nodeState.config?.apiPort || apiPort}</dd>
                </div>
                <div>
                  <dt>Status</dt>
                  <dd>{startupStatusLabel}</dd>
                </div>
                <div>
                  <dt>Miner</dt>
                  <dd>
                    {warmMinerOnStartup
                      ? miningStatus?.warmup.status ?? "pending"
                      : "skipped"}
                  </dd>
                </div>
              </dl>
              <div className="bootstrap-panel">
                <h3>Bootstrap Peers</h3>
                <div className="bootstrap-list">
                  {(bootstrapAttempts.length === 0
                    ? BOOTSTRAP_PEERS.map((peer): BootstrapAttempt => ({ peer, status: "pending" }))
                    : bootstrapAttempts
                  ).map((attempt) => (
                    <div className={`peer-status ${attempt.status}`} key={attempt.peer}>
                      <ReferenceCode value={attempt.peer} />
                      <span title={attempt.rawDetail ?? attempt.detail}>{bootstrapAttemptLabel(attempt)}</span>
                    </div>
                  ))}
                </div>
              </div>
              {startupPhase === "fastsync" ? (
                <div className="bootstrap-panel">
                  <h3>Fastsync</h3>
                  {activeSyncPeers.length === 0 ? (
                    <p className="empty">Waiting for fastsync status...</p>
                  ) : (
                    <div className="bootstrap-list">
                      {activeSyncPeers.map((peer) => (
                        <div className="peer-status connected" key={peer.peer}>
                          <ReferenceCode value={peer.peer} />
                          <span>height {peer.expected_start_height}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : null}
              {error ? <p className="launch-error">{error}</p> : null}
              {launchLogs.length > 0 ? (
                <details className="launch-log-details">
                  <summary>Node output</summary>
                  <pre className="launch-log">
                    {launchLogs.map((entry) => `[${entry.stream}] ${entry.message}`).join("")}
                  </pre>
                </details>
              ) : null}
              <div className="button-row">
                <button type="button" onClick={handleStop} disabled={busyAction === "stop-node"}>
                  Stop
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="launch-header">
                <div>
                  <h1>UncCoin Desktop</h1>
                  <p>Start a node from an existing wallet or create a new one.</p>
                </div>
                <span className="status-pill">offline</span>
              </div>

              <div className="launch-split">
                <section className="launch-pane">
                  <div className="pane-title">
                    <h2>Launch Existing Wallet</h2>
                    <p>{walletName || "No wallet selected"}</p>
                  </div>
                  <form className="launch-form" onSubmit={handleStart}>
                    <label>
                      Search Wallets
                      <input
                        value={walletSearch}
                        placeholder="Filter by wallet name, address, or port"
                        onChange={(event) => setWalletSearch(event.target.value)}
                        disabled={busyAction !== null}
                      />
                    </label>

                    <div className="wallet-picker">
                      {wallets.length === 0 ? (
                        <p className="empty">No stored wallets found.</p>
                      ) : filteredWallets.length === 0 ? (
                        <p className="empty">No wallets match this filter.</p>
                      ) : (
                        filteredWallets.map((wallet) => (
                          <button
                            type="button"
                            className={walletName === wallet.name ? "wallet-choice selected" : "wallet-choice"}
                            key={wallet.name}
                            onClick={() => applyWalletSelection(wallet.name)}
                            onDoubleClick={() => void handleWalletDoubleClick(wallet)}
                            disabled={busyAction !== null}
                          >
                            <span>{wallet.name}</span>
                            <ReferenceCode value={wallet.address} />
                            <small>port {wallet.preferredPort}</small>
                          </button>
                        ))
                      )}
                    </div>

                    <div className="field-row">
                      <label>
                        P2P Port
                        <input
                          value={port}
                          inputMode="numeric"
                          onChange={(event) => {
                            setPort(event.target.value);
                            const nextPort = Number(event.target.value || DEFAULT_PORT);
                            setApiPort(String(nextPort + 10000));
                          }}
                          disabled={busyAction !== null}
                        />
                      </label>
                      <label>
                        API Port
                        <input
                          value={apiPort}
                          inputMode="numeric"
                          onChange={(event) => setApiPort(event.target.value)}
                          disabled={busyAction !== null}
                        />
                      </label>
                    </div>

                    <div className="preferred-port-bar">
                      <div>
                        <span>Wallet Preferred Port</span>
                        <strong>{selectedWallet?.preferredPort ?? "-"}</strong>
                      </div>
                      <button
                        type="button"
                        onClick={handleSavePreferredPort}
                        disabled={!walletName || busyAction !== null || !isPreferredPortDirty}
                      >
                        Save Preferred Port
                      </button>
                    </div>

                    {selectedWallet ? (
                      <div className="wallet-delete-zone">
                        {walletDeleteCandidate === selectedWallet.name ? (
                          <>
                            <div>
                              <strong>Move {selectedWallet.name} to deleted wallets?</strong>
                              <span>The wallet JSON will be archived in state/deleted with a timestamp.</span>
                            </div>
                            <div className="button-row">
                              <button
                                type="button"
                                className="danger-button"
                                onClick={() => void handleDeleteWallet()}
                                disabled={busyAction !== null}
                              >
                                Confirm Delete
                              </button>
                              <button
                                type="button"
                                onClick={() => setWalletDeleteCandidate("")}
                                disabled={busyAction !== null}
                              >
                                Cancel
                              </button>
                            </div>
                          </>
                        ) : (
                          <>
                            <div>
                              <strong>{selectedWallet.name}</strong>
                              <span>Delete archives this wallet file without destroying it.</span>
                            </div>
                            <button
                              type="button"
                              className="danger-button"
                              onClick={() => setWalletDeleteCandidate(selectedWallet.name)}
                              disabled={busyAction !== null}
                            >
                              Delete Wallet
                            </button>
                          </>
                        )}
                      </div>
                    ) : null}

                    <button
                      type="submit"
                      className="primary-action"
                      disabled={!walletName || busyAction !== null}
                    >
                      Start Node
                    </button>
                  </form>
                </section>

                <section className="launch-pane create-pane">
                  <div className="pane-title">
                    <h2>Create New Wallet</h2>
                    <p>Saves this port on the wallet and launches the node immediately.</p>
                  </div>
                  <form className="launch-create" onSubmit={handleCreateWallet}>
                    <label>
                      Wallet Name
                      <input
                        value={newWalletName}
                        placeholder="Wallet name"
                        onChange={(event) => setNewWalletName(event.target.value)}
                        disabled={busyAction !== null}
                      />
                    </label>
                    <label>
                      Preferred Port
                      <input
                        value={newWalletPreferredPort}
                        inputMode="numeric"
                        onChange={(event) => setNewWalletPreferredPort(event.target.value)}
                        disabled={busyAction !== null}
                      />
                    </label>
                    <dl className="create-summary">
                      <div>
                        <dt>API Port</dt>
                        <dd>{newWalletApiPort}</dd>
                      </div>
                    </dl>
                    <button type="submit" disabled={!newWalletName.trim() || busyAction !== null || newWalletApiPort === "-"}>
                      Create and Start
                    </button>
                  </form>
                </section>
              </div>

              <section className="bootstrap-panel shared-launch-settings">
                <div className="secondary-title">
                  <h3>Node Settings</h3>
                  <p>Used when launching an existing wallet or creating a new one.</p>
                </div>
                <div className="field-row">
                  <label>
                    Host
                    <input
                      value={host}
                      onChange={(event) => setHost(event.target.value)}
                      disabled={busyAction !== null}
                    />
                  </label>

                  <label>
                    Peers
                    <input
                      value={launchPeers}
                      placeholder="127.0.0.1:9001, 127.0.0.1:9002"
                      onChange={(event) => setLaunchPeers(event.target.value)}
                      disabled={busyAction !== null}
                    />
                  </label>
                </div>
                <label className="option-toggle">
                  <input
                    type="checkbox"
                    checked={warmMinerOnStartup}
                    disabled={busyAction !== null}
                    onChange={(event) => setWarmMinerOnStartup(event.target.checked)}
                  />
                  <span>
                    <strong>Warm up miner on startup</strong>
                    <small>Runs backend checks and tuning before the node window opens.</small>
                  </span>
                </label>
              </section>

              <section className="bootstrap-panel bootstrap-secondary">
                <div className="secondary-title">
                  <h3>Bootstrap Peers</h3>
                  <p>Used only for this startup; disable any peer to skip it for this launch.</p>
                </div>
                <div className="bootstrap-list horizontal">
                  {BOOTSTRAP_PEERS.map((peer) => {
                    const isDisabled = disabledBootstrapPeers.includes(peer);
                    const isSelf = isLocalBootstrapPeer(peer, previewNodeConfig, localAddresses);
                    return (
                      <label
                        className={`peer-status bootstrap-toggle ${isDisabled ? "disabled" : ""} ${isSelf ? "skipped" : ""}`}
                        key={peer}
                      >
                        <input
                          type="checkbox"
                          checked={!isDisabled}
                          disabled={busyAction !== null}
                          onChange={() => toggleBootstrapPeer(peer)}
                        />
                        <ReferenceCode value={peer} />
                        <span>{isDisabled ? "off" : isSelf ? "self" : "auto"}</span>
                      </label>
                    );
                  })}
                </div>
              </section>

              {notice ? <p className="launch-notice">{notice}</p> : null}
              {error ? <p className="launch-error">{error}</p> : null}
            </>
          )}
        </section>
      </main>
    );
  }

  const loadedWallet = snapshot.nodeInfo?.wallet;
  const ownBalance = loadedWallet
    ? snapshot.balances.find((balance) => balance.address === loadedWallet.address)
    : undefined;
  const blockchainTargetHeight = blockchainWindow?.targetHeight
    ?? snapshot.chainHead?.height
    ?? (snapshot.blocks.length > 0 ? snapshot.blocks[snapshot.blocks.length - 1].height : null)
    ?? null;
  const blockchainBlocks = blockchainWindow?.blocks ?? snapshot.blocks;
  const focusedBlockchainBlock = blockchainTargetHeight === null
    ? null
    : blockchainBlocks.find((block) => block.height === blockchainTargetHeight)
      ?? blockchainBlocks.find((block) => block.block_hash === blockchainWindow?.targetHash)
      ?? null;
  const focusedBlockchainHeight = focusedBlockchainBlock?.height ?? blockchainTargetHeight;
  const previousBlockchainBlock = focusedBlockchainHeight === null
    ? null
    : blockchainBlocks.find((block) => block.height === focusedBlockchainHeight - 1) ?? null;
  const nextBlockchainBlock = focusedBlockchainHeight === null
    ? null
    : blockchainBlocks.find((block) => block.height === focusedBlockchainHeight + 1) ?? null;
  const blockchainTipHeight = snapshot.chainHead?.height ?? null;
  const showGenesisBoundary = previousBlockchainBlock === null && focusedBlockchainHeight === 0;
  const showTipBoundary = (
    nextBlockchainBlock === null
    && focusedBlockchainHeight !== null
    && blockchainTipHeight !== null
    && focusedBlockchainHeight >= blockchainTipHeight
  );
  const blockchainWindowLabel = focusedBlockchainHeight !== null
    ? `Focused on block #${focusedBlockchainHeight}`
    : "No block focused";
  const blockchainNavBusy = busyAction === "blockchain-search" || busyAction === "blockchain-nav";
  const canNavigatePrevious = (
    isApiAvailable
    && !blockchainNavBusy
    && blockchainTargetHeight !== null
    && blockchainTargetHeight > 0
  );
  const canNavigateNext = (
    isApiAvailable
    && !blockchainNavBusy
    && blockchainTargetHeight !== null
    && blockchainTipHeight !== null
    && blockchainTargetHeight < blockchainTipHeight
  );
  const latestMessages = newestFirst(snapshot.messages).slice(0, 10);
  const latestReceipts = [...snapshot.receipts]
    .sort((left, right) => (
      receiptBlockSortValue(right) - receiptBlockSortValue(left)
      || right.transaction_id.localeCompare(left.transaction_id)
    ))
    .slice(0, 8);
  const executableContracts = snapshot.contracts.filter((contract) => !contractIsDone(contract, snapshot.receipts));
  const latestAuthorizations = snapshot.authorizations.slice(-8).reverse();
  const balancesByAmount = sortBalancesDescending(snapshot.balances);
  const connectedPeers = snapshot.peers.connected;
  const knownPeers = snapshot.peers.known;
  const disableNodeAction = !isApiAvailable || busyAction !== null;
  const miningActive = miningStatus?.active === true;
  const automineRunning = miningStatus?.automine.running === true;
  const miningModeLabel = miningActive
    ? miningStatus?.mode ?? "mining"
    : automineRunning
    ? "automine queued"
    : "ready";
  const miningDifficulty = miningStatus?.difficulty_bits ?? snapshot.chainHead?.next_difficulty_bits ?? null;
  const miningStartDisabled = !isApiAvailable || busyAction !== null || miningActive || automineRunning;
  const miningStopDisabled = !isApiAvailable || busyAction === "stop-automine" || !automineRunning;
  const selectedMiningBackend = miningBackends?.selected ?? miningStatus?.backend ?? "auto";
  const miningWarmupStatus = miningBackends?.warmup ?? miningStatus?.warmup ?? null;
  const miningBackendOptions = miningBackends?.backends ?? [];
  const activeTabLabel = tabs.find((tab) => tab.id === activeTab)?.label ?? "";
  const walletDisplayName = loadedWallet?.name || walletName || "No wallet loaded";
  const walletBalance = loadedWallet ? formatAmount(ownBalance?.balance) : "-";
  const keyWalletName = selectedWallet?.name || loadedWallet?.name || walletName;
  const keyWalletAddress = selectedWallet?.address || loadedWallet?.address || "";
  const runningNodeConfig = nodeState.config;
  const runningNodeHost = runningNodeConfig?.host ?? host;
  const runningNodePort = runningNodeConfig?.port ?? Number(port);
  const runningNodeApiPort = runningNodeConfig?.apiPort ?? Number(apiPort);
  const runningNodeWallet = runningNodeConfig?.walletName ?? walletName;
  const runningNodePeers = runningNodeConfig?.peers ?? launchPeerList;

  async function copyToClipboard(value: string, label: string) {
    if (!value) {
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
      setError(null);
      setNotice(`${label} copied`);
    } catch (copyError) {
      setError(`Could not copy ${label.toLowerCase()}: ${copyError instanceof Error ? copyError.message : String(copyError)}`);
    }
  }

  function prepareContractExecution(contract: ContractEntry) {
    setExecuteContractAddress(contract.address);
    setAuthContractAddress(contract.address);
    setActiveContractSubTab("execute");
  }

  async function handleRevealWalletKeys() {
    if (walletKeysVisible) {
      setWalletKeysVisible(false);
      return;
    }
    if (!keyWalletName) {
      setError("Select a wallet before revealing keys.");
      return;
    }

    setBusyAction("read-wallet-keys");
    setError(null);
    setNotice(null);
    try {
      const keys = await window.unccoinDesktop.readWalletKeys(keyWalletName);
      setWalletKeys(keys);
      setWalletKeysVisible(true);
    } catch (keyError) {
      setError(String(keyError));
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <header className="brand">
          <div>
            <h1>UncCoin</h1>
            <p>{loadedWallet?.name || walletName || "Desktop node"}</p>
          </div>
          <span className={`status-pill ${nodeState.running ? "online" : ""}`}>
            {nodeState.running ? "online" : "offline"}
          </span>
        </header>

        <section className="side-section node-info-panel" aria-label="Node information">
          <div className="node-info-header">
            <span>Node Info</span>
            <span className="node-state-dot online" aria-label="Node online" />
          </div>
          <dl className="node-info-list">
            <div>
              <dt>Wallet</dt>
              <dd>{runningNodeWallet || "-"}</dd>
            </div>
            <div>
              <dt>P2P</dt>
              <dd>
                <ReferenceCode value={Number.isInteger(runningNodePort) ? `${runningNodeHost}:${runningNodePort}` : null} />
              </dd>
            </div>
            <div>
              <dt>API</dt>
              <dd>
                <ReferenceCode value={Number.isInteger(runningNodeApiPort) ? runningNodeApiPort : null} />
              </dd>
            </div>
            <div>
              <dt>Launch Peers</dt>
              <dd>{runningNodePeers.length > 0 ? runningNodePeers.length : "none"}</dd>
            </div>
          </dl>
          <button type="button" onClick={handleStop} disabled={!nodeState.running || busyAction === "stop-node"}>
            Stop Node
          </button>
        </section>

        <nav className="tabs" aria-label="Primary">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={activeTab === tab.id ? "active" : ""}
              onClick={() => setActiveTab(tab.id)}
            >
              <TabIcon name={tab.icon} />
              <span className="tab-label">{tab.label}</span>
              {tab.id === "messages" && unreadMessageCount > 0 ? (
                <span className="unread-badge">{unreadMessageCount}</span>
              ) : null}
              {tab.id === "blockchain" && unreadBlockCount > 0 ? (
                <span className="unread-badge">{unreadBlockCount}</span>
              ) : null}
              {tab.id === "network" && unreadNetworkEventCount > 0 ? (
                <span className="unread-badge">{unreadNetworkEventCount}</span>
              ) : null}
            </button>
          ))}
        </nav>

        <section className="side-section compact">
          <dl className="mini-list">
            <div>
              <dt>PID</dt>
              <dd>{nodeState.pid ?? "-"}</dd>
            </div>
            <div>
              <dt>API</dt>
              <dd>{apiStatus}</dd>
            </div>
            <div>
              <dt>Balance</dt>
              <dd>{formatAmount(ownBalance?.balance)}</dd>
            </div>
          </dl>
        </section>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="wallet-info">
            <div className="wallet-heading">
              <span className="section-label">Current Wallet</span>
              <h2>{walletDisplayName}</h2>
            </div>
            <dl className="wallet-facts">
              <div>
                <dt>Balance</dt>
                <dd>{walletBalance}</dd>
              </div>
              <div className="wallet-address-fact">
                <dt>Address</dt>
                <dd>
                  {loadedWallet ? (
                    <button
                      type="button"
                      className="address-copy"
                      onClick={() => void copyToClipboard(loadedWallet.address, "Wallet address")}
                      title={loadedWallet.address}
                      aria-label="Copy wallet address"
                    >
                      <ReferenceCode value={loadedWallet.address} />
                    </button>
                  ) : (
                    "-"
                  )}
                </dd>
              </div>
            </dl>
          </div>
          <div className="topbar-actions">
            {notice ? <span className="notice" title={notice}>{notice}</span> : null}
            {error ? <span className="error-banner" title={error}>{error}</span> : null}
            <button type="button" onClick={() => void handleRefresh()} disabled={!isApiAvailable}>
              Refresh
            </button>
          </div>
        </header>

        <div className="workspace-scroll" aria-label={`${activeTabLabel} content`}>
          <header className="page-heading">
            <span>Current Tab</span>
            <h2>{activeTabLabel}</h2>
          </header>
          {activeTab === "contracts" ? (
            <nav className="subtab-bar" aria-label="Contract workflows">
              {contractSubTabs.map((contractTab) => (
                <button
                  type="button"
                  className={activeContractSubTab === contractTab.id ? "active" : ""}
                  key={contractTab.id}
                  onClick={() => setActiveContractSubTab(contractTab.id)}
                >
                  {contractTab.label}
                </button>
              ))}
            </nav>
          ) : null}

        {activeTab === "blockchain" ? (
          <section className="view blockchain-view">
            <div className="metric-grid">
              <article className="metric">
                <span>Height</span>
                <strong>{snapshot.chainHead?.height ?? "-"}</strong>
              </article>
              <article className="metric">
                <span>Pending</span>
                <strong>{snapshot.chainHead?.pending_transaction_count ?? "-"}</strong>
              </article>
              <article className="metric">
                <span>Difficulty</span>
                <strong>{snapshot.chainHead?.next_difficulty_bits ?? "-"}</strong>
              </article>
              <article className="metric">
                <span>Peers</span>
                <strong>{connectedPeers.length}</strong>
              </article>
              <article className="metric wide">
                <span>Tip</span>
                <ReferenceStrong value={snapshot.chainHead?.tip_hash} />
              </article>
            </div>

            <section className="panel blockchain-toolbar">
              <div className="blockchain-focus">
                <strong>{blockchainWindowLabel}</strong>
                <ReferenceText value={blockchainWindow ? blockchainWindow.targetHash : snapshot.chainHead?.tip_hash} />
              </div>
              <div className="blockchain-nav-actions">
                <button
                  type="button"
                  disabled={!canNavigatePrevious}
                  onClick={() => void handleBlockchainStep(-1)}
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={!canNavigateNext}
                  onClick={() => void handleBlockchainStep(1)}
                >
                  Next
                </button>
              </div>
              <form className="block-search-form" onSubmit={handleBlockchainSearch}>
                <input
                  value={blockchainSearch}
                  placeholder="Block height or hash"
                  onChange={(event) => setBlockchainSearch(event.target.value)}
                  disabled={blockchainNavBusy}
                />
                <button type="submit" disabled={!isApiAvailable || blockchainNavBusy}>
                  Jump
                </button>
                <button type="button" onClick={clearBlockchainSearch} disabled={blockchainNavBusy}>
                  Latest
                </button>
              </form>
              {blockchainSearchError ? <p>{blockchainSearchError}</p> : null}
            </section>
            <div className="blockchain-carousel">
              <div className="block-preview previous" aria-label="Previous block preview">
                {showGenesisBoundary ? (
                  <BlockchainBoundaryCard kind="genesis" />
                ) : (
                  <BlockchainBlockCard
                    block={previousBlockchainBlock}
                    preview
                    emptyLabel="No previous block loaded."
                  />
                )}
              </div>
              <BlockchainHashConnector active={previousBlockchainBlock !== null && focusedBlockchainBlock !== null} />
              <BlockchainBlockCard block={focusedBlockchainBlock} focused emptyLabel="No focused block loaded." />
              <BlockchainHashConnector active={focusedBlockchainBlock !== null && nextBlockchainBlock !== null} />
              <div className="block-preview next" aria-label="Next block preview">
                {showTipBoundary ? (
                  <BlockchainBoundaryCard kind="tip" />
                ) : (
                  <BlockchainBlockCard
                    block={nextBlockchainBlock}
                    preview
                    emptyLabel="No next block loaded."
                  />
                )}
              </div>
            </div>
          </section>
        ) : null}

        {activeTab === "balances" ? (
          <section className="view balances-view">
            <section className="panel">
              <div className="panel-title">
                <h3>Wallet Balances</h3>
                <span>{snapshot.balances.length}</span>
              </div>
              {balancesByAmount.length === 0 ? (
                <p className="empty">No balances loaded.</p>
              ) : (
                <div className="balance-card-list">
                  {balancesByAmount.map((balance, index) => (
                    <article className="balance-card" key={balance.address}>
                      <span className="balance-rank">{index + 1}</span>
                      <div className="balance-identity">
                        <strong>{balance.alias || "Unnamed wallet"}</strong>
                        <ReferenceCode value={balance.address} />
                      </div>
                      <strong className="balance-amount">{balance.balance}</strong>
                    </article>
                  ))}
                </div>
              )}
            </section>
          </section>
        ) : null}

        {activeTab === "transfer" ? (
          <section className="view">
            <div className="transfer-layout">
              <div className="transfer-main-column">
                <section className="panel transfer-panel">
                  <div className="panel-title">
                    <h3>Send Transfer</h3>
                    <span>{loadedWallet ? `${formatAmount(ownBalance?.balance)} available` : "wallet required"}</span>
                  </div>
                  <form className="form-grid" onSubmit={handleTransaction}>
                    <label>
                      Recipient
                      <input
                        value={txReceiver}
                        placeholder="Wallet address or alias"
                        onChange={(event) => setTxReceiver(event.target.value)}
                      />
                    </label>
                    <div className="field-row">
                      <label>
                        Amount
                        <input
                          value={txAmount}
                          inputMode="decimal"
                          onChange={(event) => setTxAmount(event.target.value)}
                        />
                      </label>
                      <label>
                        Fee
                        <input
                          value={txFee}
                          inputMode="decimal"
                          onChange={(event) => setTxFee(event.target.value)}
                        />
                      </label>
                    </div>
                    <button type="submit" disabled={disableNodeAction}>
                      Send Transfer
                    </button>
                  </form>
                </section>

                <section className="panel">
                  <div className="panel-title">
                    <h3>Pending Transfers</h3>
                    <span>{snapshot.pendingTransactions.length}</span>
                  </div>
                  <div className="list">
                    {snapshot.pendingTransactions.length === 0 ? (
                      <p className="empty">Mempool is empty.</p>
                    ) : (
                      snapshot.pendingTransactions.map((transaction) => (
                        <div className="list-row stacked" key={transaction.transaction_id}>
                          <ReferenceText value={outgoingTransactionSummary(transaction)} />
                          <ReferenceCode value={transaction.transaction_id} />
                        </div>
                      ))
                    )}
                  </div>
                </section>
              </div>

              <section className="panel">
                <div className="panel-title">
                  <h3>Recipients</h3>
                  <span>{snapshot.balances.length}</span>
                </div>
                <div className="list">
                  {snapshot.balances.length === 0 ? (
                    <p className="empty">No known wallet balances.</p>
                  ) : (
                    snapshot.balances.map((balance) => (
                      <button
                        type="button"
                        className="select-row recipient-row"
                        key={balance.address}
                        onClick={() => setTxReceiver(balance.alias || balance.address)}
                      >
                        <ReferenceText value={balance.alias || balance.address} title={balance.address} />
                        <strong>{balance.balance}</strong>
                      </button>
                    ))
                  )}
                </div>
              </section>
            </div>
          </section>
        ) : null}

        {activeTab === "mining" ? (
          <section className="view mining-view">
            <section className="panel mining-panel">
              <div className="panel-title">
                <h3>Mining</h3>
                <span>{miningModeLabel}</span>
              </div>

              <div className="mining-summary-row">
                <div className={`mining-readout ${miningActive ? "active" : ""}`}>
                  <span>{miningActive ? "Current Nonce" : "Last Nonce"}</span>
                  <strong>{formatNumber(miningStatus?.nonce)}</strong>
                  <small>
                    {miningActive
                      ? `running ${formatElapsed(miningStatus?.started_at)}`
                      : miningStatus?.last_block.block_hash
                      ? `last block #${miningStatus.last_block.height ?? "-"}`
                      : "idle"}
                  </small>
                </div>

                <dl className="detail-list mining-stats">
                  <div>
                    <dt>Difficulty</dt>
                    <dd>{formatNumber(miningDifficulty)}</dd>
                  </div>
                  <div>
                    <dt>Pending Tx</dt>
                    <dd>{snapshot.chainHead?.pending_transaction_count ?? "-"}</dd>
                  </div>
                  <div>
                    <dt>Last Checked</dt>
                    <dd>{formatNumber(miningStatus?.last_block.nonces_checked)}</dd>
                  </div>
                </dl>
              </div>

              <section className="miner-backends">
                <div className="panel-title compact-title">
                  <h3 className="backend-title">
                    <span>Miner Backend</span>
                    {miningWarmupStatus?.active ? (
                      <span className="backend-header-spinner" title="Miner warmup in progress" />
                    ) : null}
                  </h3>
                </div>
                <div className="backend-meta">
                  <span>Selected: {selectedMiningBackend}</span>
                  <span className={miningWarmupStatus?.active ? "warmup-pill active" : "warmup-pill"}>
                    {miningWarmupStatus?.active ? <span className="warmup-pill-spinner" /> : null}
                    Warmup: {miningWarmupStatus?.status ?? "idle"}
                  </span>
                </div>
                <div className="backend-grid">
                  {miningBackendOptions.length === 0 ? (
                    <p className={miningBackendsError ? "inline-warning" : "empty"}>
                      {miningBackendsLoading ? (
                        <>
                          <span className="backend-loading-spinner" /> Loading miner backend status...
                        </>
                      ) : miningBackendsError ? (
                        `Miner backend status unavailable: ${miningBackendsError}`
                      ) : isApiAvailable ? (
                        "Miner backend status has not loaded yet."
                      ) : (
                        "Start the node to inspect miner backends."
                      )}
                    </p>
                  ) : (
                    miningBackendOptions.map((option) => {
                      const isSelected = option.id === selectedMiningBackend;
                      const canAct = option.available || option.can_build;
                      const isWarmingBackend = (
                        miningWarmupStatus?.active === true
                        && miningWarmupStatus.backend === option.id
                      );
                      const needsWarmup = option.available
                        && !isWarmingBackend
                        && !miningBackendIsWarmed(option, miningWarmupStatus);
                      return (
                        <button
                          type="button"
                          className={[
                            "backend-option",
                            isSelected ? "selected" : "",
                            !option.available ? "unavailable" : "",
                          ].filter(Boolean).join(" ")}
                          key={option.id}
                          title={option.description}
                          disabled={
                            !isApiAvailable
                            || busyAction !== null
                            || miningActive
                            || automineRunning
                            || miningWarmupStatus?.active === true
                            || !canAct
                            || (option.available && isSelected && !needsWarmup)
                          }
                          onClick={() => {
                            if (!option.available && option.can_build) {
                              void handleBuildMiningBackend(option.id);
                              return;
                            }
                            void handleUseMiningBackend(option.id);
                          }}
                        >
                          <span className="backend-option-heading">
                            <span className="backend-label">
                              <span>{option.label}</span>
                              {isWarmingBackend ? (
                                <span className="backend-loading-spinner" title={`${option.label} is warming`} />
                              ) : null}
                            </span>
                            {!option.available ? (
                              <span className="backend-warning-badge" title={`${option.label} is not built`}>
                                <WarningIcon className="backend-warning-icon" />
                                Not built
                              </span>
                            ) : null}
                          </span>
                          <small>{option.description}</small>
                          <strong>
                            {miningBackendButtonLabel(option, selectedMiningBackend, needsWarmup, isWarmingBackend)}
                          </strong>
                        </button>
                      );
                    })
                  )}
                </div>
                {miningWarmupStatus?.error ? (
                  <p className="inline-warning">{miningWarmupStatus.error}</p>
                ) : null}
              </section>

              <form className="form-grid mining-controls" onSubmit={handleMine}>
                <label>
                  Mine Description
                  <input
                    value={mineDescription}
                    placeholder="Block description"
                    onChange={(event) => setMineDescription(event.target.value)}
                    disabled={!isApiAvailable || busyAction === "mine-block"}
                  />
                </label>
                <div className="button-row">
                  <button type="submit" disabled={miningStartDisabled}>
                    Mine Once
                  </button>
                  <button
                    type="button"
                    disabled={miningStartDisabled}
                    onClick={() => void runNodeAction("start-automine", async () => {
                      const response = await startAutomine(activeApiPort, mineDescription || undefined);
                      setMiningStatus((currentStatus) => (
                        currentStatus === null
                          ? currentStatus
                          : {
                            ...currentStatus,
                            automine: {
                              running: response.running,
                              description: response.description,
                            },
                          }
                      ));
                      return { label: "Automine started", detail: response.description };
                    }, "mining")}
                  >
                    Start Auto
                  </button>
                  <button
                    type="button"
                    disabled={miningStopDisabled}
                    onClick={() => void runNodeAction("stop-automine", async () => {
                      await stopAutomine(activeApiPort);
                      return { label: "Automine stopped" };
                    }, "mining")}
                  >
                    Stop
                  </button>
                </div>
              </form>
            </section>

            <section className="panel miner-board">
              <div className="panel-title compact-title">
                <h3>Active Miners</h3>
                <span>{miningStatus?.recent_miners.length ?? 0}</span>
              </div>
              <div className="list">
                {miningStatus?.recent_miners.length ? (
                  miningStatus.recent_miners.map((miner) => (
                    <div className="list-row stacked" key={miner.address}>
                      <ReferenceText value={miner.alias || miner.address} title={miner.address} />
                      <code>{miner.blocks} recent block{miner.blocks === 1 ? "" : "s"}</code>
                    </div>
                  ))
                ) : (
                  <p className="empty">No recent mined blocks.</p>
                )}
              </div>
            </section>
          </section>
        ) : null}

        {activeTab === "wallet" ? (
          <section className="view">
            <section className="panel alias-autosend-panel">
              <div className="panel-title">
                <h3>Aliases and Autosend</h3>
                <span>{snapshot.nodeInfo?.autosend.enabled ? "autosend on" : "autosend off"}</span>
              </div>
              <form className="form-grid" onSubmit={handleAlias}>
                <label>
                  Wallet
                  <input value={aliasWallet} onChange={(event) => setAliasWallet(event.target.value)} />
                </label>
                <label>
                  Alias
                  <input value={aliasName} onChange={(event) => setAliasName(event.target.value)} />
                </label>
                <button type="submit" disabled={disableNodeAction}>
                  Save Alias
                </button>
              </form>
              <form className="form-grid autosend-form" onSubmit={handleAutosend}>
                <label>
                  Autosend Target
                  <input value={autosendTarget} onChange={(event) => setAutosendTarget(event.target.value)} />
                </label>
                <div className="button-row">
                  <button type="submit" disabled={disableNodeAction}>
                    Enable
                  </button>
                  <button
                    type="button"
                    disabled={disableNodeAction}
                    onClick={() => void runNodeAction("disable-autosend", async () => {
                      await setAutosend(activeApiPort, null);
                      setAutosendTarget("");
                      return { label: "Autosend disabled" };
                    })}
                  >
                    Disable
                  </button>
                </div>
              </form>
            </section>

            <section className="panel wallet-key-panel">
              <div className="panel-title">
                <h3>Wallet Keys</h3>
                <span>{walletKeysVisible ? "revealed" : "hidden"}</span>
              </div>
              <div className="key-toolbar">
                <div>
                  <strong>{keyWalletName || "No wallet selected"}</strong>
                  <ReferenceCode value={keyWalletAddress} />
                </div>
                <button
                  type="button"
                  disabled={!keyWalletName || busyAction === "read-wallet-keys"}
                  onClick={() => void handleRevealWalletKeys()}
                >
                  {walletKeysVisible ? "Hide Keys" : "Reveal Keys"}
                </button>
              </div>

              {walletKeysVisible && walletKeys ? (
                <div className="key-grid">
                  <section className="key-card">
                    <div className="panel-title compact-title">
                      <h3>Public Key</h3>
                      <button
                        type="button"
                        onClick={() => void copyToClipboard(formatWalletKey(walletKeys.publicKey), "Public key")}
                      >
                        Copy
                      </button>
                    </div>
                    <pre>{formatWalletKey(walletKeys.publicKey)}</pre>
                  </section>

                  <section className="key-card private">
                    <div className="panel-title compact-title">
                      <h3>Private Key</h3>
                      <button
                        type="button"
                        onClick={() => void copyToClipboard(formatWalletKey(walletKeys.privateKey), "Private key")}
                      >
                        Copy
                      </button>
                    </div>
                    <pre>{formatWalletKey(walletKeys.privateKey)}</pre>
                  </section>
                </div>
              ) : null}
            </section>

          </section>
        ) : null}

        {activeTab === "network" ? (
          <section className="view">
            <div className="panel-grid two">
              <section className="panel">
                <div className="panel-title">
                  <h3>Peer Control</h3>
                  <span>{connectedPeers.length} connected</span>
                </div>
                <form className="inline-form" onSubmit={handleConnectPeer}>
                  <input
                    value={peerAddress}
                    placeholder="127.0.0.1:9001"
                    onChange={(event) => setPeerAddress(event.target.value)}
                  />
                  <button type="submit" disabled={disableNodeAction}>
                    Connect
                  </button>
                  <button
                    type="button"
                    disabled={disableNodeAction}
                    onClick={() => void runNodeAction("discover-peers", async () => {
                      const response = await discoverPeers(activeApiPort);
                      return { label: "Peer discovery sent", detail: `${response.known.length} known` };
                    })}
                  >
                    Discover
                  </button>
                  <button
                    type="button"
                    disabled={disableNodeAction}
                    onClick={() => void runNodeAction("sync-chain", async () => {
                      const response = await syncChain(activeApiPort, true);
                      return { label: "Sync requested", detail: `${response.requested_peers} peers` };
                    })}
                  >
                    Sync
                  </button>
                  <button
                    type="button"
                    disabled={disableNodeAction}
                    onClick={() => void runNodeAction("rebroadcast-pending", async () => {
                      const response = await rebroadcastPendingTransactions(activeApiPort);
                      return {
                        label: "Pending transactions rebroadcast",
                        detail: `${response.rebroadcast} transaction(s)`,
                      };
                    })}
                  >
                    Rebroadcast
                  </button>
                  <button
                    type="button"
                    disabled={disableNodeAction || busyAction === "connect-bootstrap-peers"}
                    onClick={() => void handleConnectBootstrapPeers()}
                  >
                    Bootstrap
                  </button>
                </form>
                {networkBootstrapAttempts.length > 0 ? (
                  <div className="bootstrap-panel network-bootstrap-panel">
                    <div className="secondary-title">
                      <strong>Bootstrap Peers</strong>
                      <span>{busyAction === "connect-bootstrap-peers" ? "connecting" : "latest attempt"}</span>
                    </div>
                    <div className="bootstrap-list">
                      {networkBootstrapAttempts.map((attempt) => (
                        <div className={`peer-status ${attempt.status}`} key={attempt.peer}>
                          <ReferenceCode value={attempt.peer} />
                          <span title={attempt.rawDetail ?? attempt.detail}>{bootstrapAttemptLabel(attempt)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </section>

              <section className="panel network-traffic-card">
                <div className="panel-title">
                  <h3>Network Traffic</h3>
                  <span>{snapshot.networkStats.peers.length} tracked</span>
                </div>
                <div className="traffic-summary vertical">
                  <article>
                    <TrafficDirectionIcon direction="ingress" />
                    <div>
                      <span>Ingress</span>
                      <strong>{formatBytes(snapshot.networkStats.ingress.bytes)}</strong>
                      <small>{formatNumber(snapshot.networkStats.ingress.messages)} messages received</small>
                    </div>
                  </article>
                  <article>
                    <TrafficDirectionIcon direction="egress" />
                    <div>
                      <span>Egress</span>
                      <strong>{formatBytes(snapshot.networkStats.egress.bytes)}</strong>
                      <small>{formatNumber(snapshot.networkStats.egress.messages)} messages sent</small>
                    </div>
                  </article>
                </div>
              </section>
            </div>

            <section className="panel network-events-panel">
              <div className="panel-title">
                <h3>Network Events</h3>
                <span>{networkEvents.length}</span>
              </div>
              <div className="network-event-list">
                {networkEvents.length === 0 ? (
                  <p className="empty">No peer connect or disconnect events recorded this session.</p>
                ) : (
                  networkEvents.map((event) => (
                    <div className={`network-event-row ${event.type}`} key={event.id}>
                      <span className="network-event-dot" aria-hidden="true" />
                      <strong>{event.type === "connected" ? "Connected" : "Disconnected"}</strong>
                      <ReferenceCode value={event.peer} />
                      <time dateTime={event.timestamp}>{formatTimestamp(event.timestamp)}</time>
                    </div>
                  ))
                )}
              </div>
            </section>

            <div className="panel-grid two">
              <PeerList
                title="Connected Peers"
                peers={connectedPeers}
                actionLabel="Disconnect"
                disableAction={disableNodeAction}
                onPeerAction={(peer) => void handleDisconnectPeer(peer)}
              />
              <PeerList title="Known Peers" peers={knownPeers} />
            </div>
          </section>
        ) : null}

        {activeTab === "messages" ? (
          <section className="view">
            <div className="panel-grid two">
              <section className="panel">
                <div className="panel-title">
                  <h3>Send Message</h3>
                  <span>{latestMessages.length} recent</span>
                </div>
                <form className="form-grid" onSubmit={handleMessage}>
                  <label>
                    Receiver
                    <input value={messageReceiver} onChange={(event) => setMessageReceiver(event.target.value)} />
                  </label>
                  <label>
                    Content
                    <textarea value={messageContent} onChange={(event) => setMessageContent(event.target.value)} />
                  </label>
                  <button type="submit" disabled={disableNodeAction}>
                    Send
                  </button>
                </form>
              </section>

              <section className="panel">
                <div className="panel-title">
                  <h3>History</h3>
                  <span>{snapshot.messages.length}</span>
                </div>
                <div className="list">
                  {latestMessages.length === 0 ? (
                    <p className="empty">No messages loaded.</p>
                  ) : (
                    latestMessages.map((message, index) => (
                      <div className="list-row stacked" key={message.message_id || `${message.timestamp}-${index}`}>
                        <span>{message.content || "-"}</span>
                        <ReferenceCode
                          value={`${message.sender || message.peer || "-"} -> ${message.receiver || "-"}`}
                        />
                      </div>
                    ))
                  )}
                </div>
              </section>
            </div>
          </section>
        ) : null}

        {activeTab === "contracts" ? (
          <section className="view contracts-view">
            {activeContractSubTab === "deploy" ? (
              <section className="panel">
                <div className="panel-title">
                  <h3>Deploy</h3>
                  <span>{snapshot.contracts.length} contracts</span>
                </div>
                <div className="subtab-bar nested-subtab-bar" role="tablist" aria-label="Deploy type">
                  <button
                    type="button"
                    className={activeDeploySubTab === "raw" ? "active" : ""}
                    onClick={() => setActiveDeploySubTab("raw")}
                  >
                    Raw JSON
                  </button>
                  <button
                    type="button"
                    className={activeDeploySubTab === "templates" ? "active" : ""}
                    onClick={() => setActiveDeploySubTab("templates")}
                  >
                    Templates
                  </button>
                </div>
                {activeDeploySubTab === "raw" ? (
                  <form className="form-grid" onSubmit={handleDeploy}>
                    <label>
                      Fee
                      <input value={deployFee} onChange={(event) => setDeployFee(event.target.value)} />
                    </label>
                    <label>
                      Deploy JSON
                      <textarea className="code-input" value={deployJson} onChange={(event) => setDeployJson(event.target.value)} />
                    </label>
                    <button type="submit" disabled={disableNodeAction}>
                      Deploy
                    </button>
                  </form>
                ) : (
                  <form className="form-grid contract-template-form" onSubmit={handleDeployTemplate}>
                    <div className="template-picker">
                      {contractTemplates.map((template) => (
                        <button
                          key={template.id}
                          type="button"
                          className={selectedContractTemplate === template.id ? "template-option selected" : "template-option"}
                          onClick={() => setSelectedContractTemplate(template.id)}
                        >
                          <strong>{template.label}</strong>
                          <span>{template.description}</span>
                        </button>
                      ))}
                    </div>
                    <div className="field-row">
                      <label>
                        Wallet 1
                        <input value={coinflipWalletOne} onChange={(event) => setCoinflipWalletOne(event.target.value)} />
                      </label>
                      <label>
                        Wallet 2
                        <input value={coinflipWalletTwo} onChange={(event) => setCoinflipWalletTwo(event.target.value)} />
                      </label>
                    </div>
                    <div className="field-row four">
                      <label>
                        Amount
                        <input value={coinflipAmount} onChange={(event) => setCoinflipAmount(event.target.value)} />
                      </label>
                      <label>
                        Reveal Deadline
                        <input value={coinflipRevealDeadline} onChange={(event) => setCoinflipRevealDeadline(event.target.value)} />
                      </label>
                      <label>
                        Fee
                        <input value={deployFee} onChange={(event) => setDeployFee(event.target.value)} />
                      </label>
                      <div className="template-request-id">
                        <span>Request ID</span>
                        <ReferenceCode value={coinflipRequestId} />
                      </div>
                    </div>
                    <div className="button-row">
                      <button type="button" onClick={() => setCoinflipRequestId(createCoinflipRequestId())}>
                        Regenerate ID
                      </button>
                      <button type="submit" disabled={disableNodeAction}>
                        Deploy Coinflip
                      </button>
                    </div>
                    <details className="template-preview">
                      <summary>Generated JSON</summary>
                      {coinflipTemplatePreview === null ? (
                        <p className="empty">Complete the template fields to preview JSON.</p>
                      ) : (
                        <pre>{coinflipTemplatePreview}</pre>
                      )}
                    </details>
                  </form>
                )}
              </section>
            ) : null}

            {activeContractSubTab === "execute" ? (
              <section className="panel">
                <div className="panel-title">
                  <h3>Execute</h3>
                  <span>{snapshot.receipts.length} receipts</span>
                </div>
                <form className="form-grid" onSubmit={handleExecute}>
                  <label>
                    Contract
                    <input value={executeContractAddress} onChange={(event) => setExecuteContractAddress(event.target.value)} />
                  </label>
                  <div className="field-row four">
                    <label>
                      Gas
                      <input value={executeGasLimit} onChange={(event) => setExecuteGasLimit(event.target.value)} />
                    </label>
                    <label>
                      Gas Price
                      <input value={executeGasPrice} onChange={(event) => setExecuteGasPrice(event.target.value)} />
                    </label>
                    <label>
                      Value
                      <input value={executeValue} onChange={(event) => setExecuteValue(event.target.value)} />
                    </label>
                    <label>
                      Fee
                      <input value={executeFee} onChange={(event) => setExecuteFee(event.target.value)} />
                    </label>
                  </div>
                  <div className="optional-json-header">
                    <span>Input JSON</span>
                    {showExecuteInputJson ? null : <code>null</code>}
                    <button type="button" onClick={() => setShowExecuteInputJson((current) => !current)}>
                      {showExecuteInputJson ? "Remove" : "Add"}
                    </button>
                  </div>
                  {showExecuteInputJson ? (
                    <textarea
                      aria-label="Execute input JSON"
                      className="code-input"
                      value={executeInputJson}
                      onChange={(event) => setExecuteInputJson(event.target.value)}
                    />
                  ) : null}
                  <button type="submit" disabled={disableNodeAction}>
                    Execute
                  </button>
                </form>
              </section>
            ) : null}

            {activeContractSubTab === "authorization" ? (
              <section className="panel">
                <div className="panel-title">
                  <h3>Authorization</h3>
                  <span>{snapshot.authorizations.length} stored</span>
                </div>
                <form className="form-grid" onSubmit={handleAuthorize}>
                  <label>
                    Contract
                    <input value={authContractAddress} onChange={(event) => setAuthContractAddress(event.target.value)} />
                  </label>
                  <div className="field-row">
                    <label>
                      Request ID
                      <input value={authRequestId} onChange={(event) => setAuthRequestId(event.target.value)} />
                    </label>
                    <label>
                      Valid Blocks
                      <input value={authValidBlocks} onChange={(event) => setAuthValidBlocks(event.target.value)} />
                    </label>
                  </div>
                  <button type="submit" disabled={disableNodeAction}>
                    Authorize
                  </button>
                </form>
                <div className="list padded authorization-list">
                  {latestAuthorizations.length === 0 ? (
                    <p className="empty">No mined authorizations.</p>
                  ) : (
                    latestAuthorizations.map((authorization, index) => (
                      <div className="list-row stacked" key={`${recordString(authorization, "wallet")}-${recordString(authorization, "request_id")}-${index}`}>
                        <div className="auth-summary">
                          <strong>{recordString(authorization, "request_id") ?? "-"}</strong>
                          <span>{authorizationScopeLabel(authorization)}</span>
                        </div>
                        <ReferenceCode value={recordString(authorization, "wallet")} prefix="wallet " />
                        <ReferenceCode value={recordString(authorization, "contract_address")} prefix="contract " />
                      </div>
                    ))
                  )}
                </div>
              </section>
            ) : null}

            {activeContractSubTab === "randomness" ? (
              <section className="panel">
                <div className="panel-title">
                  <h3>Randomness</h3>
                  <span>commit reveal</span>
                </div>
                <form className="form-grid" onSubmit={handleCommit}>
                  <div className="field-row">
                    <label>
                      Request ID
                      <input value={commitRequestId} onChange={(event) => setCommitRequestId(event.target.value)} />
                    </label>
                    <label>
                      Fee
                      <input value={commitFee} onChange={(event) => setCommitFee(event.target.value)} />
                    </label>
                  </div>
                  <div className="field-row">
                    <label>
                      Seed
                      <input value={commitSeed} onChange={(event) => setCommitSeed(event.target.value)} />
                    </label>
                    <label>
                      Salt
                      <input value={commitSalt} onChange={(event) => setCommitSalt(event.target.value)} />
                    </label>
                  </div>
                  <button type="submit" disabled={disableNodeAction}>
                    Commit
                  </button>
                </form>

                <div className="randomness-overview">
                  <div className="randomness-section">
                    <div className="randomness-section-title">
                      <h4>Pending</h4>
                      <label>
                        Reveal Fee
                        <input value={revealFee} onChange={(event) => setRevealFee(event.target.value)} />
                      </label>
                    </div>
                    <div className="list">
                      {pendingRandomnessCommits.length === 0 ? (
                        <p className="empty">No pending randomness commits.</p>
                      ) : (
                        pendingRandomnessCommits.map((record) => (
                          <div className="list-row stacked randomness-record" key={record.id}>
                            <div className="auth-summary">
                              <strong>{record.requestId}</strong>
                              <button
                                type="button"
                                disabled={disableNodeAction}
                                onClick={() => void handleRevealSavedCommit(record)}
                              >
                                Reveal
                              </button>
                            </div>
                            <ReferenceCode value={record.transactionId} prefix="commit " />
                            <span>{formatTimestamp(record.createdAt)}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  <div className="randomness-section">
                    <div className="randomness-section-title">
                      <h4>Finished</h4>
                      <span>{finishedRandomnessCommits.length}</span>
                    </div>
                    <div className="list">
                      {finishedRandomnessCommits.length === 0 ? (
                        <p className="empty">No finished reveals.</p>
                      ) : (
                        finishedRandomnessCommits.map((record) => (
                          <div className="list-row stacked randomness-record" key={record.id}>
                            <div className="auth-summary">
                              <strong>{record.requestId}</strong>
                              <span>{formatTimestamp(record.revealedAt)}</span>
                            </div>
                            <ReferenceCode value={record.transactionId} prefix="commit " />
                            {record.revealTransactionId ? (
                              <ReferenceCode value={record.revealTransactionId} prefix="reveal " />
                            ) : (
                              <span>reveal detected on chain</span>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  <div className="randomness-section">
                    <div className="randomness-section-title">
                      <h4>Stale</h4>
                      <span>{staleRandomnessCommits.length}</span>
                    </div>
                    <div className="list">
                      {staleRandomnessCommits.length === 0 ? (
                        <p className="empty">No stale randomness records.</p>
                      ) : (
                        staleRandomnessCommits.map((record) => (
                          <div className="list-row stacked randomness-record stale-record" key={record.id}>
                            <div className="auth-summary">
                              <strong>{record.requestId}</strong>
                              <span>{record.staleReason ?? "Not usable on current chain"}</span>
                            </div>
                            <ReferenceCode value={record.transactionId} prefix="commit " />
                            <span>{formatTimestamp(record.createdAt)}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </div>

                <form className="form-grid separated" onSubmit={handleReveal}>
                  <div className="randomness-section-title">
                    <h4>Manual Reveal</h4>
                  </div>
                  <div className="field-row">
                    <label>
                      Request ID
                      <input value={revealRequestId} onChange={(event) => setRevealRequestId(event.target.value)} />
                    </label>
                    <label>
                      Fee
                      <input value={revealFee} onChange={(event) => setRevealFee(event.target.value)} />
                    </label>
                  </div>
                  <div className="field-row">
                    <label>
                      Seed
                      <input value={revealSeed} onChange={(event) => setRevealSeed(event.target.value)} />
                    </label>
                    <label>
                      Salt
                      <input value={revealSalt} onChange={(event) => setRevealSalt(event.target.value)} />
                    </label>
                  </div>
                  <button type="submit" disabled={disableNodeAction}>
                    Reveal
                  </button>
                </form>
              </section>
            ) : null}

            {activeContractSubTab === "contracts" ? (
              <section className="panel">
                <div className="panel-title">
                  <h3>Contracts</h3>
                  <span>{snapshot.contracts.length}</span>
                </div>
                <div className="contract-execute-panel">
                  <div className="secondary-title">
                    <strong>Ready to Execute</strong>
                    <span>{executableContracts.length} open</span>
                  </div>
                  <div className="contract-list">
                    {executableContracts.length === 0 ? (
                      <p className="empty">No open contracts need execution.</p>
                    ) : (
                      executableContracts.map((contract) => (
                        <article className="contract-card featured" key={`execute-${contract.address}`}>
                          <div className="contract-card-main">
                            <div className="contract-title-line">
                              <strong>{contractDisplayName(contract)}</strong>
                              <span className="contract-status">{contractExecutionStatus(contract, snapshot.receipts)}</span>
                            </div>
                            <ReferenceCode value={contract.address} />
                            <p>{contractDescription(contract) ?? "No contract description."}</p>
                          </div>
                          <div className="contract-row-meta">
                            <ReferenceCode value={contractCodeHash(contract)} prefix="code " />
                            <span>{Object.keys(contract.storage).length} storage</span>
                          </div>
                          <div className="contract-card-actions">
                            <button type="button" onClick={() => prepareContractExecution(contract)}>
                              Execute
                            </button>
                          </div>
                        </article>
                      ))
                    )}
                  </div>
                </div>

                <div className="contract-execute-panel">
                  <div className="secondary-title">
                    <strong>All Contracts</strong>
                    <span>{snapshot.contracts.length} deployed</span>
                  </div>
                  <div className="contract-list">
                  {snapshot.contracts.length === 0 ? (
                    <p className="empty">No contracts deployed.</p>
                  ) : (
                    snapshot.contracts.map((contract) => (
                      <article className="contract-card" key={contract.address}>
                        <div className="contract-card-main">
                          <div className="contract-title-line">
                            <strong>{contractDisplayName(contract)}</strong>
                            <span className={contractIsDone(contract, snapshot.receipts) ? "contract-status done" : "contract-status"}>
                              {contractExecutionStatus(contract, snapshot.receipts)}
                            </span>
                          </div>
                          <ReferenceCode value={contract.address} />
                          <p>{contractDescription(contract) ?? "No contract description."}</p>
                        </div>
                        <div className="contract-row-meta">
                          <ReferenceCode value={contractCodeHash(contract)} prefix="code " />
                          <span>{Object.keys(contract.storage).length} storage</span>
                        </div>
                        <div className="contract-card-actions">
                          {contractIsDone(contract, snapshot.receipts) ? (
                            <span className="contract-done-label">Done</span>
                          ) : (
                            <button type="button" onClick={() => prepareContractExecution(contract)}>
                              Execute
                            </button>
                          )}
                        </div>
                      </article>
                    ))
                  )}
                  </div>
                </div>
              </section>
            ) : null}

            {activeContractSubTab === "receipts" ? (
              <section className="panel">
                <div className="panel-title">
                  <h3>Receipts</h3>
                  <span>{latestReceipts.length}</span>
                </div>
                <div className="list">
                  {latestReceipts.length === 0 ? (
                    <p className="empty">No receipts yet.</p>
                  ) : (
                    latestReceipts.map((receipt) => {
                      const success = receiptSuccess(receipt);
                      return (
                        <details className="details-row receipt-row" key={receipt.transaction_id}>
                          <summary>
                            <span className="receipt-chevron" aria-hidden="true" />
                            <span className="receipt-summary">
                              <span className="receipt-title">
                                <strong>{receipt.contract_name || "Contract execution"}</strong>
                                <span className={success === false ? "receipt-status failed" : "receipt-status"}>
                                  {success === null ? "unknown" : success ? "success" : "failed"}
                                </span>
                              </span>
                              <ReferenceText value={receipt.transaction_id} />
                              <span className="receipt-description">
                                {receipt.contract_description || receipt.block_description || "No contract description."}
                              </span>
                              <span className="receipt-meta-line">
                                <span>
                                  Block {typeof receipt.block_height === "number" ? `#${receipt.block_height}` : "-"}
                                </span>
                                <ReferenceCode value={receipt.block_hash} prefix="hash " />
                              </span>
                            </span>
                          </summary>
                          <div className="receipt-meta-grid">
                            <div>
                              <span>Contract</span>
                              <ReferenceCode value={receipt.contract_address} />
                            </div>
                            <div>
                              <span>Block Description</span>
                              <strong>{receipt.block_description || "-"}</strong>
                            </div>
                            <div>
                              <span>Gas Used</span>
                              <strong>{recordString(receipt.receipt, "gas_used") ?? "-"}</strong>
                            </div>
                            <div>
                              <span>Error</span>
                              <strong>{recordString(receipt.receipt, "error") ?? "-"}</strong>
                            </div>
                          </div>
                          <pre>{formatJson(receipt.receipt)}</pre>
                        </details>
                      );
                    })
                  )}
                </div>
              </section>
            ) : null}
          </section>
        ) : null}

        {activeTab === "logs" ? (
          <section className="view">
            <section className="panel full">
              <div className="panel-title">
                <h3>Node Output</h3>
                <span>{logs.length}</span>
              </div>
              <pre className="log-output">
                {logs.length === 0
                  ? "Node output will appear here."
                  : logs.map((entry) => `[${entry.stream}] ${entry.message}`).join("")}
              </pre>
            </section>
          </section>
        ) : null}
        </div>
      </section>
    </main>
  );
}

function BlockchainBoundaryCard({ kind }: { kind: "genesis" | "tip" }) {
  const isGenesis = kind === "genesis";
  return (
    <section className="block-card preview-block boundary-block">
      <header>
        <span>{isGenesis ? "Chain Start" : "Chain End"}</span>
        <strong>{isGenesis ? "Genesis" : "Current Tip"}</strong>
      </header>
      <p>{isGenesis ? "No canonical block exists before the genesis block." : "No newer canonical block exists yet."}</p>
    </section>
  );
}

function BlockchainBlockCard({
  block,
  focused = false,
  preview = false,
  emptyLabel = "No canonical block loaded.",
}: {
  block: BlockPayload | null;
  focused?: boolean;
  preview?: boolean;
  emptyLabel?: string;
}) {
  const cardClassName = [
    "block-card",
    focused ? "focused-block" : "",
    preview ? "preview-block" : "",
  ].filter(Boolean).join(" ");

  if (!block) {
    return (
      <section className={`${cardClassName} empty-block`}>
        <header>
          <span>Block</span>
          <strong>Waiting</strong>
        </header>
        <p className="empty">{emptyLabel}</p>
      </section>
    );
  }

  return (
    <section className={cardClassName}>
      <header>
        <span>Block #{block.height}</span>
        <ReferenceStrong value={block.block_hash} />
      </header>

      <dl className="block-meta">
        <div>
          <dt>Previous</dt>
          <dd>
            <ReferenceText value={block.previous_hash} />
          </dd>
        </div>
        <div>
          <dt>Nonce</dt>
          <dd>{formatNumber(block.nonce)}</dd>
        </div>
        <div>
          <dt>Checked</dt>
          <dd>{formatNumber(block.nonces_checked)}</dd>
        </div>
        <div>
          <dt>Time</dt>
          <dd>{formatTimestamp(block.timestamp)}</dd>
        </div>
        <div>
          <dt>Description</dt>
          <dd>{block.description || "-"}</dd>
        </div>
      </dl>

      <div className="block-transactions">
        <div className="block-subtitle">
          <h3>Transactions</h3>
          <span>{block.transactions.length}</span>
        </div>
        {block.transactions.length === 0 ? (
          <p className="empty">No transactions in this block.</p>
        ) : (
          block.transactions.map((transaction) => (
            <BlockchainTransactionCard transaction={transaction} key={transaction.transaction_id} />
          ))
        )}
      </div>
    </section>
  );
}

function BlockchainTransactionCard({ transaction }: { transaction: TransactionPayload }) {
  const transactionClass = isMiningRewardTransaction(transaction)
    ? "reward"
    : transactionKind(transaction).replace(/[^a-z0-9-]/gi, "-").toLowerCase();

  return (
    <article className={`chain-transaction ${transactionClass}`}>
      <div className="transaction-heading">
        <strong>{transactionKindLabel(transaction)}</strong>
        <ReferenceText value={transaction.transaction_id} />
      </div>
      <dl>
        {transactionRows(transaction).map((row) => (
          <div key={`${transaction.transaction_id}-${row.label}`}>
            <dt>{row.label}</dt>
            <dd title={row.title}>
              <ReferenceText value={row.value} title={row.title ?? row.value} />
            </dd>
          </div>
        ))}
      </dl>
    </article>
  );
}

function PeerList({
  title,
  peers,
  actionLabel,
  disableAction = false,
  onPeerAction,
}: {
  title: string;
  peers: string[];
  actionLabel?: string;
  disableAction?: boolean;
  onPeerAction?: (peer: string) => void;
}) {
  return (
    <section className="panel">
      <div className="panel-title">
        <h3>{title}</h3>
        <span>{peers.length}</span>
      </div>
      <div className="list">
        {peers.length === 0 ? (
          <p className="empty">None</p>
        ) : (
          peers.map((peer) => (
            <div className="list-row" key={peer}>
              <ReferenceCode value={peer} />
              {actionLabel && onPeerAction ? (
                <button
                  type="button"
                  className="compact-action"
                  disabled={disableAction}
                  onClick={() => onPeerAction(peer)}
                >
                  {actionLabel}
                </button>
              ) : null}
            </div>
          ))
        )}
      </div>
    </section>
  );
}

export default App;

import { Fragment, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  authorizeContract,
  buildMiningBackend,
  connectPeer,
  createCommitment,
  deployContract,
  discoverPeers,
  executeContract,
  mineBlock,
  readAuthorizations,
  readBalances,
  readBlock,
  readBlocks,
  readChainHead,
  readContracts,
  readMiningBackends,
  readMiningStatus,
  readMessages,
  readNetworkStats,
  readNodeInfo,
  readPeers,
  readPendingTransactions,
  readReceipts,
  readSyncStatus,
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
  "100.83.72.12:6000",
];
const DEFAULT_DEPLOY_JSON = `{
  "program": [["HALT"]],
  "metadata": {"name": "noop"}
}`;
const DEFAULT_EXECUTE_JSON = "null";
const RECENT_BLOCK_LIMIT = 12;
const BLOCKCHAIN_VIEW_BLOCKS = 2;
const MINING_REWARD_SENDER = "SYSTEM";
const RANDOMNESS_SEED_MODULUS = 1n << 256n;

type TabId = "overview" | "blockchain" | "transfer" | "mining" | "wallet" | "network" | "messages" | "contracts" | "logs";
type TabIconName = "overview" | "blocks" | "transfer" | "pickaxe" | "wallet" | "network" | "messages" | "contracts" | "logs";

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
};

type StartupPhase = "idle" | "starting-node" | "waiting-api" | "warming-miner" | "connecting-bootstrap" | "fastsync" | "ready";

const tabs: Array<{ id: TabId; label: string; icon: TabIconName }> = [
  { id: "overview", label: "Overview", icon: "overview" },
  { id: "blockchain", label: "Blockchain", icon: "blocks" },
  { id: "transfer", label: "Transfer", icon: "transfer" },
  { id: "mining", label: "Mining", icon: "pickaxe" },
  { id: "wallet", label: "Wallet", icon: "wallet" },
  { id: "network", label: "Network", icon: "network" },
  { id: "messages", label: "Messages", icon: "messages" },
  { id: "contracts", label: "Contracts", icon: "contracts" },
  { id: "logs", label: "Logs", icon: "logs" },
];

function TabIcon({ name }: { name: TabIconName }) {
  switch (name) {
    case "overview":
      return (
        <svg className="tab-icon" viewBox="0 0 20 20" aria-hidden="true">
          <path d="M4 11.5h4.5V16H4z" />
          <path d="M11.5 4H16v12h-4.5z" />
          <path d="M4 4h4.5v4.5H4z" />
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

  const [activeTab, setActiveTab] = useState<TabId>("overview");
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
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [miningStatus, setMiningStatus] = useState<MiningStatus | null>(null);
  const [miningBackends, setMiningBackends] = useState<MiningBackendsResponse | null>(null);
  const [miningBackendsLoading, setMiningBackendsLoading] = useState(false);
  const [miningBackendsError, setMiningBackendsError] = useState<string | null>(null);
  const [warmMinerOnStartup, setWarmMinerOnStartup] = useState(true);
  const [blockchainSearch, setBlockchainSearch] = useState("");
  const [blockchainWindow, setBlockchainWindow] = useState<BlockchainWindow | null>(null);
  const [blockchainSearchError, setBlockchainSearchError] = useState<string | null>(null);
  const [seenReceivedMessageCount, setSeenReceivedMessageCount] = useState(0);
  const [randomnessCommits, setRandomnessCommits] = useState<RandomnessCommitRecord[]>([]);
  const [localAddresses, setLocalAddresses] = useState<string[]>([]);
  const [disabledBootstrapPeers, setDisabledBootstrapPeers] = useState<string[]>([]);
  const latestSnapshotRef = useRef<Snapshot>(snapshot);
  const snapshotRefreshRef = useRef<Promise<void> | null>(null);
  const snapshotRefreshQueuedRef = useRef(false);

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
  const [executeContractAddress, setExecuteContractAddress] = useState("");
  const [executeGasLimit, setExecuteGasLimit] = useState("1000");
  const [executeGasPrice, setExecuteGasPrice] = useState("0");
  const [executeValue, setExecuteValue] = useState("0");
  const [executeFee, setExecuteFee] = useState("0");
  const [executeInputJson, setExecuteInputJson] = useState(DEFAULT_EXECUTE_JSON);
  const [authContractAddress, setAuthContractAddress] = useState("");
  const [authRequestId, setAuthRequestId] = useState("");
  const [authValidBlocks, setAuthValidBlocks] = useState("");

  const activeApiPort = nodeState.config?.apiPort ?? Number(apiPort);
  const isApiAvailable = nodeState.running && Number.isInteger(activeApiPort);
  const launchPeerList = useMemo(
    () => launchPeers.split(",").map((peer) => peer.trim()).filter(Boolean),
    [launchPeers],
  );
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
  const unreadMessageCount = Math.max(0, receivedMessageCount - seenReceivedMessageCount);
  const pendingRandomnessCommits = useMemo(
    () => randomnessCommits.filter((record) => record.status === "pending").reverse(),
    [randomnessCommits],
  );
  const finishedRandomnessCommits = useMemo(
    () => randomnessCommits.filter((record) => record.status === "revealed").reverse(),
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

  const saveRandomnessCommits = useCallback(async (records: RandomnessCommitRecord[]) => {
    setRandomnessCommits(records);
    if (!desktopStateKey) {
      return;
    }
    const nextState = await window.unccoinDesktop.updateDesktopState(desktopStateKey, {
      randomnessCommits: records,
    });
    setRandomnessCommits(nextState.randomnessCommits);
  }, [desktopStateKey]);

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
  }, []);

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
    if (!desktopStateKey) {
      setSeenReceivedMessageCount(0);
      setRandomnessCommits([]);
      return undefined;
    }

    let cancelled = false;
    window.unccoinDesktop.readDesktopState(desktopStateKey)
      .then((state) => {
        if (!cancelled) {
          setSeenReceivedMessageCount(state.seenReceivedMessageCount);
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
            detail: connectError instanceof Error ? connectError.message : String(connectError),
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
      const targetBlock = await readBlock(activeApiPort, resolvedReference);
      const fromHeight = targetBlock.height === 0 ? 0 : targetBlock.height - 1;
      const response = await readBlocks(activeApiPort, BLOCKCHAIN_VIEW_BLOCKS, fromHeight);
      const blocks = response.blocks.some((block) => block.block_hash === targetBlock.block_hash)
        ? response.blocks
        : [targetBlock];
      setBlockchainWindow({
        reference: resolvedReference,
        targetHash: targetBlock.block_hash,
        targetHeight: targetBlock.height,
        blocks,
      });
      if (movedToTip) {
        setBlockchainSearch(String(targetBlock.height));
        setNotice(`Moved to tip with hash ${targetBlock.block_hash.slice(0, 8)}`);
      }
    } catch (searchError) {
      setBlockchainSearchError(searchError instanceof Error ? searchError.message : String(searchError));
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
              detail: connectError instanceof Error ? connectError.message : String(connectError),
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
      await saveRandomnessCommits([...randomnessCommits, nextRecord]);
      return { label: "Broadcast commitment", detail: response.transaction_id };
    });
  }

  async function handleRevealSavedCommit(record: RandomnessCommitRecord) {
    await runNodeAction("reveal-randomness", async () => {
      const response = await revealCommitment(activeApiPort, {
        request_id: record.requestId,
        seed: record.seed,
        fee: revealFee,
        salt: record.salt,
      });
      const revealedRecord: RandomnessCommitRecord = {
        ...record,
        status: "revealed",
        revealTransactionId: response.transaction_id,
        revealedAt: new Date().toISOString(),
      };
      await saveRandomnessCommits(
        randomnessCommits.map((currentRecord) => (
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

  async function handleExecute(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("execute-contract", async () => {
      const parsedInput = parseJsonField(executeInputJson, "Execute input JSON");
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
                    ? BOOTSTRAP_PEERS.map((peer) => ({ peer, status: "pending" as const }))
                    : bootstrapAttempts
                  ).map((attempt) => (
                    <div className={`peer-status ${attempt.status}`} key={attempt.peer}>
                      <ReferenceCode value={attempt.peer} />
                      <span>{attempt.status}</span>
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
  const latestBlockchainBlocks = snapshot.blocks.slice(-BLOCKCHAIN_VIEW_BLOCKS);
  const blockchainBlocks = blockchainWindow?.blocks ?? latestBlockchainBlocks;
  const blockchainSlots = [
    ...Array<BlockPayload | null>(Math.max(0, BLOCKCHAIN_VIEW_BLOCKS - blockchainBlocks.length)).fill(null),
    ...blockchainBlocks,
  ];
  const blockchainWindowLabel = blockchainWindow
    ? `Focused on block #${blockchainWindow.targetHeight}`
    : "Latest blocks";
  const latestBlocks = [...snapshot.blocks].reverse().slice(0, 8);
  const latestMessages = newestFirst(snapshot.messages).slice(0, 10);
  const latestReceipts = snapshot.receipts.slice(-8).reverse();
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

        {activeTab === "overview" ? (
          <section className="view">
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

            <section className="panel">
              <div className="panel-title">
                <h3>All Balances</h3>
                <span>{snapshot.balances.length}</span>
              </div>
              <div className="table">
                {balancesByAmount.length === 0 ? (
                  <p className="empty">No balances loaded.</p>
                ) : (
                  balancesByAmount.map((balance) => (
                    <div className="table-row" key={balance.address}>
                      <ReferenceCode value={balance.address} />
                      <span>{balance.alias || "-"}</span>
                      <strong>{balance.balance}</strong>
                    </div>
                  ))
                )}
              </div>
            </section>

            <section className="panel">
              <div className="panel-title">
                <h3>Recent Blocks</h3>
                <span>{latestBlocks.length}</span>
              </div>
              <div className="list">
                {latestBlocks.length === 0 ? (
                  <p className="empty">No blocks loaded.</p>
                ) : (
                  latestBlocks.map((block) => (
                    <div className="list-row" key={block.block_hash}>
                      <ReferenceText value={block.block_hash} title={block.block_hash} prefix={`#${block.height} `} />
                      <strong>{block.transaction_count} tx</strong>
                    </div>
                  ))
                )}
              </div>
            </section>
          </section>
        ) : null}

        {activeTab === "blockchain" ? (
          <section className="view blockchain-view">
            <section className="panel blockchain-toolbar">
              <div>
                <strong>{blockchainWindowLabel}</strong>
                <ReferenceText value={blockchainWindow ? blockchainWindow.targetHash : snapshot.chainHead?.tip_hash} />
              </div>
              <form className="block-search-form" onSubmit={handleBlockchainSearch}>
                <input
                  value={blockchainSearch}
                  placeholder="Block height or hash"
                  onChange={(event) => setBlockchainSearch(event.target.value)}
                  disabled={busyAction === "blockchain-search"}
                />
                <button type="submit" disabled={!isApiAvailable || busyAction === "blockchain-search"}>
                  Jump
                </button>
                <button type="button" onClick={clearBlockchainSearch} disabled={busyAction === "blockchain-search"}>
                  Latest
                </button>
              </form>
              {blockchainSearchError ? <p>{blockchainSearchError}</p> : null}
            </section>
            <div className="blockchain-strip">
              {blockchainSlots.map((block, index) => (
                <Fragment key={block?.block_hash ?? `empty-${index}`}>
                  <BlockchainBlockCard
                    block={block}
                    focused={block !== null && block.block_hash === blockchainWindow?.targetHash}
                  />
                  {index < BLOCKCHAIN_VIEW_BLOCKS - 1 ? (
                    <div className="block-arrow" aria-label="Next block">
                      <span aria-hidden="true">&rarr;</span>
                    </div>
                  ) : null}
                </Fragment>
              ))}
            </div>
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
                        className="select-row"
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
                              ) : needsWarmup ? (
                                <span
                                  className="backend-warmup-warning"
                                  title={`${option.label} is not warmed up`}
                                >
                                  <WarningIcon className="backend-warmup-icon" />
                                </span>
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
                          <span title={attempt.detail}>{attempt.detail ?? attempt.status}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </section>

              <section className="panel">
                <div className="panel-title">
                  <h3>Node</h3>
                  <span>{snapshot.nodeInfo?.private_automine ? "private automine" : "canonical"}</span>
                </div>
                <dl className="detail-list">
                  <div>
                    <dt>Host</dt>
                    <dd>{snapshot.nodeInfo?.host ?? host}</dd>
                  </div>
                  <div>
                    <dt>Port</dt>
                    <dd>{snapshot.nodeInfo?.port ?? port}</dd>
                  </div>
                  <div>
                    <dt>API Port</dt>
                    <dd>{activeApiPort || "-"}</dd>
                  </div>
                </dl>
              </section>
            </div>

            <section className="panel network-stats-panel">
              <div className="panel-title">
                <h3>Network Traffic</h3>
                <span>{snapshot.networkStats.peers.length} tracked</span>
              </div>
              <div className="traffic-summary">
                <article>
                  <span>Ingress</span>
                  <strong>{formatBytes(snapshot.networkStats.ingress.bytes)}</strong>
                  <small>{formatNumber(snapshot.networkStats.ingress.messages)} messages</small>
                </article>
                <article>
                  <span>Egress</span>
                  <strong>{formatBytes(snapshot.networkStats.egress.bytes)}</strong>
                  <small>{formatNumber(snapshot.networkStats.egress.messages)} messages</small>
                </article>
              </div>
              <div className="traffic-peer-list">
                {snapshot.networkStats.peers.length === 0 ? (
                  <p className="empty">No P2P traffic recorded yet.</p>
                ) : (
                  snapshot.networkStats.peers.map((peer) => (
                    <div className="traffic-peer-row" key={peer.peer}>
                      <div>
                        <ReferenceCode value={peer.peer} />
                        <span>{peer.connected ? "connected" : "disconnected"}</span>
                      </div>
                      <dl>
                        <div>
                          <dt>In</dt>
                          <dd>{formatBytes(peer.ingress.bytes)} / {formatNumber(peer.ingress.messages)} msg</dd>
                        </div>
                        <div>
                          <dt>Out</dt>
                          <dd>{formatBytes(peer.egress.bytes)} / {formatNumber(peer.egress.messages)} msg</dd>
                        </div>
                      </dl>
                    </div>
                  ))
                )}
              </div>
            </section>

            <div className="panel-grid two">
              <PeerList title="Connected Peers" peers={connectedPeers} />
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
          <section className="view">
            <div className="panel-grid two">
              <section className="panel">
                <div className="panel-title">
                  <h3>Deploy</h3>
                  <span>{snapshot.contracts.length} contracts</span>
                </div>
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
              </section>

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
                  <label>
                    Input JSON
                    <textarea className="code-input" value={executeInputJson} onChange={(event) => setExecuteInputJson(event.target.value)} />
                  </label>
                  <button type="submit" disabled={disableNodeAction}>
                    Execute
                  </button>
                </form>
              </section>
            </div>

            <div className="panel-grid two">
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
                            <ReferenceCode value={record.revealTransactionId} prefix="reveal " />
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
            </div>

            <div className="panel-grid two">
              <section className="panel">
                <div className="panel-title">
                  <h3>Contracts</h3>
                  <span>{snapshot.contracts.length}</span>
                </div>
                <div className="list">
                  {snapshot.contracts.length === 0 ? (
                    <p className="empty">No contracts deployed.</p>
                  ) : (
                    snapshot.contracts.map((contract) => (
                      <button
                        type="button"
                        className="select-row"
                        key={contract.address}
                        onClick={() => {
                          setExecuteContractAddress(contract.address);
                          setAuthContractAddress(contract.address);
                        }}
                      >
                        <span className="contract-card-main">
                          <strong>{contractDisplayName(contract)}</strong>
                          <ReferenceCode value={contract.address} />
                        </span>
                        <span className="contract-row-meta">
                          <ReferenceCode value={contractCodeHash(contract)} prefix="code " />
                          <span>{Object.keys(contract.storage).length} storage</span>
                        </span>
                      </button>
                    ))
                  )}
                </div>
              </section>

              <section className="panel">
                <div className="panel-title">
                  <h3>Receipts</h3>
                  <span>{latestReceipts.length}</span>
                </div>
                <div className="list">
                  {latestReceipts.length === 0 ? (
                    <p className="empty">No receipts yet.</p>
                  ) : (
                    latestReceipts.map((receipt) => (
                      <details className="details-row" key={receipt.transaction_id}>
                        <summary>
                          <ReferenceText value={receipt.transaction_id} />
                        </summary>
                        <pre>{formatJson(receipt.receipt)}</pre>
                      </details>
                    ))
                  )}
                </div>
              </section>
            </div>
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

function BlockchainBlockCard({ block, focused = false }: { block: BlockPayload | null; focused?: boolean }) {
  if (!block) {
    return (
      <section className="block-card empty-block">
        <header>
          <span>Block</span>
          <strong>Waiting</strong>
        </header>
        <p className="empty">No earlier canonical block loaded.</p>
      </section>
    );
  }

  return (
    <section className={`block-card ${focused ? "focused-block" : ""}`}>
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

function PeerList({ title, peers }: { title: string; peers: string[] }) {
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
            </div>
          ))
        )}
      </div>
    </section>
  );
}

export default App;

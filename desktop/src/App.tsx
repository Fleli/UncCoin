import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  authorizeContract,
  connectPeer,
  createCommitment,
  deployContract,
  discoverPeers,
  executeContract,
  mineBlock,
  readAuthorizations,
  readBalances,
  readBlocks,
  readChainHead,
  readContracts,
  readMessages,
  readNodeInfo,
  readPeers,
  readPendingTransactions,
  readReceipts,
  readSyncStatus,
  revealCommitment,
  sendAuthorization,
  sendMessage,
  sendTransaction,
  setAlias,
  setAutosend,
  startAutomine,
  stopAutomine,
  storeAuthorization,
  syncChain,
  type BalanceRow,
  type BlockPayload,
  type ChainHead,
  type ContractEntry,
  type MessageEntry,
  type NodeInfo,
  type PeersResponse,
  type ReceiptEntry,
  type SyncStatus,
  type TransactionPayload,
} from "./api";
import "./styles.css";

const DEFAULT_PORT = 9000;
const BOOTSTRAP_PEERS = [
  "100.98.249.35:9000",
  "100.98.249.35:9001",
  "100.71.105.5:4040",
];
const DEFAULT_DEPLOY_JSON = `{
  "program": [["HALT"]],
  "metadata": {"name": "noop"}
}`;
const DEFAULT_EXECUTE_JSON = "null";
const DEFAULT_AUTH_JSON = "[]";

type TabId = "overview" | "wallet" | "network" | "messages" | "contracts" | "logs";

type Snapshot = {
  nodeInfo: NodeInfo | null;
  chainHead: ChainHead | null;
  balances: BalanceRow[];
  peers: PeersResponse;
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

type BootstrapAttempt = {
  peer: string;
  status: "pending" | "connected" | "failed" | "skipped";
  detail?: string;
};

type StartupPhase = "idle" | "starting-node" | "waiting-api" | "connecting-bootstrap" | "fastsync" | "ready";

const tabs: Array<{ id: TabId; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "wallet", label: "Wallet" },
  { id: "network", label: "Network" },
  { id: "messages", label: "Messages" },
  { id: "contracts", label: "Contracts" },
  { id: "logs", label: "Logs" },
];

function emptySnapshot(): Snapshot {
  return {
    nodeInfo: null,
    chainHead: null,
    balances: [],
    peers: { connected: [], known: [] },
    pendingTransactions: [],
    blocks: [],
    messages: [],
    contracts: [],
    receipts: [],
    authorizations: [],
  };
}

function shortHash(value: string | null | undefined, length = 12): string {
  if (!value) {
    return "-";
  }
  return value.length > length ? value.slice(0, length) : value;
}

function formatAmount(value: string | null | undefined): string {
  return value ?? "0";
}

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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
    return `${shortHash(transaction.sender)} -> ${shortHash(transaction.receiver)} (${transaction.amount})`;
  }
  return `${kind} ${shortHash(transaction.receiver)}`;
}

function newestFirst<T extends { timestamp?: string }>(items: T[]): T[] {
  return [...items].sort((left, right) => String(right.timestamp ?? "").localeCompare(String(left.timestamp ?? "")));
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
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
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [localAddresses, setLocalAddresses] = useState<string[]>([]);
  const [disabledBootstrapPeers, setDisabledBootstrapPeers] = useState<string[]>([]);

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
  const [commitHash, setCommitHash] = useState("");
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
  const [executeAuthJson, setExecuteAuthJson] = useState(DEFAULT_AUTH_JSON);
  const [authContractAddress, setAuthContractAddress] = useState("");
  const [authRequestId, setAuthRequestId] = useState("");
  const [authValidBlocks, setAuthValidBlocks] = useState("");
  const [authReceiver, setAuthReceiver] = useState("");
  const [authorizationJson, setAuthorizationJson] = useState("{}");

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
  const isPreferredPortDirty = (
    selectedWallet !== undefined
    && Number(port) !== selectedWallet.preferredPort
  );
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

  const loadSnapshot = useCallback(async (apiPortToUse: number) => {
    const [
      nodeInfo,
      chainHead,
      balances,
      peers,
      pendingTransactions,
      blocks,
      messages,
      contracts,
      receipts,
      authorizations,
    ] = await Promise.all([
      readNodeInfo(apiPortToUse),
      readChainHead(apiPortToUse),
      readBalances(apiPortToUse),
      readPeers(apiPortToUse),
      readPendingTransactions(apiPortToUse),
      readBlocks(apiPortToUse),
      readMessages(apiPortToUse),
      readContracts(apiPortToUse),
      readReceipts(apiPortToUse),
      readAuthorizations(apiPortToUse),
    ]);

    setSnapshot({
      nodeInfo,
      chainHead,
      balances: balances.balances,
      peers,
      pendingTransactions: pendingTransactions.transactions,
      blocks: blocks.blocks,
      messages: messages.messages,
      contracts: contracts.contracts,
      receipts: receipts.receipts,
      authorizations: authorizations.authorizations,
    });
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

    await loadSnapshot(activeApiPort);
  }, [activeApiPort, isApiAvailable, loadSnapshot]);

  function applyWalletSelection(walletNameToSelect: string, availableWallets = wallets) {
    setWalletName(walletNameToSelect);
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
      setSnapshot(emptySnapshot());
      setApiStatus("offline");
      return undefined;
    }

    let cancelled = false;
    const poll = async () => {
      try {
        await refreshSnapshot();
        if (!cancelled) {
          setError(null);
        }
      } catch (pollError) {
        if (!cancelled) {
          setApiStatus("starting");
          setError(String(pollError));
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
  }, [isApiAvailable, refreshSnapshot]);

  async function waitForNodeApi(apiPortToCheck: number) {
    setStartupPhase("waiting-api");
    setApiStatus("starting");
    for (let attempt = 0; attempt < 60; attempt += 1) {
      try {
        const nodeInfo = await readNodeInfo(apiPortToCheck);
        setSnapshot((currentSnapshot) => ({
          ...currentSnapshot,
          nodeInfo,
        }));
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

    await loadSnapshot(apiPortToUse);
    setStartupPhase("ready");
    setStartupComplete(true);
  }

  async function runNodeAction(label: string, action: () => Promise<ActionResult | void>) {
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
      await refreshSnapshot();
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
    try {
      const wallet = await window.unccoinDesktop.createWallet(name, undefined, Number(port));
      const nextWallets = await window.unccoinDesktop.listWallets();
      setWallets(nextWallets);
      applyWalletSelection(wallet.name, nextWallets);
      setWalletSearch("");
      setNewWalletName("");
      setNotice(`Created wallet ${wallet.name}`);
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
      const wallet = await window.unccoinDesktop.updateWalletPreferredPort(walletName, Number(port));
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

  async function handleStart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusyAction("start-node");
    setStartupPhase("starting-node");
    setStartupComplete(false);
    setBootstrapAttempts([]);
    setSyncStatus(null);
    setError(null);
    setNotice(null);
    try {
      const nextState = await window.unccoinDesktop.startNode({
        walletName,
        host,
        port: Number(port),
        apiPort: Number(apiPort),
        peers: launchPeerList,
      });
      setNodeState(nextState);
      const startupApiPort = nextState.config?.apiPort ?? Number(apiPort);
      await finishStartup(startupApiPort, nextState.config);
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
      setSnapshot(emptySnapshot());
      setApiStatus("offline");
      setStartupPhase("idle");
      setStartupComplete(false);
      setBootstrapAttempts([]);
      setSyncStatus(null);
      setNotice("Stopped node");
    } catch (stopError) {
      setError(String(stopError));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleTransaction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("send-transaction", async () => {
      const response = await sendTransaction(activeApiPort, {
        receiver: txReceiver,
        amount: txAmount,
        fee: txFee,
      });
      return { label: "Broadcast transaction", detail: shortHash(response.transaction_id) };
    });
  }

  async function handleMine(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("mine-block", async () => {
      const response = await mineBlock(activeApiPort, mineDescription || undefined);
      return { label: "Mined block", detail: `${response.block.height} ${shortHash(response.block.block_hash)}` };
    });
  }

  async function handleConnectPeer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("connect-peer", async () => {
      const response = await connectPeer(activeApiPort, peerAddress);
      return { label: "Connected peers", detail: String(response.connected.length) };
    });
  }

  async function handleMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("send-message", async () => {
      const response = await sendMessage(activeApiPort, {
        receiver: messageReceiver,
        content: messageContent,
      });
      setMessageContent("");
      return { label: "Sent message", detail: shortHash(response.message.message_id) };
    });
  }

  async function handleAlias(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("set-alias", async () => {
      const response = await setAlias(activeApiPort, {
        wallet: aliasWallet,
        alias: aliasName,
      });
      return { label: "Saved alias", detail: response.alias ?? shortHash(response.wallet) };
    });
  }

  async function handleAutosend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("set-autosend", async () => {
      const response = await setAutosend(activeApiPort, autosendTarget || null);
      return {
        label: response.enabled ? "Autosend enabled" : "Autosend disabled",
        detail: response.target ? shortHash(response.target) : undefined,
      };
    });
  }

  async function handleCommit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("commit-randomness", async () => {
      const response = await createCommitment(activeApiPort, {
        request_id: commitRequestId,
        commitment_hash: commitHash,
        fee: commitFee,
      });
      return { label: "Broadcast commitment", detail: shortHash(response.transaction_id) };
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
      return { label: "Broadcast reveal", detail: shortHash(response.transaction_id) };
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
      return { label: "Broadcast deploy", detail: shortHash(response.contract_address) };
    });
  }

  async function handleExecute(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runNodeAction("execute-contract", async () => {
      const parsedInput = parseJsonField(executeInputJson, "Execute input JSON");
      const parsedAuthorizations = parseJsonField(executeAuthJson || "[]", "Authorizations JSON");
      if (!Array.isArray(parsedAuthorizations)) {
        throw new Error("Authorizations JSON must be an array.");
      }
      const response = await executeContract(activeApiPort, {
        contract_address: executeContractAddress,
        gas_limit: executeGasLimit,
        gas_price: executeGasPrice,
        value: executeValue,
        fee: executeFee,
        input: parsedInput,
        authorizations: parsedAuthorizations.filter(isRecord),
      });
      return { label: "Broadcast execute", detail: shortHash(response.transaction_id) };
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
      setAuthorizationJson(formatJson(response.authorization));
      return { label: "Created authorization", detail: authRequestId };
    });
  }

  async function handleStoreAuthorization() {
    await runNodeAction("store-authorization", async () => {
      const parsedAuthorization = parseJsonField(authorizationJson, "Authorization JSON");
      if (!isRecord(parsedAuthorization)) {
        throw new Error("Authorization JSON must be an object.");
      }
      const response = await storeAuthorization(activeApiPort, parsedAuthorization);
      return { label: response.stored ? "Stored authorization" : "Authorization already stored" };
    });
  }

  async function handleSendAuthorization() {
    await runNodeAction("send-authorization", async () => {
      const response = await sendAuthorization(activeApiPort, {
        receiver: authReceiver,
        contract_address: authContractAddress,
        request_id: authRequestId,
        valid_for_blocks: authValidBlocks || null,
      });
      return { label: "Sent authorization", detail: shortHash(response.message.message_id) };
    });
  }

  const isStartingNode = (
    busyAction === "start-node"
    || (nodeState.running && !startupComplete)
  );
  const launchLogs = logs.slice(-5);
  const activeSyncPeers = syncStatus?.fastsync.peers ?? [];
  const startupStatusLabel = startupPhase.replace("-", " ");
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
              <div className="launch-header">
                <div>
                  <h1>Starting Node</h1>
                  <p>{nodeState.config?.walletName || walletName || "Selected wallet"}</p>
                </div>
                <span className="spinner" aria-label="Starting" />
              </div>
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
              </dl>
              <div className="bootstrap-panel">
                <h3>Bootstrap Peers</h3>
                <div className="bootstrap-list">
                  {(bootstrapAttempts.length === 0
                    ? BOOTSTRAP_PEERS.map((peer) => ({ peer, status: "pending" as const }))
                    : bootstrapAttempts
                  ).map((attempt) => (
                    <div className={`peer-status ${attempt.status}`} key={attempt.peer}>
                      <code>{attempt.peer}</code>
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
                          <code>{peer.peer}</code>
                          <span>height {peer.expected_start_height}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : null}
              {error ? <p className="launch-error">{error}</p> : null}
              {launchLogs.length > 0 ? (
                <pre className="launch-log">
                  {launchLogs.map((entry) => `[${entry.stream}] ${entry.message}`).join("")}
                </pre>
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
                            <code>{shortHash(wallet.address, 18)}</code>
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

                    <button type="submit" disabled={!walletName || busyAction !== null}>
                      Start Node
                    </button>
                  </form>
                </section>

                <section className="launch-pane create-pane">
                  <div className="pane-title">
                    <h2>Create New Wallet</h2>
                    <p>Uses the selected P2P port as the wallet default.</p>
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
                    <dl className="create-summary">
                      <div>
                        <dt>Preferred Port</dt>
                        <dd>{port}</dd>
                      </div>
                      <div>
                        <dt>API Port</dt>
                        <dd>{apiPort}</dd>
                      </div>
                    </dl>
                    <button type="submit" disabled={!newWalletName.trim() || busyAction !== null}>
                      Create Wallet
                    </button>
                  </form>
                </section>
              </div>

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
                        <code>{peer}</code>
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
  const latestBlocks = [...snapshot.blocks].reverse().slice(0, 8);
  const latestMessages = newestFirst(snapshot.messages).slice(0, 10);
  const latestReceipts = snapshot.receipts.slice(-8).reverse();
  const connectedPeers = snapshot.peers.connected;
  const knownPeers = snapshot.peers.known;
  const disableNodeAction = !isApiAvailable || busyAction !== null;

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

        <section className="side-section">
          <form onSubmit={handleStart}>
            <label>
              Wallet
              <select
                value={walletName}
                onChange={(event) => applyWalletSelection(event.target.value)}
                disabled={nodeState.running}
              >
                <option value="">Select wallet</option>
                {wallets.map((wallet) => (
                  <option key={wallet.name} value={wallet.name}>
                    {wallet.name}
                  </option>
                ))}
              </select>
            </label>
            <div className="field-row">
              <label>
                P2P
                <input
                  value={port}
                  inputMode="numeric"
                  onChange={(event) => {
                    setPort(event.target.value);
                    if (!nodeState.running) {
                      const nextPort = Number(event.target.value || DEFAULT_PORT);
                      setApiPort(String(nextPort + 10000));
                    }
                  }}
                  disabled={nodeState.running}
                />
              </label>
              <label>
                API
                <input
                  value={apiPort}
                  inputMode="numeric"
                  onChange={(event) => setApiPort(event.target.value)}
                  disabled={nodeState.running}
                />
              </label>
            </div>
            <label>
              Host
              <input
                value={host}
                onChange={(event) => setHost(event.target.value)}
                disabled={nodeState.running}
              />
            </label>
            <label>
              Peers
              <input
                value={launchPeers}
                placeholder="127.0.0.1:9001, 127.0.0.1:9002"
                onChange={(event) => setLaunchPeers(event.target.value)}
                disabled={nodeState.running}
              />
            </label>
            <div className="button-row">
              <button type="submit" disabled={nodeState.running || busyAction === "start-node"}>
                Start
              </button>
              <button type="button" onClick={handleStop} disabled={!nodeState.running || busyAction === "stop-node"}>
                Stop
              </button>
            </div>
          </form>
        </section>

        <nav className="tabs" aria-label="Primary">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={activeTab === tab.id ? "active" : ""}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
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
          <div>
            <h2>{tabs.find((tab) => tab.id === activeTab)?.label}</h2>
            <p>{loadedWallet ? shortHash(loadedWallet.address, 18) : "No wallet loaded"}</p>
          </div>
          <div className="topbar-actions">
            {notice ? <span className="notice">{notice}</span> : null}
            {error ? <span className="error-banner">{error}</span> : null}
            <button type="button" onClick={() => void refreshSnapshot()} disabled={!isApiAvailable}>
              Refresh
            </button>
          </div>
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
                <strong>{shortHash(snapshot.chainHead?.tip_hash, 22)}</strong>
              </article>
            </div>

            <div className="panel-grid two">
              <section className="panel">
                <div className="panel-title">
                  <h3>Balances</h3>
                  <span>{snapshot.balances.length}</span>
                </div>
                <div className="list">
                  {snapshot.balances.length === 0 ? (
                    <p className="empty">No balances loaded.</p>
                  ) : (
                    snapshot.balances.map((balance) => (
                      <div className="list-row" key={balance.address}>
                        <span>{balance.alias || shortHash(balance.address, 18)}</span>
                        <strong>{balance.balance}</strong>
                      </div>
                    ))
                  )}
                </div>
              </section>

              <section className="panel">
                <div className="panel-title">
                  <h3>Pending Transactions</h3>
                  <span>{snapshot.pendingTransactions.length}</span>
                </div>
                <div className="list">
                  {snapshot.pendingTransactions.length === 0 ? (
                    <p className="empty">Mempool is empty.</p>
                  ) : (
                    snapshot.pendingTransactions.map((transaction) => (
                      <div className="list-row stacked" key={transaction.transaction_id}>
                        <span>{transactionSummary(transaction)}</span>
                        <code>{shortHash(transaction.transaction_id, 18)}</code>
                      </div>
                    ))
                  )}
                </div>
              </section>
            </div>

            <div className="panel-grid two">
              <section className="panel">
                <div className="panel-title">
                  <h3>Mining</h3>
                  <span>{busyAction === "mine-block" ? "mining" : "ready"}</span>
                </div>
                <form className="inline-form" onSubmit={handleMine}>
                  <input
                    value={mineDescription}
                    placeholder="Block description"
                    onChange={(event) => setMineDescription(event.target.value)}
                    disabled={disableNodeAction}
                  />
                  <button type="submit" disabled={disableNodeAction}>
                    Mine
                  </button>
                  <button
                    type="button"
                    disabled={disableNodeAction}
                    onClick={() => void runNodeAction("start-automine", async () => {
                      const response = await startAutomine(activeApiPort, mineDescription || undefined);
                      return { label: "Automine started", detail: response.description };
                    })}
                  >
                    Automine
                  </button>
                  <button
                    type="button"
                    disabled={disableNodeAction}
                    onClick={() => void runNodeAction("stop-automine", async () => {
                      await stopAutomine(activeApiPort);
                      return { label: "Automine stopped" };
                    })}
                  >
                    Stop
                  </button>
                </form>
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
                        <span>#{block.height} {shortHash(block.block_hash, 14)}</span>
                        <strong>{block.transaction_count} tx</strong>
                      </div>
                    ))
                  )}
                </div>
              </section>
            </div>
          </section>
        ) : null}

        {activeTab === "wallet" ? (
          <section className="view">
            <div className="panel-grid two">
              <section className="panel">
                <div className="panel-title">
                  <h3>Local Wallets</h3>
                  <span>{wallets.length}</span>
                </div>
                <form className="inline-form" onSubmit={handleCreateWallet}>
                  <input
                    value={newWalletName}
                    placeholder="New wallet name"
                    onChange={(event) => setNewWalletName(event.target.value)}
                    disabled={busyAction === "create-wallet"}
                  />
                  <button type="submit" disabled={busyAction === "create-wallet"}>
                    Create
                  </button>
                </form>
                <div className="list padded">
                  {wallets.length === 0 ? (
                    <p className="empty">No local wallets found.</p>
                  ) : (
                    wallets.map((wallet) => (
                      <button
                        type="button"
                        className="select-row"
                        key={wallet.name}
                        onClick={() => applyWalletSelection(wallet.name)}
                        disabled={nodeState.running}
                      >
                        <span>{wallet.name}</span>
                        <code>{shortHash(wallet.address, 18)}</code>
                      </button>
                    ))
                  )}
                </div>
              </section>

              <section className="panel">
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
                <form className="form-grid" onSubmit={handleAutosend}>
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
            </div>

            <section className="panel">
              <div className="panel-title">
                <h3>All Balances</h3>
                <span>{snapshot.balances.length}</span>
              </div>
              <div className="table">
                {snapshot.balances.map((balance) => (
                  <div className="table-row" key={balance.address}>
                    <code>{balance.address}</code>
                    <span>{balance.alias || "-"}</span>
                    <strong>{balance.balance}</strong>
                  </div>
                ))}
              </div>
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
                </form>
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
                        <code>{shortHash(message.sender || message.peer, 14)}{" -> "}{shortHash(message.receiver, 14)}</code>
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
                  <label>
                    Authorizations JSON
                    <textarea className="code-input short" value={executeAuthJson} onChange={(event) => setExecuteAuthJson(event.target.value)} />
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
                  <label>
                    Receiver
                    <input value={authReceiver} onChange={(event) => setAuthReceiver(event.target.value)} />
                  </label>
                  <label>
                    Authorization JSON
                    <textarea className="code-input short" value={authorizationJson} onChange={(event) => setAuthorizationJson(event.target.value)} />
                  </label>
                  <div className="button-row">
                    <button type="submit" disabled={disableNodeAction}>
                      Create
                    </button>
                    <button type="button" disabled={disableNodeAction} onClick={() => void handleStoreAuthorization()}>
                      Store
                    </button>
                    <button type="button" disabled={disableNodeAction} onClick={() => void handleSendAuthorization()}>
                      Send
                    </button>
                  </div>
                </form>
              </section>

              <section className="panel">
                <div className="panel-title">
                  <h3>Randomness</h3>
                  <span>commit reveal</span>
                </div>
                <form className="form-grid" onSubmit={handleCommit}>
                  <label>
                    Request ID
                    <input value={commitRequestId} onChange={(event) => setCommitRequestId(event.target.value)} />
                  </label>
                  <label>
                    Commitment Hash
                    <input value={commitHash} onChange={(event) => setCommitHash(event.target.value)} />
                  </label>
                  <label>
                    Fee
                    <input value={commitFee} onChange={(event) => setCommitFee(event.target.value)} />
                  </label>
                  <button type="submit" disabled={disableNodeAction}>
                    Commit
                  </button>
                </form>
                <form className="form-grid separated" onSubmit={handleReveal}>
                  <label>
                    Request ID
                    <input value={revealRequestId} onChange={(event) => setRevealRequestId(event.target.value)} />
                  </label>
                  <div className="field-row">
                    <label>
                      Seed
                      <input value={revealSeed} onChange={(event) => setRevealSeed(event.target.value)} />
                    </label>
                    <label>
                      Salt
                      <input value={revealSalt} onChange={(event) => setRevealSalt(event.target.value)} />
                    </label>
                    <label>
                      Fee
                      <input value={revealFee} onChange={(event) => setRevealFee(event.target.value)} />
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
                        <span>{shortHash(contract.address, 18)}</span>
                        <code>{shortHash(String(contract.contract.code_hash ?? ""), 14)}</code>
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
                        <summary>{shortHash(receipt.transaction_id, 18)}</summary>
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
      </section>
    </main>
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
              <code>{peer}</code>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

export default App;

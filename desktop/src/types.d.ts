type StartNodeConfig = {
  walletName: string;
  host: string;
  port: number;
  apiPort?: number;
  peers?: string[];
};

type NodeRuntimeState = {
  running: boolean;
  pid: number | null;
  config: {
    walletName: string;
    host: string;
    port: number;
    apiPort: number;
    peers: string[];
  } | null;
};

type NodeLogEntry = {
  stream: "stdout" | "stderr" | "system";
  message: string;
  timestamp: string;
};

type WalletSummary = {
  name: string;
  address: string;
  path: string;
  preferredPort: number;
};

type WalletKeyDetails = {
  name: string;
  address: string;
  publicKey: {
    exponent: string;
    modulus: string;
  };
  privateKey: {
    exponent: string;
    modulus: string;
  };
};

type DeletedWalletSummary = {
  name: string;
  deletedPath: string;
};

type RandomnessCommitRecord = {
  id: string;
  requestId: string;
  seed: string;
  salt: string;
  commitmentHash: string;
  transactionId: string;
  createdAt: string;
  status: "pending" | "revealed";
  revealTransactionId?: string;
  revealedAt?: string;
};

type DesktopState = {
  seenReceivedMessageCount: number;
  randomnessCommits: RandomnessCommitRecord[];
};

type ApiRequestOptions = {
  method?: "GET" | "POST";
  body?: unknown;
  timeoutMs?: number;
};

interface Window {
  unccoinDesktop: {
    startNode(config: StartNodeConfig): Promise<NodeRuntimeState>;
    stopNode(): Promise<NodeRuntimeState>;
    getNodeState(): Promise<NodeRuntimeState>;
    listWallets(): Promise<WalletSummary[]>;
    readWalletKeys(name: string): Promise<WalletKeyDetails>;
    createWallet(name: string, bitLength?: number, preferredPort?: number): Promise<WalletSummary>;
    updateWalletPreferredPort(name: string, preferredPort: number): Promise<WalletSummary>;
    deleteWallet(name: string): Promise<DeletedWalletSummary>;
    readDesktopState(walletKey: string): Promise<DesktopState>;
    updateDesktopState(walletKey: string, state: Partial<DesktopState>): Promise<DesktopState>;
    getLocalAddresses(): Promise<string[]>;
    fetchApi(apiPort: number, path: string, options?: ApiRequestOptions): Promise<unknown>;
    onNodeLog(callback: (entry: NodeLogEntry) => void): () => void;
    onNodeState(callback: (state: NodeRuntimeState) => void): () => void;
  };
}

import { contextBridge, ipcRenderer, type IpcRendererEvent } from "electron";

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

contextBridge.exposeInMainWorld("unccoinDesktop", {
  startNode: (config: StartNodeConfig): Promise<NodeRuntimeState> => (
    ipcRenderer.invoke("node:start", config)
  ),
  stopNode: (): Promise<NodeRuntimeState> => ipcRenderer.invoke("node:stop"),
  getNodeState: (): Promise<NodeRuntimeState> => ipcRenderer.invoke("node:state"),
  listWallets: (): Promise<WalletSummary[]> => ipcRenderer.invoke("wallets:list"),
  readWalletKeys: (name: string): Promise<WalletKeyDetails> => ipcRenderer.invoke("wallets:keys", name),
  createWallet: (
    name: string,
    bitLength?: number,
    preferredPort?: number,
  ): Promise<WalletSummary> => (
    ipcRenderer.invoke("wallets:create", { name, bitLength, preferredPort })
  ),
  updateWalletPreferredPort: (
    name: string,
    preferredPort: number,
  ): Promise<WalletSummary> => (
    ipcRenderer.invoke("wallets:update-preferred-port", { name, preferredPort })
  ),
  deleteWallet: (name: string): Promise<DeletedWalletSummary> => (
    ipcRenderer.invoke("wallets:delete", { name })
  ),
  readDesktopState: (walletKey: string): Promise<DesktopState> => (
    ipcRenderer.invoke("desktop-state:read", { walletKey })
  ),
  updateDesktopState: (
    walletKey: string,
    state: Partial<DesktopState>,
  ): Promise<DesktopState> => (
    ipcRenderer.invoke("desktop-state:update", { walletKey, ...state })
  ),
  getLocalAddresses: (): Promise<string[]> => ipcRenderer.invoke("system:local-addresses"),
  fetchApi: (apiPort: number, path: string, options: ApiRequestOptions = {}): Promise<unknown> => (
    ipcRenderer.invoke("node-api:fetch", { apiPort, path, ...options })
  ),
  onNodeLog: (callback: (entry: NodeLogEntry) => void): (() => void) => {
    const listener = (_event: IpcRendererEvent, entry: NodeLogEntry) => {
      callback(entry);
    };
    ipcRenderer.on("node-log", listener);
    return () => ipcRenderer.removeListener("node-log", listener);
  },
  onNodeState: (callback: (state: NodeRuntimeState) => void): (() => void) => {
    const listener = (_event: IpcRendererEvent, state: NodeRuntimeState) => {
      callback(state);
    };
    ipcRenderer.on("node-state", listener);
    return () => ipcRenderer.removeListener("node-state", listener);
  },
});

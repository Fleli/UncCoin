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

type DeletedWalletSummary = {
  name: string;
  deletedPath: string;
};

type ApiRequestOptions = {
  method?: "GET" | "POST";
  body?: unknown;
};

contextBridge.exposeInMainWorld("unccoinDesktop", {
  startNode: (config: StartNodeConfig): Promise<NodeRuntimeState> => (
    ipcRenderer.invoke("node:start", config)
  ),
  stopNode: (): Promise<NodeRuntimeState> => ipcRenderer.invoke("node:stop"),
  getNodeState: (): Promise<NodeRuntimeState> => ipcRenderer.invoke("node:state"),
  listWallets: (): Promise<WalletSummary[]> => ipcRenderer.invoke("wallets:list"),
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

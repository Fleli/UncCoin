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

interface Window {
  unccoinDesktop: {
    startNode(config: StartNodeConfig): Promise<NodeRuntimeState>;
    stopNode(): Promise<NodeRuntimeState>;
    getNodeState(): Promise<NodeRuntimeState>;
    listWallets(): Promise<WalletSummary[]>;
    createWallet(name: string, bitLength?: number, preferredPort?: number): Promise<WalletSummary>;
    updateWalletPreferredPort(name: string, preferredPort: number): Promise<WalletSummary>;
    deleteWallet(name: string): Promise<DeletedWalletSummary>;
    getLocalAddresses(): Promise<string[]>;
    fetchApi(apiPort: number, path: string, options?: ApiRequestOptions): Promise<unknown>;
    onNodeLog(callback: (entry: NodeLogEntry) => void): () => void;
    onNodeState(callback: (state: NodeRuntimeState) => void): () => void;
  };
}

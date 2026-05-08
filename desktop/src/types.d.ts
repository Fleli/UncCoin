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
    createWallet(name: string, bitLength?: number): Promise<WalletSummary>;
    getLocalAddresses(): Promise<string[]>;
    fetchApi(apiPort: number, path: string, options?: ApiRequestOptions): Promise<unknown>;
    onNodeLog(callback: (entry: NodeLogEntry) => void): () => void;
    onNodeState(callback: (state: NodeRuntimeState) => void): () => void;
  };
}

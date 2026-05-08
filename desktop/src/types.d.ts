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

interface Window {
  unccoinDesktop: {
    startNode(config: StartNodeConfig): Promise<NodeRuntimeState>;
    stopNode(): Promise<NodeRuntimeState>;
    getNodeState(): Promise<NodeRuntimeState>;
    fetchApi(apiPort: number, path: string): Promise<unknown>;
    onNodeLog(callback: (entry: NodeLogEntry) => void): () => void;
    onNodeState(callback: (state: NodeRuntimeState) => void): () => void;
  };
}

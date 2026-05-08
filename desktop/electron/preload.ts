import { contextBridge, ipcRenderer } from "electron";

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

contextBridge.exposeInMainWorld("unccoinDesktop", {
  startNode: (config: StartNodeConfig): Promise<NodeRuntimeState> => (
    ipcRenderer.invoke("node:start", config)
  ),
  stopNode: (): Promise<NodeRuntimeState> => ipcRenderer.invoke("node:stop"),
  getNodeState: (): Promise<NodeRuntimeState> => ipcRenderer.invoke("node:state"),
  fetchApi: (apiPort: number, path: string): Promise<unknown> => (
    ipcRenderer.invoke("node-api:fetch", { apiPort, path })
  ),
  onNodeLog: (callback: (entry: NodeLogEntry) => void): (() => void) => {
    const listener = (_event: Electron.IpcRendererEvent, entry: NodeLogEntry) => {
      callback(entry);
    };
    ipcRenderer.on("node-log", listener);
    return () => ipcRenderer.removeListener("node-log", listener);
  },
  onNodeState: (callback: (state: NodeRuntimeState) => void): (() => void) => {
    const listener = (_event: Electron.IpcRendererEvent, state: NodeRuntimeState) => {
      callback(state);
    };
    ipcRenderer.on("node-state", listener);
    return () => ipcRenderer.removeListener("node-state", listener);
  },
});

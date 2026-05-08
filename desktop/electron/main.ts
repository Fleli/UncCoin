import electron from "electron/main";
import type { BrowserWindow as BrowserWindowType } from "electron";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { mkdir, readFile, readdir, rename, writeFile } from "node:fs/promises";
import { networkInterfaces } from "node:os";
import path from "node:path";

const { app, BrowserWindow, ipcMain } = electron;

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
  config: Required<Omit<StartNodeConfig, "peers">> & { peers: string[] } | null;
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

type CreateWalletRequest = {
  name: string;
  bitLength?: number;
  preferredPort?: number;
};

type UpdateWalletPreferredPortRequest = {
  name: string;
  preferredPort: number;
};

type DeleteWalletRequest = {
  name: string;
};

type DeletedWalletSummary = {
  name: string;
  deletedPath: string;
};

type DesktopState = {
  seenReceivedMessageCount: number;
};

type DesktopStateRequest = {
  walletKey: string;
};

type UpdateDesktopStateRequest = DesktopStateRequest & Partial<DesktopState>;

type NodeApiRequest = {
  apiPort: number;
  path: string;
  method?: "GET" | "POST";
  body?: unknown;
};

let mainWindow: BrowserWindowType | null = null;
let nodeProcess: ChildProcessWithoutNullStreams | null = null;
let nodeConfig: NodeRuntimeState["config"] = null;

const DEFAULT_PREFERRED_PORT = 9000;

function repoRoot(): string {
  return path.resolve(app.getAppPath(), "..");
}

function pythonCommand(): string {
  if (process.env.UNCCOIN_PYTHON) {
    return process.env.UNCCOIN_PYTHON;
  }
  return process.platform === "win32" ? "python" : "python3";
}

function runtimeState(): NodeRuntimeState {
  return {
    running: nodeProcess !== null && nodeProcess.exitCode === null,
    pid: nodeProcess?.pid ?? null,
    config: nodeConfig,
  };
}

function localAddresses(): string[] {
  const addresses = new Set(["127.0.0.1", "::1", "localhost"]);
  for (const networkInterface of Object.values(networkInterfaces())) {
    for (const addressInfo of networkInterface ?? []) {
      addresses.add(addressInfo.address);
    }
  }
  return [...addresses].sort();
}

function normalizePort(value: unknown, fallback = DEFAULT_PREFERRED_PORT): number {
  const port = Number(value);
  if (Number.isInteger(port) && port > 0 && port < 65536) {
    return port;
  }
  return fallback;
}

function requirePort(value: unknown, label: string): number {
  const port = Number(value);
  if (Number.isInteger(port) && port > 0 && port < 65536) {
    return port;
  }
  throw new Error(`${label} must be between 1 and 65535.`);
}

function desktopStatePath(walletKey: string): string {
  const normalizedKey = walletKey.trim();
  if (!normalizedKey) {
    throw new Error("Wallet key is required.");
  }
  const safeKey = normalizedKey.replace(/[^a-zA-Z0-9_.-]/g, "_");
  return path.join(repoRoot(), "state", "desktop", `${safeKey}.json`);
}

function normalizeDesktopState(value: Partial<DesktopState>): DesktopState {
  const seenReceivedMessageCount = Number(value.seenReceivedMessageCount);
  return {
    seenReceivedMessageCount: (
      Number.isInteger(seenReceivedMessageCount) && seenReceivedMessageCount >= 0
        ? seenReceivedMessageCount
        : 0
    ),
  };
}

function sendNodeLog(stream: "stdout" | "stderr" | "system", message: string): void {
  mainWindow?.webContents.send("node-log", {
    stream,
    message,
    timestamp: new Date().toISOString(),
  });
}

function sendNodeState(): void {
  mainWindow?.webContents.send("node-state", runtimeState());
}

async function waitForNodeExit(processToStop: ChildProcessWithoutNullStreams): Promise<void> {
  if (processToStop.exitCode !== null) {
    return;
  }

  await new Promise<void>((resolve) => {
    const timeout = setTimeout(() => {
      if (processToStop.exitCode === null) {
        processToStop.kill();
      }
      resolve();
    }, 5000);

    processToStop.once("exit", () => {
      clearTimeout(timeout);
      resolve();
    });
  });
}

async function stopNode(): Promise<NodeRuntimeState> {
  const processToStop = nodeProcess;
  if (processToStop === null) {
    return runtimeState();
  }

  sendNodeLog("system", "Stopping UncCoin node...");
  if (process.platform === "win32") {
    processToStop.kill();
  } else {
    processToStop.kill("SIGINT");
  }
  await waitForNodeExit(processToStop);
  nodeProcess = null;
  nodeConfig = null;
  sendNodeState();
  return runtimeState();
}

async function startNode(config: StartNodeConfig): Promise<NodeRuntimeState> {
  if (nodeProcess !== null && nodeProcess.exitCode === null) {
    return runtimeState();
  }

  const walletName = config.walletName.trim();
  const port = Number(config.port);
  const apiPort = Number(config.apiPort || port + 10000);
  const host = config.host.trim() || "127.0.0.1";
  const peers = config.peers ?? [];

  if (!walletName) {
    throw new Error("Wallet name is required.");
  }
  if (!Number.isInteger(port) || port <= 0 || port > 65535) {
    throw new Error("Node port must be between 1 and 65535.");
  }
  if (!Number.isInteger(apiPort) || apiPort <= 0 || apiPort > 65535) {
    throw new Error("API port must be between 1 and 65535.");
  }

  const args = [
    "-m",
    "node.cli",
    "--host",
    host,
    "--wallet-name",
    walletName,
    "--port",
    String(port),
    "--api-port",
    String(apiPort),
    "--no-interactive",
    ...peers.flatMap((peer) => ["--peer", peer]),
  ];

  const child = spawn(pythonCommand(), args, {
    cwd: repoRoot(),
    env: {
      ...process.env,
      PYTHONUNBUFFERED: "1",
    },
  });

  nodeProcess = child;
  nodeConfig = {
    walletName,
    host,
    port,
    apiPort,
    peers,
  };
  sendNodeLog("system", `${pythonCommand()} ${args.join(" ")}`);
  sendNodeState();

  child.stdout.on("data", (chunk: Buffer) => {
    sendNodeLog("stdout", chunk.toString());
  });
  child.stderr.on("data", (chunk: Buffer) => {
    sendNodeLog("stderr", chunk.toString());
  });
  child.once("error", (error) => {
    sendNodeLog("stderr", `Failed to start node: ${error.message}`);
  });
  child.once("exit", (code, signal) => {
    sendNodeLog("system", `Node exited with code ${code ?? "null"} signal ${signal ?? "none"}.`);
    nodeProcess = null;
    nodeConfig = null;
    sendNodeState();
  });

  return runtimeState();
}

async function listWallets(): Promise<WalletSummary[]> {
  const walletsDir = path.join(repoRoot(), "state", "wallets");
  let entries: string[] = [];
  try {
    entries = await readdir(walletsDir);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return [];
    }
    throw error;
  }

  const wallets = await Promise.all(
    entries
      .filter((entry) => entry.endsWith(".json"))
      .map(async (entry): Promise<WalletSummary | null> => {
        const filePath = path.join(walletsDir, entry);
        try {
          const walletData = JSON.parse(await readFile(filePath, "utf-8")) as {
            name?: string;
            address?: string;
            preferred_port?: unknown;
          };
          return {
            name: walletData.name || path.basename(entry, ".json"),
            address: walletData.address || "",
            path: filePath,
            preferredPort: normalizePort(walletData.preferred_port),
          };
        } catch (error) {
          sendNodeLog("stderr", `Skipping unreadable wallet ${filePath}: ${String(error)}`);
          return null;
        }
      }),
  );

  return wallets
    .filter((wallet): wallet is WalletSummary => wallet !== null)
    .sort((left, right) => left.name.localeCompare(right.name));
}

function runPython(args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(pythonCommand(), args, {
      cwd: repoRoot(),
      env: {
        ...process.env,
        PYTHONUNBUFFERED: "1",
      },
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString();
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code === 0) {
        resolve(stdout);
        return;
      }
      reject(new Error(stderr.trim() || stdout.trim() || `Python exited with code ${code}`));
    });
  });
}

async function createWallet(request: CreateWalletRequest): Promise<WalletSummary> {
  const name = request.name.trim();
  if (!name) {
    throw new Error("Wallet name is required.");
  }
  const bitLength = Number(request.bitLength || 1024);
  if (!Number.isInteger(bitLength) || bitLength < 512) {
    throw new Error("Wallet bit length must be at least 512.");
  }
  const preferredPort = normalizePort(request.preferredPort);

  await runPython([
    "-m",
    "wallet.cli",
    "create",
    "--name",
    name,
    "--bit-length",
    String(bitLength),
    "--preferred-port",
    String(preferredPort),
  ]);

  const wallet = (await listWallets()).find((candidate) => candidate.name === name);
  if (!wallet) {
    throw new Error(`Created wallet '${name}', but could not read it from disk.`);
  }
  return wallet;
}

async function readWalletKeys(name: string): Promise<WalletKeyDetails> {
  const walletName = name.trim();
  if (!walletName) {
    throw new Error("Wallet name is required.");
  }
  const existingWallet = (await listWallets()).find((candidate) => candidate.name === walletName);
  if (!existingWallet) {
    throw new Error(`Wallet '${walletName}' was not found.`);
  }

  const output = await runPython([
    "-m",
    "wallet.cli",
    "show",
    "--name",
    walletName,
    "--json",
    "--include-private",
  ]);
  const walletData = JSON.parse(output) as {
    name?: string;
    address?: string;
    public_key?: {
      exponent?: unknown;
      modulus?: unknown;
    };
    private_key?: {
      exponent?: unknown;
      modulus?: unknown;
    };
  };

  return {
    name: walletData.name || existingWallet.name,
    address: walletData.address || existingWallet.address,
    publicKey: {
      exponent: String(walletData.public_key?.exponent ?? ""),
      modulus: String(walletData.public_key?.modulus ?? ""),
    },
    privateKey: {
      exponent: String(walletData.private_key?.exponent ?? ""),
      modulus: String(walletData.private_key?.modulus ?? ""),
    },
  };
}

async function updateWalletPreferredPort(
  request: UpdateWalletPreferredPortRequest,
): Promise<WalletSummary> {
  const name = request.name.trim();
  if (!name) {
    throw new Error("Wallet name is required.");
  }
  const preferredPort = requirePort(request.preferredPort, "Preferred port");
  const existingWallet = (await listWallets()).find((candidate) => candidate.name === name);
  if (!existingWallet) {
    throw new Error(`Wallet '${name}' was not found.`);
  }

  const walletData = JSON.parse(await readFile(existingWallet.path, "utf-8")) as Record<string, unknown>;
  walletData.preferred_port = preferredPort;
  await writeFile(existingWallet.path, `${JSON.stringify(walletData, null, 2)}\n`, "utf-8");

  const updatedWallet = (await listWallets()).find((candidate) => candidate.path === existingWallet.path);
  if (!updatedWallet) {
    throw new Error(`Updated wallet '${name}', but could not read it from disk.`);
  }
  return updatedWallet;
}

async function deleteWallet(request: DeleteWalletRequest): Promise<DeletedWalletSummary> {
  const name = request.name.trim();
  if (!name) {
    throw new Error("Wallet name is required.");
  }
  if (nodeProcess !== null && nodeProcess.exitCode === null) {
    throw new Error("Stop the running node before deleting a wallet.");
  }

  const existingWallet = (await listWallets()).find((candidate) => candidate.name === name);
  if (!existingWallet) {
    throw new Error(`Wallet '${name}' was not found.`);
  }

  const deletedDir = path.join(repoRoot(), "state", "deleted");
  const parsedPath = path.parse(existingWallet.path);
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const deletedPath = path.join(
    deletedDir,
    `${parsedPath.name}.${timestamp}${parsedPath.ext || ".json"}`,
  );

  await mkdir(deletedDir, { recursive: true });
  await rename(existingWallet.path, deletedPath);
  return { name, deletedPath };
}

async function readDesktopState(request: DesktopStateRequest): Promise<DesktopState> {
  const statePath = desktopStatePath(request.walletKey);
  try {
    const stateData = JSON.parse(await readFile(statePath, "utf-8")) as Partial<DesktopState>;
    return normalizeDesktopState(stateData);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return normalizeDesktopState({});
    }
    throw error;
  }
}

async function updateDesktopState(request: UpdateDesktopStateRequest): Promise<DesktopState> {
  const statePath = desktopStatePath(request.walletKey);
  const currentState = await readDesktopState(request);
  const nextState = normalizeDesktopState({
    ...currentState,
    ...request,
  });

  await mkdir(path.dirname(statePath), { recursive: true });
  await writeFile(statePath, `${JSON.stringify(nextState, null, 2)}\n`, "utf-8");
  return nextState;
}

async function fetchNodeApi(request: NodeApiRequest): Promise<unknown> {
  const apiPort = Number(request.apiPort);
  if (!Number.isInteger(apiPort) || apiPort <= 0 || apiPort > 65535) {
    throw new Error("API port must be between 1 and 65535.");
  }
  const method = request.method || "GET";
  if (!["GET", "POST"].includes(method)) {
    throw new Error("Unsupported API method.");
  }
  const endpointPath = request.path;
  const normalizedPath = endpointPath.startsWith("/") ? endpointPath : `/${endpointPath}`;
  const response = await fetch(`http://127.0.0.1:${apiPort}/api/v1${normalizedPath}`, {
    method,
    headers: request.body === undefined ? undefined : {
      "Content-Type": "application/json",
    },
    body: request.body === undefined ? undefined : JSON.stringify(request.body),
  });
  const bodyText = await response.text();
  const body = bodyText ? JSON.parse(bodyText) : null;
  if (!response.ok) {
    throw new Error(
      typeof body?.detail === "string"
        ? body.detail
        : `API request failed with status ${response.status}`,
    );
  }
  return body;
}

function createWindow(): void {
  const preloadPath = path.join(app.getAppPath(), "dist-electron", "preload.cjs");
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 760,
    minWidth: 1180,
    minHeight: 640,
    backgroundColor: "#101417",
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.webContents.on("preload-error", (_event, preload, error) => {
    console.error(`Preload failed: ${preload}`);
    console.error(error);
  });

  if (process.env.VITE_DEV_SERVER_URL) {
    void mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
    return;
  }

  void mainWindow.loadFile(path.join(app.getAppPath(), "dist", "index.html"));
}

ipcMain.handle("node:start", (_event, config: StartNodeConfig) => startNode(config));
ipcMain.handle("node:stop", () => stopNode());
ipcMain.handle("node:state", () => runtimeState());
ipcMain.handle("wallets:list", () => listWallets());
ipcMain.handle("wallets:create", (_event, request: CreateWalletRequest) => createWallet(request));
ipcMain.handle("wallets:keys", (_event, name: string) => readWalletKeys(name));
ipcMain.handle(
  "wallets:update-preferred-port",
  (_event, request: UpdateWalletPreferredPortRequest) => updateWalletPreferredPort(request),
);
ipcMain.handle("wallets:delete", (_event, request: DeleteWalletRequest) => deleteWallet(request));
ipcMain.handle("desktop-state:read", (_event, request: DesktopStateRequest) => readDesktopState(request));
ipcMain.handle(
  "desktop-state:update",
  (_event, request: UpdateDesktopStateRequest) => updateDesktopState(request),
);
ipcMain.handle("node-api:fetch", (_event, request: NodeApiRequest) => fetchNodeApi(request));
ipcMain.handle("system:local-addresses", () => localAddresses());

app.whenReady().then(createWindow).catch((error) => {
  console.error(error);
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", (event) => {
  if (nodeProcess === null) {
    return;
  }
  event.preventDefault();
  stopNode()
    .catch((error) => {
      console.error(error);
    })
    .finally(() => {
      app.quit();
    });
});

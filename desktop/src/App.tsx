import { FormEvent, useEffect, useMemo, useState } from "react";
import { readBalances, readChainHead, type BalanceRow, type ChainHead } from "./api";
import "./styles.css";

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

const DEFAULT_PORT = 9000;

function shortHash(value: string | null): string {
  if (!value) {
    return "none";
  }
  return value.slice(0, 12);
}

function App() {
  const [walletName, setWalletName] = useState("frederik");
  const [host, setHost] = useState("127.0.0.1");
  const [port, setPort] = useState(String(DEFAULT_PORT));
  const [apiPort, setApiPort] = useState(String(DEFAULT_PORT + 10000));
  const [peers, setPeers] = useState("");
  const [nodeState, setNodeState] = useState<NodeRuntimeState>({
    running: false,
    pid: null,
    config: null,
  });
  const [logs, setLogs] = useState<NodeLogEntry[]>([]);
  const [chainHead, setChainHead] = useState<ChainHead | null>(null);
  const [balances, setBalances] = useState<BalanceRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const resolvedApiPort = nodeState.config?.apiPort ?? Number(apiPort);

  useEffect(() => {
    window.unccoinDesktop.getNodeState().then(setNodeState).catch((stateError) => {
      setError(String(stateError));
    });
    const removeLogListener = window.unccoinDesktop.onNodeLog((entry) => {
      setLogs((currentLogs) => [...currentLogs.slice(-300), entry]);
    });
    const removeStateListener = window.unccoinDesktop.onNodeState(setNodeState);
    return () => {
      removeLogListener();
      removeStateListener();
    };
  }, []);

  useEffect(() => {
    if (!nodeState.running || !Number.isInteger(resolvedApiPort)) {
      return undefined;
    }

    let cancelled = false;
    const poll = async () => {
      try {
        const [head, balanceRows] = await Promise.all([
          readChainHead(resolvedApiPort),
          readBalances(resolvedApiPort),
        ]);
        if (!cancelled) {
          setChainHead(head);
          setBalances(balanceRows.balances);
          setError(null);
        }
      } catch (pollError) {
        if (!cancelled) {
          setError(String(pollError));
        }
      }
    };

    void poll();
    const interval = window.setInterval(() => {
      void poll();
    }, 2500);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [nodeState.running, resolvedApiPort]);

  const peerList = useMemo(
    () => peers.split(",").map((peer) => peer.trim()).filter(Boolean),
    [peers],
  );

  async function handleStart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      const nextState = await window.unccoinDesktop.startNode({
        walletName,
        host,
        port: Number(port),
        apiPort: Number(apiPort),
        peers: peerList,
      });
      setNodeState(nextState);
    } catch (startError) {
      setError(String(startError));
    }
  }

  async function handleStop() {
    setError(null);
    try {
      const nextState = await window.unccoinDesktop.stopNode();
      setNodeState(nextState);
      setChainHead(null);
      setBalances([]);
    } catch (stopError) {
      setError(String(stopError));
    }
  }

  return (
    <main className="shell">
      <section className="toolbar">
        <div>
          <h1>UncCoin Desktop</h1>
          <p>Local node launcher and status dashboard</p>
        </div>
        <div className={`status ${nodeState.running ? "running" : ""}`}>
          {nodeState.running ? `running pid ${nodeState.pid}` : "stopped"}
        </div>
      </section>

      <section className="content">
        <form className="panel controls" onSubmit={handleStart}>
          <h2>Node</h2>
          <label>
            Wallet
            <input
              value={walletName}
              onChange={(event) => setWalletName(event.target.value)}
              disabled={nodeState.running}
            />
          </label>
          <div className="grid">
            <label>
              Host
              <input
                value={host}
                onChange={(event) => setHost(event.target.value)}
                disabled={nodeState.running}
              />
            </label>
            <label>
              P2P Port
              <input
                value={port}
                inputMode="numeric"
                onChange={(event) => {
                  setPort(event.target.value);
                  if (!nodeState.running) {
                    setApiPort(String(Number(event.target.value || DEFAULT_PORT) + 10000));
                  }
                }}
                disabled={nodeState.running}
              />
            </label>
            <label>
              API Port
              <input
                value={apiPort}
                inputMode="numeric"
                onChange={(event) => setApiPort(event.target.value)}
                disabled={nodeState.running}
              />
            </label>
          </div>
          <label>
            Peers
            <input
              value={peers}
              placeholder="127.0.0.1:9001, 127.0.0.1:9002"
              onChange={(event) => setPeers(event.target.value)}
              disabled={nodeState.running}
            />
          </label>
          <div className="actions">
            <button type="submit" disabled={nodeState.running}>
              Start
            </button>
            <button type="button" onClick={handleStop} disabled={!nodeState.running}>
              Stop
            </button>
          </div>
          {error ? <p className="error">{error}</p> : null}
        </form>

        <section className="panel summary">
          <h2>Chain</h2>
          <dl>
            <div>
              <dt>Height</dt>
              <dd>{chainHead?.height ?? "-"}</dd>
            </div>
            <div>
              <dt>Tip</dt>
              <dd>{shortHash(chainHead?.tip_hash ?? null)}</dd>
            </div>
            <div>
              <dt>Blocks</dt>
              <dd>{chainHead?.block_count ?? "-"}</dd>
            </div>
            <div>
              <dt>Pending</dt>
              <dd>{chainHead?.pending_transaction_count ?? "-"}</dd>
            </div>
            <div>
              <dt>Next Difficulty</dt>
              <dd>{chainHead?.next_difficulty_bits ?? "-"}</dd>
            </div>
          </dl>
        </section>

        <section className="panel balances">
          <h2>Balances</h2>
          <div className="table">
            {balances.length === 0 ? (
              <p className="empty">No balances loaded.</p>
            ) : (
              balances.map((balance) => (
                <div className="row" key={balance.address}>
                  <span>{balance.alias ?? shortHash(balance.address)}</span>
                  <strong>{balance.balance}</strong>
                </div>
              ))
            )}
          </div>
        </section>

        <section className="panel logs">
          <h2>Logs</h2>
          <pre>
            {logs.length === 0
              ? "Node output will appear here."
              : logs.map((entry) => `[${entry.stream}] ${entry.message}`).join("")}
          </pre>
        </section>
      </section>
    </main>
  );
}

export default App;

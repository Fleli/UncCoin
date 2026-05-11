import argparse
import asyncio
import contextlib
import ipaddress
import os
import signal

from node.node import Node
from wallet import load_wallet


def _normalize_api_token(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _api_host_is_loopback(host: str) -> bool:
    normalized_host = host.strip().lower()
    if normalized_host == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized_host).is_loopback
    except ValueError:
        return False


async def _run_from_cli() -> None:
    parser = argparse.ArgumentParser(description="Run an UncCoin node.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument(
        "--peer",
        action="append",
        default=[],
        help="Optional peer in host:port form. Can be passed multiple times.",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Disable the interactive node console.",
    )
    parser.add_argument(
        "--wallet-name",
        help="Optional wallet name to load from the state/wallets directory.",
    )
    parser.add_argument(
        "--private-automine",
        action="store_true",
        help=(
            "Keep mining on a preferred private branch tip and only rebase "
            "when that same branch advances."
        ),
    )
    parser.add_argument(
        "--mining-only",
        action="store_true",
        help="Disable transaction and mempool relay for a dedicated miner.",
    )
    parser.add_argument(
        "--cloud-native-automine",
        action="store_true",
        help=(
            "Use the dedicated cloud reward-only burst autominer. "
            "Requires --mining-only."
        ),
    )
    parser.add_argument(
        "--mined-block-persist-interval",
        type=int,
        default=1,
        help=(
            "Save blockchain state every N locally mined blocks. "
            "Use 0 to save only on shutdown or chain sync."
        ),
    )
    parser.add_argument(
        "--api-host",
        default="127.0.0.1",
        help="Host interface for the optional state/control HTTP API.",
    )
    parser.add_argument(
        "--api-port",
        type=int,
        help="Enable the optional state/control HTTP API on this port.",
    )
    parser.add_argument(
        "--api-token",
        help=(
            "Bearer token required for /api/v1/control/* endpoints. "
            "Can also be set with UNCCOIN_API_TOKEN."
        ),
    )
    args = parser.parse_args()
    if args.api_port is not None and not 0 < args.api_port < 65536:
        parser.error("--api-port must be between 1 and 65535.")
    if args.mined_block_persist_interval < 0:
        parser.error("--mined-block-persist-interval must be non-negative.")
    if args.cloud_native_automine and not args.mining_only:
        parser.error("--cloud-native-automine requires --mining-only.")
    api_token = _normalize_api_token(
        args.api_token
        if args.api_token is not None
        else os.environ.get("UNCCOIN_API_TOKEN")
    )
    if (
        args.api_port is not None
        and api_token is None
        and not _api_host_is_loopback(args.api_host)
    ):
        parser.error("--api-token or UNCCOIN_API_TOKEN is required when --api-host is not loopback.")

    print("Loading node...", flush=True)
    wallet = load_wallet(args.wallet_name) if args.wallet_name else None
    node = Node(
        host=args.host,
        port=args.port,
        wallet=wallet,
        private_automine=args.private_automine,
        mining_only=args.mining_only,
        cloud_native_automine=args.cloud_native_automine,
        mined_block_persist_interval=args.mined_block_persist_interval,
    )
    await node.start()

    if args.peer:
        print("Connecting to peers...", flush=True)
    for peer in args.peer:
        peer_host, peer_port = peer.split(":", maxsplit=1)
        try:
            await node.connect_to_peer(peer_host, int(peer_port))
        except ValueError as error:
            print(error, flush=True)

    print("Node ready.", flush=True)

    api_server = None
    if args.api_port is not None:
        try:
            from node.api_server import NodeAPIServer
        except ImportError as error:
            raise SystemExit(
                "The HTTP API requires FastAPI dependencies. "
                "Install them with: python3 -m pip install -r requirements-api.txt"
            ) from error

        api_server = NodeAPIServer(
            node=node,
            host=args.api_host,
            port=args.api_port,
            api_token=api_token,
        )
        await api_server.start()
        print(
            "Node state/control API listening on "
            f"http://{args.api_host}:{args.api_port}/api/v1",
            flush=True,
        )
        if api_token is not None:
            print("Control API requires bearer-token authentication.", flush=True)
        else:
            print("Control API is unauthenticated; keep the API host loopback.", flush=True)

    server_task = asyncio.create_task(node.serve_forever())
    stop_event = asyncio.Event()
    stop_task = None
    loop = asyncio.get_running_loop()
    registered_signals = []
    if args.no_interactive:
        for signum in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(signum, stop_event.set)
                registered_signals.append(signum)

    try:
        if args.no_interactive:
            stop_task = asyncio.create_task(stop_event.wait())
            done, _pending = await asyncio.wait(
                {server_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if server_task in done:
                await server_task
        else:
            await node.interactive_console()
    finally:
        if stop_task is not None:
            stop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stop_task
        for signum in registered_signals:
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.remove_signal_handler(signum)
        try:
            if api_server is not None:
                await api_server.stop()
            await node.stop()
        finally:
            server_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await server_task


def main() -> None:
    asyncio.run(_run_from_cli())


if __name__ == "__main__":
    main()

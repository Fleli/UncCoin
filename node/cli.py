import argparse
import asyncio

from node.node import Node
from wallet import load_wallet


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
        "--api-host",
        default="127.0.0.1",
        help="Host interface for the optional read-only HTTP API.",
    )
    parser.add_argument(
        "--api-port",
        type=int,
        help="Enable the optional read-only HTTP API on this port.",
    )
    args = parser.parse_args()
    if args.api_port is not None and not 0 < args.api_port < 65536:
        parser.error("--api-port must be between 1 and 65535.")

    print("Loading node...", flush=True)
    wallet = load_wallet(args.wallet_name) if args.wallet_name else None
    node = Node(
        host=args.host,
        port=args.port,
        wallet=wallet,
        private_automine=args.private_automine,
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
        )
        await api_server.start()
        print(
            "Read-only API listening on "
            f"http://{args.api_host}:{args.api_port}/api/v1",
            flush=True,
        )

    server_task = asyncio.create_task(node.serve_forever())

    try:
        if args.no_interactive:
            await server_task
        else:
            await node.interactive_console()
    finally:
        if api_server is not None:
            await api_server.stop()
        server_task.cancel()
        await node.stop()


def main() -> None:
    asyncio.run(_run_from_cli())


if __name__ == "__main__":
    main()

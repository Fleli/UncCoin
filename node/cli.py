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
    args = parser.parse_args()

    print("Loading node...", flush=True)
    wallet = load_wallet(args.wallet_name) if args.wallet_name else None
    node = Node(host=args.host, port=args.port, wallet=wallet)
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

    server_task = asyncio.create_task(node.serve_forever())

    try:
        if args.no_interactive:
            await server_task
        else:
            await node.interactive_console()
    finally:
        server_task.cancel()
        await node.stop()


def main() -> None:
    asyncio.run(_run_from_cli())


if __name__ == "__main__":
    main()

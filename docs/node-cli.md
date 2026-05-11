# Node CLI

The terminal node exposes an interactive prompt for local control and debugging. It is useful
for servers, dedicated miners, and checking behavior without the desktop app.

Start a terminal node:

```bash
./scripts/run.sh <wallet-name> <p2p-port> [peer-host:peer-port ...]
```

Start a headless cloud GPU miner:

```bash
./scripts/cloud_automine.sh <wallet-name> <p2p-port> [peer-host:peer-port ...]
```

The cloud launcher enables `--mining-only --cloud-native-automine` by default. That mode is
reserved for dedicated cloud miners: it mines reward-only blocks in a long-running burst
worker using serialized block prefixes and compact periodic summaries, then validates each
block's proof-of-work and reward consensus rules before broadcast.

Example:

```bash
./scripts/run.sh alice 9000
./scripts/run.sh bob 9001 127.0.0.1:9000
```

## Wallet Commands

Create a wallet:

```bash
./.venv/bin/python -m wallet.cli create --name <wallet-name>
```

Inspect a wallet:

```bash
./.venv/bin/python -m wallet.cli show --name <wallet-name>
```

Shortcut:

```bash
./scripts/wallet.sh <wallet-name>
```

## Interactive Commands

```text
help
peers
known-peers
discover
sync
localself
add-peer <host:port>
alias <wallet-id> <alias>
autosend <wallet-id>
autosend off
mute
unmute
tx <receiver> <amount> <fee>
commit <request-id> <commitment-hash> <fee>
reveal <request-id> <seed> <fee> [salt]
rebroadcast-pending
deploy <fee> <json-or-file>
view-contract <contract>
authorize <contract> <request-id> <fee> [valid-blocks]
execute <contract> <gas-limit> <gas-price> <value> <max-fee> <json>
receipt <txid-prefix>
msg <wallet> <content>
messages
mine [description]
automine [description]
stop
blockchain
balance [address]
balances
balances >100
balances <50
txtbalances <relative-path>
txtblockchain <relative-path>
send <host:port> <json>
clear
quit
<raw json>
```

Commands that take wallet ids, such as `tx`, `msg`, `balance`, `alias`, and `autosend`,
accept either a raw wallet address or a locally stored alias.

## Local Convenience Commands

These are mostly for local testing on one machine:

```bash
make wallet name=alice
make show-wallet name=alice
make 9000
make 9001
make 9002
```

## Persistence

Local state is stored under `state/` and is ignored by git. This includes wallets,
blockchain state, messages, aliases, desktop preferences, and mining tuning data.

Wallet JSON files are sensitive. The desktop delete action archives wallet files under
`state/deleted/` instead of permanently deleting them.

# UncCoin

## Interactive Node Commands

```text
peers
known-peers
discover
tx <receiver> <amount> <fee>
mine [description]
automine [description]
stop
blockchain
balance [address]
send <host:port> <json>
clear
quit
<raw json>
```

## Commands

```bash
make wallet NAME=alice
make show-wallet NAME=alice
make 9000
make 9001
make 9002
```

## Scripts

```bash
./scripts/build_native_pow.sh
./scripts/build_native_pow.sh --force
./scripts/run_node.sh <wallet-name> <port> [peer-host:peer-port ...]
```

## Direct CLI

```bash
python3 -m wallet.cli create --name alice
python3 -m wallet.cli show --name alice
python3 -m core.native_pow --force
python3 -m node.cli --wallet-name <wallet-name> --port <port> [--peer <host:port> ...]
```

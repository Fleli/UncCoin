# Node API

Every node can expose a local FastAPI API for reading current blockchain state and performing
node actions. This replaces ad hoc text-file polling for local tools and is what the desktop
app uses.

## Ports

`scripts/run.sh` starts both the P2P node and the API server:

```text
P2P:  0.0.0.0:<p2p-port>
API:  127.0.0.1:<p2p-port + 10000>
Docs: http://127.0.0.1:<api-port>/docs
```

For example, a node on P2P port `9000` normally has API docs at:

```text
http://127.0.0.1:19000/docs
```

Override the API bind address or port when needed:

```bash
UNCCOIN_API_HOST=127.0.0.1 UNCCOIN_API_PORT=19001 ./scripts/run.sh alice 9001
```

## Security

Read endpoints are open on the API host. Control endpoints under `/api/v1/control/*` can sign
transactions, mine, connect peers, change aliases, and change node behavior.

When the API is bound to loopback, terminal-run nodes may omit a token because local terminal
access is already equivalent to control of the node. If the API is bound beyond loopback, a
bearer token is required.

Set a token explicitly:

```bash
UNCCOIN_API_HOST=0.0.0.0 \
UNCCOIN_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
./scripts/run.sh alice 9000
```

Use the token with control requests:

```bash
curl -H "Authorization: Bearer $UNCCOIN_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"fast": true}' \
  http://127.0.0.1:19000/api/v1/control/sync
```

The desktop app generates and passes a per-run token automatically.

## Read Endpoints

Common read endpoints:

```text
GET /api/v1/health
GET /api/v1/node
GET /api/v1/peers
GET /api/v1/network/stats
GET /api/v1/sync/status
GET /api/v1/mining/status
GET /api/v1/mining/backends
GET /api/v1/mining/warmup
GET /api/v1/chain/head
GET /api/v1/chain/blocks
GET /api/v1/chain/block/{height-or-hash}
GET /api/v1/balances
GET /api/v1/balances/{address}
GET /api/v1/transactions/pending
GET /api/v1/messages
GET /api/v1/contracts
GET /api/v1/contracts/{contract-address}
GET /api/v1/contracts/{contract-address}/storage
GET /api/v1/receipts
GET /api/v1/receipts/{transaction-id-or-prefix}
GET /api/v1/commitments/{request-id}
GET /api/v1/reveals/{request-id}
GET /api/v1/authorizations
```

## Control Endpoints

Control endpoints require a bearer token when `UNCCOIN_API_TOKEN` is set:

```text
POST /api/v1/control/peers/connect
POST /api/v1/control/peers/discover
POST /api/v1/control/sync
POST /api/v1/control/transactions
POST /api/v1/control/messages
POST /api/v1/control/mine
POST /api/v1/control/mining/backend
POST /api/v1/control/mining/backend/build
POST /api/v1/control/mining/warmup
POST /api/v1/control/automine/start
POST /api/v1/control/automine/stop
POST /api/v1/control/aliases
POST /api/v1/control/autosend
POST /api/v1/control/commitments
POST /api/v1/control/reveals
POST /api/v1/control/contracts/deploy
POST /api/v1/control/contracts/execute
POST /api/v1/control/contracts/authorize
```

The OpenAPI schema at `/docs` is the best reference for request and response shapes.

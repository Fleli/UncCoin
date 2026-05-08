# Contracts and UVM

UncCoin transactions are versioned and typed. Normal money movement is a `transfer`
transaction. The newer transaction kinds provide a first-pass contract workflow built around
commitments, reveals, on-chain authorizations, and deterministic UVM execution.

## Typed Transactions

`commit` records a 64-character hex commitment hash under a caller-provided `request_id`,
keyed by the committing wallet address. This is the first primitive for shared-randomness
workflows where a later UVM program can link a participant's commitment to a later seed.

`reveal` uploads the seed for a prior commitment. The commitment hash is:

```text
sha256("UVM_REVEAL|1|<wallet>|<request_id>|<seed>|<salt>")
```

Seeds are normalized as unsigned 256-bit integers. Decimal and `0x` hexadecimal seed strings
are accepted. Salt is optional.

`deploy` stores UVM code and metadata under a deterministic contract address derived from the
deployer, deploy nonce, and code hash. Deploy source can be inline JSON or a file in
`state/contracts`. The JSON can be either a program directly or an object with `program` and
`metadata` fields.

Readable `.uvm-asm` files can be compiled into deployable `.uvm` JSON:

```bash
python3 -m assembler <source.uvm-asm> -o <output.uvm>
```

`view-contract` prints a deployed contract's full address, deployer, code hash, metadata, and
program by exact address or unique address prefix.

`authorize` broadcasts an on-chain UVM consent transaction for a deployed contract and
request id. The authorization is bound to the authorizing wallet, contract address, contract
code hash, request id, and optional block-height scope. Once mined, every synced node can use
it during execution.

`execute` runs deployed UVM code, or inline code when no deployed contract exists. The
execute JSON can be a program directly or an object with an `input` field. Execute
transactions read matching on-chain authorizations from chain state.

`receipt` prints a UVM execution receipt by transaction id or unique transaction-id prefix.

## UVM Model

The UVM is a deterministic stack machine. Programs can be provided as a JSON instruction list
or as assembly text. Each instruction is charged gas before it executes. If gas runs out, the
execute transaction is still included with a failed receipt, but no UVM state changes are
applied.

Example program:

```json
[
  ["READ_COMMIT", "<wallet-address>", "casino-play-1"],
  ["STORE", "commitment"],
  ["HALT"]
]
```

`READ_COMMIT <wallet> <request_id>` is protected: chain state must contain a valid on-chain
authorization from `<wallet>` for that exact contract code hash and `<request_id>`.

`READ_REVEAL <wallet> <request_id>` reads a public revealed seed and pushes it as a stack
integer.

`HAS_REVEAL <wallet> <request_id>` pushes `1` when that wallet has revealed for the request
and `0` otherwise. `BLOCK_HEIGHT` pushes the block height currently executing the contract.

`READ_METADATA <key>` reads an immutable integer value from deploy metadata and pushes it
onto the stack. Missing keys and non-integer values fail execution.

`TRANSFER_FROM <source> <receiver> <request_id>` pops a positive integer amount and moves
that amount between balances. The source must be the execute transaction sender, the contract
itself, or a wallet that provided a valid UVM authorization for the exact request id. Use the
reserved `$CONTRACT` operand for the currently executing contract address.

## Instructions

```text
PUSH <int>
POP
DUP
SWAP
ADD
SUB
MUL
DIV
MOD
EQ
LT
GT
AND
OR
XOR
NOT
SHA256
MEM_LOAD <key>
MEM_STORE <key>
READ_METADATA <key>
LOAD <key>
STORE <key>
READ_COMMIT <wallet> <request_id>
READ_REVEAL <wallet> <request_id>
HAS_REVEAL <wallet> <request_id>
TRANSFER_FROM <source> <receiver> <request_id>
HAS_AUTH <wallet> <request_id>
REQUIRE_AUTH <wallet> <request_id>
BLOCK_HEIGHT
JUMP <pc>
JUMPI <pc>
HALT
REVERT
```

`MEM_LOAD` and `MEM_STORE` are transient execution memory. `LOAD` and `STORE` are persistent
contract storage under the execute transaction's contract address.

## Gas Costs

```text
PUSH/POP: 1
DUP/SWAP: 2
ADD/SUB: 3
MUL/DIV/MOD: 5
EQ/LT/GT/NOT: 2
AND/OR/XOR/JUMP: 3
JUMPI/MEM_STORE: 5
MEM_LOAD: 3
BLOCK_HEIGHT: 2
HAS_REVEAL/READ_METADATA: 10
SHA256/HAS_AUTH/REQUIRE_AUTH: 20
LOAD: 25
READ_COMMIT: 30
READ_REVEAL: 30
TRANSFER_FROM: 50
STORE: 100
HALT/REVERT: 0
```

Execute transactions may transfer value to the contract address before execution starts. UVM
balance mutations are scoped through `TRANSFER_FROM`; blocks only accept those mutations when
the VM finishes successfully and all source authorization checks pass.

Fuel economics are represented by the execute transaction fee as a max fuel escrow. If
`gas_price` is zero, the fee is a flat fee as in earlier transactions. If `gas_price` is
positive, the fee must cover `gas_limit * gas_price`, but only `gas_used * gas_price` is paid
to the miner and the unused escrow is refunded. Failed UVM runs still consume fuel, advance
the sender nonce, and store a failed receipt.

## Coinflip Example

A local `state/contracts/coinflip.uvm` file can hold a two-wallet contract deployed with:

```text
deploy 0 coinflip.uvm
```

The toy contract expects both hardcoded wallets to authorize the printed contract address and
reveal under request id `coinflip`, stakes `100` from each wallet, and pays `200` to the
derived winner. It can also read a `reveal_deadline` metadata value so a missing revealer
forfeits after the deadline.

# UVM Assembler

The assembler compiles `.uvm-asm` files into `.uvm` deploy JSON accepted by the
existing `deploy` command.

```bash
python3 -m assembler state/contracts/counter.uvm-asm -o state/contracts/counter.uvm
```

If `-o` is omitted, the output path is the input path with a `.uvm` suffix.

## Source Format

Assembly is line-oriented. Blank lines and comments are ignored. Comments can
start with `#` or `//`.

```text
.metadata name "counter"
.metadata request_ids ["counter-round-1"]
.const STEP 1

start:
  LOAD count
  PUSH @STEP
  ADD
  STORE count
  HALT
```

Supported features:

- Labels: `label:` on its own line or before an instruction. `JUMP label` and
  `JUMPI label` compile to numeric instruction indexes.
- Constants: `.const NAME VALUE`, referenced as `@NAME` in operands. Values can
  be JSON, decimal integers, hex integers, or strings.
- Metadata: `.metadata KEY VALUE`, `.meta KEY VALUE`, or
  `.metadata {"key": "value"}`. Values are written into the output deploy JSON.
- Quoting: operands are parsed with shell-like quoting, so strings with spaces
  or punctuation can be quoted.

The normal output is a deploy payload:

```json
{
  "metadata": {
    "name": "counter"
  },
  "program": [
    ["LOAD", "count"],
    ["PUSH", 1],
    ["ADD"],
    ["STORE", "count"],
    ["HALT"]
  ]
}
```

Use `--program-only` when you need only the raw instruction list.

## Library API

Frontend or CLI code can call the assembler directly:

```python
from assembler import assemble_source

result = assemble_source(source_text, source_name="counter.uvm-asm")
payload = result.to_deploy_payload()
labels = result.labels
source_map = result.source_map
```

`AssemblyError` includes the source name, line number, and source line when the
assembler can locate an error.

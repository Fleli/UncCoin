import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.uvm import UVM_GAS_COSTS
from core.uvm import parse_uvm_program


LABEL_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*):(.*)$")
NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class OpcodeSpec:
    operand_count: int
    operand_types: tuple[type, ...] = ()


OPCODE_SPECS: dict[str, OpcodeSpec] = {
    "PUSH": OpcodeSpec(1, (int,)),
    "POP": OpcodeSpec(0),
    "DUP": OpcodeSpec(0),
    "SWAP": OpcodeSpec(0),
    "ADD": OpcodeSpec(0),
    "SUB": OpcodeSpec(0),
    "MUL": OpcodeSpec(0),
    "DIV": OpcodeSpec(0),
    "MOD": OpcodeSpec(0),
    "EQ": OpcodeSpec(0),
    "LT": OpcodeSpec(0),
    "GT": OpcodeSpec(0),
    "AND": OpcodeSpec(0),
    "OR": OpcodeSpec(0),
    "XOR": OpcodeSpec(0),
    "NOT": OpcodeSpec(0),
    "SHA256": OpcodeSpec(0),
    "MEM_LOAD": OpcodeSpec(1, (str,)),
    "MEM_STORE": OpcodeSpec(1, (str,)),
    "READ_METADATA": OpcodeSpec(1, (str,)),
    "READ_INPUT": OpcodeSpec(1, (str,)),
    "LOAD": OpcodeSpec(1, (str,)),
    "STORE": OpcodeSpec(1, (str,)),
    "READ_COMMIT": OpcodeSpec(2, (str, str)),
    "READ_REVEAL": OpcodeSpec(2, (str, str)),
    "HAS_REVEAL": OpcodeSpec(2, (str, str)),
    "TRANSFER_FROM": OpcodeSpec(3, (str, str, str)),
    "HAS_AUTH": OpcodeSpec(2, (str, str)),
    "REQUIRE_AUTH": OpcodeSpec(2, (str, str)),
    "BLOCK_HEIGHT": OpcodeSpec(0),
    "TX_SENDER": OpcodeSpec(0),
    "JUMP": OpcodeSpec(1, (int,)),
    "JUMPI": OpcodeSpec(1, (int,)),
    "HALT": OpcodeSpec(0),
    "REVERT": OpcodeSpec(0),
}


@dataclass(frozen=True)
class SourceMapEntry:
    instruction_index: int
    line: int
    source: str


@dataclass(frozen=True)
class AssemblyResult:
    program: list[list[Any]]
    metadata: dict[str, Any]
    labels: dict[str, int]
    constants: dict[str, Any]
    source_map: list[SourceMapEntry]
    source_name: str

    def to_deploy_payload(self, *, program_only: bool = False) -> Any:
        if program_only:
            return self.program
        return {
            "metadata": self.metadata,
            "program": self.program,
        }

    def to_json(self, *, program_only: bool = False, pretty: bool = True) -> str:
        indent = 2 if pretty else None
        return json.dumps(
            self.to_deploy_payload(program_only=program_only),
            indent=indent,
            sort_keys=not program_only,
            separators=None if pretty else (",", ":"),
        )


class AssemblyError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        line: int | None = None,
        source_name: str | None = None,
        source: str | None = None,
    ) -> None:
        self.message = message
        self.line = line
        self.source_name = source_name
        self.source = source
        location = ""
        if source_name is not None:
            location = source_name
        if line is not None:
            location = f"{location}:{line}" if location else f"line {line}"
        super().__init__(f"{location}: {message}" if location else message)


@dataclass(frozen=True)
class _ParsedInstruction:
    opcode: str
    operands: tuple[str, ...]
    line: int
    source: str


def assemble_file(
    input_path: str | Path,
    *,
    validate: bool = True,
) -> AssemblyResult:
    path = Path(input_path)
    return assemble_source(
        path.read_text(encoding="utf-8"),
        source_name=str(path),
        validate=validate,
    )


def write_uvm_file(
    result: AssemblyResult,
    output_path: str | Path,
    *,
    program_only: bool = False,
    pretty: bool = True,
) -> None:
    Path(output_path).write_text(
        result.to_json(program_only=program_only, pretty=pretty) + "\n",
        encoding="utf-8",
    )


def assemble_source(
    source: str,
    *,
    source_name: str = "<memory>",
    validate: bool = True,
) -> AssemblyResult:
    labels: dict[str, int] = {}
    constants: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    parsed_instructions: list[_ParsedInstruction] = []

    for line_number, raw_line in enumerate(source.splitlines(), start=1):
        line = _strip_comment(raw_line).strip()
        if not line:
            continue

        while True:
            label_match = LABEL_PATTERN.match(line)
            if label_match is None:
                break
            label = label_match.group(1)
            if label in labels:
                raise AssemblyError(
                    f"duplicate label {label}",
                    line=line_number,
                    source_name=source_name,
                    source=raw_line,
                )
            labels[label] = len(parsed_instructions)
            line = label_match.group(2).strip()
            if not line:
                break
        if not line:
            continue

        if line.startswith("."):
            _parse_directive(
                line,
                constants=constants,
                metadata=metadata,
                line_number=line_number,
                source_name=source_name,
                raw_line=raw_line,
            )
            continue

        tokens = _split_tokens(
            line,
            line_number=line_number,
            source_name=source_name,
            raw_line=raw_line,
        )
        opcode = tokens[0].upper()
        if opcode not in OPCODE_SPECS:
            raise AssemblyError(
                f"unknown opcode {opcode}",
                line=line_number,
                source_name=source_name,
                source=raw_line,
            )
        parsed_instructions.append(
            _ParsedInstruction(
                opcode=opcode,
                operands=tuple(tokens[1:]),
                line=line_number,
                source=raw_line,
            )
        )

    program: list[list[Any]] = []
    source_map: list[SourceMapEntry] = []
    for instruction_index, instruction in enumerate(parsed_instructions):
        operands = _resolve_operands(
            instruction,
            labels=labels,
            constants=constants,
            source_name=source_name,
        )
        _validate_instruction(
            instruction.opcode,
            operands,
            line=instruction.line,
            source_name=source_name,
            source=instruction.source,
        )
        program.append([instruction.opcode, *operands])
        source_map.append(
            SourceMapEntry(
                instruction_index=instruction_index,
                line=instruction.line,
                source=instruction.source,
            )
        )

    if validate:
        try:
            parse_uvm_program(program)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise AssemblyError(
                f"assembled program is not valid UVM: {error}",
                source_name=source_name,
            ) from error

    return AssemblyResult(
        program=program,
        metadata=metadata,
        labels=labels,
        constants=constants,
        source_map=source_map,
        source_name=source_name,
    )


def _parse_directive(
    line: str,
    *,
    constants: dict[str, Any],
    metadata: dict[str, Any],
    line_number: int,
    source_name: str,
    raw_line: str,
) -> None:
    tokens = _split_tokens(
        line,
        line_number=line_number,
        source_name=source_name,
        raw_line=raw_line,
    )
    directive = tokens[0].lower()
    rest = line[len(tokens[0]):].strip()

    if directive == ".const":
        if len(tokens) < 3:
            raise AssemblyError(
                ".const expects NAME VALUE",
                line=line_number,
                source_name=source_name,
                source=raw_line,
            )
        name = tokens[1]
        if not NAME_PATTERN.match(name):
            raise AssemblyError(
                f"invalid constant name {name}",
                line=line_number,
                source_name=source_name,
                source=raw_line,
            )
        if name in constants:
            raise AssemblyError(
                f"duplicate constant {name}",
                line=line_number,
                source_name=source_name,
                source=raw_line,
            )
        value_text = rest[len(name):].strip()
        constants[name] = _parse_directive_value(value_text)
        return

    if directive in {".metadata", ".meta"}:
        if len(tokens) < 2:
            raise AssemblyError(
                f"{directive} expects KEY VALUE or a JSON object",
                line=line_number,
                source_name=source_name,
                source=raw_line,
            )
        value_text = rest
        if value_text.startswith("{"):
            value = _parse_json_value(
                value_text,
                line=line_number,
                source_name=source_name,
                source=raw_line,
            )
            if not isinstance(value, dict):
                raise AssemblyError(
                    f"{directive} JSON value must be an object",
                    line=line_number,
                    source_name=source_name,
                    source=raw_line,
                )
            metadata.update(value)
            return

        if len(tokens) < 3:
            raise AssemblyError(
                f"{directive} expects KEY VALUE",
                line=line_number,
                source_name=source_name,
                source=raw_line,
            )
        key = tokens[1]
        value_text = rest[len(key):].strip()
        metadata[key] = _parse_directive_value(value_text)
        return

    raise AssemblyError(
        f"unknown directive {tokens[0]}",
        line=line_number,
        source_name=source_name,
        source=raw_line,
    )


def _resolve_operands(
    instruction: _ParsedInstruction,
    *,
    labels: dict[str, int],
    constants: dict[str, Any],
    source_name: str,
) -> list[Any]:
    operands: list[Any] = []
    for operand_index, operand in enumerate(instruction.operands):
        if instruction.opcode in {"JUMP", "JUMPI"} and operand_index == 0:
            if operand in labels:
                operands.append(labels[operand])
                continue
            if operand.startswith("@") and operand[1:] in labels:
                operands.append(labels[operand[1:]])
                continue

        operands.append(
            _parse_instruction_operand(
                operand,
                constants=constants,
                line=instruction.line,
                source_name=source_name,
                source=instruction.source,
            )
        )
    return operands


def _parse_instruction_operand(
    operand: str,
    *,
    constants: dict[str, Any],
    line: int,
    source_name: str,
    source: str,
) -> Any:
    if operand.startswith("@"):
        name = operand[1:]
        if name not in constants:
            raise AssemblyError(
                f"unknown constant {name}",
                line=line,
                source_name=source_name,
                source=source,
            )
        return _normalize_constant_value(constants[name])
    return _parse_scalar_token(operand)


def _normalize_constant_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    return value


def _parse_directive_value(value_text: str) -> Any:
    stripped_value = value_text.strip()
    if not stripped_value:
        return ""
    try:
        return json.loads(stripped_value)
    except json.JSONDecodeError:
        pass

    value_tokens = shlex.split(stripped_value)
    if len(value_tokens) == 1:
        return _parse_scalar_token(value_tokens[0])
    return " ".join(value_tokens)


def _parse_scalar_token(token: str) -> Any:
    stripped_token = token.strip()
    if stripped_token.startswith(("0x", "0X", "-0x", "-0X")):
        try:
            return int(stripped_token, 16)
        except ValueError:
            return stripped_token
    try:
        return int(stripped_token)
    except ValueError:
        return stripped_token


def _parse_json_value(
    value_text: str,
    *,
    line: int,
    source_name: str,
    source: str,
) -> Any:
    try:
        return json.loads(value_text)
    except json.JSONDecodeError as error:
        raise AssemblyError(
            f"invalid JSON value: {error.msg}",
            line=line,
            source_name=source_name,
            source=source,
        ) from error


def _validate_instruction(
    opcode: str,
    operands: list[Any],
    *,
    line: int,
    source_name: str,
    source: str,
) -> None:
    spec = OPCODE_SPECS[opcode]
    if len(operands) != spec.operand_count:
        raise AssemblyError(
            f"{opcode} expects {spec.operand_count} operand(s), got {len(operands)}",
            line=line,
            source_name=source_name,
            source=source,
        )

    for operand_index, expected_type in enumerate(spec.operand_types):
        operand = operands[operand_index]
        if expected_type is int and isinstance(operand, bool):
            operand_is_valid = False
        else:
            operand_is_valid = isinstance(operand, expected_type)
        if not operand_is_valid:
            expected_name = expected_type.__name__
            actual_name = type(operand).__name__
            raise AssemblyError(
                f"{opcode} operand {operand_index + 1} must be {expected_name}, "
                f"got {actual_name}",
                line=line,
                source_name=source_name,
                source=source,
            )


def _split_tokens(
    line: str,
    *,
    line_number: int,
    source_name: str,
    raw_line: str,
) -> list[str]:
    try:
        tokens = shlex.split(line)
    except ValueError as error:
        raise AssemblyError(
            f"could not parse line: {error}",
            line=line_number,
            source_name=source_name,
            source=raw_line,
        ) from error
    if not tokens:
        raise AssemblyError(
            "line is empty",
            line=line_number,
            source_name=source_name,
            source=raw_line,
        )
    return tokens


def _strip_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(line):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if quote is not None:
            if character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
            continue
        if character == "#":
            return line[:index]
        if character == "/" and index + 1 < len(line) and line[index + 1] == "/":
            return line[:index]
    return line

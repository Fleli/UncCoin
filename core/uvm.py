import hashlib
import json
import shlex
from dataclasses import dataclass, field
from typing import Any

from core.uvm_authorization import is_request_authorized


UVM_WORD_MODULUS = 2**256
UVM_MAX_STACK_ITEMS = 1024

UVM_GAS_COSTS = {
    "PUSH": 1,
    "POP": 1,
    "DUP": 2,
    "SWAP": 2,
    "ADD": 3,
    "SUB": 3,
    "MUL": 5,
    "DIV": 5,
    "MOD": 5,
    "EQ": 2,
    "LT": 2,
    "GT": 2,
    "AND": 3,
    "OR": 3,
    "NOT": 2,
    "SHA256": 20,
    "MEM_LOAD": 3,
    "MEM_STORE": 5,
    "LOAD": 25,
    "STORE": 100,
    "READ_COMMIT": 30,
    "READ_REVEAL": 30,
    "HAS_AUTH": 20,
    "REQUIRE_AUTH": 20,
    "JUMP": 3,
    "JUMPI": 5,
    "HALT": 0,
    "REVERT": 0,
}


@dataclass(frozen=True)
class UvmInstruction:
    opcode: str
    operands: tuple[Any, ...] = ()


@dataclass
class UvmExecutionContext:
    tx_sender: str
    contract_address: str
    gas_limit: int
    storage: dict[str, int] = field(default_factory=dict)
    commitments: dict[str, dict[str, str]] = field(default_factory=dict)
    reveals: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)
    authorization_index: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class UvmExecutionResult:
    success: bool
    reverted: bool
    gas_used: int
    gas_remaining: int
    gas_exhausted: bool
    used_all_gas: bool
    error: str | None
    stack: tuple[int, ...]
    memory: dict[str, int]
    storage: dict[str, int]
    program_counter: int

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "reverted": self.reverted,
            "gas_used": self.gas_used,
            "gas_remaining": self.gas_remaining,
            "gas_exhausted": self.gas_exhausted,
            "used_all_gas": self.used_all_gas,
            "error": self.error,
            "stack": list(self.stack),
            "memory": self.memory,
            "storage": self.storage,
            "program_counter": self.program_counter,
        }


def parse_uvm_program(program: Any) -> list[UvmInstruction]:
    if isinstance(program, str):
        stripped_program = program.strip()
        if not stripped_program:
            return []
        if stripped_program[0] in "[{":
            decoded_program = json.loads(stripped_program)
            if isinstance(decoded_program, dict):
                decoded_program = decoded_program.get("program", [])
            return parse_uvm_program(decoded_program)
        return _parse_assembly_program(stripped_program)

    if not isinstance(program, list):
        raise ValueError("UVM program must be a list, JSON string, or assembly string")

    instructions: list[UvmInstruction] = []
    for index, raw_instruction in enumerate(program):
        instructions.append(_parse_instruction(raw_instruction, index))
    return instructions


def execute_uvm_program(program: Any, context: UvmExecutionContext) -> UvmExecutionResult:
    try:
        instructions = parse_uvm_program(program)
        gas_limit = int(context.gas_limit)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        return _result(
            success=False,
            reverted=False,
            gas_limit=max(int(context.gas_limit), 0) if str(context.gas_limit).isdigit() else 0,
            gas_remaining=max(int(context.gas_limit), 0) if str(context.gas_limit).isdigit() else 0,
            gas_exhausted=False,
            error=f"invalid program: {error}",
            stack=[],
            memory={},
            storage=context.storage.copy(),
            program_counter=0,
        )

    if gas_limit < 0:
        return _result(
            success=False,
            reverted=False,
            gas_limit=0,
            gas_remaining=0,
            gas_exhausted=False,
            error="gas_limit must be non-negative",
            stack=[],
            memory={},
            storage=context.storage.copy(),
            program_counter=0,
        )

    stack: list[int] = []
    memory: dict[str, int] = {}
    storage = {
        str(key): _normalize_word(value)
        for key, value in context.storage.items()
    }
    pc = 0
    gas_remaining = gas_limit

    while pc < len(instructions):
        instruction = instructions[pc]
        opcode = instruction.opcode
        gas_cost = UVM_GAS_COSTS.get(opcode)
        if gas_cost is None:
            return _failure(
                gas_limit,
                gas_remaining,
                f"unknown opcode {opcode}",
                stack,
                memory,
                storage,
                pc,
            )
        if gas_remaining < gas_cost:
            return _failure(
                gas_limit,
                0,
                f"out of gas before {opcode}",
                stack,
                memory,
                storage,
                pc,
                gas_exhausted=True,
            )

        gas_remaining -= gas_cost
        next_pc = pc + 1

        try:
            jumped_pc = _execute_instruction(
                instruction,
                stack,
                memory,
                storage,
                context,
                len(instructions),
            )
        except _UvmRevert as error:
            return _result(
                success=False,
                reverted=True,
                gas_limit=gas_limit,
                gas_remaining=gas_remaining,
                gas_exhausted=False,
                error=str(error),
                stack=stack,
                memory=memory,
                storage=storage,
                program_counter=pc,
            )
        except _UvmExecutionError as error:
            return _failure(
                gas_limit,
                gas_remaining,
                str(error),
                stack,
                memory,
                storage,
                pc,
            )

        if opcode == "HALT":
            return _result(
                success=True,
                reverted=False,
                gas_limit=gas_limit,
                gas_remaining=gas_remaining,
                gas_exhausted=False,
                error=None,
                stack=stack,
                memory=memory,
                storage=storage,
                program_counter=pc,
            )

        pc = next_pc if jumped_pc is None else jumped_pc

    return _result(
        success=True,
        reverted=False,
        gas_limit=gas_limit,
        gas_remaining=gas_remaining,
        gas_exhausted=False,
        error=None,
        stack=stack,
        memory=memory,
        storage=storage,
        program_counter=pc,
    )


def _parse_instruction(raw_instruction: Any, index: int) -> UvmInstruction:
    if isinstance(raw_instruction, str):
        parts = shlex.split(raw_instruction)
        if not parts:
            raise ValueError(f"instruction {index} is empty")
        return UvmInstruction(
            opcode=parts[0].upper(),
            operands=tuple(_parse_operand(part) for part in parts[1:]),
        )

    if isinstance(raw_instruction, (list, tuple)):
        if not raw_instruction:
            raise ValueError(f"instruction {index} is empty")
        return UvmInstruction(
            opcode=str(raw_instruction[0]).upper(),
            operands=tuple(_parse_operand(operand) for operand in raw_instruction[1:]),
        )

    if isinstance(raw_instruction, dict):
        opcode = raw_instruction.get("op", raw_instruction.get("opcode"))
        if opcode is None:
            raise ValueError(f"instruction {index} is missing op")
        operands = raw_instruction.get("args", raw_instruction.get("operands", []))
        if not isinstance(operands, list):
            raise ValueError(f"instruction {index} operands must be a list")
        return UvmInstruction(
            opcode=str(opcode).upper(),
            operands=tuple(_parse_operand(operand) for operand in operands),
        )

    raise ValueError(f"instruction {index} has unsupported type")


def _parse_assembly_program(program: str) -> list[UvmInstruction]:
    raw_instructions: list[str] = []
    for raw_line in program.splitlines():
        line = raw_line.split("#", maxsplit=1)[0].strip()
        if line:
            raw_instructions.append(line)
    return [
        _parse_instruction(raw_instruction, index)
        for index, raw_instruction in enumerate(raw_instructions)
    ]


def _parse_operand(raw_operand: Any) -> Any:
    if isinstance(raw_operand, bool):
        return int(raw_operand)
    if isinstance(raw_operand, int):
        return raw_operand
    if isinstance(raw_operand, str):
        stripped_operand = raw_operand.strip()
        if stripped_operand.startswith(("0x", "0X")):
            try:
                return int(stripped_operand, 16)
            except ValueError:
                return stripped_operand
        try:
            return int(stripped_operand)
        except ValueError:
            return stripped_operand
    return raw_operand


def _execute_instruction(
    instruction: UvmInstruction,
    stack: list[int],
    memory: dict[str, int],
    storage: dict[str, int],
    context: UvmExecutionContext,
    program_length: int,
) -> int | None:
    opcode = instruction.opcode
    operands = instruction.operands

    if opcode == "PUSH":
        _require_operand_count(opcode, operands, 1)
        _push(stack, _require_int_operand(opcode, operands[0]))
        return None

    if opcode == "POP":
        _require_operand_count(opcode, operands, 0)
        _pop(stack)
        return None

    if opcode == "DUP":
        _require_operand_count(opcode, operands, 0)
        _push(stack, _peek(stack))
        return None

    if opcode == "SWAP":
        _require_operand_count(opcode, operands, 0)
        if len(stack) < 2:
            raise _UvmExecutionError("stack underflow")
        stack[-1], stack[-2] = stack[-2], stack[-1]
        return None

    if opcode in {"ADD", "SUB", "MUL", "DIV", "MOD", "EQ", "LT", "GT", "AND", "OR"}:
        _require_operand_count(opcode, operands, 0)
        right = _pop(stack)
        left = _pop(stack)
        if opcode == "ADD":
            _push(stack, left + right)
        elif opcode == "SUB":
            _push(stack, left - right)
        elif opcode == "MUL":
            _push(stack, left * right)
        elif opcode == "DIV":
            if right == 0:
                raise _UvmExecutionError("division by zero")
            _push(stack, left // right)
        elif opcode == "MOD":
            if right == 0:
                raise _UvmExecutionError("modulo by zero")
            _push(stack, left % right)
        elif opcode == "EQ":
            _push(stack, 1 if left == right else 0)
        elif opcode == "LT":
            _push(stack, 1 if left < right else 0)
        elif opcode == "GT":
            _push(stack, 1 if left > right else 0)
        elif opcode == "AND":
            _push(stack, 1 if left != 0 and right != 0 else 0)
        elif opcode == "OR":
            _push(stack, 1 if left != 0 or right != 0 else 0)
        return None

    if opcode == "NOT":
        _require_operand_count(opcode, operands, 0)
        _push(stack, 1 if _pop(stack) == 0 else 0)
        return None

    if opcode == "SHA256":
        _require_operand_count(opcode, operands, 0)
        value = _pop(stack)
        digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
        _push(stack, int(digest, 16))
        return None

    if opcode == "MEM_LOAD":
        _require_operand_count(opcode, operands, 1)
        _push(stack, memory.get(_require_key_operand(opcode, operands[0]), 0))
        return None

    if opcode == "MEM_STORE":
        _require_operand_count(opcode, operands, 1)
        memory[_require_key_operand(opcode, operands[0])] = _pop(stack)
        return None

    if opcode == "LOAD":
        _require_operand_count(opcode, operands, 1)
        _push(stack, storage.get(_require_key_operand(opcode, operands[0]), 0))
        return None

    if opcode == "STORE":
        _require_operand_count(opcode, operands, 1)
        storage[_require_key_operand(opcode, operands[0])] = _pop(stack)
        return None

    if opcode == "READ_COMMIT":
        _require_operand_count(opcode, operands, 2)
        wallet = _require_key_operand(opcode, operands[0])
        request_id = _require_key_operand(opcode, operands[1])
        if not is_request_authorized(context.authorization_index, wallet, request_id):
            raise _UvmExecutionError(
                f"wallet {wallet} is not authorized for request_id {request_id}"
            )
        commitment_hash = context.commitments.get(request_id, {}).get(wallet)
        if commitment_hash is None:
            raise _UvmExecutionError(
                f"missing commitment for wallet {wallet} and request_id {request_id}"
            )
        _push(stack, int(commitment_hash, 16))
        return None

    if opcode == "READ_REVEAL":
        _require_operand_count(opcode, operands, 2)
        wallet = _require_key_operand(opcode, operands[0])
        request_id = _require_key_operand(opcode, operands[1])
        reveal = context.reveals.get(request_id, {}).get(wallet)
        if reveal is None:
            raise _UvmExecutionError(
                f"missing reveal for wallet {wallet} and request_id {request_id}"
            )
        try:
            seed_value = int(reveal["seed"])
        except (KeyError, TypeError, ValueError) as error:
            raise _UvmExecutionError(f"invalid reveal seed: {error}") from error
        _push(stack, seed_value)
        return None

    if opcode == "HAS_AUTH":
        _require_operand_count(opcode, operands, 2)
        wallet = _require_key_operand(opcode, operands[0])
        request_id = _require_key_operand(opcode, operands[1])
        _push(
            stack,
            1 if is_request_authorized(context.authorization_index, wallet, request_id) else 0,
        )
        return None

    if opcode == "REQUIRE_AUTH":
        _require_operand_count(opcode, operands, 2)
        wallet = _require_key_operand(opcode, operands[0])
        request_id = _require_key_operand(opcode, operands[1])
        if not is_request_authorized(context.authorization_index, wallet, request_id):
            raise _UvmExecutionError(
                f"wallet {wallet} is not authorized for request_id {request_id}"
            )
        return None

    if opcode == "JUMP":
        _require_operand_count(opcode, operands, 1)
        return _validate_jump_target(_require_int_operand(opcode, operands[0]), program_length)

    if opcode == "JUMPI":
        _require_operand_count(opcode, operands, 1)
        target = _validate_jump_target(_require_int_operand(opcode, operands[0]), program_length)
        condition = _pop(stack)
        return target if condition != 0 else None

    if opcode == "HALT":
        _require_operand_count(opcode, operands, 0)
        return None

    if opcode == "REVERT":
        _require_operand_count(opcode, operands, 0)
        raise _UvmRevert("execution reverted")

    raise _UvmExecutionError(f"unknown opcode {opcode}")


def _require_operand_count(opcode: str, operands: tuple[Any, ...], count: int) -> None:
    if len(operands) != count:
        raise _UvmExecutionError(
            f"{opcode} expects {count} operand(s), got {len(operands)}"
        )


def _require_int_operand(opcode: str, operand: Any) -> int:
    if not isinstance(operand, int):
        raise _UvmExecutionError(f"{opcode} operand must be an integer")
    return operand


def _require_key_operand(opcode: str, operand: Any) -> str:
    if not isinstance(operand, str) or not operand:
        raise _UvmExecutionError(f"{opcode} operand must be a non-empty string")
    return operand


def _validate_jump_target(target: int, program_length: int) -> int:
    if target < 0 or target >= program_length:
        raise _UvmExecutionError(f"jump target {target} is out of bounds")
    return target


def _push(stack: list[int], value: int) -> None:
    if len(stack) >= UVM_MAX_STACK_ITEMS:
        raise _UvmExecutionError("stack limit exceeded")
    stack.append(_normalize_word(value))


def _pop(stack: list[int]) -> int:
    if not stack:
        raise _UvmExecutionError("stack underflow")
    return stack.pop()


def _peek(stack: list[int]) -> int:
    if not stack:
        raise _UvmExecutionError("stack underflow")
    return stack[-1]


def _normalize_word(value: int) -> int:
    return int(value) % UVM_WORD_MODULUS


def _failure(
    gas_limit: int,
    gas_remaining: int,
    error: str,
    stack: list[int],
    memory: dict[str, int],
    storage: dict[str, int],
    program_counter: int,
    gas_exhausted: bool = False,
) -> UvmExecutionResult:
    return _result(
        success=False,
        reverted=False,
        gas_limit=gas_limit,
        gas_remaining=gas_remaining,
        gas_exhausted=gas_exhausted,
        error=error,
        stack=stack,
        memory=memory,
        storage=storage,
        program_counter=program_counter,
    )


def _result(
    success: bool,
    reverted: bool,
    gas_limit: int,
    gas_remaining: int,
    gas_exhausted: bool,
    error: str | None,
    stack: list[int],
    memory: dict[str, int],
    storage: dict[str, int],
    program_counter: int,
) -> UvmExecutionResult:
    bounded_gas_remaining = max(gas_remaining, 0)
    return UvmExecutionResult(
        success=success,
        reverted=reverted,
        gas_used=max(gas_limit - bounded_gas_remaining, 0),
        gas_remaining=bounded_gas_remaining,
        gas_exhausted=gas_exhausted,
        used_all_gas=bounded_gas_remaining == 0,
        error=error,
        stack=tuple(stack),
        memory=memory.copy(),
        storage=storage.copy(),
        program_counter=program_counter,
    )


class _UvmExecutionError(Exception):
    pass


class _UvmRevert(Exception):
    pass

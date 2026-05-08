import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from assembler.compiler import AssemblyError
from assembler.compiler import OPCODE_SPECS
from assembler.compiler import assemble_source
from core.uvm import UVM_GAS_COSTS


class AssemblerTests(unittest.TestCase):
    def test_opcode_specs_cover_full_uvm_instruction_set(self) -> None:
        self.assertEqual(set(OPCODE_SPECS), set(UVM_GAS_COSTS))

    def test_assembles_labels_constants_and_metadata(self) -> None:
        source = """
        # deploy metadata is emitted into the .uvm payload
        .metadata request_ids ["coinflip"]
        .metadata reveal_deadline 10
        .const PLAYER_A fe269f427a5ad619ce480192db583a29a7ce4098b22111d9b7216e2fee6bc964
        .const REQUEST "coinflip:payout"

        start:
          LOAD settled
          JUMPI already_settled
          BLOCK_HEIGHT
          READ_METADATA reveal_deadline
          GT
          JUMPI after_deadline
          HALT

        after_deadline:
          PUSH 100
          TRANSFER_FROM @PLAYER_A $CONTRACT @REQUEST
          HALT

        already_settled:
          HALT
        """

        result = assemble_source(source, source_name="coinflip.uvm-asm")

        self.assertEqual(
            result.metadata,
            {
                "request_ids": ["coinflip"],
                "reveal_deadline": 10,
            },
        )
        self.assertEqual(
            result.labels,
            {
                "start": 0,
                "after_deadline": 7,
                "already_settled": 10,
            },
        )
        self.assertEqual(result.program[1], ["JUMPI", 10])
        self.assertEqual(result.program[5], ["JUMPI", 7])
        self.assertEqual(
            result.program[8],
            [
                "TRANSFER_FROM",
                "fe269f427a5ad619ce480192db583a29a7ce4098b22111d9b7216e2fee6bc964",
                "$CONTRACT",
                "coinflip:payout",
            ],
        )
        self.assertEqual(result.source_map[8].line, 19)

    def test_metadata_json_object_directive_merges_into_payload(self) -> None:
        result = assemble_source(
            """
            .metadata {"request_ids": ["round-1"], "deadline": 12}
            PUSH 1
            HALT
            """
        )

        self.assertEqual(
            result.to_deploy_payload(),
            {
                "metadata": {
                    "request_ids": ["round-1"],
                    "deadline": 12,
                },
                "program": [
                    ["PUSH", 1],
                    ["HALT"],
                ],
            },
        )

    def test_rejects_unknown_labels_and_bad_operand_types(self) -> None:
        with self.assertRaisesRegex(AssemblyError, "JUMPI operand 1 must be int"):
            assemble_source("JUMPI missing_label")

        with self.assertRaisesRegex(AssemblyError, "PUSH operand 1 must be int"):
            assemble_source("PUSH not-a-number")

    def test_cli_compiles_uvm_asm_file_to_uvm_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "counter.uvm-asm"
            output_path = Path(tmpdir) / "counter.uvm"
            source_path.write_text(
                """
                .metadata name "counter"
                LOAD count
                PUSH 1
                ADD
                STORE count
                HALT
                """,
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "assembler",
                    str(source_path),
                    "-o",
                    str(output_path),
                ],
                cwd=Path(__file__).resolve().parent.parent,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            compiled = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(compiled["metadata"], {"name": "counter"})
            self.assertEqual(
                compiled["program"],
                [
                    ["LOAD", "count"],
                    ["PUSH", 1],
                    ["ADD"],
                    ["STORE", "count"],
                    ["HALT"],
                ],
            )


if __name__ == "__main__":
    unittest.main()

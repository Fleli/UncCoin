import argparse
import sys
from pathlib import Path

from assembler.compiler import AssemblyError
from assembler.compiler import assemble_file
from assembler.compiler import write_uvm_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m assembler",
        description="Compile .uvm-asm source into a .uvm deploy JSON file.",
    )
    parser.add_argument("input", help="Path to a .uvm-asm source file.")
    parser.add_argument(
        "-o",
        "--output",
        help="Output .uvm path. Defaults to input path with .uvm suffix.",
    )
    parser.add_argument(
        "--program-only",
        action="store_true",
        help="Write only the UVM instruction list instead of deploy payload JSON.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Write compact JSON instead of pretty JSON.",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip final validation through the UVM parser.",
    )
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.with_suffix(".uvm")

    try:
        result = assemble_file(input_path, validate=not args.no_validate)
        if str(output_path) == "-":
            print(
                result.to_json(
                    program_only=args.program_only,
                    pretty=not args.compact,
                )
            )
        else:
            write_uvm_file(
                result,
                output_path,
                program_only=args.program_only,
                pretty=not args.compact,
            )
    except (AssemblyError, OSError) as error:
        print(f"assembler error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

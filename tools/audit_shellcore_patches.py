#!/usr/bin/env python3
"""Audit ShellCore patch tables and optionally dump target bytes from an ELF.

The source-only audit catches malformed sizes and overlapping writes.  Passing
an exact SceShellCore image additionally proves that every patch lies in an
executable segment and records the original bytes for disassembly review.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re
import sys

from validate_ppr_offsets import PF_X, bytes_at, load_image


ARRAY_RE = re.compile(
    r"static\s+struct\s+shellcore_patch\s+"
    r"shellcore_patches_(\d+)_(retail|testkit|devkit)\[\]\s*=\s*\{"
    r"(.*?)\};",
    re.DOTALL,
)
ENTRY_RE = re.compile(
    r"\{\s*(0x[0-9a-fA-F]+)\s*,\s*"
    r'"((?:\\.|[^"\\])*)"\s*,\s*(\d+)\s*\}',
)


def decode_c_bytes(value: str) -> bytes:
    try:
        decoded = ast.literal_eval(f'b"{value}"')
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"invalid C byte string {value!r}") from exc
    if not isinstance(decoded, bytes):
        raise ValueError("patch value is not a byte string")
    return decoded


def parse_tables(path: Path) -> dict[tuple[str, str], list[tuple[int, bytes]]]:
    source = path.read_text()
    tables: dict[tuple[str, str], list[tuple[int, bytes]]] = {}
    for firmware, kit, body in ARRAY_RE.findall(source):
        entries = []
        for offset, value, declared_size in ENTRY_RE.findall(body):
            data = decode_c_bytes(value)
            size = int(declared_size)
            if len(data) != size:
                raise ValueError(
                    f"{firmware} {kit} {offset}: declared {size} byte(s), "
                    f"literal contains {len(data)}"
                )
            entries.append((int(offset, 16), data))
        if body.count("{") != len(entries):
            raise ValueError(f"{firmware} {kit}: could not parse every entry")
        tables[(firmware, kit)] = entries
    if not tables:
        raise ValueError(f"no ShellCore patch tables found in {path}")
    return tables


def validate_ranges(
    firmware: str, kit: str, entries: list[tuple[int, bytes]]
) -> list[str]:
    errors = []
    previous_end = -1
    for offset, data in sorted(entries):
        if not data:
            errors.append(f"{firmware} {kit} {offset:#x}: empty patch")
            continue
        if offset < previous_end:
            errors.append(
                f"{firmware} {kit} {offset:#x}: overlaps the previous patch"
            )
        previous_end = max(previous_end, offset + len(data))
    return errors


def audit_image(
    image: Path, entries: list[tuple[int, bytes]]
) -> tuple[list[str], list[str]]:
    segments = load_image(image)
    errors = []
    report = []
    for offset, replacement in entries:
        original = bytes_at(segments, offset, len(replacement))
        executable = any(
            segment.flags & PF_X
            and offset >= segment.vaddr
            and offset + len(replacement)
            <= segment.vaddr + len(segment.data)
            for segment in segments
        )
        if len(original) != len(replacement) or not executable:
            errors.append(f"{offset:#x}: outside an executable image segment")
            continue
        if original == replacement:
            errors.append(f"{offset:#x}: image already contains replacement")
        report.append(
            f"{offset:#010x}: {original.hex(' ')} -> "
            f"{replacement.hex(' ')}"
        )
    return errors, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--header", type=Path,
        default=Path(__file__).resolve().parents[1]
                / "ps5-kstuff" / "shellcore_patches" / "13_60.h",
    )
    parser.add_argument("--firmware", default="1360")
    parser.add_argument(
        "--kit", choices=("retail", "testkit", "devkit"), default="retail"
    )
    parser.add_argument(
        "--image", type=Path,
        help="exact unmodified SceShellCore ELF/raw image for target-byte audit",
    )
    args = parser.parse_args()

    try:
        tables = parse_tables(args.header)
    except (OSError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1

    errors = []
    for (firmware, kit), entries in sorted(tables.items()):
        errors.extend(validate_ranges(firmware, kit, entries))
        print(f"PASS {firmware} {kit}: {len(entries)} structural patch(es)")

    key = (args.firmware, args.kit)
    if args.image:
        if key not in tables:
            errors.append(f"{args.firmware} {args.kit}: table not found")
        else:
            try:
                image_errors, report = audit_image(args.image, tables[key])
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
            else:
                for line in report:
                    print(line)
                errors.extend(image_errors)

    for error in errors:
        print(f"FAIL: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

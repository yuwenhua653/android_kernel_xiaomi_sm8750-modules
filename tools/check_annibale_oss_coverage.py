#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fail closed on incomplete source-module name coverage; never certify flashing.

Inputs are the stock normal-boot inventory and verify_annibale_modules output.
This checks the actual source ELF hashes rather than trusting a saved module
count. Variants are retained in the stock inventory; a renamed implementation
does not automatically satisfy an OEM module/ABI contract.
"""
import argparse
import hashlib
import json
from pathlib import Path


def coverage(stock, source):
    required = {item["name"] for item in stock["modules"]}
    valid, invalid = {}, []
    for name, item in sorted(source["modules"].items()):
        path = Path(item["path"])
        try:
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
        except OSError as exc:
            invalid.append({"name": name, "error": str(exc)})
            continue
        if actual != item["sha256"]:
            invalid.append({"name": name, "error": "source ELF hash changed"})
            continue
        valid[name] = {"path": str(path), "sha256": actual}
    covered = required & valid.keys()
    missing = required - valid.keys()
    return {
        "schema_version": 1,
        "scope": "stock normal-boot inventory, including optional variants",
        "source_release": source.get("release"),
        "stock_unique_names": len(required),
        "verified_source_files": len(valid),
        "same_name_covered": sorted(covered),
        "missing_same_name_source": sorted(missing),
        "source_only_names": sorted(valid.keys() - required),
        "invalid_source_files": invalid,
        "module_name_coverage_complete": bool(required) and not missing and not invalid,
        "flash_ready": False,
        "limitations": [
            "Source provenance comes from the supplied build-verification report; "
            "this tool does not independently prove how a binary was built.",
            "A matching name is not proof of OEM ABI or functional equivalence.",
            "No optional OEM variant or renamed replacement is waived automatically.",
            "Module ownership, dependency/load order, DT, firmware/HAL contracts, "
            "AVB and runtime behavior require independent checks.",
        ],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stock-report", type=Path, required=True)
    ap.add_argument("--source-report", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()
    result = coverage(json.loads(args.stock_report.read_text()),
                      json.loads(args.source_report.read_text()))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Matched {len(result['same_name_covered'])}/{result['stock_unique_names']} "
          f"stock names; {len(result['missing_same_name_source'])} missing; "
          f"{len(result['invalid_source_files'])} invalid source files. "
          "Not a flash-readiness certificate.")
    return 0 if result["module_name_coverage_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

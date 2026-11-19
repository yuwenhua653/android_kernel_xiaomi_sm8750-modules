#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Pinned CI build of Annibale Image and source modules. No device access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()

def run(command, **kwargs):
    print("+", " ".join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), check=True, **kwargs)

def toolchain(root, spec):
    # Gitiles tar.gz bytes are not our content identity. Fetch Git objects for
    # the exact reviewed commit and materialize only the required subtree.
    revision = spec["revision"]
    subdir = Path(spec["subdir"])
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("toolchain requires a full commit ID")
    if subdir.is_absolute() or ".." in subdir.parts:
        raise ValueError("toolchain subtree must be relative")
    checkout = root / spec["name"]
    checkout.mkdir()
    git = ["git", "-C", checkout]
    run([*git, "init", "--quiet"])
    run([*git, "config", "transfer.fsckObjects", "true"])
    run([*git, "remote", "add", "origin", spec["repo"]])
    run([*git, "sparse-checkout", "init", "--cone"])
    run([*git, "sparse-checkout", "set", spec["subdir"]])
    run([*git, "-c", "http.lowSpeedLimit=1024", "-c", "http.lowSpeedTime=120",
         "fetch", "--no-tags", "--depth=1", "--filter=blob:none", "origin", revision],
        timeout=1800)
    run([*git, "checkout", "--detach", revision], timeout=1800)
    observed = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
    if observed != revision:
        raise ValueError("toolchain commit mismatch: " + spec["name"])
    destination = checkout / subdir
    if not destination.is_dir() or not destination.resolve().is_relative_to(checkout.resolve()):
        raise ValueError("missing/invalid toolchain subtree: " + spec["name"])
    tree = subprocess.check_output([*git, "rev-parse", f"HEAD:{spec['subdir']}"], text=True).strip()
    print("Verified Git toolchain", spec["name"], "commit", observed, "tree", tree, flush=True)
    return destination

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=4, choices=range(1, 9))
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    modules = Path(__file__).resolve().parents[1]
    pins = json.loads((modules / "configs/annibale-ci-pins.json").read_text())
    kernel = workspace / "sm8750"
    dt = workspace / "sm8750-devicetrees"
    for key, path in (("kernel", kernel), ("devicetrees", dt)):
        observed = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
        if observed != pins[key]["commit"]:
            raise ValueError("source pin mismatch: " + key)
    if modules != workspace / "sm8750-modules":
        raise ValueError("requires sibling sm8750, sm8750-modules and sm8750-devicetrees")
    out = workspace / "out"
    out.mkdir(exist_ok=False)
    toolroot = workspace / "pinned-tools"
    toolroot.mkdir(exist_ok=False)
    paths = {key: toolchain(toolroot, spec) for key, spec in pins["toolchains"].items()}
    env = dict(os.environ)
    env.update(OUT_DIR=str(out / "kernel"),
               CLANG_BIN=str(paths["clang"] / "bin"),
               HOST_TOOLS_BIN=str(paths["build-tools"] / "bin"),
               BISON_PKGDATADIR=str(paths["bison-data"]),
               KERNEL_TOOLS_BIN=str(paths["kernel-tools"] / "bin"),
               JOBS=str(args.jobs))
    for name in ("KBUILD_MODPOST_WARN", "KBUILD_MODPOST_NOFINAL", "KBUILD_EXTRA_SYMBOLS",
                 "KBUILD_MIXED_TREE", "KBUILD_MODPOST_ALLOW_MISSING_NAMESPACE_IMPORTS"):
        if env.get(name):
            raise ValueError("qualification bypass is not permitted: " + name)
    provenance = {
        "schema_version": 1, "pins": pins,
        "modules_commit": subprocess.check_output(["git", "-C", str(modules), "rev-parse", "HEAD"], text=True).strip(),
        "module_source_dirty": bool(subprocess.check_output(["git", "-C", str(modules), "status", "--porcelain"], text=True).strip()),
        "status": "started", "flashable": False, "runtime_verified": False,
    }
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    run(["bash", kernel / "scripts/xiaomi/compile-annibale-board.sh", "qualify"], env=env)
    run(["python3", "-B", modules / "tools/build_annibale_modules.py",
         "--kernel", kernel, "--kernel-out", out / "kernel",
         "--clang-bin", paths["clang"] / "bin",
         "--kernel-tools-bin", paths["kernel-tools"] / "bin",
         "--output", out / "external", "--profile", "audio", "--experimental-sla",
         "--jobs", str(args.jobs)], env=env)
    stages = list((out / "external").glob("modules-*"))
    if len(stages) != 1:
        raise ValueError("ambiguous module build stage")
    stage = stages[0]
    build = json.loads((stage / "build.json").read_text())
    if build["returncode"] != 0 or build["verification_status"] != "passed":
        raise ValueError("module qualification did not pass")
    report = json.loads((stage / "verification.json").read_text())
    provenance.update(status="kernel_and_modules_verified",
                      external_module_count=report["external_module_count"],
                      release=(out / "kernel/include/config/kernel.release").read_text().strip())
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    destination = workspace / "artifacts"
    destination.mkdir(exist_ok=True)
    target = destination / "annibale-r47-ARM64-NOT-FLASHABLE.zip"
    selected = {out / "provenance.json": "provenance.json"}
    for rel in (".config", "Module.symvers", "modules.order", "modules.builtin",
                "vmlinux", "arch/arm64/boot/Image"):
        selected[out / "kernel" / rel] = "kernel/" + rel
    for rel in (out / "kernel/modules.order").read_text().splitlines():
        module = (out / "kernel" / rel).with_suffix(".ko").resolve()
        if not module.is_relative_to((out / "kernel").resolve()):
            raise ValueError("module path escapes kernel output: " + rel)
        selected[module] = "kernel/" + module.relative_to((out / "kernel").resolve()).as_posix()
    for path in stage.rglob("*.ko"):
        selected[path] = "external/" + path.relative_to(stage).as_posix()
    for path in out.rglob("*.log"):
        selected[path] = "logs/" + path.relative_to(out).as_posix()
    for name in ("build.json", "verification.json", "Module.symvers", "modules.order"):
        selected[stage / name] = "external/" + name
    hashes = {}
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
        for path, name in sorted(selected.items(), key=lambda item: item[1]):
            if not path.is_file():
                raise ValueError("missing build artifact: " + str(path))
            hashes[name] = digest(path)
            archive.write(path, name)
        archive.writestr("SHA256SUMS.json", json.dumps(hashes, indent=2) + "\n")
        archive.writestr("NOT-FLASHABLE.txt",
            "Source qualification only. No boot/vendor_boot/DTBO/DLKM images are assembled.\n"
            "Do not install these source modules over retained-OEM HyperOS modules.\n")
    print("PASS:", target, "sha256", digest(target), flush=True)

if __name__ == "__main__":
    main()

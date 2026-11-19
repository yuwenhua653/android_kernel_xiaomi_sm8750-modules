#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Restore hash-bound R47 inputs and stage source modules without recompiling Image."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import zipfile

from ci_annibale_arm64 import toolchain
from check_annibale_rom_paths import check_build_inputs
from verify_annibale_modules import verify
from stage_annibale_android import stage
from prepare_annibale_sla_policy import extend

ZIP_SHA = "b85e97c9d80e1edab54d6b0d5baae13a1c665dd00d37b58f41e598804742f949"
SOURCE_COMMIT = "53e21323104f0ad3f5596a2032b95d676b92ed6d"
BASE = Path("/tmp/ak.bVlans")
EXTERNAL = BASE / "out/external/modules-2lxnhcuk"

def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def run(cmd, **kw):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run(list(map(str, cmd)), check=True, **kw)

def unpack_verified(archive, root):
    if sha(archive) != ZIP_SHA:
        raise ValueError("R47 qualification ZIP hash mismatch")
    root.mkdir()
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicate ZIP paths")
        manifest = json.loads(z.read("SHA256SUMS.json"))
        if set(names) != set(manifest) | {"SHA256SUMS.json", "NOT-FLASHABLE.txt"}:
            raise ValueError("unmanifested/missing ZIP entries")
        for name in names:
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or "\\" in name:
                raise ValueError("unsafe ZIP path")
            dest = root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(name) as source, dest.open("xb") as output:
                shutil.copyfileobj(source, output)
            if name in manifest and sha(dest) != manifest[name]:
                raise ValueError("ZIP member hash mismatch: " + name)
    return manifest

def clone_exact(source, destination, commit):
    run(["git", "clone", "--shared", "--no-checkout", source, destination])
    run(["git", "-C", destination, "checkout", "--detach", commit])
    head = subprocess.check_output(["git", "-C", str(destination), "rev-parse", "HEAD"], text=True).strip()
    if head != commit:
        raise ValueError("source checkout differs")

def write_zip(root, output):
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(root).as_posix())
    return sha(output)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifact", type=Path, required=True)
    ap.add_argument("--kernel-source", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    repo = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(exist_ok=False)
    report = {"source_run": 44487958049, "source_commit": SOURCE_COMMIT,
              "status": "started", "flashable": False, "hyperos_installation_ready": False,
              "kernel_image_recompiled": False, "external_modules_recompiled": False,
              "builtin_metadata_regenerated": False, "profiles": {}}
    report_path = output / "assembly.json"
    def save():
        report_path.write_text(json.dumps(report, indent=2) + "\n")
    save()
    try:
        if BASE.exists():
            raise ValueError("recorded restoration root already exists")
        BASE.mkdir()
        manifest = unpack_verified(args.artifact, BASE / "archive")
        report["archive_members_verified"] = len(manifest)
        archive = BASE / "archive"
        provenance = json.loads((archive / "provenance.json").read_text())
        if (provenance["modules_commit"] != SOURCE_COMMIT or
            provenance["module_source_dirty"] or
            provenance["status"] != "kernel_and_modules_verified"):
            raise ValueError("wrong/nonqualified R47 source provenance")
        kout = BASE / "out/kernel"
        kout.parent.mkdir()
        shutil.copytree(archive / "kernel", kout)
        EXTERNAL.parent.mkdir()
        shutil.copytree(archive / "external", EXTERNAL)
        build = json.loads((EXTERNAL / "build.json").read_text())
        if build["stage"] != str(EXTERNAL) or build["source_commit"] != SOURCE_COMMIT:
            raise ValueError("unexpected recorded build layout")
        recorded = build["kernel_inputs"]
        release = kout / "include/config/kernel.release"
        release.parent.mkdir(parents=True)
        release.write_text(provenance["release"] + "\n")
        if sha(release) != recorded[str(release)]:
            raise ValueError("release reconstruction differs from recorded hash")
        # The original ZIP omitted autoconf.h. Regenerate it with the original
        # source/config/tools, then require its original recorded hash.
        pins = provenance["pins"]
        clone_exact(args.kernel_source.resolve(), BASE / "sm8750", pins["kernel"]["commit"])
        head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        clone_exact(repo, BASE / "sm8750-modules", head)
        toolroot = BASE / "tools"
        toolroot.mkdir()
        paths = {k: toolchain(toolroot, v) for k, v in pins["toolchains"].items()}
        env = dict(os.environ)
        env["PATH"] = os.pathsep.join([str(paths["kernel-tools"] / "bin"),
            str(paths["clang"] / "bin"), str(paths["build-tools"] / "bin"), env["PATH"]])
        env["M4"] = str(paths["build-tools"] / "bin/m4")
        env["BISON_PKGDATADIR"] = str(paths["bison-data"])
        regen = BASE / "regen"
        regen.mkdir()
        shutil.copyfile(kout / ".config", regen / ".config")
        kt = paths["kernel-tools"]
        cmd = ["make", "-C", BASE / "sm8750", f"O={regen}", "ARCH=arm64",
               "LLVM=1", "HOSTCC=gcc", "-j4", f"HOSTCFLAGS=-I{kt}/include",
               f"HOSTLDFLAGS=-L{kt}/lib64 -Wl,-rpath,{kt}/lib64",
               "olddefconfig", "prepare"]
        run(cmd, env=env)
        if sha(regen / ".config") != sha(kout / ".config"):
            subprocess.run(["diff", "-u", str(kout / ".config"), str(regen / ".config")], check=False)
            raise ValueError("regenerated configuration differs; no assembly allowed")
        header = kout / "include/generated/autoconf.h"
        header.parent.mkdir(parents=True, exist_ok=True)
        if sha(regen / "include/generated/autoconf.h") != recorded[str(header)]:
            raise ValueError("regenerated autoconf.h differs from original recorded hash")
        shutil.copyfile(regen / "include/generated/autoconf.h", header)
        report["restored_header_matches_original_sha256"] = sha(header)
        report["kernel_inputs"] = check_build_inputs(kout, EXTERNAL)
        verification = verify(kout, EXTERNAL)
        original = json.loads((EXTERNAL / "verification.json").read_text())
        if verification != original:
            raise ValueError("restored verification differs from original R47 report")
        (output / "verification.json").write_text(json.dumps(verification, indent=2) + "\n")
        report["kernel_module_count"] = verification["kernel_module_count"]
        report["external_module_count"] = verification["external_module_count"]
        save()
        print("PASS: original kernel inputs, configuration and 505-module report restored", flush=True)
        # Final vmlinux discards .modinfo; it cannot supply this omitted file.
        # Generate it through the pinned kernel's real Kbuild rule, keeping the
        # qualified Image/modules untouched. Do not synthesize an empty file or
        # suppress depmod diagnostics.
        run(cmd[:-2] + ["modules.builtin.modinfo"], env=env)
        if sha(regen / "modules.builtin") != sha(kout / "modules.builtin"):
            raise ValueError("regenerated built-in ownership differs from qualified kernel")
        if sha(regen / ".config") != sha(kout / ".config"):
            raise ValueError("configuration changed while generating builtin metadata")
        metadata = regen / "modules.builtin.modinfo"
        if not metadata.is_file() or not metadata.stat().st_size:
            raise ValueError("missing/empty real Kbuild builtin metadata")
        shutil.copyfile(metadata, kout / metadata.name)
        report["builtin_metadata_regenerated"] = True
        report["builtin_metadata"] = {
            "method": "pinned Kbuild modules.builtin.modinfo target",
            "sha256": sha(metadata), "size": metadata.stat().st_size,
            "ownership_sha256": sha(regen / "modules.builtin"),
            "ownership_matches_original": True}
        save()
        print("PASS: real Kbuild builtin metadata and original builtin ownership match", flush=True)
        for family in ("tfa", "sia"):
            base_policy = repo / f"Documentation/xiaomi/annibale-spu-{family}-partitions.json"
            for sla in (False, True):
                label = family + ("-sla-experimental" if sla else "")
                policy_path = base_policy
                if sla:
                    policy_path = output / (label + "-policy.json")
                    policy_path.write_text(json.dumps(extend(json.loads(base_policy.read_text())), indent=2) + "\n")
                staged = BASE / ("stage-" + label)
                result = stage(kout, EXTERNAL, policy_path, staged,
                               kt / "bin/depmod", paths["clang"] / "bin/llvm-strip")
                target = output / ("annibale-r48-" + label + "-SOURCE-STAGE-NOT-FLASHABLE.zip")
                report["profiles"][label] = {
                    "selected_module_count": result["selected_module_count"],
                    "partitions": result["partitions"],
                    "archive": target.name, "sha256": write_zip(staged, target)}
                save()
                print("PASS: staged", label, result["selected_module_count"], "modules", flush=True)
        portable = BASE / "portable-inputs"
        portable.mkdir()
        for rel in (".config", "Module.symvers", "modules.order", "modules.builtin",
                    "modules.builtin.modinfo", "include/config/kernel.release",
                    "include/generated/autoconf.h", "arch/arm64/boot/Image"):
            dest = portable / "kernel" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(kout / rel, dest)
        shutil.copyfile(archive / "provenance.json", portable / "provenance.json")
        (portable / "README.txt").write_text(
            "R47 kernel metadata and Image for offline assembly; NOT a boot image or installer.\n"
            "Use only with matching hash-verified source modules and reviewed firmware inputs.\n")
        pzip = output / "annibale-r48-kernel-inputs-NOT-FLASHABLE.zip"
        report["kernel_inputs_zip"] = {"file": pzip.name, "sha256": write_zip(portable, pzip)}
        report["status"] = "source_stages_verified"
        report["remaining"] = ["Exact HyperOS original partition inputs are unavailable in this execution context",
            "HyperOS source/OEM module ownership and mixed ABI/loader audit",
            "Matching DT, firmware, init/SELinux, AVB, recovery and runtime validation"]
        save()
        print(json.dumps(report, indent=2), flush=True)
    except Exception as error:
        report.update(status="failed", error=str(error))
        save()
        raise

if __name__ == "__main__":
    main()

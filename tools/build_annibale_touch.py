#!/usr/bin/env python3
"""Compile the opt-in touch port against an already prepared arm64 kernel.

Default validation stops at relocatable module objects. --modules also runs
modpost and requires the real kernel Module.symvers; no symbol stubs are used.
The source checkout is copied to a new staging directory and is never built in.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--kernel-out", type=Path, required=True)
    parser.add_argument("--clang-bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jobs", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--modules", action="store_true")
    args = parser.parse_args()
    kernel, kout, clang = (p.resolve() for p in
                           (args.kernel, args.kernel_out, args.clang_bin))
    repo = Path(__file__).resolve().parents[1]
    source = repo / "xiaomi/touch/annibale"
    output = args.output.resolve()
    if any(output == tree or tree in output.parents for tree in (repo, kernel)):
        parser.error("--output must be outside the module and kernel source trees")
    for required in (kernel / "Makefile", kout / "include/generated/autoconf.h",
                     kout / "include/config/kernel.release", clang / "clang"):
        if not required.is_file():
            parser.error(f"required prepared-kernel/toolchain file missing: {required}")
    if args.modules and not (kout / "Module.symvers").is_file():
        parser.error("--modules requires the real kernel-out/Module.symvers")
    output.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="touch-", dir=output))
    shutil.copytree(source, stage / "src")
    env = dict(os.environ, PATH=f"{clang}:{os.environ.get('PATH', '')}")
    command = ["make", "-C", str(kernel), f"O={kout}", f"M={stage / 'src'}",
               "ARCH=arm64", "LLVM=1", "LLVM_IAS=1", f"-j{args.jobs}",
               "CONFIG_TOUCHSCREEN_XIAOMI_ANNIBALE=m"]
    command += (["modules"] if args.modules else
                ["xiaomi/xiaomi_touch.o", "goodix_9916k/goodix_core.o"])
    print("Staged sources:", stage / "src", flush=True)
    print("Validation:", "modules including modpost" if args.modules else
          "relocatable objects only; not loadable modules or a boot test", flush=True)
    result = subprocess.run(command, env=env, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

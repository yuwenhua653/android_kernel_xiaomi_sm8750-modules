# SPDX-License-Identifier: GPL-2.0-only
"""Exercise real RMNET flow predicates with address-family collisions."""
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "qcom/opensource/datarmnet-ext"
BASELINE = "e0ce4601d9cac01d9007e1ebae5931040c628929"


def extract(source, pattern):
    match = re.search(pattern, source)
    if match is None:
        raise ValueError("missing C definition: " + pattern)
    start = source.index("{", match.start())
    depth, end = 1, start + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end]


def fixture(source, production, baseline=False):
    main_h = (BASE / "src/offload/rmnet_offload_main.h").read_text()
    engine_h = (BASE / "src/offload/rmnet_offload_engine.h").read_text()
    code = """#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
typedef uint8_t u8;
typedef uint16_t u16, __be16;
typedef uint32_t u32, __be32;
struct hlist_node { void *next, *pprev; };
struct list_head { void *next, *prev; };
struct rmnet_frag_descriptor;
"""
    # Use the actual readable header declarations, including address unions.
    for header, name in ((main_h, "rmnet_offload_header_info"),
                         (main_h, "rmnet_offload_info"),
                         (engine_h, "rmnet_offload_flow")):
        code += extract(header, r"struct\s+" + name + r"\s*\{") + ";\n"
    name = "DATARMNET6895620058" if production else "rmnet_offload_engine_flow_match"
    aliases = {
        "DATARMNET6895620058": "rmnet_offload_engine_flow_match",
        "DATARMNETd7c9631acd": "rmnet_offload_flow",
        "DATARMNETd812bcdbb5": "rmnet_offload_info",
        "DATARMNET4287f07234": "rmnet_offload_header_info",
        "DATARMNET78fd20ce0e": "rof_hdrs",
        "DATARMNET144d119066": "roi_hdrs",
        "DATARMNET1db11fa85e": "rof_pkts_held",
        "DATARMNET381f1cadc4": "rof_hash_key",
        "DATARMNET645e8912b8": "roi_hash_key",
        "DATARMNET388842c721": "roh_ip_proto",
        "DATARMNET7fa8b2acbf": "roh_trans_proto",
        "DATARMNETa60d2ae3f6": "roh_sport",
        "DATARMNET5e7452ec23": "roh_dport",
        "DATARMNET1a2be7b6c2": "roh_saddr4",
        "DATARMNET0a28fa80f4": "roh_daddr4",
        "DATARMNET949c2754de": "roh_saddr6",
        "DATARMNET45ec858bc5": "roh_daddr6",
    }
    if production:
        code += "\n".join("#define " + a + " " + b for a, b in aliases.items()) + "\n"
    code += extract(source, r"static\s+bool\s+" + name + r"\s*\(") + "\n"
    code += "#define EXPECT_CROSS_FAMILY " + ("1" if baseline else "0") + "\n"
    code += r"""
static void setup(struct rmnet_offload_flow *f, struct rmnet_offload_info *p,
                  unsigned int family, unsigned int transport)
{
    memset(f, 0, sizeof(*f));
    memset(p, 0, sizeof(*p));
    f->rof_pkts_held = 1;
    f->rof_hash_key = p->roi_hash_key = 0x12345678;
    f->rof_hdrs.roh_ip_proto = family;
    f->rof_hdrs.roh_trans_proto = transport;
    f->rof_hdrs.roh_sport = 1234;
    f->rof_hdrs.roh_dport = 5678;
    f->rof_hdrs.roh_saddr6[0] = 0x20010db8;
    f->rof_hdrs.roh_daddr6[0] = 0x20010db9;
    p->roi_hdrs = f->rof_hdrs;
}
int main(void)
{
    struct rmnet_offload_flow f;
    struct rmnet_offload_info p;
    unsigned int families[] = {4, 6}, protocols[] = {6, 17};
    for (unsigned int a = 0; a < 2; a++)
        for (unsigned int b = 0; b < 2; b++) {
            setup(&f, &p, families[a], protocols[b]);
            assert(rmnet_offload_engine_flow_match(&f, &p));
            /* Same address bytes/ports/hash but the opposite IP version. */
            p.roi_hdrs.roh_ip_proto = families[1-a];
            assert(rmnet_offload_engine_flow_match(&f, &p) == EXPECT_CROSS_FAMILY);
            p.roi_hdrs.roh_ip_proto = families[a];
            p.roi_hdrs.roh_trans_proto = protocols[1-b];
            assert(!rmnet_offload_engine_flow_match(&f, &p));
            p.roi_hdrs = f.rof_hdrs;
            p.roi_hdrs.roh_sport++;
            assert(!rmnet_offload_engine_flow_match(&f, &p));
            p.roi_hdrs = f.rof_hdrs;
            p.roi_hdrs.roh_dport++;
            assert(!rmnet_offload_engine_flow_match(&f, &p));
            p.roi_hdrs = f.rof_hdrs;
            p.roi_hdrs.roh_saddr6[0]++;
            assert(!rmnet_offload_engine_flow_match(&f, &p));
            p.roi_hdrs = f.rof_hdrs;
            p.roi_hdrs.roh_daddr6[0]++;
            assert(!rmnet_offload_engine_flow_match(&f, &p));
            if (families[a] == 6) {
                for (unsigned int i = 1; i < 4; i++) {
                    p.roi_hdrs = f.rof_hdrs;
                    p.roi_hdrs.roh_saddr6[i]++;
                    assert(!rmnet_offload_engine_flow_match(&f, &p));
                    p.roi_hdrs = f.rof_hdrs;
                    p.roi_hdrs.roh_daddr6[i]++;
                    assert(!rmnet_offload_engine_flow_match(&f, &p));
                }
            }
            /* An empty slot has no valid headers and remains reusable. */
            f.rof_pkts_held = 0;
            p.roi_hdrs.roh_ip_proto = families[1-a];
            assert(rmnet_offload_engine_flow_match(&f, &p));
            p.roi_hash_key++;
            assert(!rmnet_offload_engine_flow_match(&f, &p));
        }
    setup(&f, &p, 5, 6);
    assert(!rmnet_offload_engine_flow_match(&f, &p));
    puts(EXPECT_CROSS_FAMILY ? "PASS: baseline cross-family false match reproduced"
                            : "PASS: cross-family rejection and same-family matching");
    return 0;
}
"""
    return code


class OffloadFlowTests(unittest.TestCase):
    def run_fixture(self, production, baseline):
        rel = ("offload" if production else "src/offload") + "/rmnet_offload_engine.c"
        path = BASE / rel
        source = (subprocess.check_output(
            ["git", "show", BASELINE + ":" + path.relative_to(ROOT).as_posix()],
            cwd=ROOT, text=True) if baseline else path.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "fixture.c").write_text(fixture(source, production, baseline))
            command = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run(command + [
                "-std=gnu11", "-Wall", "-Werror", "-Wno-misleading-indentation",
                "-fsanitize=undefined", "-fno-sanitize-recover=all",
                str(p / "fixture.c"), "-o", str(p / "test")], check=True)
            subprocess.run([str(p / "test")], check=True, timeout=10)

    def test_readable_current(self):
        self.run_fixture(False, False)

    def test_production_current(self):
        self.run_fixture(True, False)

    def test_readable_baseline_reproduces_bug(self):
        self.run_fixture(False, True)

    def test_production_baseline_reproduces_bug(self):
        self.run_fixture(True, True)


if __name__ == "__main__":
    unittest.main()

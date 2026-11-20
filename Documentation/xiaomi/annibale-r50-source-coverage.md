# R50 full-source replacement accounting

Keep the R49 working hybrid package separate from the R50 source-only port.
The new kernel `oss-power` profile includes the public MCA candidate and official
diagnostic drivers. It is not yet a complete HyperOS replacement.

Rebuild the external `audio` profile against the exact new kernel output. This
profile also contains the platform, graphics, network, Wi-Fi, camera, DSP,
security and touch groups. Its verifier checks actual ordered ARM64 modules,
symbol CRCs, vermagic, BTF and hard dependencies. No old symvers is imported.

```sh
python3 -B tools/build_annibale_modules.py --profile audio \
  --kernel /path/to/kernel --kernel-out /path/to/new-kernel-output \
  --clang-bin /path/to/clang-r510928/bin \
  --kernel-tools-bin /path/to/kernel-tools/linux-x86/bin \
  --output /short/external-output --jobs 6
```

Use a short physical external-output path for the WLAN include argument list.
The final report and actual ELF files feed the new inventory check:

```sh
python3 -B tools/check_annibale_oss_coverage.py \
  --stock-report /path/to/OS4-stock-normal-abi.json \
  --source-report /path/to/new-source-verification.json \
  --report /path/to/source-coverage.json
```

Exit status 1 is expected while any stock name lacks a source counterpart or
the actual source file no longer matches its recorded hash. Optional variants
are not removed silently. A differently named driver requires explicit board,
ABI and load-policy review, not a spelling alias that hides a missing function.
Even complete name coverage is **not** flash certification.

For kernel-only intermediate builds, `verify_annibale_modules.py --kernel-only`
uses just that build's authoritative modules.order and Module.symvers while
retaining all ELF, CRC, BTF and dependency checks. It does not permit an empty
or fictitious external module stage.

See the kernel repository's `Documentation/xiaomi/annibale-r50-oss.md` for
source provenance, hardware/policy limitations and conditions blocking a flash
package. The MCA candidate must not be mixed with retained OEM MCA modules.

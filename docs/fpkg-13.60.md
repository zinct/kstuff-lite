# fPKG/PPR status for firmware 13.60

Firmware 13.60 is wired into the loader, prosper0gdb, and ShellCore patch
tables, but installed native PS5 fPKG is **not supported**. The public
kernel-side offsets are candidates, and the required external A53 selector in
[`drakmor/ppr-patch`](https://github.com/drakmor/ppr-patch) has exact profiles
only through firmware 11.40. Its documentation explicitly states that adding
an A53 profile alone does not add the matching kernel-side marker.

For that reason kstuff keeps installed native PS5 fPKG/PPR limited to 11.60
and earlier. On newer firmware the package GOT wrappers are not installed and
the UELF does not arm candidate PPR traps. This converts an unsupported launch
from a ShellCore/kernel freeze into a normal failure. Firmware 13.60 users
must use the dump/`.ffpkg` workflow until both sides below are ported.

## Baseline and provenance

The 13.60 kernel table was introduced by commit `fb70287`. The eight PPR
offsets and the generation-13 ABI profile were added by `a7ca1c3`.  Upstream
then capped plaintext interception at 11.60 in `bd8928c`, while retaining the
newer offsets for later validation. Enabling those candidates without the
matching A53 13.60 profile caused installed PS5 games to hang during launch,
so this branch preserves the upstream safety limit.

Full 13.60 support requires work in two repositories:

1. `kstuff-lite`: validate the kernel and ShellCore offsets described below;
2. `drakmor/ppr-patch`: obtain the exact retail 13.60 A53 image, extend its
   generator inventory, generate a 13.60 target profile, and pass that
   repository's `make verify` and `make host-test`.

Do not copy an 11.x A53 profile. The external patcher validates complete
instruction layouts and intentionally fails closed on unknown firmware.

Compared with 13.40/13.42, 13.60 has a different kernel layout.  Many text and
data-relative addresses move, so the 13.40/13.42 table must not be reused.
The complete 13.60 table lives in
`prosper0gdb/offsets/13_60.h`.

The fPKG path depends on these groups:

- mailbox and crypto: `sceSblServiceMailbox`, its verified return addresses,
  `sceSblServiceCryptAsync`, and `crypt_message_resolve`;
- SELF loading: `loadSelfSegment_*`, `decryptSelfBlock_*`, and
  `decryptMultipleSelfBlocks_*`;
- debug/FPU transitions: `cpu_switch`, `mov_rax_cr0`, and the CR0 helpers;
- plaintext PPR: both `ppr_pfs_get_*_index` entries and returns,
  `ppr_pfs_cleanup_keys`, `ppr_pfs_clear_key_missing`,
  `sceSblServiceMailbox_lr_verifyImage`, and
  `ppr_pfs_verify_image_no_key_success`.

The UELF now rejects plaintext PPR when any of the eight optional PPR symbols
is unresolved.  This keeps an incomplete table fail-closed instead of arming
partial debug-register traps.

## Retail kernel validation

Keep copyrighted kernel images outside git.  Use this local layout:

```text
/path/to/kernels/
└── retail/
    └── 13.60.elf
```

Run the exact-version check:

```sh
python3 tools/validate_ppr_offsets.py /path/to/kernels --firmware 13.60
```

The command fails if `13.60.elf`/`.bin` is absent, if a required PPR offset is
zero, or if any validated instruction/call relationship differs.  The release
criterion is:

```text
PASS 13.60.elf
Checked 1 retail image(s): 1 passed, 0 failed.
```

If it fails, derive candidates from the target image rather than copying a
delta from a neighboring firmware:

```sh
python3 tools/find_ppr_offsets.py /path/to/kernels/retail/13.60.elf \
  --reference-dir /path/to/kernels/retail
```

Setting `KSTUFF_KERNEL_CORPUS=/path/to/kernels` makes
`ci-ps5-kstuff-ldr.sh` require this validation before building.

## ShellCore patch audit

First validate the source table itself:

```sh
python3 tools/audit_shellcore_patches.py
```

With the exact unmodified 13.60 image, dump and range-check every retail target:

```sh
python3 tools/audit_shellcore_patches.py \
  --kit retail --image /path/to/SceShellCore.elf
```

Review the reported original/replacement byte pairs in a disassembler.  Verify
the installer branches, the three `ps4_nongame_mini` category checks, the RIF
callback, and the final PKG-installer return.  The image audit proves target
ranges and records bytes; it does not replace control-flow review.

At runtime, every patch is checked against the ShellCore text range and read
back after writing. On firmware 11.60 and earlier, the fPKG wrapper additionally
verifies its mapped blob and GOT installation. Success emits:

```text
fpkg scope: ShellCore hook installed
```

## Observable console test after both ports exist

Build:

```sh
export PS5_PAYLOAD_SDK=/opt/ps5-payload-sdk
KSTUFF_OBS=1 ./ci-ps5-kstuff-ldr.sh
```

Deploy `ps5-kstuff-ldr/kstuff.elf`, then run
`ps5-kstuff/debug-reader.elf`.  The reader appends
`/data/kstuff_debug.log`, fsyncs every snapshot, and keeps a compact
`/data/kstuff_debug_last.txt` for post-reboot diagnosis.

Only after `kstuff-lite` validation and a generated external A53 13.60 profile
both pass, enable the shared firmware limit and run these tests on a retail
13.60 console:

1. Mount and launch a game fPKG.  `syscall_fpkg_dispatches`,
   `mailbox_fpkg`, and the relevant crypto counters must advance without a
   corresponding surge in `fpkg_reject_*`.
2. Mount a plaintext `.ffpkg` through `sceFsMountPprPkg`.
   `ppr_plaintext_profile_matches` and `ppr_plaintext_g6_applied` must
   advance.
3. Unmount it.  `ppr_plaintext_cleanup_put_emulated` must advance and
   `ppr_plaintext_key_pairs_outstanding` must return to zero.
4. Repeat mount/read/unmount.  ShellCore must remain responsive and no stale
   key pair may accumulate.

Do not raise `KSTUFF_FPKG_MAX_FW` or claim full 13.60 support until the retail
kernel validator, ShellCore image review, external A53 profile verification,
and all four console checks have recorded passing evidence.

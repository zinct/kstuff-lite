# fPKG/PPR validation for firmware 13.60

Firmware 13.60 is wired into the loader, prosper0gdb, ShellCore patch tables,
and the UELF fPKG/PPR profile.  Plaintext PPR interception remains
**experimental** until both the exact retail images and a retail console pass
the checks below.  A successful build alone is not proof of runtime support.

## Baseline and provenance

The 13.60 kernel table was introduced by commit `fb70287`.  The eight PPR
offsets and the generation-13 ABI profile were added by `a7ca1c3`.  Upstream
then capped plaintext interception at 11.60 in `bd8928c`, while retaining the
newer offsets for later validation.  This branch raises the experimental gate
to 13.60 and adds persistent observability.

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

At runtime, every patch is now checked against the ShellCore text range and
read back after writing.  The fPKG wrapper additionally verifies its mapped
blob and GOT installation.  Success emits:

```text
fpkg scope: ShellCore hook installed
```

## Observable console test

Build:

```sh
export PS5_PAYLOAD_SDK=/opt/ps5-payload-sdk
KSTUFF_OBS=1 ./ci-ps5-kstuff-ldr.sh
```

Deploy `ps5-kstuff-ldr/kstuff.elf`, then run
`ps5-kstuff/debug-reader.elf`.  The reader appends
`/data/kstuff_debug.log`, fsyncs every snapshot, and keeps a compact
`/data/kstuff_debug_last.txt` for post-reboot diagnosis.

Run these tests on a retail 13.60 console:

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

Do not remove the experimental label or claim full 13.60 support until the
retail kernel validator, ShellCore image review, and all four console checks
have recorded passing evidence.

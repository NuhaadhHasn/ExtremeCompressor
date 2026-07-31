# 16 — Source study: Inno Setup 7.1.0-dev (line-by-line)

> Part of the 2026-07-31 source-code study series (docs 13-21). Method: full
> clone read by a dedicated study agent; every claim carries a file:line
> reference. Studied commit: `899f6edd3538517b12b7c039979f3b76d9eebd95`
> (2026-07-29) from https://github.com/jrsoftware/issrc. Paths relative to
> the repo root. This doc decides **Phase H** (installer-style output) —
> especially hard rule **H1: byte-identical signed stub**.

## Version & license

- Version = **7.1.0-dev** (`Projects/Src/Shared.Struct.pas:20`), setup-data
  format ID `'Inno Setup Setup Data (7.0.0.3)'` (`Shared.Struct.pas:36`).
- **License** (`license.txt:1-32`): custom permissive (zlib-like), **not
  OSI-listed** but OSI-clean in substance. "Permission is granted to anyone
  to use this software for any purpose, including commercial applications,
  and to alter and redistribute it" (:13-14). Conditions: (1) source
  redistributions keep notices (:16-17); (2) **binary redistributions must
  retain all occurrences of the copyright notice and web-site addresses
  "currently in place"** (:19-20); (3) no misrepresentation of origin
  (acknowledgment "appreciated but is not required", :22-24); (4) modified
  versions must be plainly marked (:26-27). `Compiler.SetupCompiler.pas:
  7136-7140` embeds a copyright string with a comment that removing it
  violates the license.
  - **(a) Invoking ISCC.exe to build installers for user archives: yes,
    unconditionally.** Generated installers are our output, not a
    "redistribution".
  - **(b) Redistributing / auto-downloading the compiler in our
    tool-downloader: yes** — binary redistribution explicitly allowed under
    condition 2 (ship official untouched binaries; never strip/repack).
  - **(c) Shipping generated installers commercially: yes** (:13). **No
    attribution required** (:23-24).

## Answers

### 2. Compiled output anatomy & the byte-identical question

Assembly sequence (normal `UseSetupLdr=yes` path,
`Compiler.SetupCompiler.pas:9066-9171`):

1. `SetupLdr.e32/.e64` (precompiled Delphi stub, trust-verified via embedded
   ECDSA keys) is **copied** to `Output\{basename}.exe` (:9072).
2. `UpdateIconsAndStyle` runs by default (condition :9077 is true because
   default `WizardDarkStyle = wdsLight`, set at :8354) — uses Windows
   `BeginUpdateResource/EndUpdateResource` to delete/replace icon resources
   (`Compiler.ExeUpdateFunc.pas:654-1074`).
3. `UpdateSetupPEHeaderFields` sets TSAware/DEP/ASLR DllCharacteristics bits
   in place (`Compiler.ExeUpdateFunc.pas:412-463`).
4. Data appended at EOF (:9113-9142): **Setup-0 header block**
   (`WriteSetup0`, :9121) → **LZMA1-compressed Setup.e32** (the real
   installer program, `CompressSetupMemoryFile` :8109-8127) → if
   `DiskSpanning=no`, compressed file chunks appended by
   `CompressFiles(ExeFilename, 0)` (:9104-9105) at `Offset1 = SizeOfExe`
   (:9142); if `DiskSpanning=yes`, `Offset1 := 0` and chunks go to `.bin`
   slices (:9126-9132).
5. `TSetupLdrOffsetTable` (`Shared.Struct.pas:422-435`: ID, Version,
   TotalSize, OffsetEXE, UncompressedSizeEXE, CRCEXE, Offset0, Offset1,
   TableCRC) is written **into RCDATA resource 11111** inside the stub's
   resource section (:9146-9149) — not appended.
6. `UpdateVersionInfo` patches RT_VERSION strings in place (:9151-9156),
   `PreventCOMCTL32Sideloading` patches the manifest in place (:9159-9162),
   file mtime set (:9167 — filesystem only, not content).

At runtime SetupLdr reads the offset table from its own resource
(`Projects/SetupLdr.dpr:296-302,438-449`), validates `Version`, `TableCRC`,
`SourceF.Size >= TotalSize`, reads Setup-0 headers from `Offset0`,
decompresses/CRC-checks Setup.e32 from `OffsetEXE` to a temp file and
spawns it with `/SL5="$hwnd,Offset0,Offset1,"` (SetupLdr.dpr:519-573).

**What is embedded per-script (the critical part):** `WriteSetup0`
(`Compiler.SetupCompiler.pas:7284-7462`) serializes `TSetupHeader` —
**AppName, AppId, AppVersion, DefaultDirName, all [Files]/[Run]/etc.
entries, the compiled [Code] byte-code (`CompiledCodeText`, :7362), wizard
images, and (LZMA1-compressed) FileLocation entries** — into the exe at
Offset0. The exe **always contains the full script state**; there is no
mode where the exe is payload-independent *if the script text differs per
archive*.

**What varies between two builds:**

- Different script (AppName etc.) → different Setup-0 block → different
  exe. **Any per-archive string in [Setup] or [Files] breaks H1.**
- Same script, rebuilt: no timestamps, no GUIDs, no script hash, and no
  randomness are embedded — random bytes (`TStrongRandom.GenerateBytes`)
  are used **only** when `Password`/`Encryption` is set (:8643-8650);
  `GetSystemTime` in `CompressFiles` (:7669-7672) only affects `touch`-ed
  embedded-file timestamps (none exist when all files are external);
  `UpdateTimeStamp` (:8234-8240) touches only the filesystem mtime.
  Internal blocks use single-stream LZMA1 (`TLZMACompressor`, :7370, :8119)
  which is thread-count-insensitive; LZMA2 (machine-dependent auto
  block-threading, `Compression.LZMACompressor.pas:904-935`,
  `NumThreadGroups` from `GetActiveProcessorGroupCount` :8296-8302) is used
  only for file chunks — absent with all-external. Residual risk: step 2's
  `EndUpdateResource` (Windows API resource rewrite) is OS-build-dependent
  in its section layout — stable on one machine/OS, not guaranteed across
  OS updates.

**Verdict for H1:** a truly byte-identical universal stub **is achievable
with stock Inno, but only via the "one frozen script → compile once →
cache the canonical setup.exe → sign once" pattern**, with *all*
per-archive variability read at runtime from sidecars. Do **not** rely on
per-archive recompiles hashing identically. The runtime-sidecar pattern is
fully supported: `AppName` may contain constants incl. `{code:...}` if
`DisableStartupPrompt=yes` (enforced at :8402-8409, flag
`shAppNameHasConsts` `Shared.Struct.pas:66`); external payload via
`Source: "{src}\payload\*"; Flags: external recursesubdirs`; config via
`[Code]` `LoadStringFromFile` (`Setup.ScriptFunc.pas:1861,1867`) / GetIni*
on `{src}\config.ini`. External files create **no** FileLocation entries
and **no** embedded data (`external` flag handling
`Compiler.SetupCompiler.pas:5102,5323,5750-5901`).

### 3. DiskSpanning mechanics

- Directives: `DiskSliceSize` valid 262,144 … 9.2e18 or `max` (:3069-3080;
  default 2,100,000,000 :8311); `SlicesPerDisk` 1-26 (:3341-3346);
  `DiskClusterSize` default 512 (:8312); `ReserveBytes` (:8314).
- Naming: `{basename}-{n}.bin`, or `{basename}-{n}{a..z}.bin` when
  SlicesPerDisk>1 (`Compiler.CompressionHandler.pas:110-122`; runtime
  mirror `Setup.FileExtractor.pas:114-125` — **the runtime prefix is
  derived from the actual setup.exe filename** (`SetupLdrOriginalFilename`),
  so a renamed stub looks for `<newname>-1.bin`).
- Each slice = `DiskSliceID 'idskb32'#26` + `TDiskSliceHeader.TotalSize`
  (`Shared.Struct.pas:43,407-410`). Validation at open: ID match +
  `FSourceF.Size = TotalSize` (`Setup.FileExtractor.pas:163-172`) — only an
  exact-size check per slice; **integrity is per-file SHA-256** verified
  during extraction (`Setup.FileExtractor.pas:361-362`), chunk magic
  `'zlb'#26` checked at seek (:249-252). Missing slice → `SelectDisk`
  prompt dialog.
- With spanning, the exe holds only headers (`Offset1=0`), first slice
  reserves room (`ReserveBytesOnSlice` CompressionHandler:151-159). Chunks
  may span slices; extractor auto-advances (:302-306).

### 4. [Code] surface for progress handoff (H3)

- **External DLL imports (the ISDone pattern):** declaration
  `function F(...): ...; external 'FuncName@files:my.dll stdcall delayload'`.
  ROPS special-proc import hook parses `dll:<name>\0<func>\0`
  (`Setup.ScriptRunner.pas:203-266`); the `files:` prefix is resolved by
  `CodeRunnerOnDllImport` (`Setup.MainFunc.pas:2279-2336`): comma-separated
  list, each `ExtractTemporaryFile`d to `{tmp}` on first import; `setup:`/
  `uninstall:` prefixes gate by context; non-`files:` names go through
  `ExpandConst` (so `{src}\helper.dll` works — key for us since our DLL can
  live next to the exe, not embedded). Caveats: uninstaller never supports
  `files:` (:2307-2311); 64-bit installers can't load 32-bit DLLs
  (whatsnew 7.0).
- **ProgressGauge:** `WizardForm.ProgressGauge: TNewProgressBar`
  (`Setup.WizardForm.pas:139,301`), scriptable (Min/Max/Position/Style
  incl. marquee).
- **Custom pages:** `CreateCustomPage` (`Setup.ScriptFunc.pas:143`),
  `CreateOutputProgressPage` (:243), `CreateOutputMarqueeProgressPage`
  (:257); `TOutputProgressWizardPage.SetProgress` pumps the message loop
  via `ProcessMsgs` (`Setup.WizardForm.CustomPages.pas:852-878`) — the
  primitive that keeps the UI live inside a `[Code]` polling loop.
- **Run external extractor + poll progress file:** `Exec` /
  `ExecAndLogOutput` / `ExecAndCaptureOutput`
  (`Setup.ScriptFunc.pas:1058-1081`); poll with `LoadStringFromFile`
  (:1861-1867) + `SetProgress` in a loop. `ewNoWait` + poll-file is the
  excmp-friendly pattern (launch `excmp extract`, tail its JSON progress
  file, drive ProgressGauge).

### 5. Signing

- `SignTool=` references a named tool (`Compiler.SetupCompiler.pas:
  3306-3318`); command template `$f`/`$p`/`$q` (:6968-7008); executed with
  retries (`SignToolRetryCount` default 2, delay 500 ms, :8346-8347).
- **What gets signed and when:** (a) uninstaller: with
  `SignedUninstaller=yes`, the **Setup.e32 image is signed *before* it is
  compressed and embedded** (`SignSetupMemoryFile` :7959-8026); without a
  SignTool it maintains a cache of `uninst-<ver>-<sha256[:10]>.e32` files
  signed manually (:7990-8025). (b) setup.exe: signed **last**, after all
  assembly (:9173-9177).
- **A presigned stub cannot survive**: the compiler rewrites the stub's
  resources (icons, offset table RCDATA, version info, manifest) and
  appends megabytes after any signature — every compile invalidates it.
  Sign-after-build is mandatory per compile ⇒ **the only way to keep one
  hash is to sign one canonical build once**. Also: do not append
  per-archive bytes to the signed exe "after the fact" — SetupLdr tolerates
  trailing junk (`Size >= TotalSize`, SetupLdr.dpr:449) but Authenticode
  does not; all per-archive bytes must be sidecars, never appended.

### 6. Compression internals

- Codecs: `cmStored/cmZip/cmBzip/cmLZMA/cmLZMA2` (`Shared.Struct.pas:84`);
  compressors drive `islzma.dll/islzma-x64.dll` or out-of-proc
  `islzma32/64.exe` workers (`Compression.LZMACompressor.pas:9,68,799`);
  zlib/bzip decompressor DLLs embedded in Setup-0 only when used
  (`WriteSetup0` :7434-7435).
- `Compression=none` → `cmStored` (:2922-2927); per-file `nocompression`
  flag clears `floChunkCompressed` → `TStoredCompressor` for that chunk
  (`GetCompressorClass` :7594-7622, chunk split :7785-7802); `solidbreak` +
  `SolidCompression=` (:3347-3349). Internal structures always use LZMA1 at
  `InternalCompressLevel` (default `clLZMANormal` :8290).
- **For excmp:** with all payload external, no double compression can occur
  at all (nothing passes through the compressor). If we ever embed
  pre-compressed data as spanning `.bin`s, use per-file `nocompression`
  (stored raw, still gets SHA-256).

### 7. Preflight/robustness (H4)

- **Free disk space:** checked when leaving the dir-select page —
  `GetSpaceOnNearestMountPoint` and a *warning* msgbox (user can continue):
  `Setup.WizardForm.pas:2440-2461` (needed = install size +
  `ExtraDiskSpaceRequired`), components page :2484-2500; plus a live
  "at least X MB required" label.
- **Path validation:** `BadDirChars = '/:*?"<>|'`
  (`Setup.WizardForm.pas:354`); dir-name length (`msgDirNameTooLong`
  :2877,2936), root/UNC rules (`shAllowUNCPath`, `shAllowRootDirectory`,
  `shAllowNetworkDrive`, `Shared.Struct.pas:60-65`). Fully Unicode;
  `shRedirectionGuard` (Setup.PathRedir.pas) protects against filesystem
  redirection attacks.
- **Privileges:** `PrivilegesRequired=lowest` (`prLowest`),
  `PrivilegesRequiredOverridesAllowed=commandline dialog` → `/ALLUSERS` /
  `/CURRENTUSER` or a TaskDialog chooser (`Setup.MainFunc.pas:3064-3120`);
  `RunAsOriginalUser` de-elevation via spawn server
  (`Setup.SpawnServer.pas`).
- **Restart:** `AlwaysRestart`/`RestartIfNeededByRun`, restart-replace via
  pending renames, RestartManager-based CloseApplications.

### 8. SmartScreen-relevant metadata

- `VersionInfo*` directives → `UpdateVersionInfo` patches RT_VERSION in
  place: CompanyName, FileDescription, FileVersion, LegalCopyright,
  ProductName, OriginalFileName, ProductVersion
  (`Compiler.ExeUpdateFunc.pas:622-631`). Defaults derive from
  AppName/AppPublisher/AppCopyright.
- Manifest (baked into the precompiled stub,
  `Projects/Src/SetupLdrAndSetup.XPTheme-x86.manifest`):
  `requestedExecutionLevel level="asInvoker"` (:24) — elevation is dynamic
  at runtime, so `PrivilegesRequired=lowest` gives a no-UAC per-user flow;
  DPI-aware (:30); supportedOS through Win10/11 (:33-41); explicit
  system-DLL `loadFrom` hijack hardening (:42-47) + forced comctl32 pinning
  (ExeUpdateFunc:1079-1113). DEP/ASLR/TSAware + HIGH_ENTROPY_VA (x64) at
  :412-463.
- Nothing else identity-bearing is written — SmartScreen publisher identity
  comes solely from the Authenticode cert on the (once-signed) exe, which
  is exactly what H1 wants.

### 9. Uninstall architecture

- `unins000.exe` = the running Setup image copied as a `ftUninstExe` file
  entry (`Setup.Install.pas:733,1116-1140`), `unins000.dat` = uninstall log
  (`Setup.UninstallLog.pas`). AppId hash appended to names to dodge AV
  heuristics (:492-496). ARP registry key `Uninstall\...\{AppId}_is1`
  (:262-271).
- `Uninstallable` is a **runtime-evaluated boolean expression**
  (`Setup.Install.pas:2749`; skips uninstaller exe :2813, data :2865).
  Uninstall comes for free for an extracted-archive install (removes every
  extracted file recorded in the log, including `external` ones), but for
  a pure "extractor" UX, `Uninstallable=no` + `CreateUninstallRegKey=no`
  removes ~4 MB of unins files + registry noise. Keep it **on** if the
  extraction should look like a first-class install.

### 10. Other genuinely valuable findings

- **DownloadTemporaryFile / CreateDownloadPage**
  (`Setup.ScriptFunc.pas:271,899-949`; WinHTTP impl
  `Setup.DownloadFileFunc.pas:336-563`): download to `{tmp}` with progress
  page, SHA-256 or ISSig verification — ready-made for optional volumes
  (H6): the stub downloads missing `.excmp` volumes on demand.
- **ISSig detached-signature system** (ECDSA/SHA-256): `[ISSigKeys]`
  (`Compiler.SetupCompiler.pas:4890-4960`) embeds only the **public key**
  (constant across archives!); `issigverify` file flag verifies
  `payload.issig` sidecars at install time — including for `external` and
  downloaded files (`Setup.Install.HelperFunc.pas:302`,
  `Setup.DownloadFileFunc.pas:364,468`; standalone `ISSigTool.dpr`,
  `Components/ISSigFunc.pas`). Cryptographic payload integrity **without
  per-archive hashes in the exe** — the missing piece that makes H1 +
  tamper-proofing coexist.
- **`extractarchive` flag + embedded 7-Zip decoders** (`is7z/is7zxa/is7zxr`
  DLLs, :8990-9005; runtime `Compression.SevenZipDLLDecoder.pas`,
  `TExtractionWizardPage`): stock Inno can already extract external .7z
  archives with progress — a useful benchmark/fallback for our extractor
  handoff.
- **Output manifest** (`OutputManifestFile`, `CreateManifestFile`
  :8153-8220): TSV of every stored file with slice/offset/SHA-256 — great
  for CI assertions on spanning layouts.
- **7.0 changes** (whatsnew.htm): 64-bit compiler + 64-bit installers
  (`Setup.e64`/`SetupLdr.e64` — pick x64 stub for HE-ASLR and >4 GB
  dictionaries); 64-bit Pascal scripting; `Encryption=full` (XChaCha20,
  `Shared.Struct.pas:108-114`).
- **Precompiled-file trust chain:** the compiler ECDSA-verifies its own
  stubs/DLLs (`.issig` files in `Files/`, `Components/TrustFunc.pas`) — if
  we ever patch the stub binary ourselves, ISCC will refuse it; keep the
  stub stock and do everything via script/sidecars.

## ADOPT list (ranked)

1. **"Frozen universal script → compile once → sign once → cache canonical
   setup.exe" build pattern** — one constant .iss with `AppName={code:...}`,
   `DisableStartupPrompt=yes`, `PrivilegesRequired=lowest`, all `[Files]`
   `external`, config read from `{src}\excmp.ini` in `[Code]`. The only
   pattern that satisfies H1 with stock Inno. Build the stub once per excmp
   release in CI, hash-pin it, sign it, ship identical bytes with every
   archive; per-archive output = stub + `config.ini` + payload sidecars.
   **Effort S** (script + CI caching).
2. **ISSig detached signatures for payload integrity** — embed our public
   key via `[ISSigKeys]`, mark external payload `issigverify`, emit
   `.issig` sidecars from our packer. Tamper-proof payloads with zero
   per-archive bytes in the exe — H1-safe integrity. **Effort M.**
3. **[Code] progress handoff: `Exec(ewNoWait)` launch of excmp extractor +
   progress-file polling loop driving `WizardForm.ProgressGauge` /
   `CreateOutputProgressPage.SetProgress`** — H3 without any custom DLL
   (skip the ISDone `external 'f@files:dll'` route initially; keep it as
   the upgrade path since `{src}\helper.dll` imports also work via
   `ExpandConst`). **Effort S-M.**
4. **`CreateDownloadPage`/`DownloadTemporaryFileWithISSigVerify` for
   optional volumes (H6)** — stub downloads absent `.excmp` volumes with
   progress + signature check. **Effort S** (script-side only).
5. **Adopt their slice format ideas for our own sidecars** — magic ID +
   TotalSize header per volume, exact-size check at open, per-file SHA-256
   at extraction, `<stubname>-N.bin` naming caveat (rename-sensitivity).
   **Effort S** (spec-level adoption in the .excmp container).
6. **Preflight UX crib:** disk-space warning flow
   (`Setup.WizardForm.pas:2440-2461`), bad-path char set + messages,
   `/ALLUSERS`/`/CURRENTUSER` override plumbing for H4 parity in our GUI.
   **Effort S.**
7. **`Uninstallable=no`, `OutputManifestFile` in dev builds** — small wins;
   the manifest TSV is excellent for CI assertions. **Effort S.**

## Gotchas (threats to H1 especially)

- **The exe is never script-independent.** AppName, [Files] rows, compiled
  [Code] all live inside the exe (WriteSetup0 :7284-7462 → embedded at
  :9120-9121). One character of per-archive script = new hash = SmartScreen
  reputation reset. All per-archive data must go through `{src}` sidecars
  at runtime.
- **Recompile determinism is not guaranteed** even with a frozen script:
  the stub's resource section is rewritten each build via Windows
  `BeginUpdateResource` (runs by default, :8354 + :9077-9084) and its
  output layout is OS-build-dependent; LZMA2 file chunks auto-thread by
  machine topology (`Compression.LZMACompressor.pas:904-935`). Never rely
  on "same script ⇒ same bytes across machines"; rely on the cached
  canonical build. (Internal LZMA1 blocks and version-info patching are
  in-place/deterministic, so same-machine rebuilds will *usually* match —
  treat that as luck, not contract.)
- **Signing forces the same conclusion:** every compile invalidates any
  signature; Inno's own flow signs after build (:9173-9177). Sign exactly
  one canonical stub. Never append per-archive bytes to the signed exe —
  SetupLdr tolerates trailing junk but Authenticode does not.
- **`Password=`/`Encryption=` inject fresh CSPRNG salt+nonce every
  compile** (:8643-8650) — never enable them in the universal stub;
  excmp-level encryption must live in our payload format.
- **Slice/sidecar naming follows the exe's runtime filename**
  (`Setup.FileExtractor.pas:119`): users renaming `setup.exe` breaks
  `-1.bin` lookup. Our config/payload lookup in `[Code]` should use fixed
  names independent of the exe name to avoid the same trap.
- **Compiler trust checks** (`.issig` on stubs, `TrustFunc.pas`): any
  binary-patching of the stub makes ISCC abort — branding must come via
  compile-time directives inside the frozen script (constant across
  archives, so fine).
- **Icon/branding directives are compile-time only** — per-archive icons or
  wizard images are impossible under H1. Ship one excmp brand identity.
- **License condition 2** requires keeping Inno's internal copyright
  notices when redistributing the compiler — download/ship official
  untouched binaries.
- **`external` + `DiskSpanning=no` leaves zero payload in the exe**, but
  nothing in stock Inno verifies payload presence at startup — add an
  explicit `[Code]` `InitializeSetup` existence/ISSig check with a friendly
  abort message (H4).
- 32-bit vs 64-bit stubs are distinct files with distinct hashes; pick one
  (x64 recommended: HE-ASLR, big dictionaries) and freeze it, or maintain
  two canonical signed stubs.

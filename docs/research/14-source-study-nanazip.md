# 14 — Source study: NanaZip (line-by-line)

> Part of the 2026-07-31 source-code study series (docs 13-21). Method: full
> clone read by a dedicated study agent; every claim carries a file:line
> reference into the studied commit. NanaZip is MIT, but reuse is conceptual
> (our codebase is Python). Studied commit:
> `4f5d4471cb974c008313709ddb94ab3b0e426a7f` (2026-07-27) from
> https://github.com/M2Team/NanaZip. Path prefix `<nz>` = the clone root.

## Architecture

NanaZip is a **fork-plus-platform-layer** design. Forked 7-Zip trees are kept
as vendored `SevenZip/` subtrees inside each product, and every local change
is fenced with `// **************** NanaZip Modification Start/End ****`
comments so upstream syncs are diffable. NanaZip-original code lives in
separate top-level projects:

- **Forked 7-Zip core**: `<nz>\NanaZip.Core\SevenZip\{ASM,C,CPP}` (mainline
  26.02) + `<nz>\NanaZip.Core\Extensions\ZSCodecs` (7-Zip ZS codec ports) +
  `<nz>\NanaZip.Core\Wrappers` (CNG SHA wrappers). `<nz>\NanaZip.Universal\
  SevenZip` is the new unified console/GUI (also 26.02).
  `<nz>\NanaZip.UI.Classic\SevenZip` and `<nz>\NanaZip.UI.Modern\SevenZip`
  are older 22.01-based UI forks kept alive with security backports.
- **NanaZip-original**: `<nz>\NanaZip.UI.Modern\NanaZip.ShellExtension.cpp`
  (IExplorerCommand), `<nz>\NanaZip.Modern\` (XAML pages hosted via XAML
  islands), `<nz>\NanaZip.Codecs\` (plugin DLL bundling
  RHash/xxHash/BLAKE3/GmSSL/Zstandard/Brotli/FastLZMA2/Lizard/LZ4/LZ5/ZSTDMT
  + original read-only archivers), `<nz>\K7Base\` (non-GUI platform layer:
  mitigations, policies, CNG hashing, Detours), `<nz>\K7User\` (Win32
  dark-mode layer), `<nz>\NanaZipPackage\` (MSIX).
- **Mile.\*** libraries are **NuGet packages, not vendored** —
  `<nz>\Directory.Build.props:6` imports the `Mile.Project.Configurations`
  MSBuild SDK, which is where the CFG/CET linker flags actually live.

## Answers

### 1. Repo layout and upstream tracking

Mapping is documented in `<nz>\Documents\UpstreamSynchronization.md`:

- 7-Zip mainline: `NanaZip.Core` = **26.02**, `NanaZip.Universal` =
  **26.02**, `NanaZip.UI.Classic`/`UI.Modern` = **22.01** with explicit
  backports (lines 6-15): CVE-2025-0411 fix from 24.09,
  CVE-2025-11001/11002 from 25.00, symlink hardening from 25.01,
  extract-callback fix from 26.02.
- 7-Zip ZS: commit `ecaa91dda…` = v26.02-v1.5.7-R1 (lines 20-25).
- Library versions (lines 27-77): BLAKE3 1.8.5, Brotli 1.2.0, FastLZMA2
  @a793db9, FreeBSD 14.2 (UFS reader), GmSSL 3.2.0, LittleFS 2.10.2 (not
  integrated), Lizard 2.1, LZ4 1.10.0, LZ5 1.5, RHash post-1.4.6 @3dbba4b,
  xxHash 0.8.3, Zstandard 1.5.7.
- `Documents\Versioning.md` and `ReleaseNotes.md` track channel/versioning;
  every in-tree divergence is comment-fenced (e.g.
  `NanaZip.Core\SevenZip\CPP\7zip\Common\CreateCoder.cpp:13-20,41-48`).

### 2. THE MAIN PRIZE — IExplorerCommand cascaded menu

All in **`<nz>\NanaZip.UI.Modern\NanaZip.ShellExtension.cpp`** (single
~1180-line file, C++/WinRT, MIT):

- **Leaf command** `ExplorerCommandBase : winrt::implements<…,
  IExplorerCommand>` (lines 211-570). Holds title + command-ID enum
  (176-206). `GetTitle` returns `S_FALSE`/null for separators (241-254);
  `GetState` always `ECS_ENABLED` (282-291); `GetFlags` returns
  `ECF_ISSEPARATOR` or `ECF_DEFAULT` (552-560); `EnumSubCommands` →
  `E_NOTIMPL` (562-567).
- **Root command** `ExplorerCommandRoot : winrt::implements<…,
  IExplorerCommand, IEnumExplorerCommand>` (573-1064) — the root object
  **is its own enumerator**. `GetFlags` → `ECF_HASSUBCOMMANDS` (991-996);
  `EnumSubCommands` resets an iterator and returns
  `this->QueryInterface(IID_PPV_ARGS(ppEnum))` (998-1011);
  `IEnumExplorerCommand::Next/Reset` walk a
  `std::vector<winrt::com_ptr<IExplorerCommand>>` (1017-1054), `Skip`/`Clone`
  → `E_NOTIMPL`.
- **Lazy population**: `Initialize(psiItemArray)` is called from the root's
  `GetTitle` (929-942). It extracts filesystem paths via
  `IShellItemArray::GetItemAt` → `IShellItem::GetDisplayName(
  SIGDN_FILESYSPATH)` (597-621), decides "needs extract" by an
  extension-exclusion list `kExtractExcludeExtensions` (37-94), computes
  archive names and the `Extract to "<name>\"` subfolder
  (`GetSubFolderNameForExtract` handles `.7z.001`/`.part1.rar` naming,
  118-140), loads user prefs `CContextMenuInfo::Load()` (707-711), then
  pushes Open/Test/Extract/ExtractHere/ExtractHereSmart/ExtractTo/
  Compress×3/Email×3/hash subcommands gated on `NContextMenuFlags` bits
  (715-914). Empty command list ⇒ `GetTitle` returns `E_NOTIMPL`, hiding the
  whole entry (935-939).
- **Invoke = spawn the GUI exe, no work in-process**: `GetNanaZipPath()` =
  module dir + `NanaZip.Modern.FileManager.exe` (168-171); Open runs
  `MyCreateProcess(path, quotedFile)` (432-436); Extract/Compress/Hash call
  `ExtractArchives/CompressFiles/CalcChecksum` which just build a command
  line — see `<nz>\NanaZip.UI.Modern\SevenZip\CPP\7zip\UI\Common\
  CompressCall.cpp:374-400`: `x -o"…" -spe -sps -sre -snz<N>` then
  `ExtractGroupCommand` launches the exe.
- **COM plumbing**: `ClassFactory` with
  `DECLSPEC_UUID("469D94E9-6AF4-4395-B396-99B1308F8CE5")` (1066-1104);
  classic `DllGetClassObject`/`DllCanUnloadNow` exports using
  `winrt::get_module_lock` (1107-1147).

**Registration — `<nz>\NanaZipPackage\Package.appxmanifest`** (the XML a
future excmp sparse MSIX would mimic):

```xml
<!-- namespaces (lines 7-13) -->
xmlns:desktop4="http://schemas.microsoft.com/appx/manifest/desktop/windows10/4"
xmlns:desktop5="http://schemas.microsoft.com/appx/manifest/desktop/windows10/5"
xmlns:desktop10="http://schemas.microsoft.com/appx/manifest/desktop/windows10/10"
xmlns:com="http://schemas.microsoft.com/appx/manifest/com/windows10"

<!-- lines 161-177: verb registration for files, directories, drives -->
<desktop4:Extension Category="windows.fileExplorerContextMenus">
  <desktop4:FileExplorerContextMenus>
    <!-- Use a low name prefix to work around our shell menu not appearing
         in the classic context menu. (MediaArea/MediaInfo#998) -->
    <desktop4:ItemType Type="*">
      <desktop4:Verb Id="0000NanaZipShellExtension" Clsid="469D94E9-6AF4-4395-B396-99B1308F8CE5" />
    </desktop4:ItemType>
    <desktop5:ItemType Type="Directory">
      <desktop5:Verb Id="0000NanaZipShellExtension" Clsid="469D94E9-6AF4-4395-B396-99B1308F8CE5" />
    </desktop5:ItemType>
    <desktop10:ItemType Type="Drive">
      <desktop10:Verb Id="0000NanaZipShellExtension" Clsid="469D94E9-6AF4-4395-B396-99B1308F8CE5" />
    </desktop10:ItemType>
  </desktop4:FileExplorerContextMenus>
</desktop4:Extension>

<!-- lines 178-184: in-proc DLL hosted in COM surrogate (dllhost) -->
<com:Extension Category="windows.comServer">
  <com:ComServer>
    <com:SurrogateServer DisplayName="NanaZip Shell Extension">
      <com:Class Id="469D94E9-6AF4-4395-B396-99B1308F8CE5"
                 Path="NanaZip.ShellExtension.dll" ThreadingModel="STA"/>
    </com:SurrogateServer>
  </com:ComServer>
</com:Extension>
```

Identity/signing requirements: `<Identity
Name="40174MouriNaruto.NanaZipPreview" Publisher="CN=E310A153-…" />`
(21-24), `<rescap:Capability Name="runFullTrust"/>` (236-238),
`<uap10:PackageIntegrity>` enforcement (30-32),
`EntryPoint="Windows.FullTrustApplication"` (58-61). The context menu only
exists because the package has **identity + a cert whose subject matches
Publisher** — exactly why excmp's plan (HKCU verbs now, signed sparse MSIX
after SignPath) is right. Note NanaZip uses `com:SurrogateServer` (DLL in
dllhost.exe), not `com.exe` — no local-server exe registration anywhere.

### 3. Security mitigations beyond upstream 7-Zip

Runtime mitigations are **`SetProcessMitigationPolicy` calls in
`<nz>\K7Base\K7BaseMitigations.cpp`**, orchestrated by
`K7BaseInitialize.cpp:13-45` (policies → DLL blocker → mandatory
mitigations):

- Strict handle checks + image-load policy (`NoRemoteImages`,
  `NoLowMandatoryLabelImages`): `K7BaseEnableMandatoryMitigations`, lines
  36-95 (get-then-set to avoid downgrading).
- Dynamic code prohibition (`ProhibitDynamicCode=1, AllowThreadOptOut=1`,
  Release builds only, HKLM-policy-gated): lines 97-131; per-thread opt-out
  helper 165-188.
- Child-process creation ban: lines 133-163. Call sites show the policy
  split: console `MainAr.cpp:119-131` and SFX `SfxWin.cpp:258-265` apply
  **both** dyn-code + child-process; GUI `FM.cpp:737-739` and installer-mode
  `SfxSetup.cpp:143-145` apply **only** dyn-code (they must spawn children).
- A Detours-based loader firewall (lines 190-847): hooks
  `NtMapViewOfSection`/`NtUnmapViewOfSection`/`VirtualAlloc(Ex)`/
  `VirtualProtect(Ex)`, blocklists known injectors (ExplorerPatcher,
  TranslucentFlyouts, Proxifier — unmapped with `STATUS_ACCESS_DENIED`,
  598-602) and grants scoped dynamic-code opt-outs to IME DLLs.
- Escape hatches are admin policies in
  `HKLM\Software\Policies\M2Team\NanaZip` (`AllowDynamicCodeGeneration`,
  `AllowChildProcessCreation` — `Documents\Policies.md:17-43`, read in
  `K7BasePolicies.cpp`).
- Link-time CFG / CETCOMPAT / EHCONT / signed-returns are **not in the repo**
  — they come from the `Mile.Project.Configurations` MSBuild SDK imported at
  `Directory.Build.props:6`; the feature list is asserted in
  `ReadMe.md:121-135`.

**What a Python/PyInstaller excmp can realistically mirror**: (a) the big one
— apply `PROC_THREAD_ATTRIBUTE_MITIGATION_POLICY` +
`PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY` to the **7z.exe child** at
CreateProcess time (7z.exe needs no children and no dynamic code), plus a Job
object; (b) `SetProcessMitigationPolicy(ProcessImageLoadPolicy{
NoRemoteImages,NoLowMandatoryLabelImages})` and strict handle checks on our
own process via ctypes; (c) `SetDefaultDllDirectories(
LOAD_LIBRARY_SEARCH_SYSTEM32|…)` early. **Do not** enable ProhibitDynamicCode
on the Python process (ctypes/libffi trampolines break) or
MicrosoftSignedOnly binary policy (kills PySide6/our own pyd files).

### 4. Added codecs and how they plug in

Two distinct mechanisms:

- **Compression codecs (Brotli, Zstd, Lizard, LZ4, LZ5, Fast-LZMA2)** are
  statically registered inside the core the same way stock codecs are:
  `<nz>\NanaZip.Core\Extensions\ZSCodecs\*Register.cpp` use
  `REGISTER_CODEC_E` (e.g. `ZstdRegister.cpp:13-17`, method ID
  `0x4F71101 "ZSTD"` — the 7-Zip ZS ID convention); registration lands in
  the global `g_Codecs` table via `RegisterCodec()` in
  `NanaZip.Core\SevenZip\CPP\7zip\Common\CreateCoder.cpp:39-51` (table
  enlarged to 256 slots, lines 18-19, 54-55, and gated on the
  `K7BaseGetAllowedCodecPolicy` admin policy, 41-48). Handlers
  (`BrotliHandler.cpp`, `ZstdHandler.cpp`, `LzHandler.cpp`…) register the
  single-stream archive formats.
- **NanaZip.Codecs.dll is a standard 7-Zip external plugin**: exports
  `CreateObject`, `GetNumberOfFormats`, `GetHandlerProperty2`, `GetHashers`
  (`NanaZip.Codecs.def:1-9`) and is force-loaded by name in
  `LoadCodecs.cpp:933-942`. It carries 38 hashers (table
  `NanaZip.Codecs.cpp:29-69`: RHash family, xxHash, BLAKE3, SM3 via GmSSL,
  CNG-backed MD/SHA) and read-only archivers (UFS, .NET single-file, asar,
  ROMFS, ZealFS, WASM, littlefs — table from line 90). It **also** exports
  the raw C APIs (`ZSTD_*`, `FL2_*`, `BROTLIMT_*`, `LZ4MT_*`… def:25-81)
  that the statically-registered core codecs call — so libraries ship once.
- Archive handler allow/block policy filter at `LoadCodecs.cpp:905-910`
  (`K7BaseGetAllowedHandlerPolicy`).
- For excmp (subprocess-driven): conceptual only. Equivalent lever = pin
  7z.exe build (ZS vs mainline) and constrain formats with an allowlist of
  `-t` types, mirroring `AllowedHandlers`.

### 5. Mark-of-the-Web

Yes — and **stronger than upstream**:

- **Read**: on opening each archive, `Extract.cpp:525-531`
  (`NanaZip.Core\SevenZip\CPP\7zip\UI\Common\`) calls
  `ReadZoneFile_Of_BaseFile(arcPath)` if `ZoneMode != kNone && !StdInMode`.
  That reads the archive's own `:Zone.Identifier` ADS, only if
  `0 < size < 32768` (`ArchiveExtractCallback.cpp:173-191`). **No source
  MOTW ⇒ nothing propagated.**
- **Write**: `CArchiveExtractCallback::CloseFile()` writes the buffer to
  `<outfile>:Zone.Identifier` *before* setting timestamps, skipping
  alt-stream items; failure (FAT/exFAT — no ADS) is deliberately swallowed
  (`ArchiveExtractCallback.cpp:1970-1986`). Directories never get it (only
  file close path). GUI in-panel open/drag paths also write it
  (`FileManager\ExtractCallback.cpp:1256`).
- **Modes**: `NZoneIdMode {kNone,kAll,kOffice}` — NanaZip modification sets
  `Default = kAll` (`ExtractMode.h:32-44`), vs upstream default none
  (`Extract.h:56-57`). `kOffice` filters by `kOfficeExtensions`, which
  NanaZip extended with executables (`bat cmd com exe hta js … ps1 scr vbs
  wsf`) and nested archives (`7z iso rar tar vhd vhdx zip`) with the comment
  "only kAll fully works on nested archives!"
  (`ArchiveExtractCallback.cpp:117-130`).
- **CVE-2025-0411-class bypass defenses**: (a) archive-*embedded*
  `Zone.Identifier` alt-stream entries are skipped when propagation is
  active, so a malicious archive can't overwrite the propagated zone with a
  benign one (`ArchiveExtractCallback.cpp:1695-1704`, `Is_ZoneId_StreamName`
  166-171); (b) NanaZip deleted upstream's `":$DATA"` suffix normalization
  in `Correct_AltStream_Name` because `Zone.Identifier:$DATA` could dodge
  check (a) (`ExtractingFilePath.cpp:99-109`).
- **Config plumbing**: HKLM policy `WriteZoneIdExtract` (0/1/2,
  `Policies.md:117-126`) → `K7BaseGetWriteZoneIdExtractPolicy()`
  (`K7BasePolicies.cpp:245-248`) → `CContextMenuInfo::Load` prefers policy
  over user setting (`ZipRegistry.cpp:586-611`) → passed as `-snz<N>` on the
  spawned command line (`CompressCall.cpp:392-396`).
- Python note: reading/writing `path + ":Zone.Identifier"` with plain
  `open()` works on NTFS — excmp can replicate this whole feature in ~40
  lines.

### 6. Extraction path-safety checklist (for our D0 sanitizer matrix)

Sanitization core: `<nz>\NanaZip.Core\SevenZip\CPP\7zip\UI\Common\
ExtractingFilePath.cpp`, applied per item in
`CArchiveExtractCallback::CorrectPathParts`
(`ArchiveExtractCallback.cpp:1029-1067`, `Correct_FsPath` call at 1038 with
`absIsAllowed = (_pathMode == kAbsPaths)`):

1. **`.` and `..` components deleted outright** — `Correct_PathPart`
   (169-181) empties them, `Correct_FsPath` removes empty parts (253-278).
   Traversal is *removed*, not rejected.
2. **Illegal chars → `_`**: `: * ? < > | "`, all chars `< 0x20`, and `/`; a
   backslash inside a name becomes the WSL replacement char
   (`ReplaceIncorrectChars`, 23-51).
3. **Trailing dots and spaces → `_`** on every component (loop 70-88;
   `g_PathTrailReplaceMode = true` on Win32, lines 11-19).
4. **Reserved device names** `CON PRN AUX NUL` and `COM0-9 LPT0-9` — matched
   case-insensitively *including* `NUL.txt` / `COM1 .x` style variants — get
   a `_` prefix (`IsSupportedName`/`CorrectUnsupportedName`, 124-165).
5. **Empty component / empty result → `_`** (183-198, 259-290).
6. **Alt-stream (ADS) names**: `: \ /` and **RLO U+202E** → `_`, empty → `_`
   (`Correct_AltStream_Name`, 96-120); the `":$DATA"` exemption is removed
   (NanaZip hardening, 99-109); colon in filename becomes literal `_` unless
   the user enabled real ADS extraction (`CorrectPathParts` 1060-1063,
   `ReplaceColonForAltStream`).
7. **Absolute/drive paths**: only honored in explicit `kAbsPaths` mode, where
   `c:name` → `c:\name` and `\\?\C:\` prefixes are parsed (`Correct_FsPath`
   201-248); in default modes the drive colon is neutralized by rule 2 (so
   `C:\evil` becomes `C_\evil` under the output dir).
8. **Prefix-strip integrity**: if the expected removable path prefix doesn't
   match, extraction of that item hard-fails with `E_FAIL`
   (`ArchiveExtractCallback.cpp:1741-1818`).
9. **Symlinks/hardlinks** (backport of 7-Zip 25.01 hardening): links are
   created **after** file extraction (post-link queue); `SetLink2`
   (`ArchiveExtractCallback.cpp:2149-2341`) rejects absolute targets, `..`
   appearing after a non-`..` component, and net-negative traversal depth
   using `CLinkLevelsInfo::Parse` (649-690) + `IsSafePath` (693-706:
   relative ∧ never below root ∧ final level > 0); "link via another link"
   is re-checked against the real filesystem (`CheckLinkPath_in_FS`,
   2222-2225); reparse data is round-trip validated (2322-2327). Tunable
   `SymLinks_DangerousLevel` (2162).
10. **Known gap**: RLO U+202E in *normal* path components is deliberately
    left unsanitized (commented out at `ExtractingFilePath.cpp:33,47`) —
    excmp's sanitizer can beat this.

**D0 test rows to copy**: `../../x`, `..\..\x`, `C:\abs`, `C:rel`,
`\\server\share`, `\\?\C:\x`, `a:b` (ADS), `Zone.Identifier` ADS entry,
`x:Zone.Identifier:$DATA`, `CON`, `NUL.txt`, `COM1 .log`, `LPT9`, `name.`,
`name `, `a<b>c|d"e*f?g`, ctrl chars, U+202E, empty parts `a//b`,
symlink→abs, symlink→`../..`, symlink chain, hardlink outside root, 32 KB+
Zone buffer.

### 7. Win11 UI modernization (conceptual)

Three-layer approach: (a) **Win32 dark mode by brute force** —
`K7User\K7UserDarkMode.cpp` subclasses/owner-draws common controls with fixed
dark brushes (43-79), hooks `OpenNcThemeData`/uxtheme, sets dark titlebars
via DWM, and disables Mica when any display is HDR
(`IsStandardDynamicRangeMode`, 81-130) because Mica+HDR looks wrong;
(b) **Mica/backdrop via DWM window attributes** wrapped by Mile.Helpers —
`NanaZip.Modern\NanaZip.Modern.cpp:237-249`
(`MileGetWindowSystemBackdropTypeAttribute`, caption-color attribute);
(c) **XAML islands** — `DesktopWindowXamlSource` per dialog window, cached as
a window prop (`NanaZip.Modern.cpp:157-160, 357-364`).

Feasible inspiration for PySide6 (skip XAML islands entirely): ctypes →
`DwmSetWindowAttribute` with `DWMWA_USE_IMMERSIVE_DARK_MODE (20)` for the
dark titlebar and `DWMWA_SYSTEMBACKDROP_TYPE (38)` = 2 (Mica) / 4 (Mica Alt)
on the top-level `winId()`, plus a matching QSS dark palette; copy their
HDR-detection guard idea; keep backdrop off the content area (Qt paints
opaque) and use it for frame/titlebar ambience only.

### 8. Other genuinely valuable finds

- **CNG hash rerouting**: 7-Zip's C `Sha1/Sha256/Sha512` APIs are
  re-implemented as thin wrappers (`NanaZip.Core\Wrappers\Sha256Wrapper.cpp`)
  over BCrypt (`K7Base\K7BaseHash.cpp:110-264`) — OS-maintained,
  HW-accelerated, FIPS-aligned. Python analog: `hashlib` already does this;
  don't hand-roll.
- **Admin policy layer + ADMX**: `HKLM\Software\Policies\M2Team\NanaZip`
  with `AllowedHandlers/BlockedHandlers/AllowedCodecs/BlockedCodecs/
  WriteZoneIdExtract` (`Documents\Policies.md`,
  `Documents\PolicyDefinitions\`), enforced at codec/handler registration —
  attack-surface reduction by format allowlisting, and a Group-Policy story
  enterprises actually want.
- **CVE bookkeeping**: backports explicitly logged per-flavor in
  `UpstreamSynchronization.md:6-15` — cheap, high-trust practice.
- **UX niceties**: Smart Extraction (`-sps`) and "open folder after
  extraction" (`-sre`) as custom CLI switches (`CompressCall.cpp:386-391`);
  extract-menu suppression for obviously-non-archive extensions
  (`kExtractExcludeExtensions`, 37-94); multi-part-aware default folder
  naming (`GetSubFolderNameForExtract`, 118-140); execution aliases
  `7z.exe/7zFM.exe/7zG.exe` with `uap8:AllowOverride`
  (`Package.appxmanifest:81-90, 199-233`); `uap16/17:UpdateWhileInUse defer`
  (40-41).
- **Found a real fork-drift bug** (unfixed upstream-merge artifact):
  `NanaZip.Universal\SevenZip\CPP\7zip\UI\Common\ZipRegistry.cpp:688` — a
  stray `WriteZone = (UInt32)(Int32)-1;` immediately clobbers the policy
  value fetched at line 682, defeating the HKLM `WriteZoneIdExtract` policy
  in the Universal flavor's context-menu info (the UI.Modern copy at
  `ZipRegistry.cpp:586-611` is correct). Object lesson in why excmp's
  no-fork/subprocess strategy is right.

## ADOPT list (ranked)

1. **Thin-launcher IExplorerCommand pattern** — shell DLL that only
   enumerates commands and spawns the GUI exe with CLI args (never extracts
   in-process). Crash/hang isolation from Explorer, tiny auditable DLL.
   *How:* define excmp's CLI contract now (`x -o<dir>` + smart-extract +
   MOTW flags analog); later a ~1-file C++ COM DLL modeled on
   `NanaZip.ShellExtension.cpp`. **Effort M** (S now for the CLI contract).
2. **AppxManifest fragments for the sparse MSIX** — desktop4/desktop5/
   desktop10 `FileExplorerContextMenus` verbs + `com:SurrogateServer` class +
   `runFullTrust`, with the `0000` verb-Id prefix trick. This is the only
   supported Win11 top-level cascade path; NanaZip's XML is a working
   template. **Effort S** (once signing exists).
3. **MOTW propagation** — read source archive's `Zone.Identifier` ADS, write
   to every extracted file, skip archive-embedded `Zone.Identifier` entries
   and `:$DATA` variants, default = all files. It's the current CVE
   battleground and a differentiator vs plain 7z.exe driving. Pure-Python
   ADS via `open(path+":Zone.Identifier")`; cap read at 32 KB; ignore write
   failures on non-NTFS. **Effort S.**
4. **D0 sanitizer test matrix from their checklist** — the 10-rule list +
   the RLO gap in answer 6 as parametrized pytest cases. It is the
   distilled, battle-tested Windows hostile-name corpus. **Effort S** for
   tests, **M** for sanitizer parity.
5. **Child-process + dynamic-code mitigations on the 7z.exe subprocess** —
   `STARTUPINFOEX` + `PROC_THREAD_ATTRIBUTE_MITIGATION_POLICY` (prohibit
   dynamic code, block non-system DLLs) and
   `PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY`; Job object with
   kill-on-close. NanaZip proves an archiver child needs neither children
   nor JIT; big cheap win a Python host *can* deliver. **Effort M.**
6. **Self-process hardening subset** — `SetProcessMitigationPolicy(
   ImageLoadPolicy{NoRemoteImages,NoLowMandatoryLabelImages})`, strict handle
   checks, `SetDefaultDllDirectories` at startup via ctypes. Free,
   PyInstaller-compatible (unlike ProhibitDynamicCode). **Effort S.**
7. **Policy/registry override layer** — HKLM policy keys that override user
   settings (format allowlist for `-t`, MOTW mode, escape hatches),
   documented like `Policies.md`. **Effort S-M.**
8. **Context-menu UX heuristics** — extension-exclusion list before showing
   Extract items; smart-extract (only make a subfolder when archive root is
   not a single folder); multi-part-aware folder naming; "open folder after
   extraction". **Effort S.**
9. **Dark titlebar + Mica via DWM attributes** for the PySide6 window (with
   their HDR guard). **Effort S.**
10. **Upstream-sync hygiene** — an `UPSTREAM.md` recording exact 7z.exe
    version/CVEs covered, and comment-fencing any vendored snippets.
    **Effort S.**

## Gotchas

- **desktop4 verbs require package identity + matching cert**; there is no
  unsigned path. Until SignPath lands, Win10 HKCU classic verbs are the only
  option — and even on Win11, the desktop4 verb also feeds the *classic*
  (Shift+F10) menu, which is what the `0000` Id-prefix hack is about
  (`Package.appxmanifest:163-166`). Drive verbs (`desktop10`) only surface
  on Win11 22H2+ (`ReadMe.md:326-329`); Explorer must be restarted after
  (un)install (`ReadMe.md:325-327`).
- **The shell DLL runs in Explorer's/dllhost's STA** and `GetTitle` is called
  before `EnumSubCommands` — hence NanaZip's lazy `Initialize()` on first
  `GetTitle` and "return `E_NOTIMPL` title to hide the entry". Anything slow
  there janks Explorer; NanaZip reads registry + one `CFileInfo::Find` max.
- **Don't mirror the wrong mitigations in Python**: `ProhibitDynamicCode`
  breaks ctypes/libffi (and PySide6's shiboken), `MicrosoftSignedOnly`
  blocks your own unsigned pyds, `NoChildProcessCreation` on yourself blocks
  7z.exe. NanaZip itself splits exactly this way (GUI keeps child-spawning;
  only CLI/SFX self-restrict — `FM.cpp:737` vs `MainAr.cpp:119-131`).
- **MOTW quirks**: propagation only happens when the *source archive* is
  marked; ADS writes silently no-op on FAT/exFAT; directories aren't marked;
  `kOffice` mode explicitly doesn't cover nested archives. Reject/ignore
  embedded `Zone.Identifier` ADS entries or you reopen CVE-2025-0411.
- **RLO (U+202E) is unsanitized in ordinary path components** in both 7-Zip
  and NanaZip (`ExtractingFilePath.cpp:33` commented out) — excmp's
  sanitizer should handle it and can honestly claim to exceed 7-Zip here.
- **`kAbsPaths` mode exists and deliberately allows absolute-path
  extraction** (`Correct_FsPath` absIsAllowed branch) — never expose an
  equivalent in excmp defaults.
- **CFG/CET flags are invisible in-repo** (they live in the
  `Mile.Project.Configurations` NuGet SDK, `Directory.Build.props:6`); if
  excmp ever ships a C++ shim DLL, set `/guard:cf /CETCOMPAT /guard:ehcont`
  explicitly — don't assume a template does it.
- **Fork drift is real**: the `ZipRegistry.cpp:688` policy-clobber bug in
  NanaZip.Universal crept in during an upstream merge despite their fencing
  discipline. Reinforces excmp's subprocess-not-fork architecture.
- **Licensing**: NanaZip is MIT but bundles BSD/Apache third-party code —
  for excmp everything stays conceptual reuse anyway (Python codebase, no
  copying), which also keeps the OSI-clean requirement trivially satisfied.

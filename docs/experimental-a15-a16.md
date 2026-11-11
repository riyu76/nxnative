# Experimental A15/A16 Vulkan compatibility

**Hardware validation pending.** This fork targets **Super Mario Galaxy 1,
`010099C022B96000`**, first. No Galaxy gameplay, rendering, memory-pressure or
performance result on A15/A16 has been measured for this implementation.
Passing compilation or synthetic tests does not establish device compatibility.
The existing supported A17 Pro and later / M-series path still uses native BC.

## Build and opt in

On the Mac, follow the repository's normal Xcode and tool prerequisites. Use
your own lawfully obtained game dump and keys, outside this repository. Create
`experimental.env` beside your game files:

```text
DM_GPU_COMPAT=1
DM_GPU_COMPAT_MB=256
```

```sh
python3 scripts/build_ipa_from_nsp.py /path/to/Galaxy1 -k /path/to/prod.keys --env-file /path/to/experimental.env --romfs separate
```

The normal script still extracts and rewrites the game and captures Galaxy's
runtime shaders on a Mac. `--romfs separate` leaves the RomFS outside the IPA;
the real game's rewritten code and translated shaders are still needed for a
playable local build. Do not upload that build to public CI or this repository.
Sideload and sign locally with your usual tool; this workflow does not sign or
install anything on a device. A Personal Team may not grant the increased
memory entitlement. An unsigned IPA alone does not establish installability
with a particular signing account or tool.

The same two variables can be placed in the app's `Documents/env.txt` before
starting a locally built game. Restart the app after changing them. The API is
stamped as `DMGraphicsAPI` in the IPA; the iOS front end admits only Vulkan when
native BC is absent. NVN and GL remain outside this experiment.

Detection uses `MTLDevice.supportsBCTextureCompression` and GPU families for
ASTC and the Apple7 feature floor, rather than an iPhone model-name list.
Opt-in does not replace native BC on A17+ or Macs. On a Mac only,
`DM_GPU_COMPAT=1 DM_GPU_COMPAT_FORCE=1` exercises the decoded Vulkan path for
synthetic testing and image comparisons. Do not infer A15 results from it.

## Runtime fallback and memory

Vulkan sampled 2D BC textures (including mip chains, arrays and cubes) can
use CPU decoding when the GPU lacks BC:

| Guest BC format | Metal storage | Semantics |
|---|---|---|
| BC1 RGB / RGBA, BC2, BC3, BC7 | RGBA8, linear or sRGB | BC1 RGB is opaque; BC1 RGBA retains punch-through alpha; sRGB changes the view, not the encoded channel values |
| BC4 / BC5 UNORM or SNORM | R8 / RG8, normalized or signed normalized | Signed endpoints and channel count preserved |
| BC6H unsigned / signed float | RGBA16Float | HDR values preserved, alpha one |

The guest's block sizes, offsets and memory requirements stay compressed.
Only the host texture expands. Uploads honor offsets, padded rows, image
strides, partial edge blocks, mips and layers. The decoder checks lengths and
arithmetic before writing. A conservative command-buffer commit/wait makes
preceding GPU writes visible before CPU decoding; staging lives until its GPU
copy completes. This can introduce stalls and needs device measurement.

The BC feature flag is not advertised as complete on a non-BC GPU. Format
queries expose the implemented sampled/upload subset. Linear BC images,
storage/attachment BC usage, compressed readback and cross-format image copies
are unsupported: creation returns `VK_ERROR_FORMAT_NOT_SUPPORTED`; an invalid
recorded operation fails with a diagnostic instead of copying decoded bytes
using compressed strides. GPU-generated BC blocks in a transfer buffer can be
decoded after synchronization; encoding through NVN uncompressed aliases is
not implemented. Whether Galaxy requests any excluded operation is **open**.

`DM_GPU_COMPAT_MB` limits expanded BC texture allocations (default 256 MiB,
range 16–2048). Allocation failure returns `VK_ERROR_OUT_OF_DEVICE_MEMORY`.
Views, descriptors and GPU commands can retain storage after image destruction;
the charge remains until the root Metal texture is released. The cap covers
these decoded textures, not the entire process. At the first three frames and
every 300 frames, `Documents/log.txt` reports expanded live/peak bytes, budget,
source upload bytes, upload count/time, Metal allocation, process footprint
and available process memory (zero means unknown). In-flight conversion staging
is capped at 8 MiB plus one block row. These limits reduce risk but do not
guarantee avoidance of iOS memory termination.

## Offline BC-to-ASTC, when the container permits it

[Issue #570](https://github.com/seedds/nxnative/issues/570) motivates converting
16-byte BC blocks to ASTC 4x4 offline. This implementation deliberately converts
only explicitly identified, little-endian, non-array **KTX1 2D BC2/3/7** assets.
It updates the container's format metadata, retains mip sizes and offsets and
writes a new file. A game must read the KTX format metadata and support ASTC;
an engine that hardcodes BC needs its own verified container adapter. There is
no global BC-to-ASTC runtime format remap and no modification of unknown archives.

Install [Arm's official astcenc release](https://github.com/ARM-software/astc-encoder/releases/tag/5.7.1)
and put its `bin/astcenc` executable on `PATH`. CI downloads the macOS universal
5.7.1 archive and checks its published SHA-256 before extraction.

```sh
python3 scripts/transcode_bc_astc.py /path/to/source.ktx /path/to/astc-copy.ktx --cache /path/to/private-astc-cache
```

The build-time tool decodes with pinned bcdec and encodes with Arm astcenc at
medium quality, retaining alpha and selecting linear/sRGB encoding explicitly.
Cache keys include source content, dimensions, format, encoder binary and
decoder sources. Encoder results are checked for ASTC block size, dimensions
and length. ASTC is lossy on top of BC. BC1/4 have 8-byte blocks and cannot
retain this footprint; BC5 channel semantics and BC6H HDR are deliberately
left for the safe runtime decoder. Unsupported containers fail closed.

**Galaxy:** its Hagi replacement archives have no verified reader here, and
runtime-generated Wii textures cannot be converted by rewriting a RomFS copy.
No offline Galaxy texture coverage is claimed. Its first path is the runtime
decoder; a verified Hagi reader and measured format census remain future work.

[Issue #1180](https://github.com/seedds/nxnative/issues/1180) motivates explicit
capability admission and a runtime compressed-texture fallback. This fork does
not import its unrelated GL, input or shader changes, nor its alpha-dropping
ETC encoder or black BC4–7 behavior. Its DOOM 3 A15 report is not Galaxy evidence.

## Validation and CI

Run the portable checks with a C compiler available:

```sh
python3 -m unittest dm.tools.tests.test_bc_fallback dm.tools.tests.test_bc_astc dm.ios.tests.test_compile_fixture -v
```

On an Apple silicon Mac with the supported toolchain:

```sh
make -C dm/gfx/tests GAME=010099C022B96000 check_t_vk_bc
```

The Metal integration test forces fallback and checks padded/edge uploads,
multiple layers, a mip tail, sRGB views, a preceding GPU buffer write, budget
rejection and retained storage. It uses synthetic blocks. GitHub's virtual
Macs compile this test but cannot provide its Metal hardware execution.

`.github/workflows/experimental-ipa.yml` compiles the production iOS project
using the Galaxy profile with synthetic zero-filled module pages, then uploads
an unsigned `Payload/DmIOS.app` IPA. It includes no game data, keys, extracted
game code or game shader libraries. A fixture marker prevents execution of
the synthetic modules and displays the validation boundary. It is useful for
compile/link and local signing/sideload smoke checks, **not for playing Galaxy**.
Workflow success is compilation/package evidence only.

Local validation for this implementation (Windows host): 12 new tests passed,
including the compiled C decoder, capability matrix, stride overflow checks,
real Arm astcenc 5.7.1 encode/decode with transparent alpha, cache reuse and IPA
wrapper contents. All six documentation checks passed. Changed Python files
passed ruff 0.17.4 and production scripts passed pyright 1.1.414; workflow YAML
parsed. This is targeted lint, not the repository's complete pinned lint ratchet.
The macOS/iOS compiler, Metal integration test, game regression harness and
A15/A16 gameplay have not run on this Windows host. No game dumps or keys are
available here. CI must report its own compile result after the branch is pushed.

Before reporting A15/A16 compatibility, record device model/chip, iOS version,
game version/build ID, signing entitlements, source revision and both cold/warm
boots. Test a new save, file select/touch, opening movie, first controllable
area, star-bit collection, pause/resume and background/foreground. Play across
several loading transitions, capture texture/alpha/sRGB/HDR comparisons against
the native path, frame-time distributions, conversion stalls, footprint peaks,
available-memory logs and any jetsam report. Repeat on A15 and A16 and regress
A17+ with the mode off. Until then the result remains **unvalidated**.

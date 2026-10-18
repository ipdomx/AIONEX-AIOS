# Phase 36I — Current renderer/browser acceptance

Date: 2026-10-18

Status: **PASS — bounded FR16C renderer, AssetInspector, browser and visual acceptance.**

Project: `ipdomx/AIONEX-AIOS`; full FR16 remains open.

## Source and verified inputs

Executed the unchanged PR #935 renderer from source snapshot `881eb7d25b75c6fe3148b85a16da27225f52986b`, using the existing AssetInspector. Runner SHA256: `27c07d6659acf2404df68d2b97401dfcfc1285a46ccb19a59b469363f2337c08`.

Blender **5.2.0** came from the [official archive URL](https://download.blender.org/release/Blender5.2/blender-5.2.0-linux-x64.tar.xz), HTTP 200. Its retained immutable checksum was verified before extraction/execution.

| Input | Bytes | SHA256 |
|---|---:|---|
| Blender archive | 384441228 | `96f6c181a30f4950607839dc84d42a354b250d8a0231b098b59b7bc69c351c48` |
| Blender ELF | 174666336 | `83e8261eace07a5337f71b52d156c1eece1a6ba913403cc6406182ae58bacf27` |
| Cached Playwright 1.62.1 Noble image ID | — | `fee853fafa59550d162cef52bca02d907694b44ebf6ef9fb075bcc0c65d8dedb` |

The image had no RepoDigest. Chromium **151.0.7922.34**, revision 1234, used matching `playwright-core@1.62.1`. Package tarballs passed official SRI verification against the snapshot's `tests/browser-e2e/package-lock.json` and `vip-frontend/package-lock.json`:

- Core: `sha512-wPYSwEBJY9GHraISXqyqtx0na0LpO3XEX7jNDhntbex7tzUS7kLnZsOlFruFJB4Hi/rhDMjXGqHewDZ68nYZVw==`.
- Three.js **0.185.1**: `sha512-5aojFCXKwnjBRZvUnt3WFfEcvUJgkN5LlijRFN95hMy8WVkG4I0QNcJE+OuWvuJ0bOdStrbfXn0pkd6/QyiAlg==`.

## Actual results and isolation

The dedicated encrypted NEW lab used UID 65534, Python 3.12.3, read-only root filesystem, no external network and no exposed hardware GPU. The original offline Blender contract produced a fresh GLB and nonconstant **512×384** PNG. Inspection passed embedded references, hero/ground identity, metallic **0.35**, roughness **0.28**, PNG decoding/CRCs and every existing asset-budget profile.

| Browser check | Both desktop 1440×900 and mobile 390×844 |
|---|---|
| Meshes / materials / textures / triangles / animations | 2 / 2 / 1 / 14 / 1 |
| Real hero X progression; duration | 0 → 1.21011245 → 2.5; 2 seconds |
| Graphics; WebGL error | SwiftShader; 0 |
| External requests / console errors / page errors / failed requests | 0 / 0 / 0 / 0 |

Real GLTFLoader, animation, draw calls and nonconstant canvas checks passed. Runtime input hashes remained unchanged. Visual inspection of the Blender preview and both browser screenshots confirmed the expected blue cube and ground, the complete hero in both viewports, and no blank/corrupt rendering.

The three failed browser attempts and their receipts remain retained: **1** crashpad database location; **2** default seccomp namespace denial; **3** sandbox chroot denial. Writable private Chrome/XDG directories fixed attempt 1. Attempt **4 passed** with `chromiumSandbox:true`, effective/bounding capabilities **0**, `NoNewPrivs=1` and `docker-default (enforce)`.

The actual OCI seccomp profile was deep-equal to the captured **12-rule** builtin baseline plus **one ALLOW rule** for `clone,setns,unshare,chroot`; all existing rules, including clone3 ENOSYS, remained exact. Docker **29.1.3** source `fbf3ed25f893e6ce21336f1101590e40a13934f4` pins seccomp **v0.1.0**; the matching Chromium sandbox uses chroot after entering a new user namespace.

## Retained evidence

Lab root: `/mnt/aionex/fr09-isolated-lab-20261011/fr16c-renderer-20261018`. Successful browser directory: `browser-output-attempt4/fr16c-current-20261018T0300Z-browser/`.

| Artifact | SHA256 |
|---|---|
| GLB, 4700 bytes | `f99e69e4b1a382eb96f4c87746ecc7a4086d501cfa4902e310839bdad3927d43` |
| Preview, 196708 bytes | `d2942c5c460644810ee27369cf248485570813d552d9286e988b031907a3bd95` |
| Runtime acceptance receipt | `2bb798abe5ce84a9574bca77d0a10e172cb755e3ad74eda05863986aa65b67f8` |
| Browser acceptance receipt | `55988873f0f673b26d8f81ca892b7087e8ff0b1a65fdf9948ac8a7baf23e294c` |
| Desktop screenshot | `79b8a5b14070c70169ede8580787be5ce87c5aa35686ca72b0883f3950eea51e` |
| Mobile screenshot | `15d539a1d5eb39d9f682319a55dcb80c964f5ce4a8bda24695076f3fdb202f9d` |
| `RENDER-LAB-RESULT.json` | `37f822ca8831923dae38bb831fa720fb36414d28b5e554a7543b0fa103b4e399` |
| `BROWSER-LAB-RESULT-ATTEMPT4.json` | `826b416e0668f08842578c3468f789815118e90a1931d9f58a4895c39cb3da8f` |
| Captured seccomp baseline | `41f307f405cc9f7830646101a687873add0f9353c5d8db295cef529d2fa676ac` |
| Final seccomp profile | `2846dff3149e88f179a32b36d10982ad731b7f40bf0fbe7f511e648cdb20eb62` |

Combined proof: `/var/lib/aionex-migration/r1-management-20261008/CONTINUATION-20261018/FR16-CURRENT-RENDERER-BROWSER-PROOF.json`, SHA256 `fc3dd61006a12b3868e9c0ada0032c403905abebd356a047862c4684573c2318`; all nine referenced files verified.

At **03:25:59 UTC**, production comparison confirmed unchanged IDs/images/policies/counts/live HEAD: **41 total, 36 running, 35 healthy, 1 without a healthcheck, 23/23 workers, 0 unhealthy, 0 restarts**. Own lab-container cleanup left **0** lab containers.

## Remaining scope

This accepts the current rendered fixture and bounded browser delivery. **Full FR16, optimization/compression/LOD execution, Hunyuan acceptance and asset recovery remain open.** Hunyuan stays quarantined and deferred providers stay deferred. No production deployment or provider activation is claimed.

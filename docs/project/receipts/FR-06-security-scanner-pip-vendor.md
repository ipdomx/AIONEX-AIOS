# FR-06 — Scanner pip vendored-library refresh (source and isolated image only)

Parent source: PR792 / `cede8ae6080a3c03adf5e365b81ca96204487f50`.
Production base remains `ce9659d2a060a31453f1f569e2e92274974d214c`.
No production worker rollout, host-memory action, blocked-action retry or FR-06 closure.

## Real code refresh, not a scanner-metadata exemption

The previous scanner child retained two flagged component versions inside pip:
msgpack 1.1.2 and the pkg_resources subset of setuptools 70.3.0. Updated the
actual four msgpack Python files from published 1.2.3, and actual pkg_resources
code from published setuptools 80.9.0. As in upstream pip, only pkg_resources is
vendored, not setuptools/package_index.py. The prior inventory finding does NOT
prove that the setuptools PackageIndex vulnerability was exploitable in this
subset. No exploitation or incident is asserted.

The output is explicitly local **pip 26.2.1+aios.1**, not an upstream pip release.
All three input wheels are SHA256-pinned and their RECORD contents verified before
rewriting. The pure-Python msgpack fallback is preserved (pip never included its
compiled extension). pkg_resources uses the import namespace/path adaptations
needed for pip's existing vendoring layout; the exact patch is included. All 153
pip engine files and its other vendored library source remain unchanged.

Licenses, local version, wheel RECORD, vendor.txt and CycloneDX component/dependency
references are updated together with the code. No ignored CVE, hidden old source,
false fixed-version label, TLS change or no-dependency resolver bypass is used.

## Do not undo the fix inside transient audit environments

Observed upstream pip-audit 2.10.1 creates a temporary venv, bootstraps pip and then
upgrades another installer there. Updating only the image pip would not constrain
that separate resolver. The allowlisted `pip-audit` executable now uses the explicit
AIONEX `security_pip_audit.py` entrypoint: both RequirementSource and PyProjectSource
retain their own venv and upstream requirement/vulnerability processing, but use
the image's pinned pip with `--python` for resolution. The venv is created WITHOUT
another pip; no floating installer upgrade runs. Input/index options, hash checks,
dry-run report and errors are retained. Unreviewed pip/pip-audit versions fail.
This is a locally maintained compatibility adapter, not an upstream API guarantee.
Direct `python -m pip_audit` is not the adapted allowlisted executable.

## Acceptance

- 32 new real ZIP/RECORD/import-adapter and command/report contract tests passed.
- The derived wheel was rebuilt independently with identical SHA256 output.
- Native image tests: five actual vendored source hashes and all 153 pip engine
  hashes match the retained provenance. Both pip metadata backends run; pip check,
  inspect, debug, CacheControl serialization, dependency resolution and real
  installation of synthetic wheels succeed.
- Hash-checked resolution succeeds for correct inputs and rejects a wrong hash;
  conflicting dependencies are rejected. No real packages are installed into a
  production environment; only fresh synthetic wheels under disposable tmpfs.
- The actual pip-audit RequirementSource and allowlisted CLI dry-run succeed offline
  without bootstrapping/upgrading another installer.
- The complete scanner functional verifier still succeeds: Semgrep/Bandit detect
  a bad synthetic source but not its safe control, real application normalizers
  consume the output, Schemathesis loads a local schema, and explicitly configured
  MCP Host/Origin checks reject invalid input. No external scan target is contacted.
- Ruff passes; Mypy passes for the three scripts with four narrow import-untyped
  boundaries because upstream pip-audit does not ship py.typed. No global checker
  disable or security-gate exemption is introduced.
- Full Root suite and exact source snapshot results are retained in runtime evidence.

The first native audit check hit the disposable /tmp noexec flag. The final
native-venv laboratory uses exec only on its OWN temporary container tmpfs. No
production /tmp, mount, swap or service setting was changed.

## Full image acceptance remains FAILED

The final full scan, without suppressions and with ignore_unfixed=false, reports
**296 HIGH/CRITICAL instances**: 145 OS plus 151 Go-binary instances. Python
HIGH/CRITICAL instances fell from 2 to 0. This is not a scan of every severity,
not a claim of zero vulnerabilities, and NOT a production-release certificate.
The image remains non-deployable pending OS/Go remediation and a complete rebuilt
image acceptance. This test image is an immutable narrow child, not claimed to be
a clean rebuild of all tools from the source Dockerfile.

## Resource reserve and continuity

The 4 GiB runtime reserve blocked the first candidate build BEFORE Docker ran.
Recovered space from explicitly identified, unused build intermediates and old
unused test/UI image tags, retaining checksum-verified Docker archives for reload.
No container, named/anonymous data volume, current image or rollback-tagged image
was removed. Unused build-cache age cleanup reclaimed zero bytes; it is not
reported as a gain. All 40 production container identities/images/epochs stayed
unchanged. The build only proceeded after the original reserve was restored.

The GitHub workflow files remain unchanged. The prior denied workflow edit,
observer operator, C5E9 receipt and other recorded blocked actions were not retried.
Backend and Telegram deployments remain intact. FR-07 is complete; FR-06, worker
updates, full image acceptance, C5D/C5E/C6 and final launch remain open.

Evidence root: `docs/project/runtime/fr06-security-scanner-vendor-20260929T2220/`.

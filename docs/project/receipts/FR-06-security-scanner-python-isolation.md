# FR-06 — Security scanner Python isolation (independent source segment)

This segment does not recreate a production container, close maintenance, alter
memory/storage controls, repeat the blocked observer operator, or close FR-06.
The current source base is `ce9659d2a060a31453f1f569e2e92274974d214c`.

## Reproduced defects and correction

The previously prepared scanner PyJWT child failed `pip check` for two real
installed-package conflicts: Semgrep 1.172.0 required PyJWT ~=2.13.0 while the
application needed 2.14.0; its OpenTelemetry 1.37.0 also conflicted with installed
Google API Core 2.38.0, which requires OpenTelemetry API >=1.44.0.

Semgrep now has an isolated `/opt/semgrep` environment. The application and the
other Python tools keep `/opt/venv`; both dependency graphs are verified rather
than bypassing dependency resolution. The runtime command still invokes the
same allowlisted `semgrep` CLI, now through a symlink to its isolated interpreter.
No application security policy, allowlist or finding severity is relaxed.

Upstream Semgrep 1.178.0 supplies fixed MCP 1.29.0 but retains the incompatible
PyJWT minor pin. The build creates the explicitly LOCAL version
`1.178.0+aios.1`: only METADATA Version and the PyJWT requirement are changed,
with a regenerated RECORD and renamed dist-info. The input SHA256 and every
input RECORD entry are checked. All **183 upstream executable/Python/library
payload files are byte-identical**, verified again after installation. This is
an AIONEX compatibility build, not an upstream release or code-level security
patch. JWT verification logic, TLS/authentication controls and signatures remain
unmodified. The allowed range is restricted to fixed PyJWT 2.14.x, and this build
pins 2.14.0 exactly. An upstream metadata/hash change fails the build.

The obsolete system pip/setuptools/wheel code and its bundled libraries are
removed from the IMAGE, not merely hidden from the scanner. Semgrep does not
need pip after construction, so its build-only pip is removed too. The app's
maintained pip remains because pip-audit needs it; its remaining bundled-library
findings are explicitly NOT suppressed or reported as resolved.

## Observed acceptance

- 22 ZIP/RECORD/metadata/build-contract tests passed; input hash drift, duplicate
  members, invalid records, unsafe paths and symlinks are rejected.
- The derived immutable scanner child was built and exercised without network
  access to any scan target or production resource.
- Both Python dependency graphs pass validation; application `pip check` passes.
- Semgrep and Bandit actually detect a synthetic unsafe source and reject a safe
  control as a finding. The application's real finding normalizers accept the
  produced outputs. Schemathesis loads a local OpenAPI schema; pip-audit starts.
- Explicitly enabled MCP Host/Origin validation accepts the allowed request and
  rejects disallowed Host/Origin inputs. No MCP server or network is started;
  this is not a claim that upgrading alone enables optional transport settings.
- The existing 21-case JWT regression suite passes inside EACH image environment;
  this is the same suite repeated, not 42 independent cases.
- Full root-suite results and source fingerprints are retained in runtime
  evidence rather than inferred from a previous commit.
- Ruff and Mypy pass for the two new scripts. The initial static-analysis runner
  lacked the source MYPYPATH; the corrected runner resolved the real modules.

## Full vulnerability gate remains FAILED

The same-date full scan, with no suppressions and `ignore_unfixed=false`, now
reports **298 HIGH/CRITICAL finding instances versus 303 previously**. Python
findings fell from 7 to 2. The remaining two are pip-vendored msgpack 1.1.2 and
setuptools 70.3.0; merely installing newer top-level packages does not remove
these copies. The official current pip artifact remains 26.2.1 in the captured
PyPI metadata. The 145 OS and 151 Go-binary finding instances remain independent
remediation work. Counts are instances, not independent vulnerabilities and not
proof of exploitability or an incident. The child image is NOT deployable.

The first scanner attempt exhausted its own private 512MiB tmpfs while expanding
Semgrep's native core and produced no valid scan. That failed log is retained.
Only the disposable scanner's tmpfs was resized for the completed second scan;
no host `/tmp`, mount, swap, production service or security rule changed.

A functional image verifier is included and has been run offline. Wiring it into
`.github/workflows/final-validation.yml` was rejected by GitHub because this
OAuth connection lacks workflow scope. That workflow remains UNCHANGED in this
source-only candidate. The proposed CI diff and unpublished commit are retained
locally; no different credential or connector was used to apply the denied change.
Existing CI still builds the source Dockerfile and checks installed tool paths;
it does not yet run the new full functional verifier automatically.

The local candidate is a narrowly scoped child of the previously observed
scanner image; it is NOT claimed to be a clean rebuild of every other tool from
the new Dockerfile. Protected CI builds the source Dockerfile separately.

Evidence root:
`docs/project/runtime/fr06-security-scanner-python-20260929T2137/`

FR-07 remains complete. Backend and both Telegram workers stay on their accepted
PyJWT 2.14.0 deployments. The observer operator block, the remaining worker
rollouts, C5D/C5E/C6 and final image security acceptance are still open.

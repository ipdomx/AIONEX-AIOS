# FR-06 — official Debian PCRE2 backport, isolated image only

Base: merged PR809 / 1e5ebb6a5109ae4a81d8e14ea0747111e52d63a6.
The owner's deployment and additional-merge hold remains in force. No live source
synchronization, production service change, maintenance transition or retry of
previously blocked observer/Syft/workflow/C5E9 operations is part of this segment.
The already-fixed Dependabot alerts #34/#36 are not reopened or reworked.

## Scoped repair

The retained scanner image had libpcre2-8-0 10.42-1, with three HIGH instances:
CVE-2026-86145, CVE-2026-89157 and CVE-2026-89161. Debian DLA-4772-1 identifies
10.42-1+deb12u1 as the official Bookworm security fix. The package was downloaded
using authenticated Debian indexes inside an unprivileged disposable container;
its SHA256 and size match the signed-index package record. No third-party fork,
changed library version string, vulnerability exclusion or untrusted APT option
is used. Source: https://security-tracker.debian.org/tracker/DLA-4772-1 .

The runtime Dockerfile explicitly installs libpcre2-8-0 so an older copy inherited
from the pinned base is upgraded, then enforces the Debian version floor using
dpkg's comparator. It retains this package's small documentation files so that
ALL installed package-file checksums can be verified without omissions. The
package-specific path-include sorts after Debian slim's existing exclusions;
it does not disable the base configuration or alter scanner exclusions.

The new verifier checks the installed package status/architecture/version,
checks dpkg file integrity, hashes the actual resolved shared library, and tests
that library through its native C API. The source Dockerfile runs the checks as
UID 1000. Other application, Python, scanner and OS packages are not upgraded.

## Native regression and compatibility evidence

Eleven bounded cases cover normal/nonmatching patterns, lookbehind, backreference,
Unicode, invalid syntax, the recursive DFA low-heap regression, copied-subject JIT
lifetime, bounded glob conversion, grep -P and Nmap list-only mode on loopback.
No real scan target, DNS lookup, customer expression, database or provider is used.

On the old packaged library, nine cases passed and two failed: the DFA child
terminated with SIGSEGV; the JIT case attempted to free a borrowed subject and
left a copied allocation unreleased. The custom allocation callbacks intercept
unknown frees and reserve checked canary space; they do NOT make vulnerable code
safe. Each native case runs in its own isolated subprocess with core dumping
disabled. The old abnormal exit was captured separately after the initial shell
loop omitted its JSON row. No native-memory-safety or ASan certificate is claimed.

On the corrected immutable image, all eleven cases passed in the actual installed
verifier, with no application/package overlays, network access or capabilities.
The DFA case returned PCRE2_ERROR_HEAPLIMIT instead of crashing. The copied-subject
JIT case left zero unknown frees, guard violations or unreleased allocations.
The huge-pattern, 32-bit CVE-2026-89157 is NOT reproduced on this amd64 target;
its remediation evidence is the official Debian patch and actual package scan,
not the bounded glob-compatibility case.

Twenty-four source/package-integrity/allocator/build-integration contracts also
passed. Final Root-suite results and exact source fingerprints are retained in
the runtime acceptance manifest. Full tests are not inferred from an older run.

## Independent image comparison and security scope

Final child: sha256:321a5ee2ece1045c12d53518e6a1c30b208a22e0c5881b920229111449f48fcf.
It preserves 517 existing application files; only the explicit verifier is added.
All 12,898 regular non-bytecode files under /opt/venv and 3,155 under /opt/semgrep
have unchanged aggregate tree hashes. Nine existing Go-tool binaries are unchanged.
Of 159 installed OS packages, only libpcre2-8-0 changes. Configuration and package
records/PCRE2 documentation change as required for the authenticated installation.
No Syft or Grype runtime verifier is replayed.

The complete unsuppressed scan using the same 07:10:47Z vulnerability DB update
reports 216 HIGH/CRITICAL instances, versus 219 in the base: 144 OS and 72 other Go.
The corrected PCRE2 package is explicitly inventoried, including version AND
Debian release; its three targeted instances are absent. The initial report
parser incorrectly expected the whole Debian version in the Version field; only
post-processing was corrected, without rerunning or weakening the scan. The
scanner's numeric process exit was not separately retained; the complete report,
its hash, positive package coverage and remaining findings are retained, and the
whole-image gate remains FAILED. No zero-package result is counted as success.

Debian's source tracker separately lists an open Bookworm JIT issue under
TEMP-1149217-B31E38. This segment does not claim all PCRE2 issues are closed or
all-severity safety. It is not a complete clean-source rebuild of all scanner
stages, a host OS update, or an authorization to deploy the still-failing image.

Initial doc-exclusion/config-order build failures and the report-parser mismatch
are preserved with corrections; none is misreported as a production incident.
FR-07 remains complete. FR-06, remaining OS/Go issues and deployment/host-state/
memory/boot acceptance remain open.

Evidence: docs/project/runtime/fr06-security-pcre2-20260930T1202/.

# FR25: include public user portal version in final release source manifest

Protected source baseline: b3bfa04a8b2fa628cfa57452379255fe82174a85.

## Source manifest completeness defect

The existing scripts/generate_production_release_manifest.py includes
core, backend, private Owner frontend, Android and iOS versions. It
omits the independent public user portal (vip-frontend / ai.vip-e.net),
although FR25 requires full scope and component/version evidence.

## Compatibility-preserving source-only fix

Read the real vip-frontend/package.json version and add publicPortal
to release.components. Reject missing or invalid version rather than
recording a fictitious value. Do not change schemaVersion=1, the
exact compose webDashboardSha256/deploySha256 fields, the runtime
manifest contract, or the FR24 strict recovery validator. Test that
FR24 accepts the additional version entry.

This change neither invokes Docker nor reads credentials nor modifies
any running service. The original production artifact is unchanged
until a separately gated release. Source acceptance alone does not
prove that the public portal has been deployed at the recorded version.

No worker operations are part of this receipt.

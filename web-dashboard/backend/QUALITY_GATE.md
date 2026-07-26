# AIONEX AIOS Quality Gate

This batch establishes the pre-release verification gate for the consolidated runtime.

## Required checks

- Backend unit and integration tests pass.
- Authentication rejects invalid credentials.
- Refresh tokens rotate and cannot be reused.
- Revoked access tokens are rejected.
- API route registrations contain no duplicate method/path pairs.
- Required runtime routes are registered.
- Health aggregation and alert lifecycle smoke tests remain within bounded execution time.
- Frontend lint and production build pass before release.
- Dependency and source security scans must report no unresolved critical findings.

## Release rule

The production release branch must not be merged into `main` until every check above passes in the target environment.

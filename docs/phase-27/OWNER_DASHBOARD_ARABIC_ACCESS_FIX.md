# Owner Dashboard Arabic and Access Cleanup

## Scope

This corrective release addresses three owner-observed issues without changing the public VIP portal or project-execution runtime:

1. repeated interface text such as `Scope: Scope: Scope`;
2. incomplete Arabic owner-dashboard coverage and incomplete RTL layout behavior;
3. duplicate-looking access roles caused by missing organization context and isolated validation fixtures that had remained in production data.

## Interface correction

The previous live translator stored one original string on a shared parent element. Sibling text nodes therefore reused the wrong source text after React updates. The replacement tracks each text node and placeholder independently with `WeakMap` state, observes both inserted nodes and character-data changes, and preserves the original source when switching languages.

The owner account language preference is now read from `/api/v1/settings` before browser and IP fallbacks. Explicit language changes are persisted to account settings.

Arabic coverage is enforced by `npm run check:owner-arabic`. The check parses owner, settings, navigation, and accessibility source files and fails when a translatable visible string lacks an Arabic catalogue entry. Current result:

- 563 translatable owner-interface strings covered;
- 5 approved technical display tokens retained unchanged;
- owner navigation, settings, security actions, status messages, forms, empty states, portal control, and operational modules included.

RTL behavior now covers the sidebar, top bar, content margins, nested navigation, profile menu, production-studio shortcut, and language controls.

## Security settings

The password section now includes:

- current password;
- new password;
- confirmation field;
- visible in-place loading, success, and error state;
- translated password actions;
- a clearly named `Sign out other sessions` action;
- a disabled `No other active sessions` state instead of an unexplained revoke button.

## Access authority

Access role records now include their owning organization and are grouped by organization in the UI. Equal role names in separate organizations are therefore represented as separate legitimate role assignments rather than apparent duplicates.

Production validation fixtures were removed only after a protected PostgreSQL backup:

`/root/.config/aionex/backups/pre-owner-access-cleanup-20260805T182510Z.dump`

Cleanup result:

- 14 active role records remain;
- 3 legitimate organizations remain;
- 0 identified fake validation organizations remain;
- 0 identified validation role records remain;
- real owner, free-user, and Phase 25 pilot records were retained.

## Validation

- Owner Arabic coverage: passed.
- Owner frontend TypeScript: passed.
- Owner frontend lint: passed with zero warnings.
- Owner frontend production build: passed, 79 pages.
- Targeted owner and language contracts: 58 passed.
- Full isolated backend suite: 268 passed, 1 skipped.
- Root web and Phase 27 contracts: 11 passed.

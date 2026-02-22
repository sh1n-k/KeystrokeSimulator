# E2E Test Plan

This project can run E2E tests, but it should be split into two tracks.

## Track A: CI-friendly integration E2E (recommended)

Goal: verify app flows with real UI state transitions while mocking OS hooks (`pynput`) and capture I/O (`mss`).

Suggested scenarios:

1. App startup creates/selects `Quick` profile.
2. Profile copy/delete flow keeps canonical profile names.
3. Favorite display label (`⭐`) does not break canonical profile operations.
4. Start/Stop toggle updates UI and calls `KeystrokeProcessor.start/stop` exactly once.
5. Empty/invalid profile cannot start simulation.
6. `main_secure` successful auth transitions to main app.
7. `main_secure` invalid session forces app close.
8. Lockout countdown starts once on the 3rd failed auth attempt.

## Track B: Real environment E2E (manual or self-hosted runner)

Goal: verify real OS permissions and external dependencies.

Required environment:

- macOS with Accessibility permission granted
- macOS with Screen Recording permission granted
- real display session (not headless)

Suggested smoke scenario:

1. Launch app with one pixel-match profile.
2. Trigger a known match on screen.
3. Verify key output fires once and app remains responsive.

## Execution notes

- Keep Track A in regular CI.
- Run Track B only in dedicated environment (nightly/manual).

# Verification

The included HTTP integration suite passed on Python 3.12:

- Independent clients, Unicode messages, live long-poll delivery, and presence.
- Binary upload/download SHA-256 equality, Unicode filename handling, and empty files.
- Password/session checks, protected downloads, cross-site request blocking, and path rejection.
- Message length validation, per-file size limits, and total upload storage limits.
- History pagination and persisted messages after a server restart.

Python compilation and JavaScript syntax checks passed.

Browser visual and end-to-end checks could not be completed in the build environment: its browser could not access the local test server. Actual Wi-Fi connectivity depends on the host firewall and router settings and must be checked on your devices.

Quick local check after starting the app:

1. Join from the host computer and a phone on the same Wi-Fi.
2. Send a message in each direction.
3. Upload a file, download it from the other device, and open it.
4. Refresh the page, then restart the server and rejoin; confirm history remains.
5. If using `--password`, try an incorrect password and confirm joining is denied.

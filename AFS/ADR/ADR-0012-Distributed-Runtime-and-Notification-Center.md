# ADR-0012: Distributed Runtime, Mission Control, and Notification Center

## Decision
AIOS distributes work through tenant-scoped workers with capability-based scheduling, durable checkpoints, failure fingerprints, and safe reassignment. Notifications are a separate bounded module with consent, severity, routing, escalation, and immutable delivery audit.

## Owner visibility
The owner receives audit visibility for important project, user, workforce, approval, incident, and policy activity. WhatsApp is an owner-only delivery channel. Other recipients cannot enable it through normal preferences.

## Boundaries
Runtime, notifications, and mission control communicate through public models and methods. No module imports another module's storage internals.

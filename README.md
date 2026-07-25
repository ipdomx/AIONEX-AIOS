# AIOS Enterprise 1.0.0

AIOS is an Engineering Intelligence Operating System designed for:

- Arabic-first interaction
- Multi-project management
- Persistent project memory
- Decision support and better-alternative suggestions
- Expert council review
- Safe code-change workflows
- Security analysis for authorized assets
- Research and knowledge capture
- Model-provider abstraction
- Telegram, CLI, and API interfaces
- Auditing, approvals, rollback, and controlled self-update planning

## Important limitation

AIOS is a complete deployable platform foundation. Its final intelligence depends on the AI model providers you connect. No package can honestly guarantee perfect memory, perfect coding, or error-free autonomous operation.

## Install

```bash
cd /opt/AIOS
./scripts/install.sh
```

## Initialize

```bash
source .venv/bin/activate
aios init
aios status
```

## Telegram

Create a bot with BotFather and add these values to `.env`:

```text
AIOS_TELEGRAM_TOKEN=...
AIOS_TELEGRAM_ALLOWED_USERS=123456789
```

Run:

```bash
./scripts/run-telegram.sh
```

## API

Run:

```bash
./scripts/run-api.sh
```

The built-in API uses Python's standard library and binds to 127.0.0.1:8080 by default.

## Data

Runtime data is stored under:

```text
/opt/AIOS/data
```

Override with `AIOS_HOME`.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable


class CommandRejected(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class CommandPolicy:
    blocked_patterns: tuple[str, ...] = (
        r"(^|\s)rm\s+-rf\s+/(?:\s|$)",
        r"(^|\s)mkfs(?:\.|\s)",
        r"(^|\s)shutdown(?:\s|$)",
        r"(^|\s)reboot(?:\s|$)",
        r"(^|\s):\(\)\s*\{\s*:\|:\s*&\s*\}\s*;\s*:",
    )
    max_length: int = 16_384
    require_approval_for_destructive: bool = True


@dataclass(slots=True)
class CommandValidator:
    policy: CommandPolicy = field(default_factory=CommandPolicy)

    def validate(self, command: str, *, destructive: bool = False, approved: bool = False) -> str:
        value = command.strip()
        if not value:
            raise CommandRejected("empty command")
        if len(value) > self.policy.max_length:
            raise CommandRejected("command exceeds maximum length")
        for pattern in self.policy.blocked_patterns:
            if re.search(pattern, value, re.IGNORECASE):
                raise CommandRejected("command blocked by infrastructure policy")
        if destructive and self.policy.require_approval_for_destructive and not approved:
            raise CommandRejected("owner approval required for destructive command")
        return value

    def validate_many(self, commands: Iterable[str], **kwargs: object) -> tuple[str, ...]:
        return tuple(self.validate(item, **kwargs) for item in commands)

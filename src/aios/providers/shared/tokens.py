from __future__ import annotations


class TokenCounter:
    """Deterministic provider-neutral estimate; adapters may replace it with native counters."""

    @staticmethod
    def estimate_text(text: str) -> int:
        if not text:
            return 0
        return max(1, (len(text.encode("utf-8")) + 3) // 4)

    def estimate_request(self, prompt: str, system_prompt: str = "") -> int:
        return self.estimate_text(prompt) + self.estimate_text(system_prompt)

from __future__ import annotations

from .contracts import APIResponse
from .middleware import RequestContext
from .rate_limits import RateLimitPolicy, RateLimiter
from .registry import APIRegistry


class APIExperienceGateway:
    def __init__(self, registry: APIRegistry, limiter: RateLimiter) -> None:
        self.registry = registry
        self.limiter = limiter
        self._policies: dict[str, RateLimitPolicy] = {}

    def set_policy(self, contract_id: str, policy: RateLimitPolicy) -> None:
        policy.validate()
        self._policies[contract_id] = policy

    def dispatch(
        self,
        version: str,
        method: str,
        path: str,
        payload: dict[str, object],
        context: RequestContext,
    ) -> APIResponse:
        try:
            endpoint = self.registry.resolve(version, method, path)
        except LookupError:
            return APIResponse(
                status_code=404,
                body={"error": "endpoint_not_found", "correlation_id": context.correlation_id},
            )

        required = endpoint.contract.required_capabilities
        if not required.issubset(context.capabilities):
            return APIResponse(
                status_code=403,
                body={"error": "forbidden", "correlation_id": context.correlation_id},
            )

        policy = self._policies.get(endpoint.contract.contract_id)
        if policy is not None and not self.limiter.allow(context.principal_id, policy):
            return APIResponse(
                status_code=429,
                body={"error": "rate_limited", "correlation_id": context.correlation_id},
            )

        response = endpoint.handler(payload, {
            "correlation_id": context.correlation_id,
            "principal_id": context.principal_id,
            "organization_id": context.organization_id,
            "project_id": context.project_id,
        })
        headers = dict(response.headers)
        headers.setdefault("X-Correlation-ID", context.correlation_id)
        return APIResponse(
            status_code=response.status_code,
            body=dict(response.body),
            headers=headers,
            generated_at=response.generated_at,
        )

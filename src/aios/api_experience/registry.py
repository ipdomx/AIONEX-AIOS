from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .contracts import APIContract, APIResponse

APIHandler = Callable[[dict[str, object], dict[str, object]], APIResponse]


@dataclass(frozen=True)
class APIEndpoint:
    contract: APIContract
    handler: APIHandler


class APIRegistry:
    def __init__(self) -> None:
        self._endpoints: dict[tuple[str, str, str], APIEndpoint] = {}

    def register(self, endpoint: APIEndpoint) -> APIEndpoint:
        endpoint.contract.validate()
        key = (
            endpoint.contract.version,
            endpoint.contract.method.value,
            endpoint.contract.path,
        )
        if key in self._endpoints:
            raise ValueError(f"duplicate API endpoint: {key}")
        self._endpoints[key] = endpoint
        return endpoint

    def resolve(self, version: str, method: str, path: str) -> APIEndpoint:
        key = (version, method.upper(), path)
        try:
            return self._endpoints[key]
        except KeyError as exc:
            raise LookupError(f"API endpoint not found: {key}") from exc

    def list_contracts(self, include_deprecated: bool = False) -> list[APIContract]:
        contracts = [endpoint.contract for endpoint in self._endpoints.values()]
        if not include_deprecated:
            contracts = [contract for contract in contracts if not contract.deprecated]
        return sorted(contracts, key=lambda item: (item.version, item.path, item.method.value))

from __future__ import annotations

from dataclasses import dataclass
import json
import time
import urllib.error
import urllib.request


class RunPodError(RuntimeError):
    """Sanitized RunPod lifecycle failure."""


@dataclass(frozen=True, slots=True)
class RunPodPod:
    pod_id: str
    desired_status: str | None = None
    runtime_status: str | None = None


class RunPodClient:
    """Minimal RunPod GraphQL client for starting/stopping a pre-provisioned GPU pod."""

    def __init__(self, api_key: str, endpoint: str = "https://api.runpod.io/graphql") -> None:
        if not api_key.strip():
            raise ValueError("RunPod API key is required")
        self.api_key = api_key.strip()
        self.endpoint = endpoint

    def _query(self, query: str, variables: dict[str, object] | None = None) -> dict:
        payload = json.dumps({"query": query, "variables": variables or {}}).encode()
        req = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            raise RunPodError(f"RunPod HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RunPodError(f"RunPod connection failed: {type(exc).__name__}") from None
        if data.get("errors"):
            raise RunPodError(str(data["errors"][0].get("message", "RunPod GraphQL error")))
        return data.get("data") or {}

    def get_pod(self, pod_id: str) -> RunPodPod:
        data = self._query(
            "query($id:String!){ pod(input:{podId:$id}) { id desiredStatus runtime { uptimeInSeconds } } }",
            {"id": pod_id},
        )
        pod = data.get("pod")
        if not pod:
            raise RunPodError("RunPod pod not found")
        return RunPodPod(pod_id=pod["id"], desired_status=pod.get("desiredStatus"), runtime_status="running" if pod.get("runtime") else "stopped")

    def start(self, pod_id: str) -> RunPodPod:
        self._query("mutation($id:String!){ podResume(input:{podId:$id, gpuCount:1}) { id } }", {"id": pod_id})
        return self.get_pod(pod_id)

    def stop(self, pod_id: str) -> RunPodPod:
        self._query("mutation($id:String!){ podStop(input:{podId:$id}) { id } }", {"id": pod_id})
        return self.get_pod(pod_id)

    def wait_running(self, pod_id: str, timeout_seconds: float = 600, poll_seconds: float = 5) -> RunPodPod:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            pod = self.get_pod(pod_id)
            if pod.runtime_status == "running":
                return pod
            time.sleep(poll_seconds)
        raise RunPodError("Timed out waiting for GPU pod to start")

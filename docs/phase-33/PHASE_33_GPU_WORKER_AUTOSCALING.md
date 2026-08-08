# Phase 33 — GPU Worker On-Demand Activation

Purpose: attach an external GPU worker without moving the main AIOS production server.

Architecture:
AIOS main server -> RunPod lifecycle control -> HTTPS Hunyuan3D worker -> S3/object output -> Blender -> glTF Transform.

Security and cost boundaries:
- GPU starts only when a job requires it.
- Worker API must be HTTPS.
- Maximum runtime is bounded.
- Pod is stopped automatically after the job.
- Credentials stay in `/opt/AIOS/web-dashboard/secrets/RUNPOD_GPU.env` and are not committed.
- No provider is reported ready until live health checks succeed.

Recommended GPU: 48GB VRAM class (RTX A6000/A40/L40S or stronger) for the full Hunyuan3D shape+texture path.

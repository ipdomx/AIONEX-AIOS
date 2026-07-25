# AIS-0021: Cloud Platform Integrations

## Status
Implemented

## Scope
DigitalOcean, AWS, Azure, Google Cloud, Kubernetes, Cloudflare, and object storage.

## Contract
Every integration derives from `BaseInfrastructureIntegration`, publishes capabilities through `IntegrationDescriptor`, connects through `ConnectionManager`, and returns normalized operation payloads.

## Safety
Destructive instance, Kubernetes, DNS, cache, bucket, and object operations require explicit owner approval in the request payload.

## Extension
Future cloud providers can derive from `BaseCloudProvider` without modifying Infrastructure Core.

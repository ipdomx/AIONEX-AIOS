import {
  getPasskeyAuthenticationOptions,
  getPasskeyRegistrationOptions,
  verifyPasskeyAuthentication,
  verifyPasskeyRegistration
} from "@/lib/api";
import type { LoginResponse, PasskeyCredentialSummary } from "@/types";

function decodeBase64Url(value: string): ArrayBuffer {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
  const binary = window.atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}

function encodeBase64Url(value: ArrayBuffer): string {
  const bytes = new Uint8Array(value);
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return window
    .btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function creationOptions(
  input: Record<string, unknown>
): PublicKeyCredentialCreationOptions {
  const user = input.user as Record<string, unknown>;
  const excluded = (input.excludeCredentials || []) as Array<Record<string, unknown>>;
  return {
    ...(input as unknown as PublicKeyCredentialCreationOptions),
    challenge: decodeBase64Url(String(input.challenge)),
    user: {
      ...(user as unknown as PublicKeyCredentialUserEntity),
      id: decodeBase64Url(String(user.id))
    },
    excludeCredentials: excluded.map((item) => ({
      ...(item as unknown as PublicKeyCredentialDescriptor),
      id: decodeBase64Url(String(item.id))
    }))
  };
}

function requestOptions(
  input: Record<string, unknown>
): PublicKeyCredentialRequestOptions {
  const allowed = (input.allowCredentials || []) as Array<Record<string, unknown>>;
  return {
    ...(input as unknown as PublicKeyCredentialRequestOptions),
    challenge: decodeBase64Url(String(input.challenge)),
    allowCredentials: allowed.map((item) => ({
      ...(item as unknown as PublicKeyCredentialDescriptor),
      id: decodeBase64Url(String(item.id))
    }))
  };
}

function serializeCredential(credential: PublicKeyCredential): Record<string, unknown> {
  const response = credential.response;
  const common = {
    clientDataJSON: encodeBase64Url(response.clientDataJSON)
  };
  const serializedResponse =
    response instanceof AuthenticatorAttestationResponse
      ? {
          ...common,
          attestationObject: encodeBase64Url(response.attestationObject),
          transports:
            typeof response.getTransports === "function" ? response.getTransports() : []
        }
      : {
          ...common,
          authenticatorData: encodeBase64Url(
            (response as AuthenticatorAssertionResponse).authenticatorData
          ),
          signature: encodeBase64Url(
            (response as AuthenticatorAssertionResponse).signature
          ),
          userHandle: (response as AuthenticatorAssertionResponse).userHandle
            ? encodeBase64Url(
                (response as AuthenticatorAssertionResponse).userHandle as ArrayBuffer
              )
            : null
        };

  return {
    id: credential.id,
    rawId: encodeBase64Url(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment,
    response: serializedResponse,
    clientExtensionResults: credential.getClientExtensionResults()
  };
}

export function passkeysSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    "PublicKeyCredential" in window &&
    Boolean(navigator.credentials)
  );
}

export async function registerPasskey(
  nickname: string
): Promise<PasskeyCredentialSummary> {
  if (!passkeysSupported()) throw new Error("Passkeys are not supported");
  const ceremony = await getPasskeyRegistrationOptions();
  const credential = (await navigator.credentials.create({
    publicKey: creationOptions(ceremony.public_key)
  })) as PublicKeyCredential | null;
  if (!credential) throw new Error("Passkey registration was cancelled");
  return verifyPasskeyRegistration(
    ceremony.ceremony_id,
    serializeCredential(credential),
    nickname
  );
}

export async function authenticateWithPasskey(): Promise<LoginResponse> {
  if (!passkeysSupported()) throw new Error("Passkeys are not supported");
  const ceremony = await getPasskeyAuthenticationOptions();
  const credential = (await navigator.credentials.get({
    publicKey: requestOptions(ceremony.public_key)
  })) as PublicKeyCredential | null;
  if (!credential) throw new Error("Passkey authentication was cancelled");
  return verifyPasskeyAuthentication(
    ceremony.ceremony_id,
    serializeCredential(credential)
  );
}

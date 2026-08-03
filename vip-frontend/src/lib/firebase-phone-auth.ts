import { FirebaseError, getApp, getApps, initializeApp } from "firebase/app";
import {
  inMemoryPersistence,
  getAuth,
  RecaptchaVerifier,
  setPersistence,
  signInWithPhoneNumber,
  signOut,
  type Auth,
  type ConfirmationResult,
} from "firebase/auth";
import type { FirebaseOptions } from "firebase/app";

export interface FirebasePhoneChallenge {
  auth: Auth;
  confirmation: ConfirmationResult;
  phoneNumber: string;
  verifier: RecaptchaVerifier;
}

const APP_NAME = "aionex-vip-phone-auth";

function firebaseErrorCode(error: unknown): string {
  if (error instanceof FirebaseError) return error.code;
  if (typeof error !== "object" || error === null || !("code" in error))
    return "";
  const candidate = (error as { code?: unknown }).code;
  return typeof candidate === "string" ? candidate.trim().toLowerCase() : "";
}

function withSafeReference(message: string, code: string): string {
  return /^auth\/[a-z0-9._-]+$/.test(code)
    ? `${message} Reference: ${code}.`
    : message;
}

function firebaseErrorMessage(error: unknown): string {
  const code = firebaseErrorCode(error);
  const messages: Record<string, string> = {
    "auth/invalid-phone-number":
      "Enter a valid mobile number in international format.",
    "auth/missing-phone-number": "Enter your mobile number first.",
    "auth/too-many-requests":
      "Too many verification attempts. Wait before trying again.",
    "auth/quota-exceeded":
      "The SMS verification quota is unavailable. Check the active billing account and project quota.",
    "auth/captcha-check-failed":
      "The security check failed. Confirm this site is listed in the authentication provider's authorized domains, reload the page, and try again.",
    "auth/invalid-app-credential":
      "The security verification credential was rejected. Reload the page and try again. If it continues, use the HTTPS production address and confirm that hostname is authorized.",
    "auth/missing-app-credential":
      "The security verification credential was not created. Reload the page and try again.",
    "auth/app-not-authorized":
      "This web application is not authorized for mobile verification. Verify the Web API key and the authorized hostname.",
    "auth/invalid-api-key":
      "The mobile verification Web API key is invalid or belongs to a different project.",
    "auth/operation-not-supported-in-this-environment":
      "Mobile verification is not supported in this browser context. Open the site directly in a standard browser tab and try again.",
    "auth/web-storage-unsupported":
      "This browser is blocking storage required for mobile verification. Enable essential cookies and site storage, then try again.",
    "auth/missing-client-type":
      "The security verification request is missing browser information. Reload the page and try again.",
    "auth/missing-recaptcha-token":
      "The security check did not return a token. Reload the page and try again.",
    "auth/invalid-recaptcha-token":
      "The security-check token was rejected. Reload the page and try again.",
    "auth/recaptcha-not-enabled":
      "The project security-check configuration is not enabled for mobile verification.",
    "auth/internal-error":
      "The verification service returned an internal error. Wait briefly and try again.",
    "auth/code-expired": "The verification code expired. Request a new code.",
    "auth/session-expired":
      "The verification session expired. Request a new code.",
    "auth/invalid-verification-code": "The verification code is incorrect.",
    "auth/invalid-verification-id":
      "The verification session is invalid. Request a new code.",
    "auth/network-request-failed":
      "The verification service could not be reached. Check the network connection and try again.",
    "auth/operation-not-allowed":
      "The mobile verification service rejected SMS for this project. Enable the Phone provider, allow this phone region under Authentication > Settings > SMS region policy, and link an active billing account.",
    "auth/unauthorized-domain":
      "Add this site hostname under the authentication provider's authorized domains.",
    "auth/user-disabled": "Mobile verification is disabled for this account.",
    "auth/credential-already-in-use":
      "This mobile number is already linked to another account.",
    "auth/argument-error":
      "The mobile verification request is incomplete. Reload the page and try again.",
  };

  if (code) {
    if (
      code.includes("requests-from-referer") &&
      code.includes("are-blocked")
    ) {
      return withSafeReference(
        "The Web API key is blocking requests from this site. Update the API key application restrictions to allow the production hostname.",
        code,
      );
    }
    return withSafeReference(
      messages[code] ?? "Mobile verification failed.",
      code,
    );
  }

  return error instanceof Error && error.message
    ? error.message
    : "Mobile verification failed.";
}

function configuredApp(options: FirebaseOptions) {
  const existing = getApps().find((app) => app.name === APP_NAME);
  if (existing) {
    if (
      existing.options.projectId !== options.projectId ||
      existing.options.appId !== options.appId ||
      existing.options.apiKey !== options.apiKey
    ) {
      throw new Error(
        "Mobile verification configuration changed; reload the page.",
      );
    }
    return getApp(APP_NAME);
  }
  return initializeApp(options, APP_NAME);
}

export async function startFirebasePhoneVerification(
  options: FirebaseOptions,
  phoneNumber: string,
  containerId: string,
): Promise<FirebasePhoneChallenge> {
  if (typeof window === "undefined") {
    throw new Error("Phone verification requires a browser.");
  }
  const container = document.getElementById(containerId);
  if (!container)
    throw new Error("Phone verification security container is missing.");
  container.replaceChildren();

  const auth = getAuth(configuredApp(options));
  auth.useDeviceLanguage();
  await setPersistence(auth, inMemoryPersistence);
  const verifier = new RecaptchaVerifier(auth, containerId, {
    size: "invisible",
  });
  try {
    const confirmation = await signInWithPhoneNumber(
      auth,
      phoneNumber,
      verifier,
    );
    return { auth, confirmation, phoneNumber, verifier };
  } catch (error) {
    verifier.clear();
    container.replaceChildren();
    throw new Error(firebaseErrorMessage(error), { cause: error });
  }
}

export async function completeFirebasePhoneVerification(
  challenge: FirebasePhoneChallenge,
  code: string,
): Promise<string> {
  try {
    const credential = await challenge.confirmation.confirm(code);
    if (credential.user.phoneNumber !== challenge.phoneNumber) {
      throw new Error(
        "The verification provider confirmed a different phone number.",
      );
    }
    return await credential.user.getIdToken(true);
  } catch (error) {
    throw new Error(firebaseErrorMessage(error), { cause: error });
  } finally {
    challenge.verifier.clear();
    await signOut(challenge.auth).catch(() => undefined);
  }
}

export function disposeFirebasePhoneChallenge(
  challenge: FirebasePhoneChallenge | null,
): void {
  if (!challenge) return;
  challenge.verifier.clear();
  void signOut(challenge.auth).catch(() => undefined);
}

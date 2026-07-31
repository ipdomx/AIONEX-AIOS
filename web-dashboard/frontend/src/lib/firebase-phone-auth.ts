import { FirebaseError, getApp, getApps, initializeApp } from "firebase/app";
import {
  inMemoryPersistence,
  RecaptchaVerifier,
  setPersistence,
  signInWithPhoneNumber,
  signOut,
  type Auth,
  type ConfirmationResult,
} from "firebase/auth";
import { getAuth } from "firebase/auth";

export type FirebasePhoneWebConfig = {
  apiKey: string;
  authDomain: string;
  projectId: string;
  storageBucket?: string;
  messagingSenderId?: string;
  appId: string;
  measurementId?: string;
};

export type FirebasePhoneChallenge = {
  auth: Auth;
  confirmation: ConfirmationResult;
  phoneNumber: string;
  verifier: RecaptchaVerifier;
};

const FIREBASE_APP_NAME = "aionex-phone-auth";

function firebaseErrorMessage(error: unknown): string {
  if (!(error instanceof FirebaseError)) {
    return error instanceof Error
      ? error.message
      : "Phone verification failed.";
  }

  const messages: Record<string, string> = {
    "auth/invalid-phone-number":
      "Enter a valid mobile number in international format.",
    "auth/missing-phone-number": "Enter your mobile number first.",
    "auth/too-many-requests":
      "Too many verification attempts. Try again later.",
    "auth/quota-exceeded": "The SMS verification quota is currently exhausted.",
    "auth/captcha-check-failed": "The security check failed. Please try again.",
    "auth/code-expired": "The verification code expired. Request a new code.",
    "auth/invalid-verification-code": "The verification code is incorrect.",
    "auth/network-request-failed":
      "The verification service could not be reached.",
    "auth/operation-not-allowed":
      "Phone verification is not enabled for this project.",
    "auth/unauthorized-domain":
      "This site domain is not authorized in Firebase.",
  };
  return messages[error.code] ?? "Phone verification failed. Please try again.";
}

function configuredApp(config: FirebasePhoneWebConfig) {
  const existing = getApps().find((app) => app.name === FIREBASE_APP_NAME);
  if (existing) {
    const existingOptions = existing.options;
    if (
      existingOptions.projectId !== config.projectId ||
      existingOptions.appId !== config.appId ||
      existingOptions.apiKey !== config.apiKey
    ) {
      throw new Error("Firebase phone configuration changed; reload the page.");
    }
    return getApp(FIREBASE_APP_NAME);
  }
  return initializeApp(config, FIREBASE_APP_NAME);
}

export async function startFirebasePhoneVerification(
  config: FirebasePhoneWebConfig,
  phoneNumber: string,
  recaptchaContainerId: string,
): Promise<FirebasePhoneChallenge> {
  if (typeof window === "undefined") {
    throw new Error("Phone verification requires a browser.");
  }

  const container = document.getElementById(recaptchaContainerId);
  if (!container)
    throw new Error("Phone verification security container is missing.");
  container.replaceChildren();

  const auth = getAuth(configuredApp(config));
  auth.languageCode = navigator.language || "en";
  await setPersistence(auth, inMemoryPersistence);

  const verifier = new RecaptchaVerifier(auth, recaptchaContainerId, {
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
  verificationCode: string,
): Promise<string> {
  try {
    const credential = await challenge.confirmation.confirm(verificationCode);
    if (credential.user.phoneNumber !== challenge.phoneNumber) {
      throw new Error("Firebase verified a different phone number.");
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

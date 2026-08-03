import {
  getApp,
  getApps,
  initializeApp,
  type FirebaseApp,
  type FirebaseOptions
} from "firebase/app";
import {
  FacebookAuthProvider,
  getAuth,
  GoogleAuthProvider,
  OAuthProvider,
  signInWithPopup,
  TwitterAuthProvider,
  type AuthProvider
} from "firebase/auth";
import type {
  FirebaseSocialConfiguration,
  OAuthProviderId
} from "@/types";

const APP_NAME = "aionex-vip-browser";

function appFor(options: FirebaseOptions): FirebaseApp {
  return getApps().some((app) => app.name === APP_NAME)
    ? getApp(APP_NAME)
    : initializeApp(options, APP_NAME);
}

function providerFor(
  providerId: OAuthProviderId,
  firebaseProvider: string
): AuthProvider {
  switch (providerId) {
    case "google":
      return new GoogleAuthProvider();
    case "facebook":
      return new FacebookAuthProvider();
    case "x":
      return new TwitterAuthProvider();
    case "apple":
    case "instagram":
      return new OAuthProvider(firebaseProvider);
  }
}

export async function firebaseSocialIdToken(
  providerId: OAuthProviderId,
  configuration: FirebaseSocialConfiguration
): Promise<string> {
  if (!configuration.enabled || !configuration.web_config) {
    throw new Error("Social authentication is unavailable");
  }
  const configuredProvider = configuration.providers.find(
    (provider) => provider.id === providerId && provider.enabled
  );
  if (!configuredProvider) throw new Error("Social provider is unavailable");

  const auth = getAuth(appFor(configuration.web_config));
  auth.useDeviceLanguage();
  const provider = providerFor(providerId, configuredProvider.firebase_provider);
  const result = await signInWithPopup(auth, provider);
  return result.user.getIdToken(true);
}

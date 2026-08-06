"use client";

import { LoaderCircle } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { StatusMessage } from "@/components/ui/status-message";
import { useAuth } from "@/hooks/use-auth";
import {
  ApiError,
  createFirebaseSocialSession,
  getFirebaseSocialConfiguration,
  prepareFirebaseSocialRegistration,
} from "@/lib/api";
import { firebaseSocialIdToken } from "@/lib/firebase-social-auth";
import { cn } from "@/lib/utils";
import type {
  FirebaseSocialConfiguration,
  OAuthProvider,
  OAuthProviderId,
  SocialRegistrationPreparation,
} from "@/types";

const styles: Record<OAuthProviderId, string> = {
  google: "bg-white text-slate-900",
  apple: "bg-white text-black",
  facebook: "bg-[#166FE5] text-white",
  x: "bg-black text-white",
  instagram:
    "bg-gradient-to-r from-[#833AB4] via-[#E1306C] to-[#F77737] text-white",
};

const glyphs: Record<OAuthProviderId, string> = {
  google: "G",
  apple: "●",
  facebook: "f",
  x: "X",
  instagram: "◎",
};

const knownProviders: OAuthProvider[] = [
  {
    id: "google",
    label: "Google",
    firebase_provider: "google.com",
    enabled: false,
  },
  {
    id: "apple",
    label: "Apple",
    firebase_provider: "apple.com",
    enabled: false,
  },
  {
    id: "facebook",
    label: "Facebook",
    firebase_provider: "facebook.com",
    enabled: false,
  },
  { id: "x", label: "X", firebase_provider: "twitter.com", enabled: false },
  {
    id: "instagram",
    label: "Instagram",
    firebase_provider: "oidc.instagram",
    enabled: false,
  },
];

interface OAuthButtonsProps {
  mode?: "login" | "register";
  onRegistrationPrepared?: (value: SocialRegistrationPreparation) => void;
}

export function OAuthButtons({
  mode = "login",
  onRegistrationPrepared,
}: OAuthButtonsProps) {
  const t = useTranslations("auth");
  const locale = useLocale();
  const router = useRouter();
  const { loginWithSocial, refreshUser } = useAuth();
  const [configuration, setConfiguration] =
    useState<FirebaseSocialConfiguration | null>(null);
  const [loadingProvider, setLoadingProvider] =
    useState<OAuthProviderId | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    getFirebaseSocialConfiguration()
      .then((result) => {
        if (active) setConfiguration(result);
      })
      .catch(() => {
        if (active) setError(t("socialConfigurationError"));
      });
    return () => {
      active = false;
    };
  }, [t]);

  const providers = useMemo(() => {
    const configured = new Map(
      (configuration?.providers || []).map((provider) => [
        provider.id,
        provider,
      ]),
    );
    return knownProviders.map(
      (provider) => configured.get(provider.id) || provider,
    );
  }, [configuration]);

  async function signIn(providerId: OAuthProviderId) {
    if (!configuration) return;
    setError("");
    setLoadingProvider(providerId);
    try {
      if (mode === "login") {
        await loginWithSocial(providerId, configuration);
        router.replace(`/${locale}/dashboard`);
        return;
      }
      const idToken = await firebaseSocialIdToken(providerId, configuration);
      try {
        await createFirebaseSocialSession(idToken);
        await refreshUser();
        router.replace(`/${locale}/dashboard`);
      } catch (cause) {
        if (
          !(cause instanceof ApiError) ||
          cause.code !== "ACCOUNT_REGISTRATION_REQUIRED"
        ) {
          throw cause;
        }
        const prepared = await prepareFirebaseSocialRegistration(idToken);
        onRegistrationPrepared?.(prepared);
      }
    } catch (cause) {
      if (
        cause instanceof ApiError &&
        cause.code === "ACCOUNT_REGISTRATION_REQUIRED"
      ) {
        setError(t("socialRegistrationRequired"));
      } else {
        setError(t("socialError"));
      }
    } finally {
      setLoadingProvider(null);
    }
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {providers.map((provider) => {
          const enabled = Boolean(configuration?.enabled && provider.enabled);
          const busy = loadingProvider === provider.id;
          return (
            <button
              key={provider.id}
              type="button"
              disabled={!enabled || Boolean(loadingProvider)}
              onClick={() => void signIn(provider.id)}
              className={cn(
                "flex h-11 items-center justify-center gap-2 rounded-xl border border-white/10 px-3 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-electric-300",
                styles[provider.id],
                (!enabled || loadingProvider) &&
                  "cursor-not-allowed opacity-55",
              )}
              title={!enabled ? t("providerUnavailable") : undefined}
              aria-label={provider.label}
            >
              {busy ? (
                <LoaderCircle
                  className="h-4 w-4 animate-spin"
                  aria-hidden="true"
                />
              ) : (
                <span className="text-base leading-none" aria-hidden="true">
                  {glyphs[provider.id]}
                </span>
              )}
              <span>{provider.label}</span>
            </button>
          );
        })}
      </div>
      {error && <StatusMessage tone="error">{error}</StatusMessage>}
    </div>
  );
}

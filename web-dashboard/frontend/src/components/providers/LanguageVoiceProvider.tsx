"use client";

import {
  createContext,
  PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  ArabicDialect,
  decideLocale,
  detectArabicDialect,
  dialectLocale,
  LocaleDecision,
  SupportedLocale,
} from "@/lib/locale-engine";

const LOCALE_KEY = "aionex.locale";
const DIALECT_KEY = "aionex.dialect";

type LocaleContextResponse = {
  ip_country?: string | null;
  accept_languages?: string[];
};

type LanguageVoiceContextValue = {
  decision: LocaleDecision;
  locale: SupportedLocale;
  dialect: ArabicDialect | null;
  setLocale: (locale: SupportedLocale) => void;
  setDialect: (dialect: ArabicDialect) => void;
  speak: (text: string) => void;
  stopSpeaking: () => void;
  startListening: () => void;
  stopListening: () => void;
  listening: boolean;
  speechRecognitionAvailable: boolean;
  speechSynthesisAvailable: boolean;
};

const LanguageVoiceContext = createContext<LanguageVoiceContextValue | null>(null);

type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: any) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
};

type RecognitionConstructor = new () => SpeechRecognitionLike;

function recognitionConstructor(): RecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  const candidate = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  return typeof candidate === "function" ? candidate : null;
}

function insertTranscript(text: string) {
  const active = document.activeElement as HTMLInputElement | HTMLTextAreaElement | HTMLElement | null;
  if (active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement) {
    const start = active.selectionStart ?? active.value.length;
    const end = active.selectionEnd ?? start;
    active.setRangeText(text, start, end, "end");
    active.dispatchEvent(new Event("input", { bubbles: true }));
    return;
  }
  if (active?.isContentEditable) {
    document.execCommand("insertText", false, text);
    active.dispatchEvent(new Event("input", { bubbles: true }));
    return;
  }
  window.dispatchEvent(new CustomEvent("aionex:voice-transcript", { detail: { text } }));
}

export default function LanguageVoiceProvider({ children }: PropsWithChildren) {
  const [decision, setDecision] = useState<LocaleDecision>(() =>
    decideLocale({ browserLocales: ["en-US"] }),
  );
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function detect() {
      let context: LocaleContextResponse = {};
      try {
        const response = await fetch("/api/v1/locale/context", { credentials: "include" });
        if (response.ok) context = (await response.json()) as LocaleContextResponse;
      } catch {
        context = {};
      }
      if (cancelled) return;
      const explicitLocale = window.localStorage.getItem(LOCALE_KEY);
      const storedDialect = window.localStorage.getItem(DIALECT_KEY) as ArabicDialect | null;
      const next = decideLocale({
        explicitLocale,
        browserLocales: navigator.languages?.length ? navigator.languages : [navigator.language],
        ipCountry: context.ip_country,
      });
      const locale = storedDialect ? dialectLocale(next.locale, storedDialect) : next.locale;
      setDecision({ ...next, locale, dialect: storedDialect ?? next.dialect, direction: locale.startsWith("ar-") || locale === "ur-PK" ? "rtl" : "ltr" });
    }
    void detect();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    document.documentElement.lang = decision.locale;
    document.documentElement.dir = decision.direction;
    document.body.dataset.locale = decision.locale;
    if (decision.dialect) document.body.dataset.dialect = decision.dialect;
    else delete document.body.dataset.dialect;
  }, [decision]);

  const setLocale = useCallback((locale: SupportedLocale) => {
    window.localStorage.setItem(LOCALE_KEY, locale);
    setDecision((current) => ({
      ...current,
      locale,
      direction: locale.startsWith("ar-") || locale === "ur-PK" ? "rtl" : "ltr",
      source: "explicit",
      confidence: 1,
      dialect: locale.startsWith("ar-") ? current.dialect ?? "msa" : null,
    }));
  }, []);

  const setDialect = useCallback((dialect: ArabicDialect) => {
    window.localStorage.setItem(DIALECT_KEY, dialect);
    setDecision((current) => {
      const locale = dialectLocale(current.locale.startsWith("ar-") ? current.locale : "ar-AE", dialect);
      return { ...current, locale, dialect, direction: "rtl", source: "explicit", confidence: 1 };
    });
  }, []);

  const stopSpeaking = useCallback(() => {
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
  }, []);

  const speak = useCallback(
    (text: string) => {
      const normalized = text.trim();
      if (!normalized || typeof window === "undefined" || !("speechSynthesis" in window)) return;
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(normalized);
      utterance.lang = decision.locale;
      const voices = window.speechSynthesis.getVoices();
      const exact = voices.find((voice) => voice.lang.toLowerCase() === decision.locale.toLowerCase());
      const sameLanguage = voices.find((voice) => voice.lang.toLowerCase().startsWith(decision.locale.slice(0, 2).toLowerCase()));
      utterance.voice = exact ?? sameLanguage ?? null;
      window.speechSynthesis.speak(utterance);
    },
    [decision.locale],
  );

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setListening(false);
  }, []);

  const startListening = useCallback(() => {
    const Constructor = recognitionConstructor();
    if (!Constructor) return;
    recognitionRef.current?.abort();
    const recognition = new Constructor();
    recognition.lang = decision.locale;
    recognition.interimResults = false;
    recognition.continuous = false;
    recognition.onresult = (event: any) => {
      const transcript = String(event.results?.[0]?.[0]?.transcript ?? "").trim();
      if (!transcript) return;
      const dialect = detectArabicDialect(transcript);
      if (dialect && dialect !== "msa") setDialect(dialect);
      insertTranscript(transcript);
    };
    recognition.onend = () => {
      recognitionRef.current = null;
      setListening(false);
    };
    recognition.onerror = () => {
      recognitionRef.current = null;
      setListening(false);
    };
    recognitionRef.current = recognition;
    setListening(true);
    recognition.start();
  }, [decision.locale, setDialect]);

  useEffect(() => () => recognitionRef.current?.abort(), []);

  const value = useMemo<LanguageVoiceContextValue>(
    () => ({
      decision,
      locale: decision.locale,
      dialect: decision.dialect,
      setLocale,
      setDialect,
      speak,
      stopSpeaking,
      startListening,
      stopListening,
      listening,
      speechRecognitionAvailable: Boolean(recognitionConstructor()),
      speechSynthesisAvailable: typeof window !== "undefined" && "speechSynthesis" in window,
    }),
    [decision, listening, setDialect, setLocale, speak, startListening, stopListening, stopSpeaking],
  );

  return <LanguageVoiceContext.Provider value={value}>{children}</LanguageVoiceContext.Provider>;
}

export function useLanguageVoice(): LanguageVoiceContextValue {
  const context = useContext(LanguageVoiceContext);
  if (!context) throw new Error("useLanguageVoice must be used within LanguageVoiceProvider");
  return context;
}

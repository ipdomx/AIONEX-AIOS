"use client";

import { Languages, Mic, MicOff, Volume2, VolumeX } from "lucide-react";

import { useLanguageVoice } from "@/components/providers/LanguageVoiceProvider";
import {
  ArabicDialect,
  SUPPORTED_LOCALES,
  SupportedLocale,
} from "@/lib/locale-engine";

const LOCALE_LABELS: Record<SupportedLocale, string> = {
  "en-US": "English",
  "ar-EG": "العربية — مصر",
  "ar-AE": "العربية — الخليج",
  "ar-SA": "العربية — السعودية",
  "ar-MA": "العربية — المغرب العربي",
  "fr-FR": "Français",
  "es-ES": "Español",
  "de-DE": "Deutsch",
  "hi-IN": "हिन्दी",
  "ur-PK": "اردو",
  "tr-TR": "Türkçe",
  "zh-CN": "中文",
};

const DIALECTS: Array<{ value: ArabicDialect; label: string }> = [
  { value: "msa", label: "العربية الفصحى" },
  { value: "egyptian", label: "المصرية" },
  { value: "gulf", label: "الخليجية" },
  { value: "saudi", label: "السعودية" },
  { value: "levantine", label: "الشامية" },
  { value: "iraqi", label: "العراقية" },
  { value: "maghrebi", label: "المغاربية" },
];

export default function LanguageVoiceControls() {
  const {
    locale,
    dialect,
    setLocale,
    setDialect,
    listening,
    startListening,
    stopListening,
    speak,
    stopSpeaking,
    speechRecognitionAvailable,
    speechSynthesisAvailable,
  } = useLanguageVoice();

  function speakSelection() {
    const selected = window.getSelection()?.toString().trim();
    if (selected) speak(selected);
  }

  return (
    <div
      className="fixed bottom-4 end-4 z-[90] flex max-w-[calc(100vw-2rem)] flex-wrap items-center gap-2 rounded-2xl border border-white/10 bg-space-900/95 p-2 shadow-2xl backdrop-blur-xl"
      role="group"
      aria-label="Language and voice controls"
    >
      <Languages className="h-4 w-4 text-cyan-300" aria-hidden="true" />
      <select
        value={locale}
        onChange={(event) => setLocale(event.target.value as SupportedLocale)}
        className="max-w-44 rounded-lg border border-white/10 bg-space-950 px-2 py-1.5 text-xs text-white outline-none"
        aria-label="Interface language"
      >
        {SUPPORTED_LOCALES.map((item) => (
          <option key={item} value={item}>
            {LOCALE_LABELS[item]}
          </option>
        ))}
      </select>
      {locale.startsWith("ar-") && (
        <select
          value={dialect ?? "msa"}
          onChange={(event) => setDialect(event.target.value as ArabicDialect)}
          className="max-w-36 rounded-lg border border-white/10 bg-space-950 px-2 py-1.5 text-xs text-white outline-none"
          aria-label="Arabic dialect"
        >
          {DIALECTS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      )}
      {speechRecognitionAvailable && (
        <button
          type="button"
          onClick={listening ? stopListening : startListening}
          className="rounded-lg border border-white/10 bg-white/5 p-2 text-white hover:bg-white/10"
          aria-label={listening ? "Stop voice input" : "Start voice input"}
          title="Voice input is inserted into the focused field"
        >
          {listening ? (
            <MicOff className="h-4 w-4 text-red-300" />
          ) : (
            <Mic className="h-4 w-4 text-cyan-300" />
          )}
        </button>
      )}
      {speechSynthesisAvailable && (
        <>
          <button
            type="button"
            onClick={speakSelection}
            className="rounded-lg border border-white/10 bg-white/5 p-2 text-white hover:bg-white/10"
            aria-label="Read selected text aloud"
            title="Select text, then press to read it aloud"
          >
            <Volume2 className="h-4 w-4 text-cyan-300" />
          </button>
          <button
            type="button"
            onClick={stopSpeaking}
            className="rounded-lg border border-white/10 bg-white/5 p-2 text-white hover:bg-white/10"
            aria-label="Stop reading aloud"
          >
            <VolumeX className="h-4 w-4 text-white/60" />
          </button>
        </>
      )}
    </div>
  );
}

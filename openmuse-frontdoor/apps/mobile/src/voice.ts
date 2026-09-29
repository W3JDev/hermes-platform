import { useCallback, useRef, useState } from "react";
import { Platform } from "react-native";
import { API_URL } from "./api";

export interface VoiceState {
  isListening: boolean;
  isSpeaking: boolean;
  provider: "minimax" | "grok";
  error?: string;
}

/**
 * Hermes Muse Real-Time Voice Hook
 * Uses MiniMax HD Audio & Grok Voice for ultra-fast, realistic speech synthesis,
 * and browser/native Web Speech for real-time dictation.
 */
export function useHermesVoice() {
  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [provider, setProvider] = useState<"minimax" | "grok">("minimax");
  const [error, setError] = useState<string>();

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const recognitionRef = useRef<any>(null);

  /**
   * Speak text out loud using MiniMax HD voice or Grok voice.
   */
  const speak = useCallback(
    async (text: string, voiceProvider: "minimax" | "grok" = provider) => {
      if (!text?.trim()) return;

      try {
        setIsSpeaking(true);
        setError(undefined);

        const res = await fetch(
          `${API_URL}/api/voice/speak?provider=${voiceProvider}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              text: text.slice(0, 2000),
              voiceId: voiceProvider === "minimax" ? "male-qn-qingse" : "grok-neutral",
            }),
          }
        );

        if (!res.ok) {
          throw new Error(`Voice synthesis failed: HTTP ${res.status}`);
        }

        const blob = await res.blob();
        const audioUrl = URL.createObjectURL(blob);

        if (Platform.OS === "web") {
          if (audioRef.current) {
            audioRef.current.pause();
          }
          const audio = new Audio(audioUrl);
          audioRef.current = audio;
          audio.onended = () => setIsSpeaking(false);
          audio.onerror = () => setIsSpeaking(false);
          await audio.play();
        } else {
          // Native fallback or React Native sound
          setIsSpeaking(false);
        }
      } catch (err: any) {
        console.warn("[HermesVoice] Speak error:", err);
        setError(err.message);
        setIsSpeaking(false);
      }
    },
    [provider]
  );

  /**
   * Start microphone dictation (Web Speech / Native speech)
   */
  const startListening = useCallback(
    (onTranscript: (text: string) => void) => {
      setError(undefined);

      if (Platform.OS === "web") {
        const SpeechRec =
          (window as any).SpeechRecognition ||
          (window as any).webkitSpeechRecognition;

        if (!SpeechRec) {
          setError("Speech recognition is not supported in this browser.");
          return;
        }

        try {
          const rec = new SpeechRec();
          rec.continuous = true;
          rec.interimResults = true;
          rec.lang = "en-US";

          rec.onresult = (event: any) => {
            let final = "";
            for (let i = event.resultIndex; i < event.results.length; i++) {
              if (event.results[i].isFinal) {
                final += event.results[i][0].transcript;
              }
            }
            if (final) {
              onTranscript(final);
            }
          };

          rec.onerror = (e: any) => {
            console.warn("[HermesVoice] Dictation error:", e);
            setIsListening(false);
          };

          rec.onend = () => {
            setIsListening(false);
          };

          rec.start();
          recognitionRef.current = rec;
          setIsListening(true);
        } catch (e: any) {
          setError(e.message);
          setIsListening(false);
        }
      }
    },
    []
  );

  const stopListening = useCallback(() => {
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {}
      recognitionRef.current = null;
    }
    setIsListening(false);
  }, []);

  const stopSpeaking = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    setIsSpeaking(false);
  }, []);

  return {
    isListening,
    isSpeaking,
    provider,
    setProvider,
    error,
    speak,
    startListening,
    stopListening,
    stopSpeaking,
  };
}

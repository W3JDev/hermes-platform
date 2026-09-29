import { z } from "zod";

export interface MiniMaxVoiceConfig {
  apiKey: string;
  baseUrl?: string;
  voiceId?: string;
  speed?: number;
  vol?: number;
}

export const speakRequestSchema = z.object({
  text: z.string().min(1).max(10000),
  voiceId: z.string().optional().default("English_expressive_narrator"),
  speed: z.number().min(0.5).max(2.0).optional().default(1.0),
  vol: z.number().min(0.1).max(2.0).optional().default(1.0),
  stream: z.boolean().optional().default(false),
});

/**
 * MiniMax Real-Time Voice Synthesis Service
 * Uses official MiniMax t2a_v2 endpoint with hex MP3 decoding.
 */
export class MiniMaxVoiceService {
  private apiKey: string;
  private baseUrl: string;
  private defaultVoice: string;

  constructor(config: MiniMaxVoiceConfig) {
    this.apiKey = config.apiKey;
    this.baseUrl = config.baseUrl || "https://api.minimax.io/v1";
    this.defaultVoice = config.voiceId || "English_expressive_narrator";
  }

  isConfigured(): boolean {
    return Boolean(this.apiKey && this.apiKey.trim().length > 0);
  }

  /**
   * Synthesize text to speech using official MiniMax t2a_v2 API.
   * Returns audio buffer (MP3).
   */
  async synthesize(text: string, voiceId?: string): Promise<Buffer> {
    if (!this.isConfigured()) {
      throw new Error("MiniMax API key not configured");
    }

    const selectedVoice = voiceId || this.defaultVoice;
    const url = `${this.baseUrl.replace(/\/$/, "")}/t2a_v2`;

    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify({
        model: "speech-01-hd",
        text,
        stream: false,
        voice_setting: {
          voice_id: selectedVoice,
          speed: 1.0,
          vol: 1.0,
          pitch: 0,
        },
        audio_setting: {
          sample_rate: 32000,
          bitrate: 128000,
          format: "mp3",
          channel: 1,
        },
      }),
    });

    if (!response.ok) {
      const err = await response.text().catch(() => "");
      throw new Error(`MiniMax Voice API HTTP error (${response.status}): ${err}`);
    }

    const payload = (await response.json()) as {
      data?: { audio?: string };
      base_resp?: { status_code: number; status_msg: string };
    };

    if (payload.base_resp && payload.base_resp.status_code !== 0 && payload.base_resp.status_code !== 1000) {
      // 1000 is success in some MiniMax regions, 0 is standard
      if (!payload.data?.audio) {
        throw new Error(`MiniMax Voice synthesis error: ${payload.base_resp.status_msg} (code ${payload.base_resp.status_code})`);
      }
    }

    if (!payload.data?.audio) {
      throw new Error("MiniMax Voice API returned no audio data");
    }

    // MiniMax returns audio as hex string
    return Buffer.from(payload.data.audio, "hex");
  }
}

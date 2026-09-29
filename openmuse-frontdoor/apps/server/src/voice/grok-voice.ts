import { z } from "zod";

export interface GrokVoiceConfig {
  apiKey?: string;
  baseUrl?: string;
  model?: string;
}

/**
 * Grok (xAI) Voice & Real-Time Audio Service
 */
export class GrokVoiceService {
  private apiKey?: string;
  private baseUrl: string;
  private model: string;

  constructor(config: GrokVoiceConfig = {}) {
    this.apiKey = config.apiKey || process.env.XAI_API_KEY;
    this.baseUrl = config.baseUrl || "https://api.x.ai/v1";
    this.model = config.model || "grok-audio";
  }

  isConfigured(): boolean {
    return Boolean(this.apiKey);
  }

  /**
   * Synthesize speech using Grok / xAI audio endpoint
   */
  async synthesize(text: string, voice: string = "grok-neutral"): Promise<Buffer> {
    if (!this.apiKey) {
      throw new Error("Grok API key is not configured. Set XAI_API_KEY in your .env");
    }

    const res = await fetch(`${this.baseUrl}/audio/speech`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify({
        model: this.model,
        input: text,
        voice,
      }),
    });

    if (!res.ok) {
      const err = await res.text().catch(() => "");
      throw new Error(`Grok Voice API error (HTTP ${res.status}): ${err}`);
    }

    const data = await res.arrayBuffer();
    return Buffer.from(data);
  }
}

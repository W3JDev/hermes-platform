import { AbstractAgent } from "@ag-ui/client";
import { type BaseEvent, EventType, type RunAgentInput } from "@ag-ui/core";
import { Observable } from "rxjs";
import { randomUUID } from "node:crypto";

export interface HermesConfig {
  gatewayUrl: string;
  apiKey?: string;
  profile?: string;
  model?: string;
  minimaxApiKey?: string;
  minimaxBaseUrl?: string;
  xaiApiKey?: string;
}

/**
 * Hermes Native Adapter
 * Bridges Hermes Agent Core (Gateway REST & WebSocket) into the OpenMuse / AG-UI runtime.
 * Seamlessly integrates MiniMax & Grok models for resilient real-time reasoning.
 */
export class HermesAdapter extends AbstractAgent {
  private gatewayUrl: string;
  private apiKey?: string;
  private profile: string;
  private model?: string;
  private minimaxApiKey?: string;
  private minimaxBaseUrl: string;

  constructor(config: HermesConfig) {
    super({ agentId: "hermes" });
    this.gatewayUrl = config.gatewayUrl.replace(/\/+$/, "");
    this.apiKey = config.apiKey;
    this.profile = config.profile || "default";
    this.model = config.model;
    this.minimaxApiKey = config.minimaxApiKey;
    this.minimaxBaseUrl = config.minimaxBaseUrl || "https://api.minimax.io/v1";
  }

  /**
   * Health and connectivity probe for Hermes Gateway.
   */
  async probe(signal?: AbortSignal): Promise<{ ok: boolean; version?: string; model?: string; error?: string }> {
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (this.apiKey) headers["Authorization"] = `Bearer ${this.apiKey}`;

      const res = await fetch(`${this.gatewayUrl}/api/health`, { headers, signal });
      if (!res.ok) {
        return { ok: false, error: `Hermes Gateway returned HTTP ${res.status}` };
      }
      const data = (await res.json().catch(() => ({}))) as { version?: string; model?: string };
      return { ok: true, version: data.version || "0.21.4", model: data.model || this.model };
    } catch (err: any) {
      return { ok: false, error: err.message || "Failed to reach Hermes Gateway" };
    }
  }

  /**
   * Run an agent turn using AG-UI standard events.
   * Maps Hermes streaming tokens, thought logs, and tool executions directly into AG-UI messages.
   */
  run(input: RunAgentInput): Observable<BaseEvent> {
    return new Observable<BaseEvent>((subscriber) => {
      subscriber.next({
        type: EventType.RUN_STARTED,
        threadId: input.threadId,
        runId: input.runId,
      });

      const latestUserMsg = input.messages.filter((m) => m.role === "user").at(-1);
      const prompt = typeof latestUserMsg?.content === "string" ? latestUserMsg.content : "";
      const messageId = randomUUID();

      subscriber.next({
        type: EventType.TEXT_MESSAGE_START,
        messageId,
        role: "assistant",
      });

      const controller = new AbortController();

      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (this.apiKey) {
        headers["Authorization"] = `Bearer ${this.apiKey}`;
      }

      const body = {
        session_id: input.threadId,
        profile: this.profile,
        message: prompt,
        model: this.model,
        stream: true,
      };

      // 1. Try Hermes Gateway
      fetch(`${this.gatewayUrl}/api/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      })
        .then(async (response) => {
          if (!response.ok || !response.body) {
            throw new Error(`Hermes Gateway unavailable (HTTP ${response.status})`);
          }

          const reader = response.body.getReader();
          const decoder = new TextDecoder("utf-8");
          let buffer = "";

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            for (const line of lines) {
              const trimmed = line.trim();
              if (!trimmed || trimmed.startsWith(":")) continue;

              const payloadStr = trimmed.startsWith("data:") ? trimmed.slice(5).trim() : trimmed;
              if (payloadStr === "[DONE]") continue;

              try {
                const data = JSON.parse(payloadStr);

                if (data.delta || data.text) {
                  subscriber.next({
                    type: EventType.TEXT_MESSAGE_CONTENT,
                    messageId,
                    delta: data.delta || data.text,
                  });
                }

                if (data.tool_call_start || (data.tool && !data.tool_output)) {
                  const toolName = data.tool?.name || data.tool_name || "hermes_tool";
                  const toolCallId = data.tool?.id || randomUUID();
                  subscriber.next({
                    type: EventType.TOOL_CALL_START,
                    toolCallId,
                    toolCallName: toolName,
                    parentMessageId: messageId,
                  });
                  if (data.tool?.args) {
                    subscriber.next({
                      type: EventType.TOOL_CALL_ARGS,
                      toolCallId,
                      delta: JSON.stringify(data.tool.args),
                    });
                  }
                  subscriber.next({ type: EventType.TOOL_CALL_END, toolCallId });
                }

                if (data.tool_output || (data.tool && data.tool.output)) {
                  const toolCallId = data.tool?.id || randomUUID();
                  subscriber.next({
                    type: EventType.TOOL_CALL_RESULT,
                    toolCallId,
                    messageId: randomUUID(),
                    role: "tool",
                    content: typeof data.tool_output === "string" ? data.tool_output : JSON.stringify(data.tool_output || data.tool.output),
                  });
                }
              } catch {
                if (payloadStr) {
                  subscriber.next({
                    type: EventType.TEXT_MESSAGE_CONTENT,
                    messageId,
                    delta: payloadStr,
                  });
                }
              }
            }
          }

          subscriber.next({ type: EventType.TEXT_MESSAGE_END, messageId });
          subscriber.next({
            type: EventType.RUN_FINISHED,
            threadId: input.threadId,
            runId: input.runId,
          });
          subscriber.complete();
        })
        .catch(async () => {
          // 2. Seamless Fallback: MiniMax Intelligent Model
          try {
            await this.streamMiniMax(prompt, messageId, subscriber, controller.signal);
            subscriber.next({ type: EventType.TEXT_MESSAGE_END, messageId });
            subscriber.next({
              type: EventType.RUN_FINISHED,
              threadId: input.threadId,
              runId: input.runId,
            });
            subscriber.complete();
          } catch (miniMaxErr: any) {
            console.error("[HermesAdapter MiniMax Error]:", miniMaxErr);
            subscriber.next({
              type: EventType.TEXT_MESSAGE_CONTENT,
              messageId,
              delta: `I encountered an issue connecting to the model: ${miniMaxErr?.message || String(miniMaxErr)}`,
            });
            subscriber.next({ type: EventType.TEXT_MESSAGE_END, messageId });
            subscriber.next({
              type: EventType.RUN_FINISHED,
              threadId: input.threadId,
              runId: input.runId,
            });
            subscriber.complete();
          }
        });

      return () => {
        controller.abort();
      };
    });
  }

  private async streamMiniMax(
    prompt: string,
    messageId: string,
    subscriber: { next: (event: BaseEvent) => void },
    signal: AbortSignal,
  ): Promise<void> {
    if (!this.minimaxApiKey) {
      throw new Error("No MiniMax API key configured");
    }

    const url = `${this.minimaxBaseUrl.replace(/\/+$/, "")}/chat/completions`;
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.minimaxApiKey}`,
      },
      body: JSON.stringify({
        model: "MiniMax-Text-01",
        messages: [
          {
            role: "system",
            content:
              "You are Hermes Muse, an autonomous AI companion and personal agent. You combine Hermes agent intelligence with open-computer sandbox abilities and real-time voice. Keep your replies friendly, concise, and helpful.",
          },
          { role: "user", content: prompt },
        ],
        stream: true,
      }),
      signal,
    });

    if (!res.ok || !res.body) {
      throw new Error(`MiniMax chat failed (HTTP ${res.status})`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith(":")) continue;
        const payloadStr = trimmed.startsWith("data:") ? trimmed.slice(5).trim() : trimmed;
        if (payloadStr === "[DONE]") continue;

        try {
          const json = JSON.parse(payloadStr);
          const delta = json.choices?.[0]?.delta?.content;
          if (delta) {
            subscriber.next({
              type: EventType.TEXT_MESSAGE_CONTENT,
              messageId,
              delta,
            });
          }
        } catch {
          // ignore malformed chunks
        }
      }
    }
  }
}

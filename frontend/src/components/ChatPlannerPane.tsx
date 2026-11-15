"use client";

import React, { useEffect, useId, useRef, useState } from "react";
import {
  Bot,
  CheckCircle2,
  Cpu,
  CornerDownLeft,
  RefreshCw,
  Send,
  Sparkles,
  User,
} from "lucide-react";
import type { ChatMessage } from "@/types/trip";

interface ChatPlannerPaneProps {
  messages: ChatMessage[];
  isPlanning: boolean;
  onSendMessage: (message: string) => void;
}

const QUICK_PROMPTS = [
  "Plan a road trip from Mumbai to Mahabaleshwar in a 3 BHK villa",
  "Plan a hybrid fly + drive trip from Bengaluru to Rishikesh",
  "Switch villa to 3 BHK within 20-28k",
  "Switch dietary to pure veg",
];

export function ChatPlannerPane({
  messages,
  isPlanning,
  onSendMessage,
}: ChatPlannerPaneProps) {
  const [draft, setDraft] = useState("");
  const chatInputId = useId();
  const formRef = useRef<HTMLFormElement | null>(null);
  const scrollEndRef = useRef<HTMLDivElement | null>(null);
  const lastCompositionEndRef = useRef<number | null>(null);

  useEffect(() => {
    scrollEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, isPlanning]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed || isPlanning) return;
    setDraft("");
    onSendMessage(trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();

      // IME-safe enter-to-submit + Safari WebKit bug 165004 protections
      if (e.nativeEvent.isComposing || e.keyCode === 229) {
        return;
      }
      if (
        lastCompositionEndRef.current !== null &&
        Math.abs(e.nativeEvent.timeStamp - lastCompositionEndRef.current) < 50
      ) {
        return;
      }

      formRef.current?.requestSubmit();
    }
  };

  return (
    <aside className="chat-sidebar" aria-label="Conversational Multi-Phase Trip Planner">
      {/* Agent Header */}
      <div
        style={{
          padding: "0.85rem 1rem",
          borderBlockEnd: "1px solid var(--border-subtle)",
          background: "var(--bg-elevated)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "0.5rem",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.55rem" }}>
          <Cpu size={18} aria-hidden="true" color="var(--accent-primary)" />
          <div>
            <div style={{ fontWeight: 800, fontSize: "0.88rem" }}>
              TripSage Planner Agent
            </div>
            <div style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
              3-Phase Tool-Calling · Live Form Sync
            </div>
          </div>
        </div>
        <span className="badge badge-emerald">
          <Sparkles size={11} aria-hidden="true" /> Active
        </span>
      </div>

      {/* Conversation Feed */}
      <div
        className="pane-scroll"
        style={{
          flex: 1,
          padding: "0.95rem",
          display: "flex",
          flexDirection: "column",
          gap: "0.9rem",
        }}
      >
        <ul
          role="list"
          style={{
            listStyle: "none",
            margin: 0,
            padding: 0,
            display: "flex",
            flexDirection: "column",
            gap: "0.9rem",
          }}
        >
          {messages.map((m) => {
            const isUser = m.role === "user";
            return (
              <li
                key={m.id}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.45rem",
                  padding: "0.8rem 0.9rem",
                  borderRadius: "0.85rem",
                  background: isUser ? "var(--bg-subtle)" : "var(--bg-elevated)",
                  border: `1px solid ${
                    isUser ? "var(--border-subtle)" : "var(--border-strong)"
                  }`,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    fontSize: "0.73rem",
                    color: "var(--text-muted)",
                    fontWeight: 700,
                  }}
                >
                  <span style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
                    {isUser ? (
                      <User size={13} aria-hidden="true" />
                    ) : (
                      <Bot size={14} aria-hidden="true" color="var(--accent-primary)" />
                    )}
                    {isUser ? "You" : "TripSage Multi-Phase Agent"}
                  </span>
                  <span>{m.timestamp}</span>
                </div>

                {/* Extracted Parameter Sync Chips */}
                {m.extracted_updates && m.extracted_updates.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
                    {m.extracted_updates.map((upd) => (
                      <span key={upd} className="badge badge-route" style={{ fontSize: "0.69rem" }}>
                        <CheckCircle2 size={11} aria-hidden="true" /> {upd}
                      </span>
                    ))}
                  </div>
                )}

                {/* Multi-Phase Planner Tool Execution Trace */}
                {m.tool_trace && m.tool_trace.length > 0 && (
                  <details
                    open={m.id === "turn-4"}
                    style={{
                      borderRadius: "0.65rem",
                      border: "1px solid var(--border-subtle)",
                      background: "var(--bg-surface)",
                      padding: "0.5rem 0.65rem",
                      fontSize: "0.75rem",
                    }}
                  >
                    <summary
                      style={{
                        cursor: "pointer",
                        fontWeight: 700,
                        color: "var(--accent-primary)",
                      }}
                    >
                      Executed {m.tool_trace.length} Planner Tools (3 Phases)
                    </summary>
                    <ol
                      role="list"
                      style={{
                        listStyle: "none",
                        margin: "0.55rem 0 0",
                        padding: 0,
                        display: "flex",
                        flexDirection: "column",
                        gap: "0.45rem",
                      }}
                    >
                      {m.tool_trace.map((t, idx) => (
                        <li
                          key={`${t.tool_name}-${idx}`}
                          style={{
                            padding: "0.45rem 0.55rem",
                            borderRadius: "0.5rem",
                            background: "var(--bg-elevated)",
                            borderInlineStart: `3px solid ${
                              t.status === "pivoted"
                                ? "var(--gold-accent)"
                                : "var(--accent-primary)"
                            }`,
                          }}
                        >
                          <div
                            style={{
                              display: "flex",
                              justifyContent: "space-between",
                              fontWeight: 700,
                              fontSize: "0.72rem",
                            }}
                          >
                            <code>{t.tool_name}()</code>
                            <span style={{ color: "var(--text-muted)" }}>{t.latency_ms}ms</span>
                          </div>
                          <div style={{ color: "var(--text-muted)", fontSize: "0.69rem" }}>
                            {t.phase}
                          </div>
                          <div style={{ marginBlockStart: "0.18rem", color: "var(--text-secondary)" }}>
                            {t.finding_summary}
                          </div>
                        </li>
                      ))}
                    </ol>
                  </details>
                )}

                <div
                  style={{
                    fontSize: "0.84rem",
                    whiteSpace: "pre-line",
                    color: "var(--text-primary)",
                  }}
                >
                  {m.content}
                </div>

                {m.follow_up_questions && m.follow_up_questions.length > 0 && (
                  <ol
                    style={{
                      margin: "0.25rem 0 0",
                      paddingInlineStart: "1.15rem",
                      fontSize: "0.8rem",
                      color: "var(--text-secondary)",
                      display: "flex",
                      flexDirection: "column",
                      gap: "0.25rem",
                    }}
                  >
                    {m.follow_up_questions.map((q, idx) => (
                      <li key={idx}>{q}</li>
                    ))}
                  </ol>
                )}
              </li>
            );
          })}

          {isPlanning && (
            <li
              aria-live="polite"
              style={{
                padding: "0.75rem 0.9rem",
                borderRadius: "0.75rem",
                background: "var(--bg-elevated)",
                border: "1px solid var(--border-subtle)",
                fontSize: "0.82rem",
                display: "flex",
                alignItems: "center",
                gap: "0.5rem",
                color: "var(--accent-primary)",
                fontWeight: 600,
              }}
            >
              <RefreshCw size={15} aria-hidden="true" />
              Running 3-phase planner &amp; channel rate deduplicator...
            </li>
          )}
        </ul>
        <div ref={scrollEndRef} />
      </div>

      {/* Quick Prompts + IME-Safe Chat Form */}
      <div
        style={{
          padding: "0.75rem 0.9rem",
          borderBlockStart: "1px solid var(--border-subtle)",
          background: "var(--bg-elevated)",
          display: "flex",
          flexDirection: "column",
          gap: "0.55rem",
        }}
      >
        <div
          style={{
            display: "flex",
            gap: "0.35rem",
            overflowX: "auto",
            paddingBlockEnd: "0.15rem",
          }}
        >
          {QUICK_PROMPTS.map((qp) => (
            <button
              key={qp}
              type="button"
              className="btn"
              disabled={isPlanning}
              onClick={() => onSendMessage(qp)}
              style={{
                minBlockSize: "1.85rem",
                padding: "0.2rem 0.55rem",
                fontSize: "0.71rem",
                whiteSpace: "nowrap",
              }}
            >
              {qp}
            </button>
          ))}
        </div>

        <form
          ref={formRef}
          onSubmit={handleSubmit}
          action="/api/chat"
          method="POST"
          style={{ display: "flex", gap: "0.45rem", alignItems: "flex-end" }}
        >
          <label htmlFor={chatInputId} className="visually-hidden">
            Describe trip updates, stay preferences, or itinerary changes
          </label>
          <textarea
            id={chatInputId}
            name="message"
            rows={2}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onCompositionEnd={(e) => {
              lastCompositionEndRef.current = e.nativeEvent.timeStamp;
            }}
            onKeyDown={handleKeyDown}
            placeholder="Chat to adjust stays, budget, mode, or stops..."
            className="chat-textarea"
            style={{ flex: 1, resize: "vertical", minBlockSize: "3rem" }}
          />
          <button
            type="submit"
            disabled={isPlanning}
            className="btn btn-primary"
            style={{ minBlockSize: "3rem", paddingInline: "0.9rem" }}
            aria-label="Send message to planner"
          >
            <Send size={16} aria-hidden="true" />
            <CornerDownLeft size={13} aria-hidden="true" />
          </button>
        </form>
      </div>
    </aside>
  );
}

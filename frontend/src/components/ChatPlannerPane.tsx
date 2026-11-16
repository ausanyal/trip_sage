"use client";

import React, { useEffect, useId, useRef, useState } from "react";
import {
  ArrowUpRight,
  Bot,
  CheckCircle2,
  Cpu,
  CornerDownLeft,
  RefreshCw,
  Send,
  Sparkles,
  User,
} from "lucide-react";
import type { ChatMessage, LivePhaseStatus, PersonaMode } from "@/types/trip";

interface ChatPlannerPaneProps {
  messages: ChatMessage[];
  isPlanning: boolean;
  livePhase?: LivePhaseStatus | null;
  personaMode: PersonaMode;
  onChangePersonaMode: (mode: PersonaMode) => void;
  onSendMessage: (message: string) => void;
}

const PERSONA_OPTIONS: Array<{ id: PersonaMode; label: string; title: string }> = [
  { id: "advisor", label: "Advisor", title: "Luxury & Quant Travel Strategist" },
  { id: "eli5", label: "ELI5", title: "Plain-English Family Analogy Mode" },
  { id: "debate", label: "Debate", title: "Pareto Knee vs. Runner-Up Committee Debate" },
  { id: "devil", label: "Risk Audit", title: "Pre-Mortem Risk, Checkpost & Fatigue Auditor" },
];

const QUICK_PROMPTS = [
  "Why does #1 win on landed fee math?",
  "Compare top 2 options in Debate mode",
  "Audit hidden risks & fatigue",
  "Search more similar places to stay",
];

function renderInlineTokens(raw: string): React.ReactNode {
  const parts = raw.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return (
        <code
          key={i}
          style={{
            padding: "0.08rem 0.34rem",
            borderRadius: "0.32rem",
            background: "var(--bg-subtle)",
            fontSize: "0.79rem",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    return <React.Fragment key={i}>{part}</React.Fragment>;
  });
}

function renderRichMarkdown(raw: string): React.ReactNode {
  const lines = raw.split("\n");
  const blocks: React.ReactNode[] = [];
  let listItems: string[] = [];

  const flushList = (keyPrefix: string) => {
    if (listItems.length === 0) return;
    const copy = listItems;
    listItems = [];
    blocks.push(
      <ul
        key={keyPrefix}
        style={{
          margin: "0.2rem 0",
          paddingInlineStart: "1.1rem",
          display: "flex",
          flexDirection: "column",
          gap: "0.22rem",
        }}
      >
        {copy.map((li, idx) => (
          <li key={idx}>{renderInlineTokens(li)}</li>
        ))}
      </ul>
    );
  };

  lines.forEach((line, idx) => {
    const trimmed = line.trim();
    if (!trimmed) {
      flushList(`list-${idx}`);
      return;
    }
    if (trimmed.startsWith("### ")) {
      flushList(`list-${idx}`);
      blocks.push(
        <div
          key={`h3-${idx}`}
          style={{
            fontWeight: 800,
            fontSize: "0.84rem",
            marginBlockStart: blocks.length > 0 ? "0.35rem" : 0,
            color: "var(--accent-primary)",
          }}
        >
          {renderInlineTokens(trimmed.slice(4))}
        </div>
      );
      return;
    }
    if (trimmed.startsWith("- ") || trimmed.startsWith("• ")) {
      listItems.push(trimmed.slice(2));
      return;
    }
    flushList(`list-${idx}`);
    blocks.push(
      <p key={`p-${idx}`} style={{ margin: 0, lineHeight: 1.48 }}>
        {renderInlineTokens(trimmed)}
      </p>
    );
  });
  flushList("list-final");
  return <div style={{ display: "flex", flexDirection: "column", gap: "0.38rem" }}>{blocks}</div>;
}

export function ChatPlannerPane({
  messages,
  isPlanning,
  livePhase,
  personaMode,
  onChangePersonaMode,
  onSendMessage,
}: ChatPlannerPaneProps) {
  const [draft, setDraft] = useState("");
  const chatInputId = useId();
  const formRef = useRef<HTMLFormElement | null>(null);
  const scrollEndRef = useRef<HTMLDivElement | null>(null);
  const lastCompositionEndRef = useRef<number | null>(null);

  useEffect(() => {
    scrollEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, isPlanning, livePhase?.phase]);

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
          padding: "0.8rem 1rem",
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
              TripSage Reasoning Copilot
            </div>
            <div style={{ fontSize: "0.71rem", color: "var(--text-muted)" }}>
              3-Stage Gemini + Vertex AI · Pareto + VRPTW
            </div>
          </div>
        </div>
        <span className="badge badge-emerald">
          <Sparkles size={11} aria-hidden="true" /> v3.2 AI
        </span>
      </div>

      {/* Material 3 Persona Reasoning Lens Bar */}
      <div className="m3-persona-bar" role="group" aria-label="Reasoning persona mode">
        {PERSONA_OPTIONS.map((p) => (
          <button
            key={p.id}
            type="button"
            className="m3-persona-pill"
            aria-pressed={personaMode === p.id}
            title={p.title}
            onClick={() => onChangePersonaMode(p.id)}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Conversation Feed */}
      <div
        className="pane-scroll"
        style={{
          flex: 1,
          padding: "0.9rem",
          display: "flex",
          flexDirection: "column",
          gap: "0.85rem",
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
            gap: "0.85rem",
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
                  borderRadius: "0.95rem",
                  background: isUser ? "var(--bg-subtle)" : "var(--bg-elevated)",
                  border: `1px solid ${
                    isUser ? "var(--border-subtle)" : "var(--border-strong)"
                  }`,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: "0.35rem",
                    fontSize: "0.72rem",
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
                    {isUser ? "You" : m.engine_label || "TripSage Reasoning Agent"}
                  </span>
                  <span>{m.timestamp}</span>
                </div>

                {/* Extracted Parameter Sync Chips */}
                {m.extracted_updates && m.extracted_updates.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "0.32rem" }}>
                    {m.extracted_updates.map((upd) => (
                      <span key={upd} className="badge badge-route" style={{ fontSize: "0.68rem" }}>
                        <CheckCircle2 size={11} aria-hidden="true" /> {upd}
                      </span>
                    ))}
                  </div>
                )}

                {/* Multi-Phase Planner Tool Execution Trace */}
                {m.tool_trace && m.tool_trace.length > 0 && (
                  <details
                    style={{
                      borderRadius: "0.65rem",
                      border: "1px solid var(--border-subtle)",
                      background: "var(--bg-surface)",
                      padding: "0.48rem 0.65rem",
                      fontSize: "0.74rem",
                    }}
                  >
                    <summary
                      style={{
                        cursor: "pointer",
                        fontWeight: 700,
                        color: "var(--accent-primary)",
                      }}
                    >
                      Executed {m.tool_trace.length} Planner &amp; Reasoning Steps
                    </summary>
                    <ol
                      role="list"
                      style={{
                        listStyle: "none",
                        margin: "0.5rem 0 0",
                        padding: 0,
                        display: "flex",
                        flexDirection: "column",
                        gap: "0.4rem",
                      }}
                    >
                      {m.tool_trace.map((t, idx) => (
                        <li
                          key={`${t.tool_name}-${idx}`}
                          style={{
                            padding: "0.42rem 0.52rem",
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
                              fontSize: "0.71rem",
                            }}
                          >
                            <code>{t.tool_name}</code>
                            <span style={{ color: "var(--text-muted)" }}>{t.latency_ms}ms</span>
                          </div>
                          <div style={{ color: "var(--text-muted)", fontSize: "0.68rem" }}>
                            {t.phase}
                          </div>
                          <div style={{ marginBlockStart: "0.15rem", color: "var(--text-secondary)" }}>
                            {t.finding_summary}
                          </div>
                        </li>
                      ))}
                    </ol>
                  </details>
                )}

                <div style={{ fontSize: "0.83rem", color: "var(--text-primary)" }}>
                  {renderRichMarkdown(m.content)}
                </div>

                {m.follow_up_questions && m.follow_up_questions.length > 0 && (
                  <ol
                    style={{
                      margin: "0.2rem 0 0",
                      paddingInlineStart: "1.15rem",
                      fontSize: "0.79rem",
                      color: "var(--text-secondary)",
                      display: "flex",
                      flexDirection: "column",
                      gap: "0.22rem",
                    }}
                  >
                    {m.follow_up_questions.map((q, idx) => (
                      <li key={idx}>{renderInlineTokens(q)}</li>
                    ))}
                  </ol>
                )}

                {/* 1-Click Follow-Up Reasoning Chips */}
                {!isUser && m.suggested_prompts && m.suggested_prompts.length > 0 && (
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: "0.3rem",
                      marginBlockStart: "0.25rem",
                    }}
                  >
                    {m.suggested_prompts.slice(0, 3).map((sp) => (
                      <button
                        key={sp}
                        type="button"
                        disabled={isPlanning}
                        className="m3-followup-chip"
                        onClick={() => onSendMessage(sp)}
                      >
                        <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
                          <ArrowUpRight size={12} aria-hidden="true" color="var(--accent-primary)" />
                          <span>{sp}</span>
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </li>
            );
          })}

          {isPlanning && (
            <li
              aria-live="polite"
              style={{
                padding: "0.8rem 0.95rem",
                borderRadius: "0.85rem",
                background: "var(--bg-elevated)",
                border: "1px solid var(--accent-primary)",
                fontSize: "0.8rem",
                display: "flex",
                flexDirection: "column",
                gap: "0.35rem",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.45rem",
                  color: "var(--accent-primary)",
                  fontWeight: 700,
                }}
              >
                <RefreshCw size={14} aria-hidden="true" className="spin-icon" />
                <span>{livePhase?.phase ?? "Phase 1 · Intent & Constraints"}</span>
              </div>
              <div style={{ color: "var(--text-secondary)", fontSize: "0.75rem" }}>
                {livePhase?.detail ??
                  "Streaming OSRM routing, cross-OTA rate deduplication & Gemini reasoning..."}
              </div>
            </li>
          )}
        </ul>
        <div ref={scrollEndRef} />
      </div>

      {/* Quick Prompts + IME-Safe Chat Form */}
      <div
        style={{
          padding: "0.7rem 0.9rem",
          borderBlockStart: "1px solid var(--border-subtle)",
          background: "var(--bg-elevated)",
          display: "flex",
          flexDirection: "column",
          gap: "0.5rem",
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
                minBlockSize: "1.8rem",
                padding: "0.18rem 0.55rem",
                fontSize: "0.7rem",
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
            Ask a travel question, compare blueprints, or update your itinerary
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
            placeholder="Ask why an option wins, audit risks, or update any city/stay/budget..."
            className="chat-textarea"
            style={{ flex: 1, resize: "vertical", minBlockSize: "2.9rem" }}
          />
          <button
            type="submit"
            disabled={isPlanning}
            className="btn btn-primary"
            style={{ minBlockSize: "2.9rem", paddingInline: "0.85rem", borderRadius: "999px" }}
            aria-label="Send message to planner"
          >
            <Send size={15} aria-hidden="true" />
            <CornerDownLeft size={12} aria-hidden="true" />
          </button>
        </form>
      </div>
    </aside>
  );
}

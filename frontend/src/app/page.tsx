"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Award,
  Car,
  CheckCircle2,
  Compass,
  ExternalLink,
  Flame,
  Fuel,
  Hotel,
  Layers,
  MapPin,
  Moon,
  Mountain,
  Plane,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Sun,
  TrendingDown,
  Utensils,
} from "lucide-react";
import presetsRaw from "@/data/presets.json";
import { ChatPlannerPane } from "@/components/ChatPlannerPane";
import { DealArbitrageDialog } from "@/components/DealArbitrageDialog";
import { RouteCorridorMap } from "@/components/RouteCorridorMap";
import { TripParametersDrawer } from "@/components/TripParametersDrawer";
import type {
  ChatMessage,
  OptimizationResponse,
  StayCandidate,
  TimelineStop,
  TripSpec,
} from "@/types/trip";

const INITIAL_PRESETS = presetsRaw as unknown as {
  wayanad: OptimizationResponse;
  goa: OptimizationResponse;
};

function buildInitialWayanadConversation(
  wayanadData: OptimizationResponse
): ChatMessage[] {
  return [
    {
      id: "turn-1",
      role: "user",
      timestamp: "7:48 PM",
      content:
        "I want to plan a road trip with my family of 4 (2 adults and 2 kids of age 8 and 10) from Koramangala, Bangalore to Wayanad, Kerala from 12/21 to 12/26.\nOn our way we want to stay at Radisson, Mysore on 12/21 and on our way back again on 12/25, returning 12/26. In Wayanad we prefer Airbnb over hotel, eat both veg & non-veg, ok with high-end stays, and have our own car.",
    },
    {
      id: "turn-2",
      role: "assistant",
      timestamp: "7:49 PM",
      extracted_updates: [
        "Mode -> Pure Road Trip (Own Car)",
        "Stays -> Hybrid (Radisson Mysore + Wayanad Villa)",
        "Party -> 2A + 2C (Ages 8 & 10)",
      ],
      content:
        "Hydrated your family road trip and verified Radisson Mysore's southern NH766 exit + age-10 child cutoff. Quick 5 questions before running live channel arbitrage:\n1. Radisson room setup?\n2. Wayanad BHK & nightly target?\n3. Which car are you driving?\n4. Kids' mix: Safaris, Water/Ziplines, Moderate Climbs, Mysuru stops?\n5. Departure & return windows?",
    },
    {
      id: "turn-3",
      role: "user",
      timestamp: "8:04 PM",
      content:
        "1. Deluxe Room + extra bed · 2. 2 BHK, within 15-20k/night · 3. Jeep Meridian SUV · 4. Safari: No, Adventure/Water: No, Moderate Climbs: Yes, Mysuru Stops: No · 5. Leave Koramangala 2pm; leave Wayanad early afternoon; leave Mysore after lunch.",
    },
    {
      id: "turn-4",
      role: "assistant",
      timestamp: "8:05 PM",
      extracted_updates: [
        "Vehicle -> Jeep Meridian SUV (203mm)",
        "Villa -> 2 BHK (₹15k–₹20k/N)",
        "Climbs -> ON · Safaris/Water/Mysuru -> OFF",
        "Rollout -> 2:00 PM Koramangala",
      ],
      tool_trace: wayanadData.tool_trace,
      content:
        "Completed all 3 planner phases! Generated 3 Pareto-optimal blueprints.\n\nTop pick: The Sattva Grove (StayVista Direct) + Radisson Mysore split-channel booking at ₹86,400 core all-in — saving ₹12,237 vs. unoptimized OTA/Airbnb checkout fees AND dodging ~₹15,000 in mandatory Dec 24 5-star Christmas Eve Gala surcharges.",
    },
  ];
}

async function postPlannerApi(path: string, payload: unknown): Promise<Response> {
  try {
    const direct = await fetch(`http://127.0.0.1:8000${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (direct.ok) return direct;
  } catch {
    // Fall back to Next.js rewrite route when hosted behind same origin
  }
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

type ActiveTab = "itinerary" | "arbitrage" | "telemetry";
type StopFilter = "all" | "climb" | "dining" | "stay_drive";

export default function TripSageWorkspacePage() {
  const [activePresetKey, setActivePresetKey] = useState<"wayanad" | "goa">("wayanad");
  const [optimization, setOptimization] = useState<OptimizationResponse>(
    INITIAL_PRESETS.wayanad
  );
  const [selectedBlueprintIdx, setSelectedBlueprintIdx] = useState<number>(0);
  const [activeDay, setActiveDay] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>("itinerary");
  const [stopFilter, setStopFilter] = useState<StopFilter>("all");
  const [stopSearchQuery, setStopSearchQuery] = useState<string>("");
  const [showParamsDrawer, setShowParamsDrawer] = useState<boolean>(false);
  const [inspectedStay, setInspectedStay] = useState<StayCandidate | null>(null);
  const [isPlanning, setIsPlanning] = useState<boolean>(false);
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    buildInitialWayanadConversation(INITIAL_PRESETS.wayanad)
  );

  // Two-state color-scheme control (System vs. Pinned Opposite)
  const [pinnedScheme, setPinnedScheme] = useState<"light" | "dark" | null>(null);
  const [systemDark, setSystemDark] = useState<boolean>(true);

  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    setSystemDark(mq.matches);
    const saved = localStorage.getItem("color-scheme");
    if (saved === "light" || saved === "dark") {
      setPinnedScheme(saved);
    }

    const onChange = (ev: MediaQueryListEvent) => {
      setSystemDark(ev.matches);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const effectiveDark = pinnedScheme ? pinnedScheme === "dark" : systemDark;

  const toggleTheme = () => {
    const meta = document.querySelector('meta[name="color-scheme"]');
    if (pinnedScheme !== null) {
      // Return to system preference
      localStorage.removeItem("color-scheme");
      if (meta) meta.setAttribute("content", "light dark");
      delete document.documentElement.dataset.theme;
      setPinnedScheme(null);
    } else {
      // Pin exact opposite of current system setting
      const opposite: "light" | "dark" = systemDark ? "light" : "dark";
      localStorage.setItem("color-scheme", opposite);
      if (meta) meta.setAttribute("content", opposite);
      document.documentElement.dataset.theme = opposite;
      setPinnedScheme(opposite);
    }
  };

  const blueprint =
    optimization.blueprints[selectedBlueprintIdx] ?? optimization.blueprints[0];

  const handleSwitchPreset = (key: "wayanad" | "goa") => {
    setActivePresetKey(key);
    const data = key === "wayanad" ? INITIAL_PRESETS.wayanad : INITIAL_PRESETS.goa;
    setOptimization(data);
    setSelectedBlueprintIdx(0);
    setActiveDay(null);
    if (key === "wayanad") {
      setMessages(buildInitialWayanadConversation(INITIAL_PRESETS.wayanad));
    } else {
      setMessages([
        {
          id: "goa-1",
          role: "user",
          timestamp: "Now",
          content:
            "Show me a Hybrid Fly + Drive family trip from Bangalore to North Goa staying in a Blue Kite private pool villa.",
        },
        {
          id: "goa-2",
          role: "assistant",
          timestamp: "Now",
          extracted_updates: [
            "Mode -> Hybrid (Fly BLR->GOX + Rental SUV)",
            "Stay -> The Blue Kite Direct (Assagao)",
          ],
          tool_trace: data.tool_trace,
          content:
            "Matched La Soria by The Blue Kite (3 BHK Pool Villa, Assagao) across thebluekite.com, MakeMyTrip, and Airbnb — booking direct saves ₹16,400 over Airbnb's service fee! Plus flying into Mopa (GOX) instead of Dabolim (GOI) saves ₹6,200 and cuts your drive to Assagao to 28 mins.",
        },
      ]);
    }
  };

  const handleUpdateSpec = useCallback(
    async (nextSpec: TripSpec, reasonLabel: string) => {
      setOptimization((prev) => ({ ...prev, trip_spec: nextSpec }));
      setIsPlanning(true);
      try {
        const res = await postPlannerApi("/api/optimize", nextSpec);
        if (res.ok) {
          const updated: OptimizationResponse = await res.json();
          setOptimization(updated);
          setSelectedBlueprintIdx(0);
          setMessages((prev) => [
            ...prev,
            {
              id: `sync-${Date.now()}`,
              role: "assistant",
              timestamp: "Live Sync",
              extracted_updates: [reasonLabel],
              content: `Synced parameter update (${reasonLabel}) -> Re-solved Pareto frontier: ₹${updated.blueprints[0].total_core_landed_inr.toLocaleString(
                "en-IN"
              )} core all-in.`,
            },
          ]);
        }
      } catch {
        // Offline graceful fallback keeps UI interactive
      } finally {
        setIsPlanning(false);
      }
    },
    []
  );

  const handleSendMessage = useCallback(
    async (userText: string) => {
      const userMsg: ChatMessage = {
        id: `u-${Date.now()}`,
        role: "user",
        timestamp: "Just now",
        content: userText,
      };
      setMessages((prev) => [...prev, userMsg]);
      setIsPlanning(true);

      try {
        const res = await postPlannerApi("/api/chat", {
          message: userText,
          current_spec: optimization.trip_spec,
          history: messages.map((m) => ({
            role: m.role,
            content: m.content,
          })),
        });

        if (res.ok) {
          const payload = await res.json();
          if (payload.optimization) {
            setOptimization(payload.optimization);
            setSelectedBlueprintIdx(0);
            setActiveDay(null);
            if (
              payload.updated_spec.destination.toLowerCase().includes("goa")
            ) {
              setActivePresetKey("goa");
            } else if (
              payload.updated_spec.destination.toLowerCase().includes("wayanad")
            ) {
              setActivePresetKey("wayanad");
            }
          }
          setMessages((prev) => [
            ...prev,
            {
              id: `a-${Date.now()}`,
              role: "assistant",
              timestamp: "Just now",
              extracted_updates: payload.extracted_updates,
              tool_trace: payload.optimization?.tool_trace,
              follow_up_questions: payload.follow_up_questions,
              content: payload.assistant_reply,
            },
          ]);
        }
      } catch {
        setMessages((prev) => [
          ...prev,
          {
            id: `a-err-${Date.now()}`,
            role: "assistant",
            timestamp: "Offline",
            content:
              "FastAPI planner server on port 8000 is unreachable — displaying cached pre-computed optimization.",
          },
        ]);
      } finally {
        setIsPlanning(false);
      }
    },
    [messages, optimization.trip_spec]
  );

  // Accessible keyboard arrow navigation for ARIA tabs
  const tabsOrder: ActiveTab[] = ["itinerary", "arbitrage", "telemetry"];
  const handleTabKeyDown = (
    e: React.KeyboardEvent<HTMLButtonElement>,
    idx: number
  ) => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const dir = e.key === "ArrowRight" ? 1 : -1;
      const nextIdx = (idx + dir + tabsOrder.length) % tabsOrder.length;
      setActiveTab(tabsOrder[nextIdx]);
      tabRefs.current[nextIdx]?.focus();
    }
  };

  const filterStopMatches = (stop: TimelineStop): boolean => {
    if (stopFilter === "climb" && stop.category !== "climb" && stop.category !== "nature") {
      return false;
    }
    if (stopFilter === "dining" && stop.category !== "dining") {
      return false;
    }
    if (
      stopFilter === "stay_drive" &&
      stop.category !== "stay" &&
      stop.category !== "drive" &&
      stop.category !== "flight"
    ) {
      return false;
    }
    if (stopSearchQuery.trim()) {
      const q = stopSearchQuery.toLowerCase();
      return (
        stop.title.toLowerCase().includes(q) ||
        stop.description.toLowerCase().includes(q) ||
        stop.location_label.toLowerCase().includes(q)
      );
    }
    return true;
  };

  const stopCategoryIcon = (cat: TimelineStop["category"]) => {
    switch (cat) {
      case "climb":
        return <Mountain size={15} aria-hidden="true" color="var(--gold-accent)" />;
      case "dining":
        return <Utensils size={15} aria-hidden="true" color="#ec4899" />;
      case "stay":
        return <Hotel size={15} aria-hidden="true" color="var(--accent-primary)" />;
      case "flight":
        return <Plane size={15} aria-hidden="true" color="var(--gold-accent)" />;
      case "drive":
        return <Car size={15} aria-hidden="true" color="var(--route-blue)" />;
      default:
        return <Compass size={15} aria-hidden="true" color="#a78bfa" />;
    }
  };

  return (
    <div className="app-shell">
      <a href="#main-content" className="skip-link visually-hidden">
        Skip to trip workspace
      </a>

      {/* Top Navigation & Live Arbitrage Scoreboard */}
      <header className="top-bar">
        <div className="brand-cluster">
          <div className="brand-mark" aria-hidden="true">
            TS
          </div>
          <div>
            <h1 className="brand-title">TripSage</h1>
            <p className="brand-subtitle">
              Joint Multi-Modal Deal Arbitrage &amp; Itinerary Engine
            </p>
          </div>
        </div>

        {/* Scenario Switcher */}
        <nav aria-label="Example trip scenarios" style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
          <button
            type="button"
            className={`btn ${activePresetKey === "wayanad" ? "btn-active-preset" : ""}`}
            onClick={() => handleSwitchPreset("wayanad")}
          >
            <Car size={15} aria-hidden="true" />
            Wayanad Family Road Trip (Dec 21–26)
          </button>
          <button
            type="button"
            className={`btn ${activePresetKey === "goa" ? "btn-active-preset" : ""}`}
            onClick={() => handleSwitchPreset("goa")}
          >
            <Plane size={15} aria-hidden="true" />
            Goa Hybrid + The Blue Kite
          </button>
        </nav>

        <div className="header-actions">
          <span className="badge badge-emerald" style={{ padding: "0.35rem 0.7rem", fontSize: "0.78rem" }}>
            <TrendingDown size={14} aria-hidden="true" />
            Saved ₹{blueprint.total_arbitrage_savings_inr.toLocaleString("en-IN")} via Arbitrage
          </span>

          <button
            type="button"
            className={`btn ${showParamsDrawer ? "btn-active-preset" : ""}`}
            aria-expanded={showParamsDrawer}
            aria-controls="trip-params-panel"
            onClick={() => setShowParamsDrawer((v) => !v)}
          >
            <SlidersHorizontal size={15} aria-hidden="true" />
            {showParamsDrawer ? "Hide Trip Inputs" : "Edit Trip Inputs"}
          </button>

          <button
            type="button"
            className="btn"
            onClick={toggleTheme}
            aria-label={
              pinnedScheme
                ? "Reset color theme to system setting"
                : `Switch to ${effectiveDark ? "light" : "dark"} mode`
            }
          >
            {effectiveDark ? (
              <Sun size={15} aria-hidden="true" />
            ) : (
              <Moon size={15} aria-hidden="true" />
            )}
            <span>{pinnedScheme ? `Pinned (${pinnedScheme})` : "System Theme"}</span>
          </button>
        </div>
      </header>

      {/* Split Workspace: Left Conversational Agent + Right Interactive Route & Arbitrage Canvas */}
      <div className="workspace-grid">
        <ChatPlannerPane
          messages={messages}
          isPlanning={isPlanning}
          onSendMessage={handleSendMessage}
        />

        <main id="main-content" tabIndex={-1} className="main-canvas">
          {/* Trip Summary Hero Banner */}
          <div
            style={{
              padding: "1.1rem 1.25rem",
              borderRadius: "1rem",
              background: "var(--bg-surface)",
              border: "1px solid var(--border-subtle)",
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "1rem",
            }}
          >
            <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.45rem", alignItems: "center" }}>
                <span className="badge badge-route">
                  {optimization.trip_spec.transport_mode === "road"
                    ? "Pure Road Trip · Own Car"
                    : optimization.trip_spec.transport_mode === "hybrid"
                    ? "Hybrid · Fly + Drive"
                    : "Fly + Stay"}
                </span>
                <span className="badge badge-gold">
                  {optimization.trip_spec.stay_strategy === "hybrid"
                    ? "Hybrid Stays (Hotel + 2BHK Villa)"
                    : optimization.trip_spec.stay_strategy === "villas"
                    ? "Villas (Airbnb / The Blue Kite)"
                    : "Hotels & Resorts"}
                </span>
                <span style={{ fontSize: "0.78rem", color: "var(--text-muted)", fontWeight: 600 }}>
                  {optimization.trip_spec.start_date} to {optimization.trip_spec.end_date} ·{" "}
                  {optimization.trip_spec.party.adults} Adults +{" "}
                  {optimization.trip_spec.party.children} Kids (
                  {optimization.trip_spec.party.child_ages.join(", ")} yrs)
                </span>
              </div>

              <h2
                style={{
                  margin: 0,
                  fontSize: "1.32rem",
                  fontWeight: 800,
                  letterSpacing: "-0.02em",
                  display: "flex",
                  flexWrap: "wrap",
                  alignItems: "center",
                  gap: "0.5rem",
                }}
              >
                <span>{optimization.trip_spec.origin}</span>
                <ArrowRight size={18} aria-hidden="true" color="var(--accent-primary)" />
                <span>{optimization.trip_spec.destination}</span>
              </h2>
              <p style={{ margin: 0, fontSize: "0.83rem", color: "var(--text-secondary)" }}>
                Vehicle: <strong>{optimization.trip_spec.vehicle_name}</strong> · Rollout:{" "}
                <strong>{optimization.trip_spec.departure_time_pref}</strong> · Dietary:{" "}
                <strong>
                  {optimization.trip_spec.activities.dietary === "both"
                    ? "Veg + Non-Veg Curated"
                    : "Pure Veg"}
                </strong>
              </p>
            </div>

            {/* Landed Cost Rollup */}
            <div
              style={{
                display: "flex",
                gap: "1.1rem",
                alignItems: "center",
                padding: "0.75rem 1rem",
                borderRadius: "0.85rem",
                background: "var(--bg-elevated)",
                border: "1px solid var(--border-subtle)",
              }}
            >
              <div>
                <div style={{ fontSize: "0.72rem", color: "var(--text-muted)", fontWeight: 700 }}>
                  CORE ALL-IN (STAYS + ROAD{blueprint.flights.length ? " + FLIGHTS" : ""})
                </div>
                <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem" }}>
                  <span style={{ fontSize: "1.45rem", fontWeight: 900, color: "var(--accent-primary)" }}>
                    ₹{blueprint.total_core_landed_inr.toLocaleString("en-IN")}
                  </span>
                  {blueprint.unoptimized_baseline_inr > blueprint.total_core_landed_inr && (
                    <span
                      style={{
                        fontSize: "0.84rem",
                        textDecoration: "line-through",
                        color: "var(--text-muted)",
                      }}
                    >
                      ₹{blueprint.unoptimized_baseline_inr.toLocaleString("en-IN")}
                    </span>
                  )}
                </div>
                <div style={{ fontSize: "0.73rem", color: "var(--text-muted)" }}>
                  + ~₹{blueprint.dining_and_activities_est_inr.toLocaleString("en-IN")} est. 6-day dining &amp; cave/falls tickets
                </div>
              </div>
            </div>
          </div>

          {/* Collapsible Bi-Directional Trip Parameters Form */}
          <div id="trip-params-panel" hidden={!showParamsDrawer}>
            {showParamsDrawer && (
              <TripParametersDrawer
                spec={optimization.trip_spec}
                onUpdateSpec={handleUpdateSpec}
              />
            )}
          </div>

          {/* Pareto-Optimal Trip Blueprint Cards */}
          <section aria-labelledby="pareto-heading">
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBlockEnd: "0.65rem",
              }}
            >
              <h2
                id="pareto-heading"
                style={{
                  margin: 0,
                  fontSize: "0.95rem",
                  fontWeight: 800,
                  display: "flex",
                  alignItems: "center",
                  gap: "0.45rem",
                }}
              >
                <Layers size={17} aria-hidden="true" color="var(--accent-primary)" />
                Pareto-Optimal Trip Blueprints ({optimization.blueprints.length} Solved)
              </h2>
              <span style={{ fontSize: "0.76rem", color: "var(--text-muted)" }}>
                Select a bundle to update map, villa base &amp; landed math
              </span>
            </div>

            <div className="blueprint-grid">
              {optimization.blueprints.map((bp, idx) => {
                const isSelected = idx === selectedBlueprintIdx;
                return (
                  <button
                    key={bp.id}
                    type="button"
                    onClick={() => setSelectedBlueprintIdx(idx)}
                    aria-pressed={isSelected}
                    style={{
                      textAlign: "start",
                      padding: "0.95rem 1.05rem",
                      borderRadius: "0.9rem",
                      cursor: "pointer",
                      background: isSelected ? "var(--bg-elevated)" : "var(--bg-surface)",
                      border: isSelected
                        ? "2px solid var(--accent-primary)"
                        : "1px solid var(--border-subtle)",
                      color: "var(--text-primary)",
                      display: "flex",
                      flexDirection: "column",
                      gap: "0.45rem",
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        gap: "0.4rem",
                      }}
                    >
                      <span
                        className={`badge ${
                          bp.recommended ? "badge-emerald" : "badge-route"
                        }`}
                      >
                        <Award size={12} aria-hidden="true" /> {bp.rank_badge}
                      </span>
                      <span style={{ fontSize: "0.74rem", fontWeight: 700, color: "var(--gold-accent)" }}>
                        Deal Score {bp.deal_anomaly_score}
                      </span>
                    </div>

                    <div style={{ fontWeight: 800, fontSize: "0.93rem", lineHeight: 1.3 }}>
                      {bp.name}
                    </div>
                    <div style={{ fontSize: "0.77rem", color: "var(--text-muted)" }}>
                      {bp.strategy_subtitle}
                    </div>

                    <div
                      style={{
                        marginBlockStart: "auto",
                        paddingBlockStart: "0.45rem",
                        borderBlockStart: "1px solid var(--border-subtle)",
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "baseline",
                      }}
                    >
                      <strong style={{ fontSize: "1.08rem" }}>
                        ₹{bp.total_core_landed_inr.toLocaleString("en-IN")}
                      </strong>
                      <span style={{ fontSize: "0.75rem", color: "var(--accent-primary)", fontWeight: 700 }}>
                        Saves ₹{bp.total_arbitrage_savings_inr.toLocaleString("en-IN")}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>

          {/* Synchronized Interactive Route & Corridor Map */}
          <RouteCorridorMap
            blueprint={blueprint}
            activeDay={activeDay}
            onSelectDay={setActiveDay}
            onInspectStay={setInspectedStay}
          />

          {/* Algorithmic Deal Callouts Banner */}
          <div
            style={{
              padding: "0.85rem 1.05rem",
              borderRadius: "0.85rem",
              background: "var(--bg-surface)",
              border: "1px solid var(--border-subtle)",
              display: "flex",
              flexDirection: "column",
              gap: "0.4rem",
            }}
          >
            <div
              style={{
                fontSize: "0.78rem",
                fontWeight: 800,
                color: "var(--gold-accent)",
                display: "flex",
                alignItems: "center",
                gap: "0.4rem",
              }}
            >
              <Flame size={15} aria-hidden="true" />
              Algorithmic Arbitrage &amp; Timing Insights Caught on This Route
            </div>
            <ul
              role="list"
              style={{
                margin: 0,
                paddingInlineStart: "1.15rem",
                fontSize: "0.82rem",
                color: "var(--text-secondary)",
                display: "flex",
                flexDirection: "column",
                gap: "0.22rem",
              }}
            >
              {blueprint.arbitrage_callouts.map((c, idx) => (
                <li key={idx}>{c}</li>
              ))}
            </ul>
          </div>

          {/* Primary Detail Tabs: Itinerary | Cross-Channel Arbitrage | SUV & Gate Telemetry */}
          <div>
            <div
              role="tablist"
              aria-label="Trip blueprint detail views"
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: "0.5rem",
                borderBlockEnd: "1px solid var(--border-subtle)",
                paddingBlockEnd: "0.65rem",
                marginBlockEnd: "1rem",
              }}
            >
              {(
                [
                  ["itinerary", `6-Day Family Itinerary (${blueprint.days.length} Days)`],
                  ["arbitrage", `Cross-Channel Stay Arbitrage (${blueprint.stays.length} Stays)`],
                  ["telemetry", "Jeep Meridian Road, Tolls & Forest Gates"],
                ] as const
              ).map(([tabKey, label], idx) => {
                const selected = activeTab === tabKey;
                return (
                  <button
                    key={tabKey}
                    ref={(el) => {
                      tabRefs.current[idx] = el;
                    }}
                    role="tab"
                    id={`tab-${tabKey}`}
                    aria-selected={selected}
                    aria-controls={`panel-${tabKey}`}
                    tabIndex={selected ? 0 : -1}
                    type="button"
                    className={`btn ${selected ? "btn-primary" : ""}`}
                    onClick={() => setActiveTab(tabKey)}
                    onKeyDown={(e) => handleTabKeyDown(e, idx)}
                  >
                    {label}
                  </button>
                );
              })}
            </div>

            {/* TAB PANEL 1: DAY-BY-DAY CURATED FAMILY ITINERARY */}
            <div
              role="tabpanel"
              id="panel-itinerary"
              aria-labelledby="tab-itinerary"
              hidden={activeTab !== "itinerary"}
            >
              {/* Semantic <search> Landmark for Filtering Stops */}
              <search
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: "0.6rem",
                  alignItems: "center",
                  marginBlockEnd: "1rem",
                }}
              >
                <div style={{ position: "relative", flex: "1 1 220px", maxInlineSize: "340px" }}>
                  <label htmlFor="itinerary-stop-search" className="visually-hidden">
                    Filter itinerary stops, climbs, or restaurants
                  </label>
                  <Search
                    size={15}
                    aria-hidden="true"
                    style={{
                      position: "absolute",
                      insetInlineStart: "0.75rem",
                      insetBlockStart: "50%",
                      transform: "translateY(-50%)",
                      color: "var(--text-muted)",
                    }}
                  />
                  <input
                    id="itinerary-stop-search"
                    type="search"
                    value={stopSearchQuery}
                    onChange={(e) => setStopSearchQuery(e.target.value)}
                    placeholder="Filter climbs, Kerala restaurants, stops..."
                    className="text-input"
                    style={{ inlineSize: "100%", paddingInlineStart: "2.2rem", minBlockSize: "2.4rem" }}
                  />
                </div>

                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
                  {(
                    [
                      ["all", "All Stops"],
                      ["climb", "Moderate Climbs & Nature"],
                      ["dining", "Veg + Non-Veg Dining"],
                      ["stay_drive", "Drives & Stays"],
                    ] as const
                  ).map(([fKey, fLabel]) => (
                    <button
                      key={fKey}
                      type="button"
                      className={`btn ${stopFilter === fKey ? "btn-active-preset" : ""}`}
                      style={{ minBlockSize: "2.25rem", fontSize: "0.78rem" }}
                      onClick={() => setStopFilter(fKey)}
                    >
                      {fLabel}
                    </button>
                  ))}
                </div>
              </search>

              <ol
                role="list"
                style={{
                  listStyle: "none",
                  margin: 0,
                  padding: 0,
                  display: "flex",
                  flexDirection: "column",
                  gap: "1rem",
                }}
              >
                {blueprint.days
                  .filter((d) => activeDay === null || d.day_number === activeDay)
                  .map((day) => {
                    const visibleStops = day.stops.filter(filterStopMatches);
                    return (
                      <li
                        key={day.day_number}
                        style={{
                          borderRadius: "0.95rem",
                          border: "1px solid var(--border-subtle)",
                          background: "var(--bg-surface)",
                          overflow: "clip",
                        }}
                      >
                        <div
                          style={{
                            padding: "0.85rem 1.1rem",
                            background: "var(--bg-elevated)",
                            borderBlockEnd: "1px solid var(--border-subtle)",
                            display: "flex",
                            flexWrap: "wrap",
                            alignItems: "center",
                            justifyContent: "space-between",
                            gap: "0.6rem",
                          }}
                        >
                          <div>
                            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                              <span className="badge badge-emerald">
                                Day {day.day_number} · {day.date_label}
                              </span>
                              <span className="badge badge-route">{day.corridor_tag}</span>
                            </div>
                            <h3 style={{ margin: "0.35rem 0 0", fontSize: "1.02rem", fontWeight: 800 }}>
                              {day.headline}
                            </h3>
                          </div>

                          <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", textAlign: "end" }}>
                            <div>Drive: <strong>{day.drive_time_label}</strong></div>
                            <div>Stay: <strong>{day.overnight_label}</strong></div>
                          </div>
                        </div>

                        <ul
                          role="list"
                          style={{
                            listStyle: "none",
                            margin: 0,
                            padding: "0.9rem 1.1rem",
                            display: "flex",
                            flexDirection: "column",
                            gap: "0.8rem",
                          }}
                        >
                          {visibleStops.map((st) => (
                            <li
                              key={st.id}
                              style={{
                                padding: "0.8rem 0.95rem",
                                borderRadius: "0.75rem",
                                background: "var(--bg-elevated)",
                                border: "1px solid var(--border-subtle)",
                                display: "flex",
                                flexDirection: "column",
                                gap: "0.32rem",
                              }}
                            >
                              <div
                                style={{
                                  display: "flex",
                                  flexWrap: "wrap",
                                  alignItems: "center",
                                  justifyContent: "space-between",
                                  gap: "0.45rem",
                                }}
                              >
                                <div style={{ display: "flex", alignItems: "center", gap: "0.45rem", fontWeight: 800, fontSize: "0.92rem" }}>
                                  {stopCategoryIcon(st.category)}
                                  <span>{st.title}</span>
                                </div>
                                <span style={{ fontSize: "0.76rem", fontWeight: 700, color: "var(--route-blue)" }}>
                                  {st.time_window} ({st.duration_label})
                                </span>
                              </div>

                              <div style={{ fontSize: "0.76rem", color: "var(--text-muted)", display: "flex", alignItems: "center", gap: "0.3rem" }}>
                                <MapPin size={12} aria-hidden="true" /> {st.location_label}
                              </div>

                              <p style={{ margin: "0.15rem 0 0", fontSize: "0.84rem", color: "var(--text-secondary)" }}>
                                {st.description}
                              </p>

                              {(st.dietary_note || st.kid_note || st.insider_tip) && (
                                <div
                                  style={{
                                    display: "flex",
                                    flexWrap: "wrap",
                                    gap: "0.45rem",
                                    marginBlockStart: "0.25rem",
                                    fontSize: "0.76rem",
                                  }}
                                >
                                  {st.dietary_note && (
                                    <span className="badge badge-gold">
                                      Menu: {st.dietary_note}
                                    </span>
                                  )}
                                  {st.kid_note && (
                                    <span className="badge badge-emerald">
                                      Kids (8 &amp; 10): {st.kid_note}
                                    </span>
                                  )}
                                  {st.insider_tip && (
                                    <span className="badge badge-route">
                                      Tip: {st.insider_tip}
                                    </span>
                                  )}
                                </div>
                              )}
                            </li>
                          ))}
                        </ul>
                      </li>
                    );
                  })}
              </ol>
            </div>

            {/* TAB PANEL 2: CROSS-CHANNEL STAY & FLIGHT ARBITRAGE */}
            <div
              role="tabpanel"
              id="panel-arbitrage"
              aria-labelledby="tab-arbitrage"
              hidden={activeTab !== "arbitrage"}
            >
              {/* Platform Adapter Scan Coverage Strip */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                  gap: "0.75rem",
                  marginBlockEnd: "1.1rem",
                }}
              >
                {optimization.platform_coverage.map((pc) => (
                  <div
                    key={pc.platform}
                    style={{
                      padding: "0.8rem 0.9rem",
                      borderRadius: "0.8rem",
                      background: "var(--bg-surface)",
                      border: "1px solid var(--border-subtle)",
                      fontSize: "0.79rem",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 800 }}>
                      <span>{pc.platform}</span>
                      <span
                        style={{
                          color:
                            pc.status === "zero_inventory_pivoted"
                              ? "var(--gold-accent)"
                              : "var(--accent-primary)",
                        }}
                      >
                        {pc.status === "zero_inventory_pivoted"
                          ? "Auto-Pivoted"
                          : `${pc.listings_scanned} Scanned`}
                      </span>
                    </div>
                    <p style={{ margin: "0.3rem 0 0", color: "var(--text-muted)", fontSize: "0.75rem" }}>
                      {pc.note}
                    </p>
                  </div>
                ))}
              </div>

              {/* Flights Section when Flight/Hybrid Mode is Active */}
              {blueprint.flights.length > 0 && (
                <div style={{ marginBlockEnd: "1.1rem" }}>
                  <h3 style={{ fontSize: "0.95rem", fontWeight: 800, marginBlockEnd: "0.5rem" }}>
                    Gateway Flight &amp; Virtual Interline Arbitrage
                  </h3>
                  {blueprint.flights.map((flt) => (
                    <div
                      key={flt.id}
                      style={{
                        padding: "0.95rem 1.1rem",
                        borderRadius: "0.85rem",
                        background: "var(--bg-surface)",
                        border: "1px solid var(--border-subtle)",
                        display: "flex",
                        flexWrap: "wrap",
                        justifyContent: "space-between",
                        gap: "0.8rem",
                      }}
                    >
                      <div>
                        <span className="badge badge-gold">{flt.carrier}</span>
                        <div style={{ fontWeight: 800, fontSize: "0.96rem", marginBlockStart: "0.3rem" }}>
                          {flt.route_label} ({flt.flight_numbers})
                        </div>
                        <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>
                          {flt.gateway_hub_note}
                        </div>
                      </div>
                      <div style={{ textAlign: "end" }}>
                        <div style={{ fontSize: "1.2rem", fontWeight: 900, color: "var(--accent-primary)" }}>
                          ₹{flt.landed_family_total_inr.toLocaleString("en-IN")}
                        </div>
                        <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                          4 Seats + Luggage · Saves ₹{flt.savings_inr.toLocaleString("en-IN")}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Size-Aware Container Query Stay Cards */}
              <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                {blueprint.stays.map((stay) => (
                  <div key={stay.id} className="card-container">
                    <article className="stay-arbitrage-card">
                      <img
                        src={stay.image_url}
                        alt={`${stay.name} in ${stay.city}`}
                        width={450}
                        height={300}
                        loading="lazy"
                        className="stay-card-media"
                      />

                      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: "0.45rem" }}>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", alignItems: "center" }}>
                          <span className="badge badge-emerald">
                            <Sparkles size={12} aria-hidden="true" /> {stay.anomaly_badge}
                          </span>
                          <span className="badge badge-route">
                            {stay.check_in} to {stay.check_out} ({stay.nights}N)
                          </span>
                          <span style={{ fontSize: "0.78rem", fontWeight: 700, marginInlineStart: "auto" }}>
                            ★ {stay.rating} ({stay.review_count} reviews)
                          </span>
                        </div>

                        <h3 style={{ margin: 0, fontSize: "1.08rem", fontWeight: 800 }}>
                          {stay.name}
                        </h3>
                        <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                          {stay.subtitle} · {stay.bedrooms_label}
                        </div>

                        <ul
                          role="list"
                          style={{
                            margin: "0.15rem 0",
                            paddingInlineStart: "1.1rem",
                            fontSize: "0.8rem",
                            color: "var(--text-secondary)",
                          }}
                        >
                          {stay.highlights.map((h, i) => (
                            <li key={i}>{h}</li>
                          ))}
                        </ul>

                        <div
                          style={{
                            marginBlockStart: "auto",
                            paddingBlockStart: "0.6rem",
                            borderBlockStart: "1px solid var(--border-subtle)",
                            display: "flex",
                            flexWrap: "wrap",
                            alignItems: "center",
                            justifyContent: "space-between",
                            gap: "0.75rem",
                          }}
                        >
                          <div>
                            <div style={{ fontSize: "0.72rem", color: "var(--text-muted)", fontWeight: 700 }}>
                              WINNING CHANNEL: {stay.best_channel.toUpperCase()}
                            </div>
                            <div style={{ display: "flex", alignItems: "baseline", gap: "0.45rem" }}>
                              <strong style={{ fontSize: "1.2rem", color: "var(--accent-primary)" }}>
                                ₹{stay.best_landed_inr.toLocaleString("en-IN")}
                              </strong>
                              <span style={{ fontSize: "0.77rem", color: "var(--text-muted)" }}>
                                (₹{Math.round(stay.best_landed_inr / stay.nights).toLocaleString("en-IN")}/night landed)
                              </span>
                            </div>
                          </div>

                          <div style={{ display: "flex", gap: "0.5rem" }}>
                            <button
                              type="button"
                              className="btn btn-primary"
                              onClick={() => setInspectedStay(stay)}
                            >
                              <CheckCircle2 size={15} aria-hidden="true" />
                              {`Inspect ${stay.offers.length}-Channel Fee Math`}
                            </button>
                            <a
                              href={stay.offers[0]?.booking_url ?? "#"}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="btn"
                              style={{ textDecoration: "none" }}
                            >
                              Portal <ExternalLink size={14} aria-hidden="true" />
                            </a>
                          </div>
                        </div>
                      </div>
                    </article>
                  </div>
                ))}
              </div>
            </div>

            {/* TAB PANEL 3: SUV TELEMETRY, FUEL, FASTAG & BANDIPUR GATE RULES */}
            <div
              role="tabpanel"
              id="panel-telemetry"
              aria-labelledby="tab-telemetry"
              hidden={activeTab !== "telemetry"}
            >
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                  gap: "0.8rem",
                  marginBlockEnd: "1rem",
                }}
              >
                <div style={{ padding: "0.9rem", borderRadius: "0.8rem", background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}>
                  <div style={{ fontSize: "0.74rem", color: "var(--text-muted)", fontWeight: 700 }}>VEHICLE &amp; CLEARANCE</div>
                  <div style={{ fontSize: "1rem", fontWeight: 800, marginBlockStart: "0.2rem" }}>{blueprint.road.vehicle}</div>
                  <div style={{ fontSize: "0.78rem", color: "var(--accent-primary)", fontWeight: 600 }}>
                    {blueprint.road.ground_clearance_mm}mm Estate Clearance Verified
                  </div>
                </div>

                <div style={{ padding: "0.9rem", borderRadius: "0.8rem", background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}>
                  <div style={{ fontSize: "0.74rem", color: "var(--text-muted)", fontWeight: 700 }}>DIESEL ESTIMATE</div>
                  <div style={{ fontSize: "1.15rem", fontWeight: 800, marginBlockStart: "0.2rem" }}>
                    ₹{blueprint.road.fuel_cost_inr.toLocaleString("en-IN")}
                  </div>
                  <div style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                    <Fuel size={12} aria-hidden="true" style={{ display: "inline", marginInlineEnd: 4 }} />
                    ~{blueprint.road.estimated_fuel_liters}L across {blueprint.road.total_distance_km} km
                  </div>
                </div>

                <div style={{ padding: "0.9rem", borderRadius: "0.8rem", background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}>
                  <div style={{ fontSize: "0.74rem", color: "var(--text-muted)", fontWeight: 700 }}>FASTAG &amp; FOREST ENTRY</div>
                  <div style={{ fontSize: "1.15rem", fontWeight: 800, marginBlockStart: "0.2rem" }}>
                    ₹{blueprint.road.fastag_and_forest_tolls_inr.toLocaleString("en-IN")}
                  </div>
                  <div style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                    NICE Rd + NH275 + Bandipur/Muthanga
                  </div>
                </div>
              </div>

              <div className="table-scroll">
                <table className="rate-table">
                  <caption>
                    Corridor-by-Corridor Driving, FASTag Toll &amp; Forest Checkpost Verification
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Day</th>
                      <th scope="col">Leg &amp; Highway</th>
                      <th scope="col">Distance / Time</th>
                      <th scope="col">FASTag + Fuel</th>
                      <th scope="col">Gate &amp; Gradient Advisory</th>
                    </tr>
                  </thead>
                  <tbody>
                    {blueprint.road.segments.map((seg) => (
                      <tr key={seg.id}>
                        <td>
                          <span className="badge badge-route">Day {seg.day_number}</span>
                        </td>
                        <td>
                          <strong>
                            {seg.from_name} → {seg.to_name}
                          </strong>
                          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                            {seg.highway_label}
                          </div>
                        </td>
                        <td>
                          {seg.distance_km} km · {Math.floor(seg.duration_mins / 60)}h{" "}
                          {seg.duration_mins % 60}m
                        </td>
                        <td>
                          ₹{(seg.fastag_toll_inr + seg.fuel_estimate_inr).toLocaleString("en-IN")}
                          <div style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
                            Toll ₹{seg.fastag_toll_inr} · Fuel ₹{seg.fuel_estimate_inr}
                          </div>
                        </td>
                        <td style={{ fontSize: "0.79rem" }}>
                          {seg.gate_alert ? (
                            <span style={{ color: "var(--gold-accent)", fontWeight: 600 }}>
                              {seg.gate_alert}
                            </span>
                          ) : (
                            <span style={{ color: "var(--accent-primary)" }}>
                              <ShieldCheck size={14} aria-hidden="true" style={{ display: "inline", marginInlineEnd: 4 }} />
                              24×7 Access-Controlled Expressway
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </main>
      </div>

      {/* Native Top-Layer Light-Dismiss Deal Breakdown Modal */}
      <DealArbitrageDialog
        stay={inspectedStay}
        onClose={() => setInspectedStay(null)}
      />
    </div>
  );
}

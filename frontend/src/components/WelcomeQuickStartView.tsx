"use client";

import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  ArrowUpRight,
  Car,
  Compass,
  Hotel,
  Pause,
  Plane,
  Play,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TrendingDown,
} from "lucide-react";
import {
  DEFAULT_FX_RATES,
  formatMoney,
  type CurrencyCode,
  type LivePhaseStatus,
  type StayStrategy,
  type TransportMode,
  type TripSpec,
} from "@/types/trip";

interface WelcomeQuickStartViewProps {
  currency: CurrencyCode;
  fxRates: Record<string, number>;
  isPlanning: boolean;
  livePhase: LivePhaseStatus | null;
  onLaunchSpec: (spec: TripSpec, label: string) => void;
  onTryExample: (exampleKey: "wayanad" | "goa" | "mahabaleshwar") => void;
}

interface HorizonScene {
  id: string;
  label: string;
  regionTag: string;
  videoUrl: string;
}

const HORIZON_SCENES: HorizonScene[] = [
  {
    id: "summit",
    label: "Golden Summit",
    regionTag: "Highland Villas & Cloud Ridges",
    videoUrl:
      "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260405_170732_8a9ccda6-5cff-4628-b164-059c500a2b41.mp4",
  },
  {
    id: "ghats",
    label: "Misty Ghats",
    regionTag: "Forest Corridors & Estate Drives",
    videoUrl:
      "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260511_131941_d136af49-e243-493a-be14-6ff3f24e09e6.mp4",
  },
  {
    id: "valley",
    label: "Starlit Valley",
    regionTag: "Fly + Drive Alpine Horizons",
    videoUrl:
      "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260402_054547_9875cfc5-155a-4229-8ec8-b7ba7125cbf8.mp4",
  },
];

const AUTO_FLIGHT_DEST_TOKENS = [
  "indonesia", "bali", "thailand", "phuket", "bangkok", "singapore",
  "malaysia", "kuala lumpur", "vietnam", "da nang", "hanoi", "cambodia",
  "philippines", "sri lanka", "colombo", "maldives", "mauritius", "seychelles",
  "dubai", "uae", "abu dhabi", "doha", "qatar", "turkey", "istanbul", "egypt",
  "japan", "tokyo", "kyoto", "seoul", "south korea", "london", "uk", "paris",
  "france", "rome", "italy", "amalfi", "zurich", "interlaken", "switzerland",
  "spain", "barcelona", "portugal", "lisbon", "greece", "athens", "santorini",
  "germany", "munich", "austria", "vienna", "amsterdam", "netherlands",
  "new york", "usa", "united states", "san francisco", "los angeles", "toronto",
  "canada", "sydney", "australia", "auckland", "new zealand",
  "andaman", "port blair", "havelock", "lakshadweep", "agatti",
];

function addDaysIso(daysFromToday: number): string {
  const d = new Date();
  d.setDate(d.getDate() + daysFromToday);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function syncAriaInvalid(el: HTMLInputElement) {
  if (!el.checkValidity()) {
    el.setAttribute("aria-invalid", "true");
  } else {
    el.removeAttribute("aria-invalid");
  }
}

export function WelcomeQuickStartView({
  currency,
  fxRates,
  isPlanning,
  livePhase,
  onLaunchSpec,
  onTryExample,
}: WelcomeQuickStartViewProps) {
  const uid = useId();
  const formRef = useRef<HTMLFormElement | null>(null);
  const videoRefs = useRef<Array<HTMLVideoElement | null>>([]);
  const sceneCooldownRef = useRef<number | null>(null);

  const [activeSceneIdx, setActiveSceneIdx] = useState<number>(0);
  const [isTransitioningScene, setIsTransitioningScene] = useState<boolean>(false);
  const [isVideoPaused, setIsVideoPaused] = useState<boolean>(false);

  const defaultDates = useMemo(
    () => ({
      start: addDaysIso(14),
      end: addDaysIso(18),
    }),
    []
  );

  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
  const [startDate, setStartDate] = useState(defaultDates.start);
  const [endDate, setEndDate] = useState(defaultDates.end);
  const [transportMode, setTransportMode] = useState<TransportMode>("road");
  const [userTouchedMode, setUserTouchedMode] = useState<boolean>(false);
  const [stayStrategy, setStayStrategy] = useState<StayStrategy>("villas");
  const [adults, setAdults] = useState(2);
  const [children, setChildren] = useState(2);
  const [villaBhk, setVillaBhk] = useState(2);
  const [maxNightlyInr, setMaxNightlyInr] = useState(20000);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (mq.matches) {
      setIsVideoPaused(true);
    }
    const handleMotionPref = (ev: MediaQueryListEvent) => {
      if (ev.matches) {
        setIsVideoPaused(true);
      }
    };
    mq.addEventListener("change", handleMotionPref);
    return () => {
      mq.removeEventListener("change", handleMotionPref);
      if (sceneCooldownRef.current !== null) {
        window.clearTimeout(sceneCooldownRef.current);
      }
    };
  }, []);

  useEffect(() => {
    videoRefs.current.forEach((vid, idx) => {
      if (!vid) return;
      vid.muted = true;
      vid.playsInline = true;
      if (idx === activeSceneIdx && !isVideoPaused) {
        vid.play().catch(() => {});
      } else {
        vid.pause();
      }
    });
  }, [activeSceneIdx, isVideoPaused]);

  const handleSwitchScene = (nextIdx: number) => {
    if (nextIdx === activeSceneIdx || isTransitioningScene) return;
    setActiveSceneIdx(nextIdx);
    setIsTransitioningScene(true);
    if (sceneCooldownRef.current !== null) {
      window.clearTimeout(sceneCooldownRef.current);
    }
    sceneCooldownRef.current = window.setTimeout(() => {
      setIsTransitioningScene(false);
    }, 650);
  };

  const originId = `${uid}-origin`;
  const originErrId = `${uid}-origin-err`;
  const destId = `${uid}-dest`;
  const destErrId = `${uid}-dest-err`;
  const startId = `${uid}-start`;
  const endId = `${uid}-end`;
  const adultsId = `${uid}-adults`;
  const kidsId = `${uid}-kids`;
  const budgetId = `${uid}-budget`;

  const handleFormBlurCapture = (e: React.FocusEvent<HTMLFormElement>) => {
    const target = e.target;
    if (target instanceof HTMLInputElement && target.required) {
      syncAriaInvalid(target);
    }
  };

  const handleFormInput = (e: React.FormEvent<HTMLFormElement>) => {
    const target = e.target;
    if (
      target instanceof HTMLInputElement &&
      target.required &&
      target.checkValidity()
    ) {
      target.removeAttribute("aria-invalid");
    }
  };

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = formRef.current;
    if (form) {
      const reqInputs = form.querySelectorAll<HTMLInputElement>("input[required]");
      reqInputs.forEach(syncAriaInvalid);
      if (!form.checkValidity()) {
        const firstInvalid = Array.from(reqInputs).find((inp) => !inp.checkValidity());
        firstInvalid?.focus();
        return;
      }
    }

    const safeOrigin = origin.trim();
    const safeDest = destination.trim();
    if (!safeOrigin || !safeDest || isPlanning) return;

    const childAges = Array.from({ length: children }, (_, i) =>
      Math.min(14, 7 + i * 2)
    );

    let safeEnd = endDate;
    if (safeEnd <= startDate) {
      const d = new Date(`${startDate}T00:00:00`);
      if (!Number.isNaN(d.getTime())) {
        d.setDate(d.getDate() + 4);
        safeEnd = d.toISOString().slice(0, 10);
      }
    }

    const spec: TripSpec = {
      origin: safeOrigin,
      destination: safeDest,
      start_date: startDate,
      end_date: safeEnd,
      departure_time_pref: "08:30 AM Departure",
      return_timing_pref: "Post-Lunch Return",
      transport_mode: transportMode,
      stay_strategy: stayStrategy,
      vehicle_name:
        transportMode === "flight"
          ? "Airport Private Transfer SUV"
          : transportMode === "hybrid"
          ? "Self-Drive Rental SUV"
          : "Family SUV (Own Car)",
      destination_villa_bhk: villaBhk,
      nightly_budget_min_inr: Math.max(5000, Math.round(maxNightlyInr * 0.65)),
      nightly_budget_max_inr: maxNightlyInr,
      party: {
        adults,
        children,
        child_ages: childAges,
        room_setup:
          stayStrategy === "hotels"
            ? children > 0
              ? "Deluxe Room + Extra Bed"
              : "Deluxe Double Room"
            : `${villaBhk} BHK Entire Private Stay`,
      },
      pinned_stays: [],
      activities: {
        wildlife_safari: false,
        adventure_water: false,
        moderate_climbs: true,
        transit_sightseeing: false,
        dietary: "both",
        pace: "balanced",
      },
    };

    onLaunchSpec(spec, `${safeOrigin} -> ${safeDest}`);
  };

  const ceilingDisplay = formatMoney(
    maxNightlyInr,
    currency,
    fxRates || DEFAULT_FX_RATES
  );

  const activeScene = HORIZON_SCENES[activeSceneIdx] ?? HORIZON_SCENES[0];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.15rem" }}>
      {/* Cinematic Inset Horizon Stage */}
      <section className="ms-horizon-stage" aria-label="TripSage Multi-Modal Travel Engine">
        {HORIZON_SCENES.map((scene, idx) => (
          <video
            key={scene.id}
            ref={(el) => {
              videoRefs.current[idx] = el;
            }}
            className="ms-horizon-video"
            data-active={String(idx === activeSceneIdx)}
            src={scene.videoUrl}
            autoPlay={idx === 0}
            muted
            loop
            playsInline
            preload={idx === activeSceneIdx ? "auto" : "metadata"}
            aria-hidden="true"
          />
        ))}
        <div className="ms-horizon-scrim" aria-hidden="true" />
        <div className="ms-noise-overlay" aria-hidden="true" />

        {/* Top Bar: Liquid-Glass Solver Chip + Atmosphere Switcher & Motion Control */}
        <div
          className="ms-fade-rise"
          style={{
            ["--d" as string]: "60ms",
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "0.75rem",
          }}
        >
          <div
            className="liquid-glass"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.55rem",
              borderRadius: "999px",
              padding: "0.26rem 0.85rem 0.26rem 0.3rem",
            }}
          >
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.28rem",
                background: "#ffffff",
                color: "#06121c",
                borderRadius: "999px",
                padding: "0.22rem 0.62rem",
                fontSize: "0.7rem",
                fontWeight: 700,
                letterSpacing: "0.02em",
              }}
            >
              <Sparkles size={11} aria-hidden="true" /> v3.0 Engine
            </span>
            <span style={{ fontSize: "0.76rem", color: "rgba(248, 250, 252, 0.92)", fontWeight: 500 }}>
              NSGA-II Pareto · OSRM 2-Opt VRPTW · Channel Arbitrage
            </span>
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.45rem" }}>
            <div
              className="liquid-glass"
              role="group"
              aria-label="Select horizon atmosphere"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.15rem",
                padding: "0.2rem",
                borderRadius: "999px",
              }}
            >
              {HORIZON_SCENES.map((sc, idx) => (
                <button
                  key={sc.id}
                  type="button"
                  className="ms-scene-pill"
                  aria-pressed={idx === activeSceneIdx}
                  onClick={() => handleSwitchScene(idx)}
                >
                  {sc.label}
                </button>
              ))}
            </div>

            <button
              type="button"
              className="liquid-glass"
              aria-pressed={isVideoPaused}
              aria-label={
                isVideoPaused
                  ? "Play ambient horizon video"
                  : "Pause ambient horizon video"
              }
              title={isVideoPaused ? "Play ambient video" : "Pause ambient video"}
              onClick={() => setIsVideoPaused((prev) => !prev)}
              style={{
                inlineSize: "2.35rem",
                blockSize: "2.35rem",
                borderRadius: "999px",
                display: "grid",
                placeItems: "center",
                color: "#f8fafc",
                cursor: "pointer",
              }}
            >
              {isVideoPaused ? (
                <Play size={14} aria-hidden="true" />
              ) : (
                <Pause size={14} aria-hidden="true" />
              )}
            </button>
          </div>
        </div>

        {/* Bottom-Anchored Editorial Headline + Proof Strip */}
        <div
          style={{
            marginBlockStart: "clamp(0.85rem, 1.8vw, 1.45rem)",
            display: "flex",
            flexDirection: "column",
            gap: "0.7rem",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            <h2
              className="ms-hero-headline ms-blur-rise"
              style={{ ["--d" as string]: "180ms" }}
            >
              Every journey hides a{" "}
              <span className="ms-serif-accent">smarter edge.</span>
            </h2>
            <p
              className="ms-hero-lede ms-fade-rise"
              style={{ ["--d" as string]: "320ms" }}
            >
              Deduplicate private villas, transit hotels, and multi-gateway flights across
              Airbnb, The Blue Kite, StayVista, and direct portals—paired with time-windowed
              daily routing.
            </p>
          </div>

          {/* Quiet Editorial Telemetry Strip */}
          <div
            className="ms-fade-rise"
            style={{
              ["--d" as string]: "440ms",
              paddingBlockStart: "0.6rem",
              borderBlockStart: "1px solid rgba(255, 255, 255, 0.14)",
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "0.5rem",
              fontSize: "0.73rem",
              color: "rgba(226, 232, 240, 0.78)",
            }}
          >
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.65rem" }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
                <TrendingDown size={13} aria-hidden="true" color="#34d399" />
                <strong style={{ color: "#ffffff", fontWeight: 600 }}>8+ Channels</strong>{" "}
                Fee Math
              </span>
              <span aria-hidden="true" style={{ opacity: 0.35 }}>
                |
              </span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
                <Compass size={13} aria-hidden="true" color="#38bdf8" />
                <strong style={{ color: "#ffffff", fontWeight: 600 }}>2-Opt VRPTW</strong>{" "}
                Routing
              </span>
              <span aria-hidden="true" style={{ opacity: 0.35 }}>
                |
              </span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
                <Plane size={13} aria-hidden="true" color="#fbbf24" />
                <strong style={{ color: "#ffffff", fontWeight: 600 }}>Multi-Gateway</strong>{" "}
                Flights
              </span>
            </div>

            <span
              style={{
                fontSize: "0.69rem",
                letterSpacing: "0.09em",
                textTransform: "uppercase",
                color: "rgba(253, 230, 138, 0.9)",
                fontWeight: 600,
              }}
            >
              {activeScene.regionTag}
            </span>
          </div>
        </div>
      </section>

      {/* Precision Trip Spec Builder Dock */}
      <section
        className="surface-card"
        style={{
          padding: "1.1rem 1.35rem",
          borderRadius: "1.35rem",
          minInlineSize: 0,
        }}
      >
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "baseline",
            justifyContent: "space-between",
            gap: "0.45rem",
            marginBlockEnd: "0.8rem",
          }}
        >
          <div>
            <span
              style={{
                display: "block",
                fontSize: "0.68rem",
                fontWeight: 700,
                letterSpacing: "0.14em",
                textTransform: "uppercase",
                color: "var(--accent-primary)",
                marginBlockEnd: "0.12rem",
              }}
            >
              01 / Configure Route &amp; Party
            </span>
            <h3 style={{ margin: 0, fontSize: "1.12rem", fontWeight: 700, letterSpacing: "-0.02em" }}>
              Where are you traveling next?
            </h3>
          </div>
          <span style={{ fontSize: "0.76rem", color: "var(--text-muted)" }}>
            Or describe your trip in plain English in the copilot on the left
          </span>
        </div>

        {/* Accessible Quick-Start Form */}
        <form
          ref={formRef}
          action="/api/optimize"
          method="POST"
          onBlurCapture={handleFormBlurCapture}
          onInput={handleFormInput}
          onSubmit={handleSubmit}
          style={{ display: "flex", flexDirection: "column", gap: "0.85rem", minInlineSize: 0 }}
        >
          {/* Origin & Destination Row */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))",
              gap: "0.85rem",
            }}
          >
            <div>
              <label htmlFor={originId} className="qs-label">
                Origin City or Neighborhood{" "}
                <span aria-hidden="true" style={{ color: "var(--danger-accent)" }}>
                  *
                </span>
              </label>
              <input
                id={originId}
                name="origin"
                type="text"
                required
                autoComplete="address-level2"
                enterKeyHint="next"
                aria-errormessage={originErrId}
                value={origin}
                onChange={(e) => setOrigin(e.target.value)}
                placeholder="e.g., Bengaluru, Mumbai, London, Austin"
                className="qs-input"
              />
              <div id={originErrId} className="qs-error-msg">
                <AlertCircle size={14} aria-hidden="true" />
                <span>Origin city is required to compute routes &amp; flights.</span>
              </div>
            </div>

            <div>
              <label htmlFor={destId} className="qs-label">
                Destination City or Region{" "}
                <span aria-hidden="true" style={{ color: "var(--danger-accent)" }}>
                  *
                </span>
              </label>
              <input
                id={destId}
                name="destination"
                type="text"
                required
                autoComplete="off"
                enterKeyHint="next"
                aria-errormessage={destErrId}
                value={destination}
                onChange={(e) => {
                  const val = e.target.value;
                  setDestination(val);
                  if (!userTouchedMode) {
                    const low = val.trim().toLowerCase();
                    if (AUTO_FLIGHT_DEST_TOKENS.some((tok) => low.includes(tok))) {
                      setTransportMode("flight");
                    }
                  }
                }}
                placeholder="e.g., Wayanad, North Goa, Bali, Sedona, Interlaken"
                className="qs-input"
              />
              <div id={destErrId} className="qs-error-msg">
                <AlertCircle size={14} aria-hidden="true" />
                <span>Destination is required to scan stays &amp; POIs.</span>
              </div>
            </div>
          </div>

          {/* Dates, Party & Budget Row */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 145px), 1fr))",
              gap: "0.75rem",
            }}
          >
            <div>
              <label htmlFor={startId} className="qs-label">
                Start Date
              </label>
              <input
                id={startId}
                name="start_date"
                type="date"
                value={startDate}
                onChange={(e) => {
                  const nextS = e.target.value;
                  setStartDate(nextS);
                  if (nextS && endDate <= nextS) {
                    const d = new Date(`${nextS}T00:00:00`);
                    if (!Number.isNaN(d.getTime())) {
                      d.setDate(d.getDate() + 4);
                      setEndDate(d.toISOString().slice(0, 10));
                    }
                  }
                }}
                className="qs-input"
              />
            </div>

            <div>
              <label htmlFor={endId} className="qs-label">
                Return Date
              </label>
              <input
                id={endId}
                name="end_date"
                type="date"
                min={startDate}
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="qs-input"
              />
            </div>

            <div>
              <label htmlFor={adultsId} className="qs-label">
                Adults
              </label>
              <select
                id={adultsId}
                name="adults"
                value={adults}
                onChange={(e) => setAdults(Number(e.target.value))}
                className="qs-input"
              >
                {[1, 2, 3, 4, 5, 6].map((n) => (
                  <option key={n} value={n}>
                    {n} {n === 1 ? "Adult" : "Adults"}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor={kidsId} className="qs-label">
                Children
              </label>
              <select
                id={kidsId}
                name="children"
                value={children}
                onChange={(e) => setChildren(Number(e.target.value))}
                className="qs-input"
              >
                {[0, 1, 2, 3, 4].map((n) => (
                  <option key={n} value={n}>
                    {n} {n === 1 ? "Child" : "Children"}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Radio Fieldsets (< 6 exclusive choices -> visible radio controls) */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 260px), 1fr))",
              gap: "0.8rem",
            }}
          >
            <fieldset className="qs-fieldset">
              <legend className="qs-legend">Transport Topology</legend>
              <div className="qs-radio-grid">
                <label className="qs-radio-option">
                  <input
                    type="radio"
                    name="transport_mode"
                    value="road"
                    checked={transportMode === "road"}
                    onChange={() => {
                      setUserTouchedMode(true);
                      setTransportMode("road");
                    }}
                  />
                  <Car size={14} aria-hidden="true" color="var(--route-blue)" />
                  <span>Road Trip</span>
                </label>
                <label className="qs-radio-option">
                  <input
                    type="radio"
                    name="transport_mode"
                    value="flight"
                    checked={transportMode === "flight"}
                    onChange={() => {
                      setUserTouchedMode(true);
                      setTransportMode("flight");
                    }}
                  />
                  <Plane size={14} aria-hidden="true" color="var(--gold-accent)" />
                  <span>Fly + Stay</span>
                </label>
                <label className="qs-radio-option">
                  <input
                    type="radio"
                    name="transport_mode"
                    value="hybrid"
                    checked={transportMode === "hybrid"}
                    onChange={() => {
                      setUserTouchedMode(true);
                      setTransportMode("hybrid");
                    }}
                  />
                  <Compass size={14} aria-hidden="true" color="var(--accent-primary)" />
                  <span>Fly + Drive</span>
                </label>
              </div>
            </fieldset>

            <fieldset className="qs-fieldset">
              <legend className="qs-legend">Stay Arbitrage Preference</legend>
              <div className="qs-radio-grid">
                <label className="qs-radio-option">
                  <input
                    type="radio"
                    name="stay_strategy"
                    value="villas"
                    checked={stayStrategy === "villas"}
                    onChange={() => setStayStrategy("villas")}
                  />
                  <Hotel size={14} aria-hidden="true" color="var(--accent-primary)" />
                  <span>Villas &amp; Airbnb</span>
                </label>
                <label className="qs-radio-option">
                  <input
                    type="radio"
                    name="stay_strategy"
                    value="hotels"
                    checked={stayStrategy === "hotels"}
                    onChange={() => setStayStrategy("hotels")}
                  />
                  <Hotel size={14} aria-hidden="true" color="var(--route-blue)" />
                  <span>Hotels Only</span>
                </label>
                <label className="qs-radio-option">
                  <input
                    type="radio"
                    name="stay_strategy"
                    value="hybrid"
                    checked={stayStrategy === "hybrid"}
                    onChange={() => setStayStrategy("hybrid")}
                  />
                  <ShieldCheck size={14} aria-hidden="true" color="var(--gold-accent)" />
                  <span>Hybrid Stays</span>
                </label>
              </div>
            </fieldset>
          </div>

          {/* Villa Size & Nightly Ceiling + Tactile Text-Roll Submit Action */}
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "1rem",
              paddingBlockStart: "0.25rem",
            }}
          >
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "1rem", flex: 1 }}>
              {stayStrategy !== "hotels" && (
                <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
                  <span style={{ fontSize: "0.82rem", fontWeight: 700, color: "var(--text-secondary)" }}>
                    Villa Size:
                  </span>
                  {[2, 3, 4].map((b) => (
                    <button
                      key={b}
                      type="button"
                      className={`btn ${villaBhk === b ? "btn-active-preset" : ""}`}
                      style={{ minBlockSize: "2.25rem", padding: "0.25rem 0.65rem", fontSize: "0.78rem" }}
                      onClick={() => setVillaBhk(b)}
                    >
                      {b} BHK / BR
                    </button>
                  ))}
                </div>
              )}

              <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", minInlineSize: "min(100%, 210px)", flex: 1 }}>
                <label
                  htmlFor={budgetId}
                  style={{ fontSize: "0.82rem", fontWeight: 700, color: "var(--text-secondary)", whiteSpace: "nowrap" }}
                >
                  Nightly Ceiling:{" "}
                  <strong style={{ color: "var(--text-primary)", fontVariantNumeric: "tabular-nums" }}>
                    {ceilingDisplay}
                  </strong>
                </label>
                <input
                  id={budgetId}
                  name="nightly_budget_max_inr"
                  type="range"
                  min={8000}
                  max={65000}
                  step={1000}
                  value={maxNightlyInr}
                  onChange={(e) => setMaxNightlyInr(Number(e.target.value))}
                  style={{ flex: 1, accentColor: "var(--accent-primary)" }}
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={isPlanning}
              className="ms-btn-roll"
            >
              {isPlanning ? (
                <>
                  <RefreshCw size={16} aria-hidden="true" className="spin-icon" />
                  <span>{livePhase?.phase ?? "Solving Route & Arbitrage..."}</span>
                </>
              ) : (
                <>
                  <span className="ms-btn-roll__window">
                    <span className="ms-btn-roll__track">
                      <span>Solve Arbitrage &amp; Itinerary</span>
                      <span aria-hidden="true">Solve Arbitrage &amp; Itinerary</span>
                    </span>
                  </span>
                  <span className="ms-btn-roll__chip" aria-hidden="true">
                    <ArrowRight size={15} />
                  </span>
                </>
              )}
            </button>
          </div>
        </form>
      </section>

      {/* Editorial Sample Scenarios */}
      <section
        className="surface-card"
        aria-label="Sample multi-modal scenarios"
        style={{ padding: "1.2rem 1.4rem", borderRadius: "1.35rem" }}
      >
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "0.45rem",
            marginBlockEnd: "0.85rem",
          }}
        >
          <div>
            <span
              style={{
                display: "block",
                fontSize: "0.68rem",
                fontWeight: 700,
                letterSpacing: "0.14em",
                textTransform: "uppercase",
                color: "var(--text-muted)",
              }}
            >
              02 / Curated Blueprints
            </span>
            <span style={{ fontSize: "0.86rem", fontWeight: 700, color: "var(--text-primary)" }}>
              Launch a live multi-modal corridor in one click
            </span>
          </div>
          <span style={{ fontSize: "0.74rem", color: "var(--text-muted)" }}>
            Automatically saved to your browser&apos;s Recent Trips
          </span>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))",
            gap: "0.8rem",
          }}
        >
          <button
            type="button"
            className="ms-sample-card"
            onClick={() => onTryExample("wayanad")}
          >
            <div style={{ display: "flex", justifyContent: "space-between", inlineSize: "100%", alignItems: "center" }}>
              <span className="badge badge-route">
                <Car size={12} aria-hidden="true" /> Road + Transit Split
              </span>
              <ArrowUpRight size={16} aria-hidden="true" className="ms-sample-card__arrow" />
            </div>
            <div>
              <div style={{ fontWeight: 700, fontSize: "0.94rem", letterSpacing: "-0.01em" }}>
                Bengaluru → Wayanad
              </div>
              <div style={{ fontSize: "0.76rem", color: "var(--text-muted)", marginBlockStart: "0.18rem" }}>
                6-Day SUV Corridor · Radisson Mysuru Transit + 2 BHK Estate Villa
              </div>
            </div>
          </button>

          <button
            type="button"
            className="ms-sample-card"
            onClick={() => onTryExample("goa")}
          >
            <div style={{ display: "flex", justifyContent: "space-between", inlineSize: "100%", alignItems: "center" }}>
              <span className="badge badge-gold">
                <Plane size={12} aria-hidden="true" /> Hybrid Fly + Drive
              </span>
              <ArrowUpRight size={16} aria-hidden="true" className="ms-sample-card__arrow" />
            </div>
            <div>
              <div style={{ fontWeight: 700, fontSize: "0.94rem", letterSpacing: "-0.01em" }}>
                Bengaluru → North Goa
              </div>
              <div style={{ fontSize: "0.76rem", color: "var(--text-muted)", marginBlockStart: "0.18rem" }}>
                GOX vs. GOI Gateway Arbitrage + The Blue Kite 3 BHK Pool Villa
              </div>
            </div>
          </button>

          <button
            type="button"
            className="ms-sample-card"
            onClick={() => onTryExample("mahabaleshwar")}
          >
            <div style={{ display: "flex", justifyContent: "space-between", inlineSize: "100%", alignItems: "center" }}>
              <span className="badge badge-emerald">
                <Compass size={12} aria-hidden="true" /> Western Ghats Ridge
              </span>
              <ArrowUpRight size={16} aria-hidden="true" className="ms-sample-card__arrow" />
            </div>
            <div>
              <div style={{ fontWeight: 700, fontSize: "0.94rem", letterSpacing: "-0.01em" }}>
                Mumbai → Mahabaleshwar
              </div>
              <div style={{ fontSize: "0.76rem", color: "var(--text-muted)", marginBlockStart: "0.18rem" }}>
                3 BHK Highland Villa + Morning Ghat Viewpoints &amp; Strawberry Trails
              </div>
            </div>
          </button>
        </div>
      </section>
    </div>
  );
}

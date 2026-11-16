"use client";

import React, { useId, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  Car,
  Compass,
  Hotel,
  Plane,
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
  const [stayStrategy, setStayStrategy] = useState<StayStrategy>("villas");
  const [adults, setAdults] = useState(2);
  const [children, setChildren] = useState(2);
  const [villaBhk, setVillaBhk] = useState(2);
  const [maxNightlyInr, setMaxNightlyInr] = useState(20000);

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

    const spec: TripSpec = {
      origin: safeOrigin,
      destination: safeDest,
      start_date: startDate,
      end_date: endDate >= startDate ? endDate : startDate,
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

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
      {/* Hero Banner */}
      <section
        className="surface-card"
        style={{
          padding: "1.5rem",
          background:
            "radial-gradient(circle at 88% 18%, rgba(16, 185, 129, 0.14), transparent 45%), var(--bg-surface)",
        }}
      >
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.45rem", marginBlockEnd: "0.65rem" }}>
          <span className="badge badge-emerald">
            <Sparkles size={12} aria-hidden="true" /> NSGA-II 3D Pareto Solver
          </span>
          <span className="badge badge-route">
            <Compass size={12} aria-hidden="true" /> OSRM N×N 2-Opt VRPTW
          </span>
          <span className="badge badge-gold">
            <TrendingDown size={12} aria-hidden="true" /> Cross-Channel Fee Arbitrage
          </span>
        </div>

        <h2 style={{ margin: 0, fontSize: "1.5rem", fontWeight: 800, letterSpacing: "-0.02em" }}>
          Where are you traveling next?
        </h2>
        <p
          style={{
            margin: "0.45rem 0 1.25rem",
            fontSize: "0.9rem",
            color: "var(--text-secondary)",
            maxInlineSize: "68ch",
          }}
        >
          Plan via the conversational AI copilot on the left or configure your route below. TripSage
          deduplicates villas &amp; hotels across Airbnb, The Blue Kite, direct portals, and OTAs while
          solving real road matrices, checkpost windows, and multi-gateway flights.
        </p>

        {/* Accessible Quick-Start Form */}
        <form
          ref={formRef}
          action="/api/optimize"
          method="POST"
          onBlurCapture={handleFormBlurCapture}
          onInput={handleFormInput}
          onSubmit={handleSubmit}
          style={{ display: "flex", flexDirection: "column", gap: "1.1rem" }}
        >
          {/* Origin & Destination Row */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))",
              gap: "0.95rem",
            }}
          >
            <div>
              <label htmlFor={originId} className="qs-label">
                Origin City or Neighborhood <span aria-hidden="true" style={{ color: "#ef4444" }}>*</span>
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
                Destination City or Region <span aria-hidden="true" style={{ color: "#ef4444" }}>*</span>
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
                onChange={(e) => setDestination(e.target.value)}
                placeholder="e.g., Coorg, North Goa, Sedona, Interlaken"
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
              gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
              gap: "0.85rem",
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
                onChange={(e) => setStartDate(e.target.value)}
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
              gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
              gap: "0.95rem",
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
                    onChange={() => setTransportMode("road")}
                  />
                  <Car size={15} aria-hidden="true" color="var(--route-blue)" />
                  <span>Pure Road Trip</span>
                </label>
                <label className="qs-radio-option">
                  <input
                    type="radio"
                    name="transport_mode"
                    value="flight"
                    checked={transportMode === "flight"}
                    onChange={() => setTransportMode("flight")}
                  />
                  <Plane size={15} aria-hidden="true" color="var(--gold-accent)" />
                  <span>Fly + Stay</span>
                </label>
                <label className="qs-radio-option">
                  <input
                    type="radio"
                    name="transport_mode"
                    value="hybrid"
                    checked={transportMode === "hybrid"}
                    onChange={() => setTransportMode("hybrid")}
                  />
                  <Compass size={15} aria-hidden="true" color="var(--accent-primary)" />
                  <span>Hybrid Fly + Drive</span>
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
                  <Hotel size={15} aria-hidden="true" color="var(--accent-primary)" />
                  <span>Villas / Airbnb / Blue Kite</span>
                </label>
                <label className="qs-radio-option">
                  <input
                    type="radio"
                    name="stay_strategy"
                    value="hotels"
                    checked={stayStrategy === "hotels"}
                    onChange={() => setStayStrategy("hotels")}
                  />
                  <Hotel size={15} aria-hidden="true" color="var(--route-blue)" />
                  <span>Hotels &amp; Resorts</span>
                </label>
                <label className="qs-radio-option">
                  <input
                    type="radio"
                    name="stay_strategy"
                    value="hybrid"
                    checked={stayStrategy === "hybrid"}
                    onChange={() => setStayStrategy("hybrid")}
                  />
                  <ShieldCheck size={15} aria-hidden="true" color="var(--gold-accent)" />
                  <span>Hybrid (Hotel + Villa)</span>
                </label>
              </div>
            </fieldset>
          </div>

          {/* Villa Size & Nightly Ceiling + Submit Action */}
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

              <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", minInlineSize: "220px", flex: 1 }}>
                <label
                  htmlFor={budgetId}
                  style={{ fontSize: "0.82rem", fontWeight: 700, color: "var(--text-secondary)", whiteSpace: "nowrap" }}
                >
                  Nightly Ceiling: <strong style={{ color: "var(--text-primary)" }}>{ceilingDisplay}</strong>
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
              className="btn btn-primary"
              style={{
                minBlockSize: "3.1rem",
                paddingInline: "1.35rem",
                fontSize: "0.92rem",
                fontWeight: 800,
              }}
            >
              {isPlanning ? (
                <>
                  <RefreshCw size={16} aria-hidden="true" className="spin-icon" />
                  <span>{livePhase?.phase ?? "Solving Route & Arbitrage..."}</span>
                </>
              ) : (
                <>
                  <span>Solve Arbitrage &amp; VRPTW Itinerary</span>
                  <ArrowRight size={16} aria-hidden="true" />
                </>
              )}
            </button>
          </div>
        </form>
      </section>

      {/* Optional Sample Scenarios for First-Time Visitors */}
      <section
        className="surface-card"
        aria-label="Sample multi-modal scenarios"
        style={{ padding: "1.15rem 1.35rem" }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBlockEnd: "0.75rem",
          }}
        >
          <span style={{ fontSize: "0.82rem", fontWeight: 800, color: "var(--text-secondary)" }}>
            Or explore a sample multi-modal optimization with one click:
          </span>
          <span style={{ fontSize: "0.74rem", color: "var(--text-muted)" }}>
            Saves to your browser&apos;s Recent Trips once opened
          </span>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: "0.75rem",
          }}
        >
          <button
            type="button"
            className="btn"
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "flex-start",
              gap: "0.25rem",
              padding: "0.8rem 0.95rem",
              textAlign: "start",
              blockSize: "auto",
            }}
            onClick={() => onTryExample("wayanad")}
          >
            <span style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem", fontWeight: 800, fontSize: "0.85rem" }}>
              <Car size={14} aria-hidden="true" color="var(--route-blue)" />
              Bengaluru -&gt; Wayanad
            </span>
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              6-Day Road Trip · Mysuru Transit Hotel + 2 BHK Coffee Villa
            </span>
          </button>

          <button
            type="button"
            className="btn"
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "flex-start",
              gap: "0.25rem",
              padding: "0.8rem 0.95rem",
              textAlign: "start",
              blockSize: "auto",
            }}
            onClick={() => onTryExample("goa")}
          >
            <span style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem", fontWeight: 800, fontSize: "0.85rem" }}>
              <Plane size={14} aria-hidden="true" color="var(--gold-accent)" />
              Bengaluru -&gt; North Goa
            </span>
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              Hybrid Fly + Drive · GOX vs GOI Gateway + The Blue Kite Villa
            </span>
          </button>

          <button
            type="button"
            className="btn"
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "flex-start",
              gap: "0.25rem",
              padding: "0.8rem 0.95rem",
              textAlign: "start",
              blockSize: "auto",
            }}
            onClick={() => onTryExample("mahabaleshwar")}
          >
            <span style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem", fontWeight: 800, fontSize: "0.85rem" }}>
              <Compass size={14} aria-hidden="true" color="var(--accent-primary)" />
              Mumbai -&gt; Mahabaleshwar
            </span>
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              Live Solver · 3 BHK Hill Villa + Western Ghats Viewpoints
            </span>
          </button>
        </div>
      </section>
    </div>
  );
}

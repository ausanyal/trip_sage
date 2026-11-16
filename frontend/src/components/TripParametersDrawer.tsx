"use client";

import React, { useEffect, useId, useState } from "react";
import { RefreshCw, SlidersHorizontal } from "lucide-react";
import {
  formatMoney,
  type CurrencyCode,
  type StayStrategy,
  type TransportMode,
  type TripSpec,
} from "@/types/trip";

interface TripParametersDrawerProps {
  spec: TripSpec;
  currency?: CurrencyCode;
  fxRates?: Record<string, number>;
  isPlanning?: boolean;
  onUpdateSpec: (nextSpec: TripSpec, reasonLabel: string) => void;
}

const DEFAULT_MODE_VEHICLES: Record<TransportMode, string> = {
  road: "Family SUV (Own Car)",
  flight: "Airport Private Transfer SUV",
  hybrid: "Self-Drive Rental SUV",
};

const GENERIC_VEHICLES = new Set([
  "Self-Drive SUV",
  "Family SUV (Own Car)",
  "Airport Private Transfer SUV",
  "Self-Drive Rental SUV",
]);

export function TripParametersDrawer({
  spec,
  currency = "INR",
  fxRates,
  isPlanning = false,
  onUpdateSpec,
}: TripParametersDrawerProps) {
  const baseId = useId();

  const [draftOrigin, setDraftOrigin] = useState(spec.origin);
  const [draftDest, setDraftDest] = useState(spec.destination);
  const [draftStart, setDraftStart] = useState(spec.start_date);
  const [draftEnd, setDraftEnd] = useState(spec.end_date);
  const [draftAdults, setDraftAdults] = useState(spec.party.adults);
  const [draftChildren, setDraftChildren] = useState(spec.party.children);
  const [draftVehicle, setDraftVehicle] = useState(spec.vehicle_name);
  const [draftBhk, setDraftBhk] = useState(spec.destination_villa_bhk);
  const [draftBudgetMax, setDraftBudgetMax] = useState(spec.nightly_budget_max_inr);

  useEffect(() => {
    setDraftOrigin(spec.origin);
    setDraftDest(spec.destination);
    setDraftStart(spec.start_date);
    setDraftEnd(spec.end_date);
    setDraftAdults(spec.party.adults);
    setDraftChildren(spec.party.children);
    setDraftVehicle(spec.vehicle_name);
    setDraftBhk(spec.destination_villa_bhk);
    setDraftBudgetMax(spec.nightly_budget_max_inr);
  }, [spec]);

  const buildMergedSpec = (overrides?: Partial<TripSpec>): TripSpec => {
    const cleanOrigin = draftOrigin.trim() || spec.origin;
    const cleanDest = draftDest.trim() || spec.destination;
    const safeEnd = draftEnd > draftStart ? draftEnd : draftStart;
    const childAges = Array.from({ length: draftChildren }, (_, i) =>
      spec.party.child_ages[i] ?? Math.min(14, 7 + i * 2)
    );
    const destChanged =
      cleanDest.toLowerCase().split(",")[0].trim() !==
      spec.destination.toLowerCase().split(",")[0].trim();

    return {
      ...spec,
      origin: cleanOrigin,
      destination: cleanDest,
      start_date: draftStart,
      end_date: safeEnd,
      vehicle_name: draftVehicle.trim() || spec.vehicle_name,
      destination_villa_bhk: draftBhk,
      nightly_budget_min_inr: Math.max(6000, Math.round(draftBudgetMax * 0.68)),
      nightly_budget_max_inr: draftBudgetMax,
      pinned_stays: destChanged ? [] : spec.pinned_stays,
      party: {
        ...spec.party,
        adults: draftAdults,
        children: draftChildren,
        child_ages: childAges,
      },
      ...overrides,
    };
  };

  const handleModeChange = (mode: TransportMode) => {
    const nextVeh = GENERIC_VEHICLES.has(draftVehicle)
      ? DEFAULT_MODE_VEHICLES[mode]
      : draftVehicle;
    setDraftVehicle(nextVeh);
    onUpdateSpec(
      buildMergedSpec({ transport_mode: mode, vehicle_name: nextVeh }),
      `Transport Mode -> ${
        mode === "road"
          ? "Pure Road Trip"
          : mode === "hybrid"
          ? "Hybrid (Fly + Drive)"
          : "Fly + Stay"
      }`
    );
  };

  const handleStayChange = (strategy: StayStrategy) => {
    onUpdateSpec(
      buildMergedSpec({ stay_strategy: strategy }),
      `Stay Strategy -> ${strategy.toUpperCase()}`
    );
  };

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (isPlanning) return;
    const merged = buildMergedSpec();
    onUpdateSpec(
      merged,
      `Updated ${merged.origin} -> ${merged.destination} (${merged.start_date}..${merged.end_date})`
    );
  };

  return (
    <section className="param-drawer" aria-labelledby={`${baseId}-heading`}>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "0.5rem",
          marginBlockEnd: "0.85rem",
        }}
      >
        <h2
          id={`${baseId}-heading`}
          style={{
            margin: 0,
            fontSize: "0.96rem",
            fontWeight: 800,
            display: "flex",
            alignItems: "center",
            gap: "0.45rem",
          }}
        >
          <SlidersHorizontal size={17} aria-hidden="true" color="var(--accent-primary)" />
          Bi-Directional Trip Spec (Synced with Chatbot &amp; URL Permalink)
        </h2>
        <span style={{ fontSize: "0.76rem", color: "var(--text-muted)" }}>
          Party: {draftAdults} {draftAdults === 1 ? "Adult" : "Adults"} + {draftChildren}{" "}
          {draftChildren === 1 ? "Child" : "Children"}
        </span>
      </div>

      <form
        action="/api/optimize"
        method="POST"
        onSubmit={handleSubmit}
        style={{ display: "flex", flexDirection: "column", gap: "0.9rem" }}
      >
        {/* Row 1: Upfront Tri-Modal Transport + Tri-Modal Stay Strategy Radios (<6 choices) */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(290px, 1fr))",
            gap: "0.85rem",
          }}
        >
          <fieldset className="radio-fieldset">
            <legend>1. Transport Architecture</legend>
            <div className="radio-row">
              {(
                [
                  ["road", "Pure Road Trip"],
                  ["flight", "Fly + Stay"],
                  ["hybrid", "Hybrid (Fly + Drive)"],
                ] as const
              ).map(([val, label]) => (
                <label key={val} htmlFor={`${baseId}-tm-${val}`} className="choice-label">
                  <input
                    type="radio"
                    id={`${baseId}-tm-${val}`}
                    name="transport_mode"
                    value={val}
                    checked={spec.transport_mode === val}
                    onChange={() => handleModeChange(val)}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset className="radio-fieldset">
            <legend>2. Stay Strategy</legend>
            <div className="radio-row">
              {(
                [
                  ["hotels", "Hotels & Resorts"],
                  ["villas", "Private Villas / Airbnb"],
                  ["hybrid", "Hybrid (Hotel + Villa)"],
                ] as const
              ).map(([val, label]) => (
                <label key={val} htmlFor={`${baseId}-ss-${val}`} className="choice-label">
                  <input
                    type="radio"
                    id={`${baseId}-ss-${val}`}
                    name="stay_strategy"
                    value={val}
                    checked={spec.stay_strategy === val}
                    onChange={() => handleStayChange(val)}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>
          </fieldset>
        </div>

        {/* Row 2: Origin, Destination, Dates, Party, Vehicle, Villa Size & Budget */}
        <div className="form-grid">
          <div className="field-group">
            <label htmlFor={`${baseId}-origin`}>Origin</label>
            <input
              id={`${baseId}-origin`}
              name="origin"
              type="text"
              required
              enterKeyHint="next"
              className="text-input"
              value={draftOrigin}
              onChange={(e) => setDraftOrigin(e.target.value)}
            />
          </div>

          <div className="field-group">
            <label htmlFor={`${baseId}-dest`}>Destination</label>
            <input
              id={`${baseId}-dest`}
              name="destination"
              type="text"
              required
              enterKeyHint="next"
              className="text-input"
              value={draftDest}
              onChange={(e) => setDraftDest(e.target.value)}
            />
          </div>

          <div className="field-group">
            <label htmlFor={`${baseId}-start`}>Start Date</label>
            <input
              id={`${baseId}-start`}
              name="start_date"
              type="date"
              required
              className="text-input"
              value={draftStart}
              onChange={(e) => {
                const nextS = e.target.value;
                setDraftStart(nextS);
                if (nextS && draftEnd <= nextS) {
                  const d = new Date(`${nextS}T00:00:00`);
                  if (!Number.isNaN(d.getTime())) {
                    d.setDate(d.getDate() + 3);
                    setDraftEnd(d.toISOString().slice(0, 10));
                  }
                }
              }}
            />
          </div>

          <div className="field-group">
            <label htmlFor={`${baseId}-end`}>Return Date</label>
            <input
              id={`${baseId}-end`}
              name="end_date"
              type="date"
              required
              min={draftStart}
              className="text-input"
              value={draftEnd}
              onChange={(e) => setDraftEnd(e.target.value)}
            />
          </div>

          <div className="field-group">
            <label htmlFor={`${baseId}-adults`}>Adults</label>
            <select
              id={`${baseId}-adults`}
              name="adults"
              className="select-input"
              value={draftAdults}
              onChange={(e) => setDraftAdults(Number(e.target.value))}
            >
              {[1, 2, 3, 4, 5, 6].map((n) => (
                <option key={n} value={n}>
                  {n} {n === 1 ? "Adult" : "Adults"}
                </option>
              ))}
            </select>
          </div>

          <div className="field-group">
            <label htmlFor={`${baseId}-children`}>Children</label>
            <select
              id={`${baseId}-children`}
              name="children"
              className="select-input"
              value={draftChildren}
              onChange={(e) => setDraftChildren(Number(e.target.value))}
            >
              {[0, 1, 2, 3, 4].map((n) => (
                <option key={n} value={n}>
                  {n} {n === 1 ? "Child" : "Children"}
                </option>
              ))}
            </select>
          </div>

          <div className="field-group">
            <label htmlFor={`${baseId}-vehicle`}>
              {spec.transport_mode === "flight" ? "Transfer Setup" : "Vehicle / Car Setup"}
            </label>
            <input
              id={`${baseId}-vehicle`}
              name="vehicle"
              type="text"
              className="text-input"
              value={draftVehicle}
              onChange={(e) => setDraftVehicle(e.target.value)}
            />
          </div>

          {spec.stay_strategy !== "hotels" && (
            <div className="field-group">
              <label htmlFor={`${baseId}-bhk`}>
                Villa Size ({draftBhk} BHK / BR)
              </label>
              <select
                id={`${baseId}-bhk`}
                name="villa_bhk"
                className="select-input"
                value={draftBhk}
                onChange={(e) => setDraftBhk(Number(e.target.value))}
              >
                <option value={1}>1 BHK / BR Suite</option>
                <option value={2}>2 BHK / BR Family Villa</option>
                <option value={3}>3 BHK / BR Estate Villa</option>
                <option value={4}>4 BHK / BR Grand Villa</option>
              </select>
            </div>
          )}

          <div className="field-group">
            <label htmlFor={`${baseId}-budget`}>
              Nightly Ceiling: {formatMoney(draftBudgetMax, currency, fxRates)} / night
            </label>
            <input
              id={`${baseId}-budget`}
              name="budget_max"
              type="range"
              min={8000}
              max={65000}
              step={1000}
              value={draftBudgetMax}
              onChange={(e) => setDraftBudgetMax(Number(e.target.value))}
            />
          </div>
        </div>

        {/* Row 3: VRPTW Curation & Activity Filters + Explicit Submit Action */}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "flex-end",
            justifyContent: "space-between",
            gap: "0.85rem",
          }}
        >
          <fieldset className="radio-fieldset" style={{ flex: "1 1 480px" }}>
            <legend>3. VRPTW Curation &amp; Activity Time-Window Filters</legend>
            <div className="radio-row">
              <label htmlFor={`${baseId}-climbs`} className="choice-label">
                <input
                  type="checkbox"
                  id={`${baseId}-climbs`}
                  name="moderate_climbs"
                  checked={spec.activities.moderate_climbs}
                  onChange={(e) =>
                    onUpdateSpec(
                      buildMergedSpec({
                        activities: { ...spec.activities, moderate_climbs: e.target.checked },
                      }),
                      `Moderate Climbs -> ${e.target.checked ? "Yes" : "No"}`
                    )
                  }
                />
                <span>Morning Scenic Climbs &amp; Trails</span>
              </label>

              <label htmlFor={`${baseId}-safari`} className="choice-label">
                <input
                  type="checkbox"
                  id={`${baseId}-safari`}
                  name="wildlife_safari"
                  checked={spec.activities.wildlife_safari}
                  onChange={(e) =>
                    onUpdateSpec(
                      buildMergedSpec({
                        activities: { ...spec.activities, wildlife_safari: e.target.checked },
                      }),
                      `Wildlife Safari -> ${e.target.checked ? "Yes" : "No"}`
                    )
                  }
                />
                <span>Wildlife &amp; Reserve Safari</span>
              </label>

              <label htmlFor={`${baseId}-water`} className="choice-label">
                <input
                  type="checkbox"
                  id={`${baseId}-water`}
                  name="adventure_water"
                  checked={spec.activities.adventure_water}
                  onChange={(e) =>
                    onUpdateSpec(
                      buildMergedSpec({
                        activities: { ...spec.activities, adventure_water: e.target.checked },
                      }),
                      `Adventure & Water -> ${e.target.checked ? "Yes" : "No"}`
                    )
                  }
                />
                <span>Adventure &amp; Water Sports</span>
              </label>

              <label htmlFor={`${baseId}-transit`} className="choice-label">
                <input
                  type="checkbox"
                  id={`${baseId}-transit`}
                  name="transit_sightseeing"
                  checked={spec.activities.transit_sightseeing}
                  onChange={(e) =>
                    onUpdateSpec(
                      buildMergedSpec({
                        activities: {
                          ...spec.activities,
                          transit_sightseeing: e.target.checked,
                        },
                      }),
                      `Transit Sightseeing -> ${e.target.checked ? "Yes" : "No"}`
                    )
                  }
                />
                <span>En-Route Transit Sightseeing</span>
              </label>
            </div>
          </fieldset>

          <button
            type="submit"
            disabled={isPlanning}
            className="btn btn-primary"
            style={{ minBlockSize: "2.85rem", paddingInline: "1.15rem", fontWeight: 800 }}
          >
            {isPlanning ? (
              <>
                <RefreshCw size={15} aria-hidden="true" className="spin-icon" />
                <span>Re-Solving...</span>
              </>
            ) : (
              <span>Update &amp; Re-Solve Trip</span>
            )}
          </button>
        </div>
      </form>
    </section>
  );
}

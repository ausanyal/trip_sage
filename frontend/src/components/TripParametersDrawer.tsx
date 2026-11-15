"use client";

import React, { useId } from "react";
import { SlidersHorizontal } from "lucide-react";
import type { StayStrategy, TransportMode, TripSpec } from "@/types/trip";

interface TripParametersDrawerProps {
  spec: TripSpec;
  onUpdateSpec: (nextSpec: TripSpec, reasonLabel: string) => void;
}

export function TripParametersDrawer({
  spec,
  onUpdateSpec,
}: TripParametersDrawerProps) {
  const baseId = useId();

  const handleModeChange = (mode: TransportMode) => {
    onUpdateSpec(
      { ...spec, transport_mode: mode },
      `Transport Mode -> ${mode.toUpperCase()}`
    );
  };

  const handleStayChange = (strategy: StayStrategy) => {
    onUpdateSpec(
      { ...spec, stay_strategy: strategy },
      `Stay Strategy -> ${strategy.toUpperCase()}`
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
          Bi-Directional Trip Spec (Synced with Chatbot)
        </h2>
        <span style={{ fontSize: "0.76rem", color: "var(--text-muted)" }}>
          Party: {spec.party.adults} Adults + {spec.party.children} Kids (Ages{" "}
          {spec.party.child_ages.join(" & ")})
        </span>
      </div>

      <form
        action="/api/optimize"
        method="POST"
        onSubmit={(e) => e.preventDefault()}
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
                  ["hotels", "Hotels Only"],
                  ["villas", "Airbnb / Blue Kite"],
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

        {/* Row 2: Origin, Destination, Dates, Vehicle, Villa Size & Budget */}
        <div className="form-grid">
          <div className="field-group">
            <label htmlFor={`${baseId}-origin`}>Origin</label>
            <input
              id={`${baseId}-origin`}
              name="origin"
              type="text"
              className="text-input"
              value={spec.origin}
              onChange={(e) =>
                onUpdateSpec({ ...spec, origin: e.target.value }, "Origin Updated")
              }
            />
          </div>

          <div className="field-group">
            <label htmlFor={`${baseId}-dest`}>Destination</label>
            <input
              id={`${baseId}-dest`}
              name="destination"
              type="text"
              className="text-input"
              value={spec.destination}
              onChange={(e) =>
                onUpdateSpec(
                  { ...spec, destination: e.target.value },
                  `Destination -> ${e.target.value}`
                )
              }
            />
          </div>

          <div className="field-group">
            <label htmlFor={`${baseId}-vehicle`}>Vehicle / Car Setup</label>
            <input
              id={`${baseId}-vehicle`}
              name="vehicle"
              type="text"
              className="text-input"
              value={spec.vehicle_name}
              onChange={(e) =>
                onUpdateSpec({ ...spec, vehicle_name: e.target.value }, "Vehicle Updated")
              }
            />
          </div>

          <div className="field-group">
            <label htmlFor={`${baseId}-bhk`}>
              Destination Villa Size ({spec.destination_villa_bhk} BHK)
            </label>
            <select
              id={`${baseId}-bhk`}
              name="villa_bhk"
              className="select-input"
              value={spec.destination_villa_bhk}
              onChange={(e) => {
                const bhk = Number(e.target.value);
                onUpdateSpec(
                  { ...spec, destination_villa_bhk: bhk },
                  `Villa Size -> ${bhk} BHK`
                );
              }}
            >
              <option value={1}>1 BHK Cottage</option>
              <option value={2}>2 BHK Family Villa (Selected)</option>
              <option value={3}>3 BHK Estate Villa</option>
              <option value={4}>4 BHK Grand Villa</option>
            </select>
          </div>

          <div className="field-group">
            <label htmlFor={`${baseId}-budget`}>
              Villa Nightly Ceiling: ₹{(spec.nightly_budget_max_inr / 1000).toFixed(0)}k / night
            </label>
            <input
              id={`${baseId}-budget`}
              name="budget_max"
              type="range"
              min={12000}
              max={40000}
              step={1000}
              value={spec.nightly_budget_max_inr}
              onChange={(e) => {
                const maxVal = Number(e.target.value);
                onUpdateSpec(
                  {
                    ...spec,
                    nightly_budget_min_inr: Math.max(10000, maxVal - 5000),
                    nightly_budget_max_inr: maxVal,
                  },
                  `Villa Ceiling -> ₹${maxVal / 1000}k/night`
                );
              }}
            />
          </div>
        </div>

        {/* Row 3: Family Curation Checkboxes */}
        <fieldset className="radio-fieldset">
          <legend>3. Family Curation &amp; Activity Filters (Kids Ages 8 &amp; 10)</legend>
          <div className="radio-row">
            <label htmlFor={`${baseId}-climbs`} className="choice-label">
              <input
                type="checkbox"
                id={`${baseId}-climbs`}
                name="moderate_climbs"
                checked={spec.activities.moderate_climbs}
                onChange={(e) =>
                  onUpdateSpec(
                    {
                      ...spec,
                      activities: { ...spec.activities, moderate_climbs: e.target.checked },
                    },
                    `Moderate Climbs -> ${e.target.checked ? "Yes" : "No"}`
                  )
                }
              />
              <span>Moderate Climbs (Edakkal / Soochipara)</span>
            </label>

            <label htmlFor={`${baseId}-safari`} className="choice-label">
              <input
                type="checkbox"
                id={`${baseId}-safari`}
                name="wildlife_safari"
                checked={spec.activities.wildlife_safari}
                onChange={(e) =>
                  onUpdateSpec(
                    {
                      ...spec,
                      activities: { ...spec.activities, wildlife_safari: e.target.checked },
                    },
                    `Wildlife Safari -> ${e.target.checked ? "Yes" : "No"}`
                  )
                }
              />
              <span>Wildlife Jeep Safari</span>
            </label>

            <label htmlFor={`${baseId}-water`} className="choice-label">
              <input
                type="checkbox"
                id={`${baseId}-water`}
                name="adventure_water"
                checked={spec.activities.adventure_water}
                onChange={(e) =>
                  onUpdateSpec(
                    {
                      ...spec,
                      activities: { ...spec.activities, adventure_water: e.target.checked },
                    },
                    `Water & Ziplines -> ${e.target.checked ? "Yes" : "No"}`
                  )
                }
              />
              <span>Adventure &amp; Water Rides</span>
            </label>

            <label htmlFor={`${baseId}-mysuru`} className="choice-label">
              <input
                type="checkbox"
                id={`${baseId}-mysuru`}
                name="transit_sightseeing"
                checked={spec.activities.transit_sightseeing}
                onChange={(e) =>
                  onUpdateSpec(
                    {
                      ...spec,
                      activities: {
                        ...spec.activities,
                        transit_sightseeing: e.target.checked,
                      },
                    },
                    `Mysuru Stops -> ${e.target.checked ? "Yes" : "No"}`
                  )
                }
              />
              <span>Mysuru Sightseeing Stops</span>
            </label>
          </div>
        </fieldset>
      </form>
    </section>
  );
}

"use client";

import React, { useMemo, useState } from "react";
import {
  Compass,
  Flame,
  Hotel,
  MapPin,
  Mountain,
  Plane,
  ShieldAlert,
  Utensils,
} from "lucide-react";
import type { ParetoBlueprint, StayCandidate, TimelineStop } from "@/types/trip";

interface RouteCorridorMapProps {
  blueprint: ParetoBlueprint;
  activeDay: number | null;
  onSelectDay: (day: number | null) => void;
  onInspectStay: (stay: StayCandidate) => void;
}

interface ProjectedPoint {
  x: number;
  y: number;
}

export function RouteCorridorMap({
  blueprint,
  activeDay,
  onSelectDay,
  onInspectStay,
}: RouteCorridorMapProps) {
  const [selectedPinId, setSelectedPinId] = useState<string | null>(null);

  const width = 860;
  const height = 400;
  const padX = 64;
  const padY = 48;

  const { project, segmentsProjected, stayPins, stopPins, bandipurBox } = useMemo(() => {
    const allCoords: Array<[number, number]> = [];

    for (const seg of blueprint.road.segments) {
      for (const c of seg.coordinates) {
        if (c.length >= 2) allCoords.push([c[0], c[1]]);
      }
    }
    for (const s of blueprint.stays) {
      allCoords.push([s.lng, s.lat]);
    }
    for (const d of blueprint.days) {
      for (const st of d.stops) {
        allCoords.push([st.lng, st.lat]);
      }
    }

    if (allCoords.length === 0) {
      allCoords.push([76.04, 11.55], [77.62, 12.93]);
    }

    let minLng = Infinity;
    let maxLng = -Infinity;
    let minLat = Infinity;
    let maxLat = -Infinity;

    for (const [lng, lat] of allCoords) {
      if (lng < minLng) minLng = lng;
      if (lng > maxLng) maxLng = lng;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }

    const lngSpan = Math.max(0.25, maxLng - minLng);
    const latSpan = Math.max(0.25, maxLat - minLat);

    const proj = (lng: number, lat: number): ProjectedPoint => {
      const nx = (lng - minLng) / lngSpan;
      const ny = (lat - minLat) / latSpan;
      return {
        x: padX + nx * (width - padX * 2),
        y: height - padY - ny * (height - padY * 2),
      };
    };

    const segs = blueprint.road.segments.map((seg) => {
      const pts = seg.coordinates.map(([lng, lat]) => proj(lng, lat));
      const dPath = pts
        .map((p, idx) => `${idx === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
        .join(" ");
      return { seg, pts, dPath };
    });

    const staysUnique = blueprint.stays.filter(
      (st, idx, arr) =>
        arr.findIndex(
          (o) => Math.abs(o.lat - st.lat) < 0.002 && Math.abs(o.lng - st.lng) < 0.002
        ) === idx
    );

    const sPins = staysUnique.map((stay) => ({
      stay,
      pt: proj(stay.lng, stay.lat),
    }));

    const relevantDays =
      activeDay === null
        ? blueprint.days
        : blueprint.days.filter((d) => d.day_number === activeDay);

    const minPinGap = activeDay === null ? 38 : 18;
    const rawStops: Array<{ stop: TimelineStop; dayNumber: number; pt: ProjectedPoint }> = [];
    for (const d of relevantDays) {
      for (const st of d.stops) {
        if (st.category === "stay") continue;
        // Deduplicate closely overlapping pins so text labels never collide
        const p = proj(st.lng, st.lat);
        const collides =
          rawStops.some(
            (r) =>
              Math.hypot(r.pt.x - p.x, r.pt.y - p.y) < minPinGap ||
              (Math.abs(r.pt.y - p.y) < 15 && Math.abs(r.pt.x - p.x) < 135)
          ) || sPins.some((sp) => Math.hypot(sp.pt.x - p.x, sp.pt.y - p.y) < 26);
        if (!collides) {
          rawStops.push({ stop: st, dayNumber: d.day_number, pt: p });
        }
      }
    }

    // Check if Wayanad/Bandipur corridor is in bounds
    const hasBandipur = blueprint.road.segments.some((s) =>
      s.highway_label.toLowerCase().includes("bandipur")
    );
    let bBox: { x: number; y: number; w: number; h: number } | null = null;
    if (hasBandipur) {
      const p1 = proj(76.34, 11.74);
      const p2 = proj(76.68, 11.60);
      bBox = {
        x: Math.min(p1.x, p2.x),
        y: Math.min(p1.y, p2.y),
        w: Math.abs(p2.x - p1.x),
        h: Math.abs(p2.y - p1.y),
      };
    }

    return {
      project: proj,
      segmentsProjected: segs,
      stayPins: sPins,
      stopPins: rawStops,
      bandipurBox: bBox,
    };
  }, [blueprint, activeDay]);

  const selectedStop = stopPins.find((p) => p.stop.id === selectedPinId);

  return (
    <div
      style={{
        borderRadius: "1rem",
        border: "1px solid var(--border-subtle)",
        background: "var(--bg-surface)",
        overflow: "clip",
      }}
    >
      {/* Map Header Bar */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: "0.6rem",
          padding: "0.85rem 1.1rem",
          borderBlockEnd: "1px solid var(--border-subtle)",
          background: "var(--bg-elevated)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <Compass size={18} aria-hidden="true" style={{ color: "var(--route-blue)" }} />
          <span style={{ fontWeight: 700, fontSize: "0.9rem" }}>
            Synchronized Corridor &amp; Micro-Region Canvas
          </span>
        </div>

        <span className="badge badge-route">
          {blueprint.road.total_distance_km} km · {blueprint.road.total_drive_hours}h total drive
        </span>

        {blueprint.flights.length > 0 && (
          <span className="badge badge-gold">
            <Plane size={12} aria-hidden="true" /> {blueprint.flights[0].route_label}
          </span>
        )}

        {/* Day Corridor Filter Buttons */}
        <div
          style={{
            marginInlineStart: "auto",
            display: "flex",
            flexWrap: "wrap",
            gap: "0.35rem",
          }}
          role="group"
          aria-label="Filter route map by itinerary day"
        >
          <button
            type="button"
            className={`btn ${activeDay === null ? "btn-active-preset" : ""}`}
            style={{ minBlockSize: "2rem", padding: "0.2rem 0.6rem", fontSize: "0.75rem" }}
            onClick={() => onSelectDay(null)}
          >
            All Days
          </button>
          {blueprint.days.map((d) => (
            <button
              key={d.day_number}
              type="button"
              className={`btn ${activeDay === d.day_number ? "btn-active-preset" : ""}`}
              style={{ minBlockSize: "2rem", padding: "0.2rem 0.6rem", fontSize: "0.75rem" }}
              onClick={() =>
                onSelectDay(activeDay === d.day_number ? null : d.day_number)
              }
            >
              D{d.day_number}
            </button>
          ))}
        </div>
      </div>

      {/* Vector Topographic Route Canvas */}
      <div
        style={{
          position: "relative",
          background:
            "radial-gradient(circle at 22% 72%, rgba(16, 185, 129, 0.12), transparent 48%), radial-gradient(circle at 78% 24%, rgba(56, 189, 248, 0.12), transparent 50%), #08111e",
          color: "#f8fafc",
        }}
      >
        <svg
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={`Interactive route corridor map for ${blueprint.name}`}
          style={{ inlineSize: "100%", blockSize: "auto", aspectRatio: "860 / 400" }}
        >
          <defs>
            <pattern id="topoGrid" width="44" height="44" patternUnits="userSpaceOnUse">
              <path
                d="M 44 0 L 0 0 0 44"
                fill="none"
                stroke="rgba(148, 163, 184, 0.08)"
                strokeWidth="1"
              />
            </pattern>
            <linearGradient id="routeStrokeGrad" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#34d399" />
              <stop offset="55%" stopColor="#38bdf8" />
              <stop offset="100%" stopColor="#fbbf24" />
            </linearGradient>
          </defs>

          <rect width={width} height={height} fill="url(#topoGrid)" />

          {/* Topographic Western Ghats / Hill Contour Rings */}
          <ellipse
            cx={165}
            cy={310}
            rx={135}
            ry={72}
            fill="rgba(16, 185, 129, 0.07)"
            stroke="rgba(52, 211, 153, 0.16)"
            strokeDasharray="4 4"
          />
          <ellipse
            cx={165}
            cy={310}
            rx={82}
            ry={44}
            fill="rgba(16, 185, 129, 0.08)"
            stroke="rgba(52, 211, 153, 0.22)"
          />

          {/* Bandipur - Muthanga Night-Ban Reserve Overlay */}
          {bandipurBox && (
            <g>
              <rect
                x={bandipurBox.x - 10}
                y={bandipurBox.y - 16}
                width={bandipurBox.w + 20}
                height={bandipurBox.h + 32}
                rx={12}
                fill="rgba(245, 158, 11, 0.11)"
                stroke="rgba(251, 191, 36, 0.48)"
                strokeDasharray="5 4"
              />
              <text
                x={bandipurBox.x + bandipurBox.w / 2}
                y={bandipurBox.y - 22}
                textAnchor="middle"
                fill="#fbbf24"
                fontSize="10.5"
                fontWeight="700"
              >
                Bandipur–Muthanga Reserve (Closed 9 PM – 6 AM · Cleared Daytime)
              </text>
            </g>
          )}

          {/* Optional Flight Arc for Hybrid / Flight Mode */}
          {blueprint.flights.length > 0 && stayPins.length > 0 && (
            <path
              d={`M ${width - 95} 62 Q ${width / 2} 12 ${stayPins[0].pt.x} ${stayPins[0].pt.y}`}
              fill="none"
              stroke="#fbbf24"
              strokeWidth="2.5"
              strokeDasharray="7 5"
              className="route-flow-dash"
            />
          )}

          {/* Highway Segments */}
          {segmentsProjected.map(({ seg, dPath }) => {
            const isHighlighted =
              activeDay === null ||
              seg.day_number === activeDay ||
              (seg.id.includes("local") && (activeDay === 3 || activeDay === 4));

            return (
              <g key={seg.id} opacity={isHighlighted ? 1 : 0.22}>
                <path
                  d={dPath}
                  fill="none"
                  stroke="rgba(56, 189, 248, 0.22)"
                  strokeWidth={isHighlighted ? 9 : 5}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <path
                  d={dPath}
                  fill="none"
                  stroke="url(#routeStrokeGrad)"
                  strokeWidth={isHighlighted ? 3.5 : 2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                {isHighlighted && (
                  <path
                    d={dPath}
                    fill="none"
                    stroke="#ffffff"
                    strokeOpacity="0.65"
                    strokeWidth="1.6"
                    strokeDasharray="6 8"
                    className="route-flow-dash"
                  />
                )}
              </g>
            );
          })}

          {/* Origin Marker (Koramangala / Origin) */}
          {segmentsProjected[0]?.pts[0] && (
            <g
              transform={`translate(${segmentsProjected[0].pts[0].x}, ${segmentsProjected[0].pts[0].y})`}
            >
              <circle r="8" fill="#38bdf8" stroke="#08111e" strokeWidth="2.5" />
              <text
                x="0"
                y="-14"
                textAnchor="end"
                fill="#e2e8f0"
                fontSize="11.5"
                fontWeight="700"
              >
                Koramangala (Start 2 PM)
              </text>
            </g>
          )}

          {/* Curated Activity & Dining Stop Pins */}
          {stopPins.map(({ stop, dayNumber, pt }) => {
            const isClimb = stop.category === "climb";
            const isDining = stop.category === "dining";
            const pinColor = isClimb
              ? "#fbbf24"
              : isDining
              ? "#f472b6"
              : "#a78bfa";
            const rawShort = stop.title.includes(":")
              ? stop.title.split(":")[1].trim()
              : stop.title;
            const shortStopLabel =
              rawShort.length > 26
                ? `${rawShort.slice(0, 24).replace(/\s+\S*$/, "")}…`
                : rawShort;
            const alignLeft = pt.x > width - 210;

            return (
              <g
                key={stop.id}
                transform={`translate(${pt.x}, ${pt.y})`}
                style={{ cursor: "pointer" }}
                onClick={() =>
                  setSelectedPinId(selectedPinId === stop.id ? null : stop.id)
                }
              >
                <circle
                  r={selectedPinId === stop.id ? 9 : 6.5}
                  fill={pinColor}
                  stroke="#08111e"
                  strokeWidth="2"
                />
                <text
                  x={alignLeft ? "-10" : "10"}
                  y="4"
                  textAnchor={alignLeft ? "end" : "start"}
                  fill="#cbd5e1"
                  fontSize="10"
                  fontWeight="600"
                >
                  D{dayNumber}: {shortStopLabel}
                </text>
              </g>
            );
          })}

          {/* Stay Anchor Pins (Radisson Mysore & Wayanad Villa / Blue Kite) */}
          {stayPins.map(({ stay, pt }) => {
            const cleanStayName = stay.name.split("(")[0].trim();
            const pillWidth = Math.max(142, Math.round(cleanStayName.length * 6.2 + 22));
            return (
              <g
                key={stay.id}
                transform={`translate(${pt.x}, ${pt.y})`}
                style={{ cursor: "pointer" }}
                onClick={() => onInspectStay(stay)}
              >
                <circle r="15" fill="rgba(52, 211, 153, 0.24)" />
                <circle r="9.5" fill="#10b981" stroke="#ffffff" strokeWidth="2.5" />
                <rect
                  x={-pillWidth / 2}
                  y="13"
                  width={pillWidth}
                  height="22"
                  rx="6"
                  fill="rgba(8, 17, 30, 0.9)"
                  stroke="rgba(52, 211, 153, 0.55)"
                />
                <text
                  x="0"
                  y="27"
                  textAnchor="middle"
                  fill="#ecfdf5"
                  fontSize="10.2"
                  fontWeight="700"
                >
                  {cleanStayName}
                </text>
              </g>
            );
          })}
        </svg>

        {/* Interactive Legend & Selected Stop Bar */}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "0.75rem",
            padding: "0.65rem 1rem",
            background: "rgba(7, 11, 18, 0.9)",
            borderBlockStart: "1px solid rgba(148, 163, 184, 0.16)",
            fontSize: "0.76rem",
            color: "#cbd5e1",
          }}
        >
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.9rem", alignItems: "center" }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
              <Hotel size={13} aria-hidden="true" color="#10b981" /> Stay Anchors (Click pin for fee breakdown)
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
              <Mountain size={13} aria-hidden="true" color="#fbbf24" /> Moderate Climbs
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
              <Utensils size={13} aria-hidden="true" color="#f472b6" /> Veg + Non-Veg Dining
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
              <ShieldAlert size={13} aria-hidden="true" color="#fbbf24" /> Forest Gate Verified
            </span>
          </div>

          {selectedStop ? (
            <div style={{ display: "flex", alignItems: "center", gap: "0.45rem", color: "#fde68a" }}>
              <MapPin size={13} aria-hidden="true" />
              <strong>{selectedStop.stop.title}</strong> ({selectedStop.stop.time_window})
            </div>
          ) : (
            <span style={{ color: "#94a3b8" }}>
              <Flame size={12} aria-hidden="true" style={{ display: "inline", marginInlineEnd: 4 }} />
              Click any emerald stay pin to open Cross-Channel Price Arbitrage
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Compass,
  Flame,
  Hotel,
  Layers,
  MapPin,
  Maximize2,
  Minus,
  Mountain,
  Plane,
  Plus,
  ShieldAlert,
  Utensils,
} from "lucide-react";
import {
  formatMoney,
  type CurrencyCode,
  type FlightOption,
  type ParetoBlueprint,
  type StayCandidate,
  type TimelineStop,
} from "@/types/trip";

interface RouteCorridorMapProps {
  blueprint: ParetoBlueprint;
  selectedFlight?: FlightOption | null;
  activeDay: number | null;
  effectiveDark?: boolean;
  currency?: CurrencyCode;
  fxRates?: Record<string, number>;
  onSelectDay: (day: number | null) => void;
  onInspectStay: (stay: StayCandidate) => void;
}

interface ProjectedPoint {
  x: number;
  y: number;
}

const TILE_SIZE = 256;
const MIN_ZOOM = 3;
const MAX_ZOOM = 16;

function clampLat(lat: number): number {
  return Math.max(-85.0511, Math.min(85.0511, lat));
}

function lngToWorldX(lng: number, zoom: number): number {
  const scale = TILE_SIZE * Math.pow(2, zoom);
  return ((lng + 180) / 360) * scale;
}

function latToWorldY(lat: number, zoom: number): number {
  const clamped = clampLat(lat);
  const rad = (clamped * Math.PI) / 180;
  const scale = TILE_SIZE * Math.pow(2, zoom);
  const mercN = Math.log(Math.tan(Math.PI / 4 + rad / 2));
  return (0.5 - mercN / (2 * Math.PI)) * scale;
}

function worldXToLng(wx: number, zoom: number): number {
  const scale = TILE_SIZE * Math.pow(2, zoom);
  const raw = (wx / scale) * 360 - 180;
  return ((((raw + 180) % 360) + 360) % 360) - 180;
}

function worldYToLat(wy: number, zoom: number): number {
  const scale = TILE_SIZE * Math.pow(2, zoom);
  const n = Math.PI - (2 * Math.PI * wy) / scale;
  return clampLat((180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n))));
}

function fitBoundsWebMercator(
  coords: Array<[number, number]>,
  width: number,
  height: number,
  padPx = 76
): { centerLng: number; centerLat: number; zoom: number } {
  if (coords.length === 0) {
    return { centerLng: 76.64, centerLat: 12.25, zoom: 7 };
  }

  let minLng = Infinity;
  let maxLng = -Infinity;
  let minLat = Infinity;
  let maxLat = -Infinity;

  for (const [lng, lat] of coords) {
    if (!Number.isFinite(lng) || !Number.isFinite(lat)) continue;
    if (lng < minLng) minLng = lng;
    if (lng > maxLng) maxLng = lng;
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
  }

  if (!Number.isFinite(minLng)) {
    return { centerLng: 76.64, centerLat: 12.25, zoom: 7 };
  }

  const availW = Math.max(180, width - padPx * 2);
  const availH = Math.max(140, height - padPx * 2);

  let chosenZoom = MIN_ZOOM;
  for (let z = MAX_ZOOM; z >= MIN_ZOOM; z--) {
    const dx = Math.abs(lngToWorldX(maxLng, z) - lngToWorldX(minLng, z));
    const dy = Math.abs(latToWorldY(minLat, z) - latToWorldY(maxLat, z));
    if (dx <= availW && dy <= availH) {
      chosenZoom = z;
      break;
    }
  }

  // Cap auto-fit zoom if all points are nearly identical
  if (Math.abs(maxLng - minLng) < 0.02 && Math.abs(maxLat - minLat) < 0.02) {
    chosenZoom = Math.min(chosenZoom, 12);
  }

  const midWx = (lngToWorldX(minLng, chosenZoom) + lngToWorldX(maxLng, chosenZoom)) / 2;
  const midWy = (latToWorldY(minLat, chosenZoom) + latToWorldY(maxLat, chosenZoom)) / 2;

  return {
    centerLng: worldXToLng(midWx, chosenZoom),
    centerLat: worldYToLat(midWy, chosenZoom),
    zoom: chosenZoom,
  };
}

export function RouteCorridorMap({
  blueprint,
  selectedFlight,
  activeDay,
  effectiveDark = true,
  currency = "INR",
  fxRates,
  onSelectDay,
  onInspectStay,
}: RouteCorridorMapProps) {
  const width = 800;
  const height = 440;

  const [selectedPinId, setSelectedPinId] = useState<string | null>(null);
  const [mapStyle, setMapStyle] = useState<"topo" | "satellite" | "vector">("topo");
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [showWheelZoomHint, setShowWheelZoomHint] = useState<boolean>(false);
  const wheelHintTimerRef = useRef<number | null>(null);
  const lastWheelHintAtRef = useRef<number>(0);

  const activeFlight = selectedFlight ?? blueprint.flights[0] ?? null;
  const hasFlightCoords =
    activeFlight !== null &&
    typeof activeFlight.origin_lat === "number" &&
    Number.isFinite(activeFlight.origin_lat) &&
    typeof activeFlight.origin_lng === "number" &&
    Number.isFinite(activeFlight.origin_lng) &&
    typeof activeFlight.dest_lat === "number" &&
    Number.isFinite(activeFlight.dest_lat) &&
    typeof activeFlight.dest_lng === "number" &&
    Number.isFinite(activeFlight.dest_lng);

  const relevantBoundsCoords = useMemo(() => {
    const pts: Array<[number, number]> = [];
    if (activeDay !== null) {
      for (const seg of blueprint.road.segments) {
        if (seg.day_number === activeDay) {
          for (const c of seg.coordinates) {
            if (c.length >= 2) pts.push([c[0], c[1]]);
          }
        }
      }
      const dayObj = blueprint.days.find((d) => d.day_number === activeDay);
      if (dayObj) {
        for (const st of dayObj.stops) {
          pts.push([st.lng, st.lat]);
        }
      }
    }

    if (pts.length < 2) {
      if (activeDay === null && hasFlightCoords && activeFlight) {
        pts.push([activeFlight.origin_lng as number, activeFlight.origin_lat as number]);
        pts.push([activeFlight.dest_lng as number, activeFlight.dest_lat as number]);
      }
      for (const seg of blueprint.road.segments) {
        for (const c of seg.coordinates) {
          if (c.length >= 2) pts.push([c[0], c[1]]);
        }
      }
      for (const s of blueprint.stays) {
        pts.push([s.lng, s.lat]);
      }
      for (const d of blueprint.days) {
        for (const st of d.stops) {
          pts.push([st.lng, st.lat]);
        }
      }
    }
    return pts;
  }, [blueprint, activeDay, hasFlightCoords, activeFlight]);

  const initialFit = useMemo(
    () => fitBoundsWebMercator(relevantBoundsCoords, width, height),
    [relevantBoundsCoords]
  );

  const [view, setView] = useState(initialFit);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const dragStateRef = useRef<{
    pointerId: number;
    startClientX: number;
    startClientY: number;
    startWx: number;
    startWy: number;
    moved: boolean;
  } | null>(null);

  useEffect(() => {
    setView(initialFit);
    setSelectedPinId(null);
  }, [initialFit]);

  const handleResetView = useCallback(() => {
    setView(initialFit);
  }, [initialFit]);

  const handleStepZoom = useCallback((delta: number) => {
    setView((prev) => ({
      ...prev,
      zoom: Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, prev.zoom + delta)),
    }));
  }, []);

  const zoomAroundClientPoint = useCallback(
    (clientX: number, clientY: number, delta: number) => {
      const rect = containerRef.current?.getBoundingClientRect();
      setView((prev) => {
        const nextZ = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, prev.zoom + delta));
        if (nextZ === prev.zoom || !rect || rect.width <= 0 || rect.height <= 0) {
          return { ...prev, zoom: nextZ };
        }
        const relX = ((clientX - rect.left) / rect.width) * width;
        const relY = ((clientY - rect.top) / rect.height) * height;
        const offsetX = relX - width / 2;
        const offsetY = relY - height / 2;

        const clickedWx = lngToWorldX(prev.centerLng, prev.zoom) + offsetX;
        const clickedWy = latToWorldY(prev.centerLat, prev.zoom) + offsetY;
        const clickedLng = worldXToLng(clickedWx, prev.zoom);
        const clickedLat = worldYToLat(clickedWy, prev.zoom);

        const nextCenterWx = lngToWorldX(clickedLng, nextZ) - offsetX;
        const nextCenterWy = latToWorldY(clickedLat, nextZ) - offsetY;

        return {
          centerLng: worldXToLng(nextCenterWx, nextZ),
          centerLat: worldYToLat(nextCenterWy, nextZ),
          zoom: nextZ,
        };
      });
    },
    []
  );

  const handleDoubleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const target = e.target as HTMLElement | null;
      if (target?.closest("[data-map-interactive='true']")) {
        return;
      }
      e.preventDefault();
      zoomAroundClientPoint(e.clientX, e.clientY, e.shiftKey ? -1 : 1);
    },
    [zoomAroundClientPoint]
  );

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const onNativeWheel = (ev: WheelEvent) => {
      // Cooperative scroll handling: let unmodified vertical/horizontal scroll pass straight
      // through to the page document so scrolling over the map never hijacks page scroll!
      if (!ev.ctrlKey && !ev.metaKey) {
        if (Math.abs(ev.deltaY) >= 14) {
          const now = Date.now();
          if (now - lastWheelHintAtRef.current > 1800) {
            lastWheelHintAtRef.current = now;
            setShowWheelZoomHint(true);
            if (wheelHintTimerRef.current !== null) {
              window.clearTimeout(wheelHintTimerRef.current);
            }
            wheelHintTimerRef.current = window.setTimeout(() => {
              setShowWheelZoomHint(false);
            }, 1500);
          }
        }
        return;
      }

      ev.preventDefault();
      if (Math.abs(ev.deltaY) < 2) return;
      const dir = ev.deltaY < 0 ? 1 : -1;
      zoomAroundClientPoint(ev.clientX, ev.clientY, dir);
    };

    el.addEventListener("wheel", onNativeWheel, { passive: false });
    return () => {
      el.removeEventListener("wheel", onNativeWheel);
    };
  }, [zoomAroundClientPoint]);

  useEffect(() => {
    return () => {
      if (wheelHintTimerRef.current !== null) {
        window.clearTimeout(wheelHintTimerRef.current);
      }
    };
  }, []);

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement | null;
    if (target?.closest("[data-map-interactive='true']")) {
      return;
    }
    e.currentTarget.setPointerCapture(e.pointerId);
    dragStateRef.current = {
      pointerId: e.pointerId,
      startClientX: e.clientX,
      startClientY: e.clientY,
      startWx: lngToWorldX(view.centerLng, view.zoom),
      startWy: latToWorldY(view.centerLat, view.zoom),
      moved: false,
    };
    setIsDragging(true);
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const st = dragStateRef.current;
    if (!st || st.pointerId !== e.pointerId) return;
    const rect = containerRef.current?.getBoundingClientRect();
    const scaleRatio = rect && rect.width > 0 ? width / rect.width : 1;
    const dx = (e.clientX - st.startClientX) * scaleRatio;
    const dy = (e.clientY - st.startClientY) * scaleRatio;
    if (Math.hypot(dx, dy) > 3) {
      st.moved = true;
    }
    const nextWx = st.startWx - dx;
    const nextWy = st.startWy - dy;
    setView((prev) => ({
      ...prev,
      centerLng: worldXToLng(nextWx, prev.zoom),
      centerLat: worldYToLat(nextWy, prev.zoom),
    }));
  };

  const handlePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (dragStateRef.current?.pointerId === e.pointerId) {
      dragStateRef.current = null;
      setIsDragging(false);
    }
  };

  const { tiles, segmentsProjected, stayPins, stopPins, advisoryZone, flightArc } = useMemo(() => {
    const z = view.zoom;
    const centerWx = lngToWorldX(view.centerLng, z);
    const centerWy = latToWorldY(view.centerLat, z);
    const topLeftWx = centerWx - width / 2;
    const topLeftWy = centerWy - height / 2;

    const proj = (lng: number, lat: number): ProjectedPoint => ({
      x: lngToWorldX(lng, z) - topLeftWx,
      y: latToWorldY(lat, z) - topLeftWy,
    });

    // Compute visible Web Mercator slippy tiles
    const maxTileIdx = Math.pow(2, z);
    const xStart = Math.floor(topLeftWx / TILE_SIZE);
    const xEnd = Math.floor((topLeftWx + width) / TILE_SIZE);
    const yStart = Math.max(0, Math.floor(topLeftWy / TILE_SIZE));
    const yEnd = Math.min(maxTileIdx - 1, Math.floor((topLeftWy + height) / TILE_SIZE));

    const tileItems: Array<{
      key: string;
      primaryUrl: string;
      overlayUrl?: string;
      fallbackOsmUrl: string;
      left: number;
      top: number;
    }> = [];

    if (mapStyle !== "vector") {
      for (let tx = xStart; tx <= xEnd; tx++) {
        const wrappedX = ((tx % maxTileIdx) + maxTileIdx) % maxTileIdx;
        for (let ty = yStart; ty <= yEnd; ty++) {
          let primaryUrl: string;
          let overlayUrl: string | undefined;

          if (mapStyle === "satellite") {
            primaryUrl = `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${ty}/${wrappedX}`;
            overlayUrl = `https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/${z}/${ty}/${wrappedX}`;
          } else if (effectiveDark) {
            primaryUrl = `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/${z}/${ty}/${wrappedX}`;
            overlayUrl = `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/${z}/${ty}/${wrappedX}`;
          } else {
            primaryUrl = `https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/${z}/${ty}/${wrappedX}`;
          }

          tileItems.push({
            key: `${z}-${tx}-${ty}-${mapStyle}-${effectiveDark ? "d" : "l"}`,
            primaryUrl,
            overlayUrl,
            fallbackOsmUrl: `https://tile.openstreetmap.org/${z}/${wrappedX}/${ty}.png`,
            left: tx * TILE_SIZE - topLeftWx,
            top: ty * TILE_SIZE - topLeftWy,
          });
        }
      }
    }

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

    const originPt = segs[0]?.pts[0] ?? null;
    const minPinGap = activeDay === null ? 42 : 20;
    const rawStops: Array<{ stop: TimelineStop; dayNumber: number; pt: ProjectedPoint }> = [];
    for (const d of relevantDays) {
      for (const st of d.stops) {
        // Drive and flight legs are represented by corridor polylines — never plot midpoint pins
        if (st.category === "stay" || st.category === "drive" || st.category === "flight") {
          continue;
        }
        const p = proj(st.lng, st.lat);
        const collidesWithOrigin =
          originPt !== null && Math.hypot(originPt.x - p.x, originPt.y - p.y) < 34;
        const collides =
          collidesWithOrigin ||
          rawStops.some(
            (r) =>
              Math.hypot(r.pt.x - p.x, r.pt.y - p.y) < minPinGap ||
              (Math.abs(r.pt.y - p.y) < 18 && Math.abs(r.pt.x - p.x) < 140)
          ) ||
          sPins.some(
            (sp) =>
              Math.hypot(sp.pt.x - p.x, sp.pt.y - p.y) < 34 ||
              (Math.abs(sp.pt.y + 22 - p.y) < 20 && Math.abs(sp.pt.x - p.x) < 110)
          );
        if (!collides) {
          rawStops.push({ stop: st, dayNumber: d.day_number, pt: p });
        }
      }
    }

    const gatedSeg = segs.find(
      ({ seg, pts }) =>
        Boolean(seg.gate_alert) &&
        /(?:reserve|checkpost|ban|forest|ghat|wildlife|tiger)/i.test(seg.gate_alert ?? "") &&
        !seg.id.includes("vrptw") &&
        !seg.id.includes("local") &&
        pts.length >= 2
    );
    let advZone: { x: number; y: number; w: number; h: number; pillW: number; label: string } | null = null;
    if (gatedSeg && gatedSeg.seg.gate_alert) {
      const midStart = Math.floor(gatedSeg.pts.length * 0.25);
      const midEnd = Math.max(midStart + 1, Math.ceil(gatedSeg.pts.length * 0.75));
      const slice = gatedSeg.pts.slice(midStart, midEnd + 1);
      const xs = slice.map((p) => p.x);
      const ys = slice.map((p) => p.y);
      const shortAlert = gatedSeg.seg.gate_alert.split(" — ")[0].slice(0, 58);
      advZone = {
        x: Math.min(...xs),
        y: Math.min(...ys),
        w: Math.max(80, Math.max(...xs) - Math.min(...xs)),
        h: Math.max(28, Math.max(...ys) - Math.min(...ys)),
        pillW: Math.max(190, Math.round(shortAlert.length * 5.8 + 24)),
        label: shortAlert,
      };
    }

    let fltArc: {
      dPath: string;
      oPt: ProjectedPoint;
      dPt: ProjectedPoint;
      midPt: ProjectedPoint;
      originLabel: string;
      arcBadge: string;
      badgeW: number;
    } | null = null;

    if (hasFlightCoords && activeFlight) {
      const oPt = proj(activeFlight.origin_lng as number, activeFlight.origin_lat as number);
      const dPt = proj(activeFlight.dest_lng as number, activeFlight.dest_lat as number);
      const chord = Math.hypot(dPt.x - oPt.x, dPt.y - oPt.y);
      const midX = (oPt.x + dPt.x) / 2;
      const midY = (oPt.y + dPt.y) / 2;
      const lift = Math.min(115, Math.max(32, chord * 0.24));
      const ctrlX = midX;
      const ctrlY = midY - lift;
      const curveMidX = 0.25 * oPt.x + 0.5 * ctrlX + 0.25 * dPt.x;
      const curveMidY = 0.25 * oPt.y + 0.5 * ctrlY + 0.25 * dPt.y;
      const oCode = activeFlight.origin_iata || "ORIG";
      const dCode = activeFlight.dest_iata || "DEST";
      const arcBadge = `${oCode} ✈ ${dCode} · ${activeFlight.duration}`;

      fltArc = {
        dPath: `M ${oPt.x.toFixed(1)} ${oPt.y.toFixed(1)} Q ${ctrlX.toFixed(1)} ${ctrlY.toFixed(1)} ${dPt.x.toFixed(1)} ${dPt.y.toFixed(1)}`,
        oPt,
        dPt,
        midPt: { x: curveMidX, y: curveMidY },
        originLabel: `${oCode} Airport`,
        arcBadge,
        badgeW: Math.max(128, Math.round(arcBadge.length * 6.2 + 22)),
      };
    }

    return {
      tiles: tileItems,
      segmentsProjected: segs,
      stayPins: sPins,
      stopPins: rawStops,
      advisoryZone: advZone,
      flightArc: fltArc,
    };
  }, [view, blueprint, activeDay, effectiveDark, mapStyle, hasFlightCoords, activeFlight]);

  const selectedStop = stopPins.find((p) => p.stop.id === selectedPinId);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        minInlineSize: 0,
        blockSize: "100%",
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
          gap: "0.5rem",
          padding: "0.75rem 1rem",
          borderBlockEnd: "1px solid var(--border-subtle)",
          background: "var(--bg-elevated)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
          <Compass size={17} aria-hidden="true" style={{ color: "var(--route-blue)" }} />
          <span style={{ fontWeight: 700, fontSize: "0.88rem" }}>
            Corridor &amp; VRPTW Map
          </span>
        </div>

        <span className="badge badge-route">
          {blueprint.road.total_distance_km} km · {blueprint.road.total_drive_hours}h · Z{view.zoom}
        </span>

        {activeFlight && (
          <span className="badge badge-gold">
            <Plane size={12} aria-hidden="true" /> {activeFlight.route_label} · {activeFlight.carrier.split("/")[0].trim()}
          </span>
        )}

        {/* Day Corridor Filter Buttons */}
        <div
          style={{
            marginInlineStart: "auto",
            display: "flex",
            flexWrap: "wrap",
            gap: "0.3rem",
          }}
          role="group"
          aria-label="Filter and zoom route map by itinerary day"
        >
          <button
            type="button"
            className={`btn ${activeDay === null ? "btn-active-preset" : ""}`}
            style={{ minBlockSize: "1.9rem", padding: "0.18rem 0.55rem", fontSize: "0.74rem" }}
            onClick={() => onSelectDay(null)}
          >
            Full Route
          </button>
          {blueprint.days.map((d) => (
            <button
              key={d.day_number}
              type="button"
              className={`btn ${activeDay === d.day_number ? "btn-active-preset" : ""}`}
              style={{ minBlockSize: "1.9rem", padding: "0.18rem 0.52rem", fontSize: "0.74rem" }}
              onClick={() =>
                onSelectDay(activeDay === d.day_number ? null : d.day_number)
              }
            >
              D{d.day_number}
            </button>
          ))}
        </div>
      </div>

      {/* Hybrid Slippy Web Mercator Tile + Synchronized Vector Route Viewport */}
      <div
        ref={containerRef}
        onDoubleClick={handleDoubleClick}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        style={{
          position: "relative",
          aspectRatio: `${width} / ${height}`,
          inlineSize: "100%",
          flex: "0 0 auto",
          overflow: "clip",
          cursor: isDragging ? "grabbing" : "grab",
          touchAction: "pan-y",
          userSelect: "none",
          background: effectiveDark
            ? "radial-gradient(circle at 22% 72%, rgba(16, 185, 129, 0.14), transparent 48%), #08111e"
            : "radial-gradient(circle at 22% 72%, rgba(4, 120, 87, 0.09), transparent 48%), #e6edf2",
          color: "#f8fafc",
        }}
      >
        {/* Layer 1: Keyless Web Mercator Slippy Tiles (Esri World Topo / Dark Canvas / Imagery + OSM Fallback) */}
        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            inset: 0,
            pointerEvents: "none",
          }}
        >
          {tiles.map((t) => (
            <React.Fragment key={t.key}>
              <img
                src={t.primaryUrl}
                alt=""
                draggable={false}
                onError={(ev) => {
                  const img = ev.currentTarget;
                  if (img.dataset.fallbackTried !== "1") {
                    img.dataset.fallbackTried = "1";
                    img.src = t.fallbackOsmUrl;
                  } else {
                    img.style.display = "none";
                  }
                }}
                style={{
                  position: "absolute",
                  left: `${(t.left / width) * 100}%`,
                  top: `${(t.top / height) * 100}%`,
                  width: `${(TILE_SIZE / width) * 100}%`,
                  height: `${(TILE_SIZE / height) * 100}%`,
                  maxInlineSize: "none",
                  opacity: effectiveDark ? 0.94 : 0.98,
                }}
              />
              {t.overlayUrl && (
                <img
                  src={t.overlayUrl}
                  alt=""
                  draggable={false}
                  onError={(ev) => {
                    ev.currentTarget.style.display = "none";
                  }}
                  style={{
                    position: "absolute",
                    left: `${(t.left / width) * 100}%`,
                    top: `${(t.top / height) * 100}%`,
                    width: `${(TILE_SIZE / width) * 100}%`,
                    height: `${(TILE_SIZE / height) * 100}%`,
                    maxInlineSize: "none",
                    opacity: 0.92,
                  }}
                />
              )}
            </React.Fragment>
          ))}
        </div>

        {/* Layer 2: Synchronized GeoJSON Highway Polyline + Interactive Stay & VRPTW Stop Pins */}
        <svg
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={`Interactive slippy route map for ${blueprint.name}`}
          style={{
            position: "relative",
            zIndex: 2,
            inlineSize: "100%",
            blockSize: "100%",
          }}
        >
          <title>
            Interactive route map for {blueprint.name}
            {activeFlight ? ` including ${activeFlight.route_label} flight corridor` : ""}
          </title>
          <defs>
            <pattern id="topoGrid" width="44" height="44" patternUnits="userSpaceOnUse">
              <path
                d="M 44 0 L 0 0 0 44"
                fill="none"
                stroke={
                  effectiveDark
                    ? "rgba(148, 163, 184, 0.07)"
                    : "rgba(15, 23, 42, 0.06)"
                }
                strokeWidth="1"
              />
            </pattern>
            <linearGradient id="routeStrokeGrad" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#10b981" />
              <stop offset="55%" stopColor="#0ea5e9" />
              <stop offset="100%" stopColor="#f59e0b" />
            </linearGradient>
          </defs>

          {mapStyle === "vector" && <rect width={width} height={height} fill="url(#topoGrid)" />}

          {/* Curved Gateway Flight Arc Overlay (Origin Hub -> Destination Gateway) */}
          {flightArc && (
            <g opacity={activeDay === null || activeDay === 1 || activeDay === blueprint.days.length ? 1 : 0.35}>
              <path
                d={flightArc.dPath}
                fill="none"
                stroke="rgba(8, 17, 30, 0.72)"
                strokeWidth="6.5"
                strokeLinecap="round"
              />
              <path
                d={flightArc.dPath}
                fill="none"
                stroke="#fbbf24"
                strokeWidth="2.8"
                strokeDasharray="9 7"
                strokeLinecap="round"
                className="route-flow-dash"
              />
              <g transform={`translate(${flightArc.oPt.x}, ${flightArc.oPt.y})`}>
                <circle r="13" fill="rgba(251, 191, 36, 0.24)" />
                <circle r="7.5" fill="#f59e0b" stroke="#ffffff" strokeWidth="2.2" />
                <rect
                  x="-42"
                  y="-28"
                  width="84"
                  height="18"
                  rx="5"
                  fill="rgba(8, 17, 30, 0.9)"
                  stroke="rgba(251, 191, 36, 0.55)"
                />
                <text
                  x="0"
                  y="-15.5"
                  textAnchor="middle"
                  fill="#fde68a"
                  fontSize="10"
                  fontWeight="700"
                >
                  {flightArc.originLabel}
                </text>
              </g>
              {activeDay === null && (
                <g transform={`translate(${flightArc.midPt.x}, ${flightArc.midPt.y})`}>
                  <rect
                    x={-flightArc.badgeW / 2}
                    y="-11"
                    width={flightArc.badgeW}
                    height="22"
                    rx="6"
                    fill="rgba(8, 17, 30, 0.92)"
                    stroke="#fbbf24"
                    strokeWidth="1.2"
                  />
                  <text
                    x="0"
                    y="3.5"
                    textAnchor="middle"
                    fill="#fef08a"
                    fontSize="10.2"
                    fontWeight="700"
                  >
                    {flightArc.arcBadge}
                  </text>
                </g>
              )}
            </g>
          )}

          {/* Dynamic Corridor Checkpost / Ghat / Reserve Advisory Overlay */}
          {advisoryZone && (
            <g>
              <rect
                x={advisoryZone.x - 10}
                y={advisoryZone.y - 16}
                width={advisoryZone.w + 20}
                height={advisoryZone.h + 32}
                rx={12}
                fill="rgba(245, 158, 11, 0.14)"
                stroke="rgba(251, 191, 36, 0.65)"
                strokeDasharray="5 4"
              />
              <rect
                x={advisoryZone.x + advisoryZone.w / 2 - advisoryZone.pillW / 2}
                y={Math.max(6, advisoryZone.y - 34)}
                width={advisoryZone.pillW}
                height={18}
                rx={5}
                fill="rgba(8, 17, 30, 0.88)"
              />
              <text
                x={advisoryZone.x + advisoryZone.w / 2}
                y={Math.max(18, advisoryZone.y - 22)}
                textAnchor="middle"
                fill="#fbbf24"
                fontSize="10"
                fontWeight="700"
              >
                {advisoryZone.label}
              </text>
            </g>
          )}

          {/* Highway & VRPTW Loop Segments */}
          {segmentsProjected.map(({ seg, dPath }) => {
            const isHighlighted =
              activeDay === null ||
              seg.day_number === activeDay ||
              ((seg.id.includes("local") || seg.id.includes("vrptw")) &&
                activeDay !== null &&
                seg.day_number === activeDay);

            return (
              <g key={seg.id} opacity={isHighlighted ? 1 : 0.28}>
                <path
                  d={dPath}
                  fill="none"
                  stroke="rgba(8, 17, 30, 0.65)"
                  strokeWidth={isHighlighted ? 8.5 : 4.5}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <path
                  d={dPath}
                  fill="none"
                  stroke="url(#routeStrokeGrad)"
                  strokeWidth={isHighlighted ? 4.2 : 2.2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                {isHighlighted && (
                  <path
                    d={dPath}
                    fill="none"
                    stroke="#ffffff"
                    strokeOpacity="0.75"
                    strokeWidth="1.6"
                    strokeDasharray="6 8"
                    className="route-flow-dash"
                  />
                )}
              </g>
            );
          })}

          {/* Origin Marker */}
          {segmentsProjected[0]?.pts[0] && (
            <g
              transform={`translate(${segmentsProjected[0].pts[0].x}, ${segmentsProjected[0].pts[0].y})`}
            >
              <circle r="8.5" fill="#0ea5e9" stroke="#ffffff" strokeWidth="2.5" />
              <rect
                x="-98"
                y="-28"
                width="92"
                height="18"
                rx="5"
                fill="rgba(8, 17, 30, 0.88)"
              />
              <text
                x="-52"
                y="-15"
                textAnchor="middle"
                fill="#f8fafc"
                fontSize="10.5"
                fontWeight="700"
              >
                {segmentsProjected[0].seg.from_name.slice(0, 14)}
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
              rawShort.length > 24
                ? `${rawShort.slice(0, 22).replace(/\s+\S*$/, "")}…`
                : rawShort;
            const alignLeft = pt.x > width - 210;
            const badgeW = Math.min(185, Math.max(92, shortStopLabel.length * 5.9 + 30));

            return (
              <g
                key={stop.id}
                data-map-interactive="true"
                transform={`translate(${pt.x}, ${pt.y})`}
                style={{ cursor: "pointer" }}
                onClick={() =>
                  setSelectedPinId(selectedPinId === stop.id ? null : stop.id)
                }
              >
                <circle
                  r={selectedPinId === stop.id ? 9.5 : 7}
                  fill={pinColor}
                  stroke="#08111e"
                  strokeWidth="2.2"
                />
                <rect
                  x={alignLeft ? -badgeW - 10 : 10}
                  y="-9"
                  width={badgeW}
                  height="18"
                  rx="5"
                  fill="rgba(8, 17, 30, 0.86)"
                  stroke="rgba(148, 163, 184, 0.35)"
                />
                <text
                  x={alignLeft ? -16 : 16}
                  y="3.5"
                  textAnchor={alignLeft ? "end" : "start"}
                  fill="#f1f5f9"
                  fontSize="9.8"
                  fontWeight="600"
                >
                  D{dayNumber}: {shortStopLabel}
                </text>
              </g>
            );
          })}

          {/* Stay Anchor Pins */}
          {stayPins.map(({ stay, pt }) => {
            const cleanStayName = stay.name.split("(")[0].trim().slice(0, 28);
            const rateTag = formatMoney(
              Math.round(stay.best_landed_inr / Math.max(1, stay.nights)),
              currency,
              fxRates
            );
            const fullLabel = `${cleanStayName} · ${rateTag}/N`;
            const pillWidth = Math.max(158, Math.round(fullLabel.length * 5.9 + 22));
            return (
              <g
                key={stay.id}
                data-map-interactive="true"
                transform={`translate(${pt.x}, ${pt.y})`}
                style={{ cursor: "pointer" }}
                onClick={() => onInspectStay(stay)}
              >
                <circle r="16" fill="rgba(16, 185, 129, 0.28)" />
                <circle r="10" fill="#10b981" stroke="#ffffff" strokeWidth="2.5" />
                <rect
                  x={-pillWidth / 2}
                  y="13"
                  width={pillWidth}
                  height="23"
                  rx="6"
                  fill="rgba(8, 17, 30, 0.92)"
                  stroke="#34d399"
                  strokeWidth="1.2"
                />
                <text
                  x="0"
                  y="28"
                  textAnchor="middle"
                  fill="#ecfdf5"
                  fontSize="10.2"
                  fontWeight="700"
                >
                  {fullLabel}
                </text>
              </g>
            );
          })}
        </svg>

        {/* Floating Zoom, Fit-Bounds & Tile Style Controls */}
        <div
          data-map-interactive="true"
          style={{
            position: "absolute",
            insetBlockStart: "0.75rem",
            insetInlineEnd: "0.75rem",
            zIndex: 5,
            display: "flex",
            flexDirection: "column",
            gap: "0.35rem",
          }}
        >
          <button
            type="button"
            onClick={() => handleStepZoom(1)}
            aria-label="Zoom in map"
            title="Zoom in"
            style={{
              inlineSize: "2.15rem",
              blockSize: "2.15rem",
              borderRadius: "0.55rem",
              border: "1px solid rgba(148, 163, 184, 0.35)",
              background: "rgba(8, 17, 30, 0.88)",
              color: "#f8fafc",
              display: "grid",
              placeItems: "center",
              cursor: "pointer",
            }}
          >
            <Plus size={15} aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={() => handleStepZoom(-1)}
            aria-label="Zoom out map"
            title="Zoom out"
            style={{
              inlineSize: "2.15rem",
              blockSize: "2.15rem",
              borderRadius: "0.55rem",
              border: "1px solid rgba(148, 163, 184, 0.35)",
              background: "rgba(8, 17, 30, 0.88)",
              color: "#f8fafc",
              display: "grid",
              placeItems: "center",
              cursor: "pointer",
            }}
          >
            <Minus size={15} aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={handleResetView}
            aria-label="Fit map to route bounds"
            title="Fit route bounds"
            style={{
              inlineSize: "2.15rem",
              blockSize: "2.15rem",
              borderRadius: "0.55rem",
              border: "1px solid rgba(148, 163, 184, 0.35)",
              background: "rgba(8, 17, 30, 0.88)",
              color: "#34d399",
              display: "grid",
              placeItems: "center",
              cursor: "pointer",
            }}
          >
            <Maximize2 size={14} aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={() =>
              setMapStyle((prev) =>
                prev === "topo" ? "satellite" : prev === "satellite" ? "vector" : "topo"
              )
            }
            aria-label={`Cycle map layer (current: ${mapStyle})`}
            title={
              mapStyle === "topo"
                ? "Switch to Satellite Imagery"
                : mapStyle === "satellite"
                ? "Switch to Vector Topo Grid"
                : "Switch to Street & Terrain Map"
            }
            style={{
              inlineSize: "2.15rem",
              blockSize: "2.15rem",
              borderRadius: "0.55rem",
              border: "1px solid rgba(148, 163, 184, 0.35)",
              background:
                mapStyle === "topo"
                  ? "rgba(16, 185, 129, 0.88)"
                  : mapStyle === "satellite"
                  ? "rgba(14, 165, 233, 0.9)"
                  : "rgba(8, 17, 30, 0.88)",
              color: "#ffffff",
              display: "grid",
              placeItems: "center",
              cursor: "pointer",
            }}
          >
            <Layers size={14} aria-hidden="true" />
          </button>
        </div>

        {/* Non-blocking Cooperative Scroll-Zoom Hint Pill */}
        {showWheelZoomHint && (
          <div
            aria-live="polite"
            style={{
              position: "absolute",
              insetBlockStart: "0.75rem",
              insetInlineStart: "0.75rem",
              zIndex: 6,
              padding: "0.3rem 0.65rem",
              borderRadius: "0.5rem",
              background: "rgba(8, 17, 30, 0.88)",
              border: "1px solid rgba(52, 211, 153, 0.45)",
              color: "#ecfdf5",
              fontSize: "0.72rem",
              fontWeight: 600,
              pointerEvents: "none",
              boxShadow: "0 6px 18px rgba(0, 0, 0, 0.28)",
            }}
          >
            Hold ⌘ / Ctrl + scroll or double-click to zoom map
          </div>
        )}

        {/* Keyless Basemap Attribution Pill */}
        {mapStyle !== "vector" && (
          <div
            style={{
              position: "absolute",
              insetBlockEnd: "0.45rem",
              insetInlineEnd: "0.6rem",
              zIndex: 4,
              padding: "0.12rem 0.45rem",
              borderRadius: "0.35rem",
              background: "rgba(8, 17, 30, 0.76)",
              color: "#cbd5e1",
              fontSize: "0.65rem",
              pointerEvents: "none",
            }}
          >
            Drag to pan · {mapStyle === "satellite" ? "Satellite" : "Topo"} · © OpenStreetMap · Esri
          </div>
        )}
      </div>

      {/* Interactive Legend & Selected Stop Bar */}
      <div
        style={{
          marginBlockStart: "auto",
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "0.55rem",
          padding: "0.6rem 0.95rem",
          background: "rgba(7, 11, 18, 0.94)",
          borderBlockStart: "1px solid rgba(148, 163, 184, 0.16)",
          fontSize: "0.73rem",
          color: "#cbd5e1",
        }}
      >
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.7rem", alignItems: "center" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
            <Hotel size={13} aria-hidden="true" color="#10b981" /> Stay Pins
          </span>
          {flightArc && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
              <Plane size={13} aria-hidden="true" color="#fbbf24" /> Flight Arc
            </span>
          )}
          <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
            <Mountain size={13} aria-hidden="true" color="#fbbf24" /> Climbs
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
            <Utensils size={13} aria-hidden="true" color="#f472b6" /> Dining
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
            <ShieldAlert size={13} aria-hidden="true" color="#fbbf24" /> Checkpost
          </span>
        </div>

        {selectedStop ? (
          <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", color: "#fde68a" }}>
            <MapPin size={13} aria-hidden="true" />
            <strong>{selectedStop.stop.title}</strong> ({selectedStop.stop.time_window})
          </div>
        ) : (
          <span style={{ color: "#94a3b8" }}>
            <Flame size={12} aria-hidden="true" style={{ display: "inline", marginInlineEnd: 4 }} />
            Double-click or ⌘/Ctrl+scroll to zoom · Drag to pan
          </span>
        )}
      </div>
    </div>
  );
}

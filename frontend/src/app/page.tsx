"use client";

import React, { useCallback, useEffect, useId, useRef, useState } from "react";
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
  Info,
  Layers,
  Link2,
  MapPin,
  Moon,
  Mountain,
  Pause,
  Plane,
  Play,
  Plus,
  Search,
  Share2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Sun,
  TrendingDown,
  Utensils,
  X,
} from "lucide-react";
import presetsRaw from "@/data/presets.json";
import { ChatPlannerPane } from "@/components/ChatPlannerPane";
import { DealArbitrageDialog } from "@/components/DealArbitrageDialog";
import { RouteCorridorMap } from "@/components/RouteCorridorMap";
import { TripParametersDrawer } from "@/components/TripParametersDrawer";
import { WelcomeQuickStartView } from "@/components/WelcomeQuickStartView";
import {
  DEFAULT_FX_RATES,
  formatMoney,
  type ChatMessage,
  type CurrencyCode,
  type LivePhaseStatus,
  type M3SeedId,
  type OptimizationResponse,
  type PersonaMode,
  type StayCandidate,
  type TimelineStop,
  type TripSpec,
  type UICommand,
} from "@/types/trip";

const M3_SEEDS: Array<{ id: M3SeedId; label: string; color: string }> = [
  { id: "emerald", label: "Emerald Forest", color: "#10b981" },
  { id: "amber", label: "Flame Amber", color: "#f59e0b" },
  { id: "sapphire", label: "Ocean Sapphire", color: "#0ea5e9" },
  { id: "violet", label: "Royal Violet", color: "#a855f7" },
];

const INITIAL_PRESETS = presetsRaw as unknown as {
  wayanad: OptimizationResponse;
  goa: OptimizationResponse;
};

const CURRENCY_OPTIONS: Array<{ code: CurrencyCode; label: string }> = [
  { code: "INR", label: "₹ INR" },
  { code: "USD", label: "$ USD" },
  { code: "EUR", label: "€ EUR" },
  { code: "GBP", label: "£ GBP" },
];

const RECENT_TRIPS_STORAGE_KEY = "tripsage_recent_trips_v1";

interface RecentTripEntry {
  id: string;
  label: string;
  mode: TripSpec["transport_mode"];
  optimization: OptimizationResponse;
  messages: ChatMessage[];
}

function shortCityName(raw: string): string {
  return (raw.split(",")[0] || raw).trim().slice(0, 18);
}

function buildRoutePillLabel(spec: TripSpec): string {
  return `${shortCityName(spec.origin)} -> ${shortCityName(spec.destination)}`;
}

function buildCleanBlankSpec(): TripSpec {
  const start = new Date();
  start.setDate(start.getDate() + 14);
  const end = new Date();
  end.setDate(end.getDate() + 18);
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
      d.getDate()
    ).padStart(2, "0")}`;

  return {
    origin: "Bengaluru",
    destination: "Coorg",
    start_date: iso(start),
    end_date: iso(end),
    departure_time_pref: "08:30 AM Departure",
    return_timing_pref: "Post-Lunch Return",
    transport_mode: "road",
    stay_strategy: "villas",
    vehicle_name: "Family SUV (Own Car)",
    destination_villa_bhk: 2,
    nightly_budget_min_inr: 12000,
    nightly_budget_max_inr: 20000,
    party: {
      adults: 2,
      children: 2,
      child_ages: [8, 10],
      room_setup: "2 BHK Entire Private Stay",
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
}

function buildWelcomeConversation(): ChatMessage[] {
  return [
    {
      id: "welcome-1",
      role: "assistant",
      timestamp: "Ready",
      content:
        "Welcome to TripSage! Describe your trip in plain English — origin, destination, dates, family size, and whether you want a Road Trip, Fly + Stay, or Hybrid Fly + Drive — or launch from the Quick-Start Trip Builder on the right.",
    },
  ];
}

const CONFIGURED_API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(
  /\/+$/,
  ""
);

async function fetchPlannerApi(
  path: string,
  init: RequestInit
): Promise<Response> {
  if (CONFIGURED_API_BASE) {
    return fetch(`${CONFIGURED_API_BASE}${path}`, init);
  }
  if (
    typeof window !== "undefined" &&
    (window.location.hostname === "localhost" ||
      window.location.hostname === "127.0.0.1")
  ) {
    try {
      const direct = await fetch(`http://127.0.0.1:8000${path}`, init);
      if (direct.ok) return direct;
    } catch {
      // Fall back to Next.js streaming route proxy
    }
  }
  return fetch(path, init);
}

async function consumeSsePost<T>(
  streamPath: string,
  fallbackJsonPath: string,
  payload: unknown,
  onPhase: (status: LivePhaseStatus) => void
): Promise<T> {
  try {
    const res = await fetchPlannerApi(streamPath, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(payload),
    });

    if (res.ok && res.body) {
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalPayload: T | null = null;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";

        for (const block of blocks) {
          let eventType = "message";
          let dataStr = "";
          for (const line of block.split("\n")) {
            if (line.startsWith("event:")) {
              eventType = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              dataStr += line.slice(5).trim();
            }
          }
          if (!dataStr) continue;
          const parsed = JSON.parse(dataStr);
          if (eventType === "phase") {
            onPhase(parsed as LivePhaseStatus);
          } else if (eventType === "complete") {
            finalPayload = parsed as T;
          } else if (eventType === "error") {
            throw new Error(parsed?.message ?? "Stream error");
          }
        }
      }

      if (finalPayload !== null) {
        return finalPayload;
      }
    }
  } catch {
    // Fall back cleanly to standard JSON POST
  }

  const jsonRes = await fetchPlannerApi(fallbackJsonPath, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!jsonRes.ok) {
    throw new Error(`HTTP ${jsonRes.status}`);
  }
  return (await jsonRes.json()) as T;
}

type ActiveTab = "itinerary" | "arbitrage" | "telemetry";
type StopFilter = "all" | "climb" | "dining" | "stay_drive";

export default function TripSageWorkspacePage() {
  const [hasActiveTrip, setHasActiveTrip] = useState<boolean>(false);
  const [recentTrips, setRecentTrips] = useState<RecentTripEntry[]>([]);
  const [activeRecentId, setActiveRecentId] = useState<string | null>(null);
  const [optimization, setOptimization] = useState<OptimizationResponse>(
    INITIAL_PRESETS.wayanad
  );
  const [currency, setCurrency] = useState<CurrencyCode>("INR");
  const [fxRates, setFxRates] = useState<Record<string, number>>(DEFAULT_FX_RATES);
  const [selectedBlueprintIdx, setSelectedBlueprintIdx] = useState<number>(0);
  const [selectedFlightIdx, setSelectedFlightIdx] = useState<number>(0);
  const [activeDay, setActiveDay] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>("itinerary");
  const [stopFilter, setStopFilter] = useState<StopFilter>("all");
  const [stopSearchQuery, setStopSearchQuery] = useState<string>("");
  const [showParamsDrawer, setShowParamsDrawer] = useState<boolean>(false);
  const [inspectedStay, setInspectedStay] = useState<StayCandidate | null>(null);
  const [isPlanning, setIsPlanning] = useState<boolean>(false);
  const [livePhase, setLivePhase] = useState<LivePhaseStatus | null>(null);
  const [personaMode, setPersonaMode] = useState<PersonaMode>("advisor");
  const [m3Seed, setM3Seed] = useState<M3SeedId>("emerald");
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    buildWelcomeConversation()
  );

  const saveRecentTripToBrowser = useCallback(
    (opt: OptimizationResponse, chatLog: ChatMessage[]) => {
      const entryId =
        opt.trip_id ||
        `local-${shortCityName(opt.trip_spec.origin).toLowerCase()}-${shortCityName(
          opt.trip_spec.destination
        ).toLowerCase()}`;
      const routeLabel = buildRoutePillLabel(opt.trip_spec);
      const entry: RecentTripEntry = {
        id: entryId,
        label: routeLabel,
        mode: opt.trip_spec.transport_mode,
        optimization: opt,
        messages: chatLog.slice(-8),
      };

      setActiveRecentId(entryId);
      setRecentTrips((prev) => {
        const deduped = prev.filter(
          (item) =>
            item.id !== entryId &&
            item.label.toLowerCase() !== routeLabel.toLowerCase()
        );
        const updated = [entry, ...deduped].slice(0, 4);
        try {
          localStorage.setItem(RECENT_TRIPS_STORAGE_KEY, JSON.stringify(updated));
        } catch {
          // Ignore storage quota errors in private browsing
        }
        return updated;
      });
    },
    []
  );

  // Two-state color-scheme control (System vs. Pinned Opposite)
  const [pinnedScheme, setPinnedScheme] = useState<"light" | "dark" | null>(null);
  const [systemDark, setSystemDark] = useState<boolean>(true);

  // Shareable Trip Permalink + Top-Layer `popover="manual"` Toast Notification state
  const toastPopoverId = useId();
  const toastRef = useRef<HTMLDivElement | null>(null);
  const toastTimerRef = useRef<number | null>(null);
  const [supportsPopover, setSupportsPopover] = useState<boolean>(true);
  const [legacyToastOpen, setLegacyToastOpen] = useState<boolean>(false);
  const [toastText, setToastText] = useState<string>("");

  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const routeBannerVideoRef = useRef<HTMLVideoElement | null>(null);
  const [bannerVideoPaused, setBannerVideoPaused] = useState<boolean>(false);

  useEffect(() => {
    const vid = routeBannerVideoRef.current;
    if (!vid) return;
    vid.muted = true;
    vid.playsInline = true;
    if (bannerVideoPaused) {
      vid.pause();
    } else {
      vid.play().catch(() => {});
    }
  }, [bannerVideoPaused, hasActiveTrip, optimization.trip_spec.transport_mode]);

  useEffect(() => {
    // MANDATORY: Feature detect 'popover' on HTMLElement.prototype
    if (typeof HTMLElement !== "undefined") {
      setSupportsPopover("popover" in HTMLElement.prototype);
    }

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setBannerVideoPaused(true);
    }

    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    setSystemDark(mq.matches);
    const saved = localStorage.getItem("color-scheme");
    if (saved === "light" || saved === "dark") {
      setPinnedScheme(saved);
    }

    const savedSeed = localStorage.getItem("m3-seed") as M3SeedId | null;
    if (
      savedSeed === "emerald" ||
      savedSeed === "amber" ||
      savedSeed === "sapphire" ||
      savedSeed === "violet"
    ) {
      setM3Seed(savedSeed);
      document.documentElement.dataset.m3Seed = savedSeed;
    }

    const onChange = (ev: MediaQueryListEvent) => {
      setSystemDark(ev.matches);
    };
    mq.addEventListener("change", onChange);

    // Fetch live ECB FX rates in background
    fetchPlannerApi("/api/fx", { method: "GET" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data?.rates) {
          setFxRates(data.rates as Record<string, number>);
        }
      })
      .catch(() => {});

    // Hydrate browser-cached Recent Trips (`localStorage`) first
    let cachedList: RecentTripEntry[] = [];
    try {
      const rawRecent = localStorage.getItem(RECENT_TRIPS_STORAGE_KEY);
      if (rawRecent) {
        const parsed = JSON.parse(rawRecent);
        if (Array.isArray(parsed)) {
          cachedList = parsed.filter(
            (x): x is RecentTripEntry =>
              Boolean(x && typeof x.id === "string" && x.optimization?.blueprints?.length)
          );
          setRecentTrips(cachedList);
        }
      }
    } catch {
      // Ignore malformed storage entries
    }

    // Hydrate shareable permalink if `?trip=ts-...` is present in URL; otherwise restore most recent browser search if any
    const params = new URLSearchParams(window.location.search);
    const sharedTripId = params.get("trip");
    if (sharedTripId) {
      fetchPlannerApi(`/api/trips/${encodeURIComponent(sharedTripId)}`, {
        method: "GET",
      })
        .then((r) => (r.ok ? r.json() : null))
        .then((savedPayload) => {
          if (savedPayload?.optimization) {
            const opt = savedPayload.optimization as OptimizationResponse;
            opt.trip_id = opt.trip_id || sharedTripId;
            setOptimization(opt);
            if (opt.fx_rates) setFxRates(opt.fx_rates);
            if (opt.active_currency) setCurrency(opt.active_currency);
            setSelectedBlueprintIdx(0);
            setSelectedFlightIdx(0);
            setActiveDay(null);
            setHasActiveTrip(true);
            const restoredMsgs: ChatMessage[] =
              Array.isArray(savedPayload.messages) && savedPayload.messages.length > 0
                ? savedPayload.messages.map(
                    (
                      m: {
                        role?: "user" | "assistant";
                        content?: string;
                        extracted_updates?: string[];
                        follow_up_questions?: string[];
                      },
                      i: number
                    ) => ({
                      id: `restored-${i}`,
                      role: m.role === "user" ? "user" : "assistant",
                      timestamp: "Saved Permalink",
                      content: String(m.content ?? ""),
                      extracted_updates: m.extracted_updates,
                      follow_up_questions: m.follow_up_questions,
                    })
                  )
                : buildWelcomeConversation();
            setMessages(restoredMsgs);
            saveRecentTripToBrowser(opt, restoredMsgs);
          }
        })
        .catch(() => {});
    } else if (cachedList.length > 0) {
      const latest = cachedList[0];
      setOptimization(latest.optimization);
      if (latest.optimization.fx_rates) setFxRates(latest.optimization.fx_rates);
      if (latest.optimization.active_currency) {
        setCurrency(latest.optimization.active_currency);
      }
      setMessages(
        latest.messages?.length ? latest.messages : buildWelcomeConversation()
      );
      setActiveRecentId(latest.id);
      setHasActiveTrip(true);
    }

    return () => {
      mq.removeEventListener("change", onChange);
      if (toastTimerRef.current) {
        window.clearTimeout(toastTimerRef.current);
      }
    };
  }, [saveRecentTripToBrowser]);

  const hideShareToast = useCallback(() => {
    if (toastTimerRef.current) {
      window.clearTimeout(toastTimerRef.current);
      toastTimerRef.current = null;
    }
    const el = toastRef.current as (HTMLDivElement & { hidePopover?: () => void }) | null;
    if (supportsPopover && el && typeof el.hidePopover === "function") {
      try {
        el.hidePopover();
      } catch {
        // Already hidden
      }
    } else {
      setLegacyToastOpen(false);
    }
  }, [supportsPopover]);

  const showShareToast = useCallback(
    (msg: string) => {
      setToastText(msg);
      if (toastTimerRef.current) {
        window.clearTimeout(toastTimerRef.current);
      }
      const el = toastRef.current as (HTMLDivElement & { showPopover?: () => void }) | null;
      if (supportsPopover && el && typeof el.showPopover === "function") {
        try {
          el.showPopover();
        } catch {
          // Already open in top layer
        }
      } else {
        setLegacyToastOpen(true);
      }
      toastTimerRef.current = window.setTimeout(() => {
        hideShareToast();
      }, 4200);
    },
    [hideShareToast, supportsPopover]
  );

  const handleShareTrip = async () => {
    let tid = optimization.trip_id ?? null;
    try {
      const res = await fetchPlannerApi("/api/trips", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          spec: { ...optimization.trip_spec, currency },
          optimization: { ...optimization, active_currency: currency, fx_rates: fxRates },
          messages: messages.map((m) => ({
            role: m.role,
            content: m.content,
            extracted_updates: m.extracted_updates ?? [],
          })),
          trip_id: tid,
        }),
      });
      if (res.ok) {
        const saved = (await res.json()) as { trip_id: string; share_path: string };
        tid = saved.trip_id;
        setOptimization((prev) => ({ ...prev, trip_id: tid }));
      }
    } catch {
      // Fallback to client URL hash/query if offline
    }

    const shareUrl = tid
      ? `${window.location.origin}/?trip=${tid}`
      : window.location.href;

    if (tid) {
      window.history.replaceState(null, "", `/?trip=${tid}`);
    }

    try {
      await navigator.clipboard.writeText(shareUrl);
      showShareToast(`Copied shareable permalink: ${shareUrl}`);
    } catch {
      showShareToast(`Permalink ready in address bar: /?trip=${tid ?? "ready"}`);
    }
  };

  const effectiveDark = pinnedScheme ? pinnedScheme === "dark" : systemDark;

  const toggleTheme = () => {
    const meta = document.querySelector('meta[name="color-scheme"]');
    if (pinnedScheme !== null) {
      localStorage.removeItem("color-scheme");
      if (meta) meta.setAttribute("content", "light dark");
      delete document.documentElement.dataset.theme;
      setPinnedScheme(null);
    } else {
      const opposite: "light" | "dark" = systemDark ? "light" : "dark";
      localStorage.setItem("color-scheme", opposite);
      if (meta) meta.setAttribute("content", opposite);
      document.documentElement.dataset.theme = opposite;
      setPinnedScheme(opposite);
    }
  };

  const blueprint =
    optimization.blueprints[selectedBlueprintIdx] ?? optimization.blueprints[0];

  const safeFlightIdx =
    selectedFlightIdx < blueprint.flights.length ? selectedFlightIdx : 0;
  const activeFlight =
    blueprint.flights[safeFlightIdx] ?? blueprint.flights[0] ?? null;
  const baseFlightLanded = blueprint.flights[0]?.landed_family_total_inr ?? 0;
  const baseFlightUnopt = blueprint.flights[0]?.ota_unoptimized_inr ?? 0;
  const displayedCoreLandedInr =
    blueprint.total_core_landed_inr -
    baseFlightLanded +
    (activeFlight?.landed_family_total_inr ?? 0);
  const displayedUnoptBaselineInr =
    blueprint.unoptimized_baseline_inr -
    baseFlightUnopt +
    (activeFlight?.ota_unoptimized_inr ?? 0);
  const displayedSavingsInr = Math.max(
    0,
    blueprint.total_arbitrage_savings_inr -
      (blueprint.flights[0]?.savings_inr ?? 0) +
      (activeFlight?.savings_inr ?? 0),
    displayedUnoptBaselineInr - displayedCoreLandedInr
  );

  const staysBestInr = blueprint.stays.reduce(
    (acc, s) => acc + s.best_landed_inr,
    0
  );
  const totalStayNights = blueprint.stays.reduce(
    (acc, s) => acc + Math.max(1, s.nights),
    0
  );
  const primaryStay = blueprint.stays.reduce<StayCandidate | null>(
    (best, s) => (!best || s.nights >= best.nights ? s : best),
    null
  );
  const focusedDayObj =
    activeDay !== null
      ? blueprint.days.find((d) => d.day_number === activeDay) ?? null
      : null;
  const groundLedgerLabel =
    optimization.trip_spec.transport_mode === "flight"
      ? "Airport & Local Transfers"
      : optimization.trip_spec.transport_mode === "hybrid"
      ? "Rental SUV, Fuel & Tolls"
      : "Highway Fuel & FASTag Tolls";

  const money = useCallback(
    (amountInr: number) => formatMoney(amountInr, currency, fxRates),
    [currency, fxRates]
  );

  const handleStartNewTrip = useCallback(() => {
    setHasActiveTrip(false);
    setActiveRecentId(null);
    setShowParamsDrawer(false);
    setActiveDay(null);
    setMessages(buildWelcomeConversation());
    window.history.replaceState(null, "", "/");
  }, []);

  const handleSelectRecentTrip = useCallback((entry: RecentTripEntry) => {
    setOptimization(entry.optimization);
    if (entry.optimization.fx_rates) setFxRates(entry.optimization.fx_rates);
    if (entry.optimization.active_currency) {
      setCurrency(entry.optimization.active_currency);
    }
    setMessages(
      entry.messages?.length ? entry.messages : buildWelcomeConversation()
    );
    setSelectedBlueprintIdx(0);
    setSelectedFlightIdx(0);
    setActiveDay(null);
    setActiveRecentId(entry.id);
    setHasActiveTrip(true);
    if (entry.optimization.trip_id) {
      window.history.replaceState(null, "", `/?trip=${entry.optimization.trip_id}`);
    } else {
      window.history.replaceState(null, "", "/");
    }
  }, []);

  const handleRemoveRecentTrip = useCallback(
    (entryId: string) => {
      setRecentTrips((prev) => {
        const next = prev.filter((item) => item.id !== entryId);
        try {
          localStorage.setItem(RECENT_TRIPS_STORAGE_KEY, JSON.stringify(next));
        } catch {
          // Ignore storage errors
        }
        if (activeRecentId === entryId) {
          if (next.length > 0) {
            const top = next[0];
            setOptimization(top.optimization);
            setMessages(
              top.messages?.length ? top.messages : buildWelcomeConversation()
            );
            setActiveRecentId(top.id);
            setHasActiveTrip(true);
          } else {
            setHasActiveTrip(false);
            setActiveRecentId(null);
            setMessages(buildWelcomeConversation());
            window.history.replaceState(null, "", "/");
          }
        }
        return next;
      });
    },
    [activeRecentId]
  );

  const handleUpdateSpec = useCallback(
    async (nextSpec: TripSpec, reasonLabel: string) => {
      const specWithCur = { ...nextSpec, currency: hasActiveTrip ? currency : null };
      setOptimization((prev) => ({ ...prev, trip_spec: specWithCur }));
      setIsPlanning(true);
      setLivePhase({
        phase: "Phase 1 · Intent & Constraints",
        detail: `Solving ${reasonLabel}...`,
      });
      try {
        const updated = await consumeSsePost<OptimizationResponse>(
          "/api/optimize/stream",
          "/api/optimize",
          specWithCur,
          (ph) => setLivePhase(ph)
        );
        setOptimization(updated);
        if (updated.fx_rates) setFxRates(updated.fx_rates);
        if (updated.active_currency) setCurrency(updated.active_currency);
        if (updated.trip_id) {
          window.history.replaceState(null, "", `/?trip=${updated.trip_id}`);
        }
        setSelectedBlueprintIdx(0);
        setSelectedFlightIdx(0);
        setActiveDay(null);
        setHasActiveTrip(true);

        const topFlt = updated.blueprints[0]?.flights?.[0];
        const fltSyncSuffix = topFlt
          ? ` Shortlisted ${updated.blueprints[0].flights.length} round-trip flight options led by ${topFlt.carrier} (${topFlt.origin_iata ?? updated.trip_spec.origin} -> ${topFlt.dest_iata ?? updated.trip_spec.destination}, ${formatMoney(
              topFlt.landed_family_total_inr,
              updated.active_currency ?? currency,
              updated.fx_rates ?? fxRates
            )}).`
          : "";

        const syncMsg: ChatMessage = {
          id: `sync-${Date.now()}`,
          role: "assistant",
          timestamp: "Solved Live",
          extracted_updates: [reasonLabel],
          tool_trace: updated.tool_trace,
          content: `Solved NSGA-II 3D Pareto frontier for ${updated.trip_spec.origin} -> ${updated.trip_spec.destination}: ${formatMoney(
            updated.blueprints[0].total_core_landed_inr,
            updated.active_currency ?? currency,
            updated.fx_rates ?? fxRates
          )} core all-in (saving ${formatMoney(
            updated.blueprints[0].total_arbitrage_savings_inr,
            updated.active_currency ?? currency,
            updated.fx_rates ?? fxRates
          )} across channels).${fltSyncSuffix}`,
        };
        setMessages((prev) => {
          const nextMsgs = [...prev, syncMsg];
          saveRecentTripToBrowser(updated, nextMsgs);
          return nextMsgs;
        });
      } catch {
        // Offline graceful fallback keeps UI interactive
      } finally {
        setIsPlanning(false);
        setLivePhase(null);
      }
    },
    [currency, fxRates, hasActiveTrip, saveRecentTripToBrowser]
  );

  const handleSendMessage = useCallback(
    async (userText: string) => {
      const userMsg: ChatMessage = {
        id: `u-${Date.now()}`,
        role: "user",
        timestamp: "Just now",
        content: userText,
      };
      const baseHistory = messages;
      setMessages((prev) => [...prev, userMsg]);
      setIsPlanning(true);
      setLivePhase({
        phase: "Phase 1 · Intent & Constraints",
        detail: "Parsing natural-language trip intent & constraints...",
      });

      const baseSpec = hasActiveTrip
        ? { ...optimization.trip_spec, currency }
        : buildCleanBlankSpec();

      try {
        const autoMode: PersonaMode =
          /\b(debate|bull\s+vs|compare\s+top)\b/i.test(userText)
            ? "debate"
            : /\b(risk\s+audit|hidden\s+risks|pre-mortem|devil)\b/i.test(userText)
            ? "devil"
            : /\b(eli5|like\s+i'm\s+5)\b/i.test(userText)
            ? "eli5"
            : personaMode;
        if (autoMode !== personaMode) {
          setPersonaMode(autoMode);
        }

        const payload = await consumeSsePost<{
          updated_spec: TripSpec;
          assistant_reply: string;
          extracted_updates: string[];
          follow_up_questions?: string[];
          suggested_prompts?: string[];
          ui_commands?: UICommand[];
          engine_label?: string;
          optimization?: OptimizationResponse;
        }>(
          "/api/chat/stream",
          "/api/chat",
          {
            message: userText,
            current_spec: baseSpec,
            mode: autoMode,
            history: baseHistory.map((m) => ({
              role: m.role,
              content: m.content,
            })),
          },
          (ph) => setLivePhase(ph)
        );

        const assistantMsg: ChatMessage = {
          id: `a-${Date.now()}`,
          role: "assistant",
          timestamp: "Just now",
          engine_label: payload.engine_label,
          extracted_updates: payload.extracted_updates,
          tool_trace: payload.optimization?.tool_trace,
          follow_up_questions: payload.follow_up_questions,
          suggested_prompts: payload.suggested_prompts,
          content: payload.assistant_reply,
        };

        const nextMsgs = [...baseHistory, userMsg, assistantMsg];
        setMessages(nextMsgs);

        if (payload.optimization) {
          setOptimization(payload.optimization);
          if (payload.optimization.fx_rates) {
            setFxRates(payload.optimization.fx_rates);
          }
          if (payload.optimization.active_currency) {
            setCurrency(payload.optimization.active_currency);
          }
          if (payload.optimization.trip_id) {
            window.history.replaceState(
              null,
              "",
              `/?trip=${payload.optimization.trip_id}`
            );
          }
          setSelectedBlueprintIdx(0);
          setSelectedFlightIdx(0);
          setActiveDay(null);
          setHasActiveTrip(true);
          saveRecentTripToBrowser(payload.optimization, nextMsgs);
        }

        if (Array.isArray(payload.ui_commands)) {
          for (const cmd of payload.ui_commands) {
            if (cmd.cmd === "SET_TAB" && cmd.tab) {
              setActiveTab(cmd.tab);
            } else if (cmd.cmd === "SELECT_DAY" && typeof cmd.day === "number") {
              setActiveDay(cmd.day);
            } else if (cmd.cmd === "SET_CURRENCY" && cmd.currency) {
              setCurrency(cmd.currency);
            } else if (cmd.cmd === "OPEN_PARAMS") {
              setShowParamsDrawer(true);
            } else if (
              cmd.cmd === "SELECT_BLUEPRINT" &&
              typeof cmd.blueprint_idx === "number"
            ) {
              setSelectedBlueprintIdx(cmd.blueprint_idx);
            }
          }
        }
      } catch {
        setMessages((prev) => [
          ...prev,
          {
            id: `a-err-${Date.now()}`,
            role: "assistant",
            timestamp: "Offline",
            content:
              "Planner API is currently unreachable — check your connection and try again.",
          },
        ]);
      } finally {
        setIsPlanning(false);
        setLivePhase(null);
      }
    },
    [currency, hasActiveTrip, messages, optimization.trip_spec, personaMode, saveRecentTripToBrowser]
  );

  const handleTryExample = useCallback(
    (exampleKey: "wayanad" | "goa" | "mahabaleshwar") => {
      if (exampleKey === "mahabaleshwar") {
        void handleSendMessage(
          "Plan a road trip from Mumbai to Mahabaleshwar in a 3 BHK villa"
        );
        return;
      }
      if (exampleKey === "goa") {
        void handleSendMessage(
          "Plan a hybrid fly and drive trip from Bangalore to North Goa in a 3 BHK villa with 2 adults and 2 kids"
        );
        return;
      }
      void handleSendMessage(
        "Plan a road trip with my family of 4 (2 adults and 2 kids of age 8 and 10) from Koramangala, Bangalore to Wayanad, Kerala from 12/21 to 12/26, stay at Radisson, Mysore on 12/21 and on our way back on 12/25, prefer Airbnb in a 2 BHK within 15-20k driving a Jeep Meridian SUV"
      );
    },
    [handleSendMessage]
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

  const renderFlightOptionsList = (radioGroupName: string) => {
    const tierBadges = [
      "Best Value Saver",
      "Fastest Full-Service",
      "Flexible Split-Return",
      "Alt Gateway Hub",
    ];
    return (
      <ul role="list" className="flight-options-grid">
        {blueprint.flights.map((flt, idx) => {
          const isChosen = idx === safeFlightIdx;
          const tierLabel = tierBadges[idx] ?? `Option #${idx + 1}`;
          const shortProv =
            flt.price_provenance === "live_verified"
              ? "Live Google Flights"
              : "Airfare Benchmark";
          const routeShort =
            flt.origin_iata && flt.dest_iata
              ? `${flt.origin_iata} → ${flt.dest_iata}`
              : flt.route_label.split("(")[0].trim();

          return (
            <li key={`${radioGroupName}-${flt.id}`} className="card-container">
              <article
                className="flight-option-card"
                data-selected={String(isChosen)}
              >
                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: "0.35rem",
                  }}
                >
                  <span
                    className={`badge ${
                      idx === 0 ? "badge-emerald" : "badge-gold"
                    }`}
                  >
                    <Plane size={11} aria-hidden="true" /> {tierLabel}
                  </span>
                  <span
                    className={`badge ${
                      flt.price_provenance === "live_verified"
                        ? "badge-emerald"
                        : "badge-route"
                    }`}
                    title={flt.provenance_label}
                  >
                    <Info size={11} aria-hidden="true" /> {shortProv}
                  </span>
                </div>

                <label className="flight-select-label">
                  <input
                    type="radio"
                    name={radioGroupName}
                    checked={isChosen}
                    onChange={() => setSelectedFlightIdx(idx)}
                  />
                  <span style={{ display: "flex", flexDirection: "column", gap: "0.2rem" }}>
                    <span style={{ fontWeight: 800, fontSize: "0.93rem", lineHeight: 1.28 }}>
                      {flt.carrier}
                    </span>
                    <span style={{ fontSize: "0.78rem", fontWeight: 700, color: "var(--route-blue)" }}>
                      Out ({routeShort}): {flt.depart_time} – {flt.arrive_time} ({flt.duration})
                    </span>
                    {flt.return_depart_time && flt.return_arrive_time && (
                      <span style={{ fontSize: "0.76rem", fontWeight: 600, color: "var(--text-secondary)" }}>
                        Ret ({flt.dest_iata && flt.origin_iata ? `${flt.dest_iata} → ${flt.origin_iata}` : "Return"}):{" "}
                        {flt.return_depart_time} – {flt.return_arrive_time}
                        {flt.return_duration ? ` (${flt.return_duration})` : ""}
                      </span>
                    )}
                    <span style={{ fontSize: "0.73rem", color: "var(--text-muted)" }}>
                      {flt.stops_label} · {flt.flight_numbers}
                    </span>
                  </span>
                </label>

                <p style={{ margin: 0, fontSize: "0.77rem", color: "var(--text-secondary)" }}>
                  {flt.gateway_hub_note}
                </p>

                {flt.inclusions && flt.inclusions.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
                    {flt.inclusions.map((inc, iIdx) => (
                      <span
                        key={iIdx}
                        style={{
                          fontSize: "0.7rem",
                          fontWeight: 600,
                          padding: "0.14rem 0.45rem",
                          borderRadius: "0.4rem",
                          background: "var(--bg-subtle)",
                          color: "var(--text-secondary)",
                        }}
                      >
                        {inc}
                      </span>
                    ))}
                  </div>
                )}

                <div className="flight-card-footer">
                  <div>
                    <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", fontWeight: 700 }}>
                      ROUND-TRIP ({optimization.trip_spec.party.adults + optimization.trip_spec.party.children} TRAVELERS)
                    </div>
                    <strong style={{ fontSize: "1.12rem", color: "var(--accent-primary)" }}>
                      {money(flt.landed_family_total_inr)}
                    </strong>
                    <div style={{ fontSize: "0.72rem", color: "var(--accent-primary)", fontWeight: 700 }}>
                      Saves {money(flt.savings_inr)} vs. OTA
                    </div>
                  </div>

                  <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
                    <a
                      href={flt.booking_url ?? "https://www.google.com/travel/flights"}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn"
                      aria-label={`Search ${flt.carrier} ${routeShort} (${flt.depart_time}) on Google Flights`}
                      style={{
                        textDecoration: "none",
                        minBlockSize: "2.1rem",
                        padding: "0.25rem 0.55rem",
                        fontSize: "0.74rem",
                      }}
                    >
                      Google Flights <ExternalLink size={12} aria-hidden="true" />
                    </a>
                    {flt.skyscanner_url && (
                      <a
                        href={flt.skyscanner_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="btn"
                        aria-label={`Compare ${flt.origin_iata ?? "origin"} to ${flt.dest_iata ?? "destination"} fares on Skyscanner`}
                        style={{
                          textDecoration: "none",
                          minBlockSize: "2.1rem",
                          padding: "0.25rem 0.55rem",
                          fontSize: "0.74rem",
                        }}
                      >
                        Skyscanner <ExternalLink size={12} aria-hidden="true" />
                      </a>
                    )}
                  </div>
                </div>
              </article>
            </li>
          );
        })}
      </ul>
    );
  };

  const isIntlVillas = optimization.platform_coverage.some(
    (pc) => pc.platform.includes("Plum Guide") || pc.platform.includes("Vrbo")
  );

  // Deduplicated list of all stays across active blueprint + alternative Pareto blueprints
  const allArbitrageStays = React.useMemo(() => {
    const items: Array<{ stay: StayCandidate; blueprintIdx: number; isActiveLeg: boolean }> = [];
    const seenNames = new Set<string>();
    for (const s of blueprint.stays) {
      const key = `${s.name.toLowerCase()}::${s.check_in}`;
      seenNames.add(key);
      items.push({ stay: s, blueprintIdx: selectedBlueprintIdx, isActiveLeg: true });
    }
    optimization.blueprints.forEach((bp, bpIdx) => {
      if (bpIdx === selectedBlueprintIdx) return;
      for (const s of bp.stays) {
        const key = `${s.name.toLowerCase()}::${s.check_in}`;
        if (!seenNames.has(key)) {
          seenNames.add(key);
          items.push({ stay: s, blueprintIdx: bpIdx, isActiveLeg: false });
        }
      }
    });
    return items;
  }, [blueprint.stays, optimization.blueprints, selectedBlueprintIdx]);

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

      {/* Top Navigation, Global Currency Switcher & Share Permalink */}
      <header className="top-bar">
        <div className="brand-cluster">
          <div className="brand-mark" aria-hidden="true">
            TS
          </div>
          <div>
            <h1 className="brand-title">TripSage</h1>
            <p className="brand-subtitle">
              Global Arbitrage, VRPTW &amp; Pareto Itinerary Engine
            </p>
          </div>
        </div>

        {/* New Trip + Browser-Cached Recent Trips (`localStorage`) */}
        <nav
          aria-label="New trip and recent searches"
          style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", alignItems: "center" }}
        >
          <button
            type="button"
            className={`btn ${!hasActiveTrip ? "btn-active-preset" : ""}`}
            onClick={handleStartNewTrip}
          >
            <Plus size={14} aria-hidden="true" />
            <span>New Trip</span>
          </button>

          {recentTrips.map((rt) => {
            const isActive = hasActiveTrip && activeRecentId === rt.id;
            return (
              <div
                key={rt.id}
                className="recent-trip-group"
                data-active={String(isActive)}
              >
                <button
                  type="button"
                  onClick={() => handleSelectRecentTrip(rt)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.4rem",
                    padding: "0.42rem 0.55rem 0.42rem 0.7rem",
                    border: 0,
                    background: "transparent",
                    color: "var(--text-primary)",
                    fontWeight: 700,
                    fontSize: "0.8rem",
                    cursor: "pointer",
                  }}
                >
                  {rt.mode === "road" ? (
                    <Car size={13} aria-hidden="true" color="var(--route-blue)" />
                  ) : (
                    <Plane size={13} aria-hidden="true" color="var(--gold-accent)" />
                  )}
                  <span>{rt.label}</span>
                </button>
                <button
                  type="button"
                  onClick={() => handleRemoveRecentTrip(rt.id)}
                  aria-label={`Remove ${rt.label} from recent trips`}
                  title="Remove from recent trips"
                  style={{
                    display: "grid",
                    placeItems: "center",
                    inlineSize: "1.65rem",
                    blockSize: "1.9rem",
                    border: 0,
                    borderInlineStart: "1px solid var(--border-subtle)",
                    background: "transparent",
                    color: "var(--text-muted)",
                    cursor: "pointer",
                  }}
                >
                  <X size={12} aria-hidden="true" />
                </button>
              </div>
            );
          })}
        </nav>

        <div className="header-actions">
          {hasActiveTrip && (
            <span className="badge badge-emerald" style={{ padding: "0.32rem 0.65rem", fontSize: "0.76rem" }}>
              <TrendingDown size={13} aria-hidden="true" />
              Saved {money(displayedSavingsInr)}
            </span>
          )}

          {/* Global + India-First Multi-Currency Switcher */}
          <div
            className="currency-pill-group"
            role="group"
            aria-label="Display currency"
          >
            {CURRENCY_OPTIONS.map((opt) => (
              <button
                key={opt.code}
                type="button"
                className="currency-pill-btn"
                aria-pressed={currency === opt.code}
                onClick={() => setCurrency(opt.code)}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {hasActiveTrip && (
            <>
              <button
                type="button"
                className="btn"
                onClick={handleShareTrip}
                aria-label="Save and copy shareable trip link"
              >
                <Share2 size={14} aria-hidden="true" />
                <span>Share Trip</span>
              </button>

              <button
                type="button"
                className={`btn ${showParamsDrawer ? "btn-active-preset" : ""}`}
                aria-expanded={showParamsDrawer}
                aria-controls="trip-params-panel"
                onClick={() => setShowParamsDrawer((v) => !v)}
              >
                <SlidersHorizontal size={14} aria-hidden="true" />
                {showParamsDrawer ? "Hide Inputs" : "Edit Inputs"}
              </button>
            </>
          )}

          {/* Android Material You Dynamic Tonal Seed Picker */}
          <div
            className="m3-seed-group"
            role="group"
            aria-label="Material You dynamic accent color"
          >
            {M3_SEEDS.map((s) => (
              <button
                key={s.id}
                type="button"
                className="m3-seed-swatch"
                aria-pressed={m3Seed === s.id}
                aria-label={`Accent theme: ${s.label}`}
                title={`Material You seed: ${s.label}`}
                onClick={() => {
                  setM3Seed(s.id);
                  if (s.id === "emerald") {
                    localStorage.removeItem("m3-seed");
                    delete document.documentElement.dataset.m3Seed;
                  } else {
                    localStorage.setItem("m3-seed", s.id);
                    document.documentElement.dataset.m3Seed = s.id;
                  }
                }}
              >
                <span className="m3-seed-dot" style={{ backgroundColor: s.color }} />
              </button>
            ))}
          </div>

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
              <Sun size={14} aria-hidden="true" />
            ) : (
              <Moon size={14} aria-hidden="true" />
            )}
            <span>{pinnedScheme ? `Pinned (${pinnedScheme})` : "Theme"}</span>
          </button>
        </div>
      </header>

      {/* Split Workspace: Left Conversational Agent + Right Interactive Route & Arbitrage Canvas */}
      <div className="workspace-grid">
        <ChatPlannerPane
          messages={messages}
          isPlanning={isPlanning}
          livePhase={livePhase}
          personaMode={personaMode}
          onChangePersonaMode={setPersonaMode}
          onSendMessage={handleSendMessage}
        />

        <main id="main-content" tabIndex={-1} className="main-canvas">
          {!hasActiveTrip ? (
            <WelcomeQuickStartView
              currency={currency}
              fxRates={fxRates}
              isPlanning={isPlanning}
              livePhase={livePhase}
              onLaunchSpec={handleUpdateSpec}
              onTryExample={handleTryExample}
            />
          ) : (
            <>
          {/* Cinematic Active Route Stage (MotionSites Liquid-Glass + Editorial Serif) */}
          <div className="ms-active-route-banner">
            <video
              ref={routeBannerVideoRef}
              className="ms-active-route-video"
              src={
                optimization.trip_spec.transport_mode === "road"
                  ? "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260511_131941_d136af49-e243-493a-be14-6ff3f24e09e6.mp4"
                  : optimization.trip_spec.transport_mode === "hybrid"
                  ? "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260402_054547_9875cfc5-155a-4229-8ec8-b7ba7125cbf8.mp4"
                  : "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260405_170732_8a9ccda6-5cff-4628-b164-059c500a2b41.mp4"
              }
              autoPlay
              muted
              loop
              playsInline
              preload="metadata"
              aria-hidden="true"
            />
            <div className="ms-active-route-scrim" aria-hidden="true" />
            <div className="ms-noise-overlay" aria-hidden="true" />

            <div style={{ display: "flex", flexDirection: "column", gap: "0.42rem", minInlineSize: 0 }}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", alignItems: "center" }}>
                <span
                  className="liquid-glass"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.32rem",
                    padding: "0.22rem 0.65rem",
                    borderRadius: "999px",
                    fontSize: "0.72rem",
                    fontWeight: 600,
                    color: "#e0f2fe",
                  }}
                >
                  {optimization.trip_spec.transport_mode === "road" ? (
                    <Car size={12} aria-hidden="true" color="#38bdf8" />
                  ) : (
                    <Plane size={12} aria-hidden="true" color="#fbbf24" />
                  )}
                  {optimization.trip_spec.transport_mode === "road"
                    ? "Pure Road Trip · Own Car"
                    : optimization.trip_spec.transport_mode === "hybrid"
                    ? "Hybrid · Fly + Drive"
                    : "Fly + Stay"}
                </span>

                <span
                  className="liquid-glass"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.32rem",
                    padding: "0.22rem 0.65rem",
                    borderRadius: "999px",
                    fontSize: "0.72rem",
                    fontWeight: 600,
                    color: "#fde68a",
                  }}
                >
                  <Hotel size={12} aria-hidden="true" color="#34d399" />
                  {optimization.trip_spec.stay_strategy === "hybrid"
                    ? `Hybrid Stays (Hotel + ${optimization.trip_spec.destination_villa_bhk}BHK Villa)`
                    : optimization.trip_spec.stay_strategy === "villas"
                    ? isIntlVillas
                      ? "Private Villas (Airbnb / Plum Guide / Vrbo)"
                      : "Villas (Airbnb / The Blue Kite / StayVista)"
                    : "Hotels & Resorts"}
                </span>

                <span style={{ fontSize: "0.76rem", color: "rgba(226, 232, 240, 0.8)", fontWeight: 500 }}>
                  {optimization.trip_spec.start_date} to {optimization.trip_spec.end_date} ·{" "}
                  {optimization.trip_spec.party.adults}{" "}
                  {optimization.trip_spec.party.adults === 1 ? "Adult" : "Adults"} +{" "}
                  {optimization.trip_spec.party.children}{" "}
                  {optimization.trip_spec.party.children === 1 ? "Kid" : "Kids"}
                  {optimization.trip_spec.party.child_ages.length > 0
                    ? ` (${optimization.trip_spec.party.child_ages.join(", ")} yrs)`
                    : ""}
                </span>
              </div>

              <h2 className="ms-route-title">
                <span>{optimization.trip_spec.origin}</span>
                <ArrowRight size={19} aria-hidden="true" color="#34d399" style={{ alignSelf: "center" }} />
                <span className="ms-serif-accent" style={{ fontSize: "1.14em" }}>
                  {optimization.trip_spec.destination}
                </span>
              </h2>

              <p style={{ margin: 0, fontSize: "0.8rem", color: "rgba(203, 213, 225, 0.86)" }}>
                {optimization.trip_spec.transport_mode === "flight" ? "Transfers" : "Vehicle"}:{" "}
                <strong style={{ color: "#ffffff" }}>{optimization.trip_spec.vehicle_name}</strong> ·{" "}
                {optimization.trip_spec.transport_mode === "flight" ? "Schedule" : "Rollout"}:{" "}
                <strong style={{ color: "#ffffff" }}>{optimization.trip_spec.departure_time_pref}</strong> ·{" "}
                {blueprint.days.length} Days · {blueprint.road.total_distance_km} km ·{" "}
                {optimization.trip_spec.activities.dietary === "both"
                  ? "Veg + Non-Veg Curated"
                  : "Pure Veg"}
              </p>
            </div>

            {/* Liquid-Glass Workspace Controls (Replaces duplicate Core All-In card) */}
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.45rem" }}>
              <button
                type="button"
                className="liquid-glass ms-glass-action"
                aria-expanded={showParamsDrawer}
                aria-controls="trip-params-panel"
                onClick={() => setShowParamsDrawer((v) => !v)}
              >
                <SlidersHorizontal size={13} aria-hidden="true" color="#34d399" />
                <span>{showParamsDrawer ? "Close Spec" : "Tune Route Spec"}</span>
              </button>

              <button
                type="button"
                className="liquid-glass ms-glass-action"
                onClick={() => {
                  setActiveTab("arbitrage");
                  document.getElementById("tab-arbitrage")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
                }}
              >
                <TrendingDown size={13} aria-hidden="true" color="#fbbf24" />
                <span>Compare {allArbitrageStays.length} Stays</span>
              </button>

              <button
                type="button"
                className="liquid-glass ms-glass-action"
                aria-pressed={bannerVideoPaused}
                aria-label={
                  bannerVideoPaused
                    ? "Play route atmosphere video"
                    : "Pause route atmosphere video"
                }
                title={bannerVideoPaused ? "Play atmosphere video" : "Pause atmosphere video"}
                onClick={() => setBannerVideoPaused((v) => !v)}
                style={{ paddingInline: "0.58rem" }}
              >
                {bannerVideoPaused ? (
                  <Play size={13} aria-hidden="true" />
                ) : (
                  <Pause size={13} aria-hidden="true" />
                )}
              </button>
            </div>
          </div>

          {/* Collapsible Bi-Directional Trip Parameters Form */}
          <div id="trip-params-panel" hidden={!showParamsDrawer}>
            {showParamsDrawer && (
              <TripParametersDrawer
                spec={optimization.trip_spec}
                currency={currency}
                fxRates={fxRates}
                isPlanning={isPlanning}
                onUpdateSpec={handleUpdateSpec}
              />
            )}
          </div>

          {/* Pareto-Optimal Trip Blueprint Cards */}
          <section aria-labelledby="pareto-heading">
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "0.4rem",
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
                Strict Non-Dominated Pareto Frontier ({optimization.blueprints.length} Solved)
              </h2>
              <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.55rem" }}>
                <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                  {optimization.pareto_frontier_note ??
                    "NSGA-II 3D Frontier across Cost × Fatigue × Utility"}
                </span>
                <button
                  type="button"
                  disabled={isPlanning}
                  className="btn"
                  style={{ minBlockSize: "1.95rem", padding: "0.2rem 0.6rem", fontSize: "0.74rem" }}
                  onClick={() =>
                    void handleSendMessage(
                      `Search more similar places to stay in ${optimization.trip_spec.destination} so I have more options to choose from`
                    )
                  }
                >
                  <Plus size={12} aria-hidden="true" />
                  <span>
                    {(optimization.trip_spec.stay_options_limit ?? 3) < 6
                      ? "More Stay Options"
                      : "Next Batch of Stays"}
                  </span>
                </button>
              </div>
            </div>

            <div className="blueprint-grid">
              {optimization.blueprints.map((bp, idx) => {
                const isSelected = idx === selectedBlueprintIdx;
                return (
                  <button
                    key={bp.id}
                    type="button"
                    className="ms-pareto-card"
                    onClick={() => setSelectedBlueprintIdx(idx)}
                    aria-pressed={isSelected}
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
                      <span
                        style={{
                          fontSize: "0.72rem",
                          fontWeight: 700,
                          color: "var(--gold-accent)",
                          fontVariantNumeric: "tabular-nums",
                        }}
                      >
                        Fatigue {bp.fatigue_score} · Score {bp.deal_anomaly_score}
                      </span>
                    </div>

                    <div style={{ fontWeight: 700, fontSize: "0.93rem", lineHeight: 1.28, letterSpacing: "-0.01em" }}>
                      {bp.name}
                    </div>
                    <div style={{ fontSize: "0.76rem", color: "var(--text-muted)" }}>
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
                      <strong style={{ fontSize: "1.08rem", fontVariantNumeric: "tabular-nums" }}>
                        {money(bp.total_core_landed_inr)}
                      </strong>
                      <span
                        style={{
                          fontSize: "0.75rem",
                          color: "var(--accent-primary)",
                          fontWeight: 700,
                          fontVariantNumeric: "tabular-nums",
                        }}
                      >
                        Saves {money(bp.total_arbitrage_savings_inr)}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>

          {/* First-Class Gateway Flight & Carrier Arbitrage Selector */}
          {blueprint.flights.length > 0 && (
            <div>
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: "0.45rem",
                  marginBlockEnd: "0.65rem",
                }}
              >
                <h2
                  style={{
                    margin: 0,
                    fontSize: "0.95rem",
                    fontWeight: 800,
                    display: "flex",
                    alignItems: "center",
                    gap: "0.45rem",
                  }}
                >
                  <Plane size={17} aria-hidden="true" color="var(--gold-accent)" />
                  Gateway Flight &amp; Carrier Arbitrage ({blueprint.flights.length} Round-Trip Options)
                </h2>
                <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                  Select any carrier or gateway airport to update your Core All-In total &amp; map flight arc
                </span>
              </div>
              {renderFlightOptionsList("workspace-gateway-flight")}
            </div>
          )}

          {/* 2/3 Corridor Map + 1/3 Live Cost Ledger & Route Companion Grid */}
          <div className="map-companion-wrap">
            <div className="map-companion-grid">
              <RouteCorridorMap
                blueprint={blueprint}
                selectedFlight={activeFlight}
                activeDay={activeDay}
                effectiveDark={effectiveDark}
                currency={currency}
                fxRates={fxRates}
                onSelectDay={setActiveDay}
                onInspectStay={setInspectedStay}
              />

              <aside
                className="map-companion-panel"
                aria-label="Core All-In Cost Ledger and Corridor Insights"
              >
                {/* Top Block: Live Itemized Core All-In Cost Ledger */}
                <div
                  style={{
                    padding: "0.85rem 1rem",
                    borderBlockEnd: "1px solid var(--border-subtle)",
                    background: "var(--bg-elevated)",
                    display: "flex",
                    flexDirection: "column",
                    gap: "0.48rem",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: "0.4rem",
                    }}
                  >
                    <span
                      style={{
                        fontSize: "0.75rem",
                        fontWeight: 800,
                        letterSpacing: "0.03em",
                        textTransform: "uppercase",
                        color: "var(--text-muted)",
                      }}
                    >
                      Core All-In Ledger
                    </span>
                    <span className="badge badge-emerald">
                      <TrendingDown size={12} aria-hidden="true" /> Saved{" "}
                      {money(displayedSavingsInr)}
                    </span>
                  </div>

                  <div className="ledger-row">
                    <span style={{ color: "var(--text-secondary)" }}>
                      Stays ({blueprint.stays.length}{" "}
                      {blueprint.stays.length === 1 ? "leg" : "legs"} · {totalStayNights}N)
                    </span>
                    <strong style={{ fontWeight: 700 }}>{money(staysBestInr)}</strong>
                  </div>

                  {activeFlight && (
                    <div className="ledger-row">
                      <span style={{ color: "var(--text-secondary)" }}>
                        Flights ({activeFlight.origin_iata && activeFlight.dest_iata
                          ? `${activeFlight.origin_iata} ↔ ${activeFlight.dest_iata}`
                          : "Round-Trip"})
                      </span>
                      <strong style={{ fontWeight: 700 }}>
                        {money(activeFlight.landed_family_total_inr)}
                      </strong>
                    </div>
                  )}

                  <div className="ledger-row">
                    <span style={{ color: "var(--text-secondary)" }}>
                      {groundLedgerLabel}
                    </span>
                    <strong style={{ fontWeight: 700 }}>
                      {money(blueprint.road.total_road_cost_inr)}
                    </strong>
                  </div>

                  <div
                    style={{
                      paddingBlockStart: "0.45rem",
                      marginBlockStart: "0.1rem",
                      borderBlockStart: "1px dashed var(--border-subtle)",
                      display: "flex",
                      alignItems: "baseline",
                      justifyContent: "space-between",
                      gap: "0.5rem",
                    }}
                  >
                    <span style={{ fontSize: "0.82rem", fontWeight: 800 }}>
                      Landed Core Total
                    </span>
                    <div style={{ textAlign: "end" }}>
                      <span
                        style={{
                          fontSize: "1.05rem",
                          fontWeight: 800,
                          color: "var(--accent-primary)",
                        }}
                      >
                        {money(displayedCoreLandedInr)}
                      </span>
                      <span
                        style={{
                          marginInlineStart: "0.4rem",
                          fontSize: "0.74rem",
                          textDecoration: "line-through",
                          color: "var(--text-muted)",
                        }}
                      >
                        {money(displayedUnoptBaselineInr)}
                      </span>
                    </div>
                  </div>

                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: "0.4rem",
                      marginBlockStart: "0.15rem",
                    }}
                  >
                    <span style={{ fontSize: "0.71rem", color: "var(--text-muted)" }}>
                      +{money(blueprint.dining_and_activities_est_inr)} est. dining &amp; entry
                    </span>
                    {primaryStay && (
                      <button
                        type="button"
                        className="btn"
                        style={{
                          minBlockSize: "1.85rem",
                          padding: "0.18rem 0.55rem",
                          fontSize: "0.73rem",
                        }}
                        onClick={() => setInspectedStay(primaryStay)}
                      >
                        <ShieldCheck size={13} aria-hidden="true" color="var(--accent-primary)" />
                        <span>Inspect Fee Math</span>
                      </button>
                    )}
                  </div>
                </div>

                {/* Bottom Block: Synchronized Day Snapshot (when D1..DN selected) OR Arbitrage & VRPTW Insights */}
                <div
                  style={{
                    padding: "0.85rem 1rem",
                    display: "flex",
                    flexDirection: "column",
                    gap: "0.5rem",
                    flex: "1 1 auto",
                  }}
                >
                  {focusedDayObj ? (
                    <>
                      <div
                        style={{
                          display: "flex",
                          flexWrap: "wrap",
                          alignItems: "center",
                          justifyContent: "space-between",
                          gap: "0.4rem",
                        }}
                      >
                        <span
                          style={{
                            fontSize: "0.78rem",
                            fontWeight: 800,
                            color: "var(--route-blue)",
                            display: "inline-flex",
                            alignItems: "center",
                            gap: "0.35rem",
                          }}
                        >
                          <Compass size={14} aria-hidden="true" />
                          Day {focusedDayObj.day_number} · {focusedDayObj.date_label}
                        </span>
                        <button
                          type="button"
                          className="btn"
                          style={{
                            minBlockSize: "1.65rem",
                            padding: "0.12rem 0.48rem",
                            fontSize: "0.7rem",
                          }}
                          onClick={() => setActiveDay(null)}
                        >
                          Full Route
                        </button>
                      </div>

                      <div style={{ fontSize: "0.84rem", fontWeight: 700, lineHeight: 1.3 }}>
                        {focusedDayObj.headline}
                      </div>

                      <div style={{ fontSize: "0.73rem", color: "var(--text-muted)" }}>
                        {focusedDayObj.drive_km} km · {focusedDayObj.drive_time_label} · Overnight:{" "}
                        <strong style={{ color: "var(--text-secondary)" }}>
                          {focusedDayObj.overnight_label}
                        </strong>
                      </div>

                      <ul
                        role="list"
                        style={{
                          margin: 0,
                          padding: 0,
                          listStyle: "none",
                          display: "flex",
                          flexDirection: "column",
                          gap: "0.35rem",
                        }}
                      >
                        {focusedDayObj.stops.slice(0, 4).map((st) => (
                          <li
                            key={st.id}
                            style={{
                              display: "flex",
                              alignItems: "flex-start",
                              gap: "0.42rem",
                              fontSize: "0.76rem",
                              lineHeight: 1.32,
                            }}
                          >
                            <span style={{ marginBlockStart: "0.1rem", flexShrink: 0 }}>
                              {stopCategoryIcon(st.category)}
                            </span>
                            <span style={{ minInlineSize: 0 }}>
                              <strong style={{ color: "var(--text-primary)" }}>
                                {st.time_window.split("–")[0].trim()}
                              </strong>{" "}
                              <span style={{ color: "var(--text-secondary)" }}>
                                {st.title}
                              </span>
                            </span>
                          </li>
                        ))}
                      </ul>
                    </>
                  ) : (
                    <>
                      <div
                        style={{
                          display: "flex",
                          flexWrap: "wrap",
                          alignItems: "center",
                          justifyContent: "space-between",
                          gap: "0.35rem",
                        }}
                      >
                        <span
                          style={{
                            fontSize: "0.78rem",
                            fontWeight: 800,
                            color: "var(--gold-accent)",
                            display: "inline-flex",
                            alignItems: "center",
                            gap: "0.38rem",
                          }}
                        >
                          <Flame size={14} aria-hidden="true" />
                          Arbitrage &amp; VRPTW Insights
                        </span>
                        <span className="badge badge-route">
                          Fatigue {blueprint.fatigue_score} · Score {blueprint.quality_score}
                        </span>
                      </div>

                      <ul
                        role="list"
                        style={{
                          margin: 0,
                          paddingInlineStart: "1.05rem",
                          fontSize: "0.78rem",
                          lineHeight: 1.42,
                          color: "var(--text-secondary)",
                          display: "flex",
                          flexDirection: "column",
                          gap: "0.32rem",
                        }}
                      >
                        {blueprint.arbitrage_callouts.map((c, idx) => (
                          <li key={idx}>{c}</li>
                        ))}
                      </ul>

                      <div
                        style={{
                          marginBlockStart: "auto",
                          paddingBlockStart: "0.5rem",
                          borderBlockStart: "1px solid var(--border-subtle)",
                          display: "flex",
                          flexDirection: "column",
                          gap: "0.35rem",
                        }}
                      >
                        <span style={{ fontSize: "0.7rem", fontWeight: 700, color: "var(--text-muted)" }}>
                          Preview Day Corridor &amp; Time Windows:
                        </span>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem" }}>
                          {blueprint.days.map((d) => (
                            <button
                              key={`ledger-day-${d.day_number}`}
                              type="button"
                              className="btn"
                              style={{
                                minBlockSize: "1.72rem",
                                padding: "0.14rem 0.48rem",
                                fontSize: "0.7rem",
                              }}
                              onClick={() => setActiveDay(d.day_number)}
                            >
                              D{d.day_number} · {d.date_label}
                            </button>
                          ))}
                        </div>
                      </div>
                    </>
                  )}
                </div>
              </aside>
            </div>
          </div>

          {/* Primary Detail Tabs: Itinerary | Cross-Channel Arbitrage | Road, Tolls & Gates */}
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
                  ["itinerary", `${blueprint.days.length}-Day VRPTW Itinerary`],
                  [
                    "arbitrage",
                    blueprint.flights.length > 0
                      ? `Flight & Stay Arbitrage (${blueprint.flights.length} Flights · ${allArbitrageStays.length} ${allArbitrageStays.length === 1 ? "Stay" : "Stays"})`
                      : `Cross-Channel Stay Arbitrage (${allArbitrageStays.length} ${allArbitrageStays.length === 1 ? "Stay" : "Stays"})`,
                  ],
                  [
                    "telemetry",
                    optimization.trip_spec.transport_mode === "flight"
                      ? "Transfers & Ground Logistics"
                      : optimization.trip_spec.transport_mode === "hybrid"
                      ? "Rental SUV, Fuel & Tolls"
                      : `${optimization.trip_spec.vehicle_name.split("(")[0].trim()} Road, Tolls & Gates`,
                  ],
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

            {/* TAB PANEL 1: DAY-BY-DAY VRPTW ITINERARY */}
            <div
              role="tabpanel"
              id="panel-itinerary"
              aria-labelledby="tab-itinerary"
              hidden={activeTab !== "itinerary"}
            >
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
                    placeholder="Filter stops, trails, or restaurants..."
                    className="text-input"
                    style={{ inlineSize: "100%", paddingInlineStart: "2.2rem", minBlockSize: "2.4rem" }}
                  />
                </div>

                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
                  {(
                    [
                      ["all", "All Stops"],
                      ["climb", "Climbs & Nature"],
                      ["dining", "Regional Dining"],
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
                          {visibleStops.map((st) => {
                            const isDay1Flight =
                              st.category === "flight" &&
                              day.day_number === 1 &&
                              activeFlight !== null;
                            const isReturnFlight =
                              st.category === "flight" &&
                              day.day_number === blueprint.days.length &&
                              activeFlight !== null;

                            const stopTitle = isDay1Flight
                              ? `Outbound Flight (${activeFlight.origin_iata ?? shortCityName(optimization.trip_spec.origin)} → ${activeFlight.dest_iata ?? shortCityName(optimization.trip_spec.destination)}) + Arrival Transfer`
                              : isReturnFlight
                              ? `Airport Transfer + Return Flight (${activeFlight.dest_iata ?? shortCityName(optimization.trip_spec.destination)} → ${activeFlight.origin_iata ?? shortCityName(optimization.trip_spec.origin)})`
                              : st.title;

                            const stopTimeWindow = isDay1Flight
                              ? `${activeFlight.depart_time} – ${activeFlight.arrive_time}`
                              : isReturnFlight && activeFlight.return_depart_time && activeFlight.return_arrive_time
                              ? `${activeFlight.return_depart_time} – ${activeFlight.return_arrive_time}`
                              : st.time_window;

                            const stopDurationLabel = isDay1Flight
                              ? `${activeFlight.duration} flight + transfer`
                              : isReturnFlight && activeFlight.return_duration
                              ? `transfer + ${activeFlight.return_duration} flight`
                              : st.duration_label;

                            const stopLocationLabel =
                              (isDay1Flight || isReturnFlight) && activeFlight
                                ? `${activeFlight.carrier} (${activeFlight.stops_label}) · ${activeFlight.flight_numbers}`
                                : st.location_label;

                            const stopTip = isDay1Flight && activeFlight
                              ? activeFlight.gateway_hub_note
                              : st.insider_tip;

                            return (
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
                                  <span>{stopTitle}</span>
                                </div>
                                <span style={{ fontSize: "0.76rem", fontWeight: 700, color: "var(--route-blue)" }}>
                                  {stopTimeWindow} ({stopDurationLabel})
                                </span>
                              </div>

                              <div style={{ fontSize: "0.76rem", color: "var(--text-muted)", display: "flex", alignItems: "center", gap: "0.3rem" }}>
                                <MapPin size={12} aria-hidden="true" /> {stopLocationLabel}
                              </div>

                              <p style={{ margin: "0.15rem 0 0", fontSize: "0.84rem", color: "var(--text-secondary)" }}>
                                {st.description}
                              </p>

                              {(st.dietary_note || st.kid_note || stopTip) && (
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
                                      Family Fit: {st.kid_note}
                                    </span>
                                  )}
                                  {stopTip && (
                                    <span className="badge badge-route">
                                      Tip: {stopTip}
                                    </span>
                                  )}
                                </div>
                              )}
                            </li>
                            );
                          })}
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

              {blueprint.flights.length > 0 && (
                <div style={{ marginBlockEnd: "1.2rem" }}>
                  <h3 style={{ fontSize: "0.95rem", fontWeight: 800, marginBlockEnd: "0.6rem" }}>
                    Gateway Flight &amp; Virtual Interline Arbitrage ({blueprint.flights.length} Round-Trip Options)
                  </h3>
                  {renderFlightOptionsList("tab-gateway-flight")}
                </div>
              )}

              <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                {allArbitrageStays.map(({ stay, blueprintIdx, isActiveLeg }) => {
                  const prov = stay.price_provenance ?? "estimated_benchmark";
                  const shortProv =
                    prov === "live_verified"
                      ? "Live Verified Quote"
                      : prov === "live_scraped"
                      ? "Live Scraped Tariff"
                      : "Benchmark Estimate";

                  return (
                    <div key={`${stay.id}-bp${blueprintIdx}`} className="card-container">
                      <article
                        className="stay-arbitrage-card"
                        style={
                          isActiveLeg
                            ? { borderColor: "var(--accent-primary)" }
                            : undefined
                        }
                      >
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
                            {isActiveLeg ? (
                              <span className="badge badge-emerald">
                                <CheckCircle2 size={12} aria-hidden="true" /> Selected in Active Itinerary
                              </span>
                            ) : (
                              <span className="badge badge-route">
                                Alternative Pareto Option #{blueprintIdx + 1}
                              </span>
                            )}
                            <span className="badge badge-emerald">
                              <Sparkles size={12} aria-hidden="true" />{" "}
                              {stay.savings_inr > 0
                                ? `Saves ${money(stay.savings_inr)} via ${stay.best_channel}`
                                : stay.anomaly_badge}
                            </span>
                            <span
                              className={`badge ${
                                prov === "live_verified"
                                  ? "badge-emerald"
                                  : prov === "live_scraped"
                                  ? "badge-route"
                                  : "badge-gold"
                              }`}
                              title={stay.provenance_label}
                            >
                              <Info size={11} aria-hidden="true" /> {shortProv}
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
                                  {money(stay.best_landed_inr)}
                                </strong>
                                <span style={{ fontSize: "0.77rem", color: "var(--text-muted)" }}>
                                  ({money(Math.round(stay.best_landed_inr / stay.nights))}/night landed)
                                </span>
                              </div>
                            </div>

                            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
                              {!isActiveLeg && (
                                <button
                                  type="button"
                                  className="btn"
                                  onClick={() => setSelectedBlueprintIdx(blueprintIdx)}
                                >
                                  Select Stay Blueprint
                                </button>
                              )}
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
                                aria-label={`Verify ${stay.name} on ${stay.best_channel}`}
                                style={{ textDecoration: "none" }}
                              >
                                Portal <ExternalLink size={14} aria-hidden="true" />
                              </a>
                            </div>
                          </div>
                        </div>
                      </article>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* TAB PANEL 3: MODE-AWARE TRANSFERS / RENTAL / ROAD TELEMETRY */}
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
                {optimization.trip_spec.transport_mode === "flight" ? (
                  <>
                    <div style={{ padding: "0.9rem", borderRadius: "0.8rem", background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}>
                      <div style={{ fontSize: "0.74rem", color: "var(--text-muted)", fontWeight: 700 }}>TRANSFER SETUP</div>
                      <div style={{ fontSize: "1rem", fontWeight: 800, marginBlockStart: "0.2rem" }}>{blueprint.road.vehicle}</div>
                      <div style={{ fontSize: "0.78rem", color: "var(--accent-primary)", fontWeight: 600 }}>
                        Airport Pickup/Drop + Daily Sightseeing Cabs
                      </div>
                    </div>

                    <div style={{ padding: "0.9rem", borderRadius: "0.8rem", background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}>
                      <div style={{ fontSize: "0.74rem", color: "var(--text-muted)", fontWeight: 700 }}>LOCAL GROUND DISTANCE</div>
                      <div style={{ fontSize: "1.15rem", fontWeight: 800, marginBlockStart: "0.2rem" }}>
                        {blueprint.road.total_distance_km} km
                      </div>
                      <div style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                        ~{blueprint.road.total_drive_hours}h total across {blueprint.days.length} days
                      </div>
                    </div>

                    <div style={{ padding: "0.9rem", borderRadius: "0.8rem", background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}>
                      <div style={{ fontSize: "0.74rem", color: "var(--text-muted)", fontWeight: 700 }}>ALL-IN TRANSFERS ({currency})</div>
                      <div style={{ fontSize: "1.15rem", fontWeight: 800, marginBlockStart: "0.2rem" }}>
                        {money(blueprint.road.total_road_cost_inr)}
                      </div>
                      <div style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                        Driver, fuel, parking &amp; airport tolls included
                      </div>
                    </div>
                  </>
                ) : (
                  <>
                    <div style={{ padding: "0.9rem", borderRadius: "0.8rem", background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}>
                      <div style={{ fontSize: "0.74rem", color: "var(--text-muted)", fontWeight: 700 }}>
                        {optimization.trip_spec.transport_mode === "hybrid"
                          ? `RENTAL SUV (${currency})`
                          : "VEHICLE & CLEARANCE"}
                      </div>
                      <div style={{ fontSize: "1rem", fontWeight: 800, marginBlockStart: "0.2rem" }}>
                        {optimization.trip_spec.transport_mode === "hybrid" && blueprint.road.rental_car_cost_inr > 0
                          ? `${money(blueprint.road.rental_car_cost_inr)} · ${blueprint.road.vehicle}`
                          : blueprint.road.vehicle}
                      </div>
                      <div style={{ fontSize: "0.78rem", color: "var(--accent-primary)", fontWeight: 600 }}>
                        {blueprint.road.ground_clearance_mm}mm Clearance Verified
                      </div>
                    </div>

                    <div style={{ padding: "0.9rem", borderRadius: "0.8rem", background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}>
                      <div style={{ fontSize: "0.74rem", color: "var(--text-muted)", fontWeight: 700 }}>FUEL ESTIMATE ({currency})</div>
                      <div style={{ fontSize: "1.15rem", fontWeight: 800, marginBlockStart: "0.2rem" }}>
                        {money(blueprint.road.fuel_cost_inr)}
                      </div>
                      <div style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                        <Fuel size={12} aria-hidden="true" style={{ display: "inline", marginInlineEnd: 4 }} />
                        ~{blueprint.road.estimated_fuel_liters}L across {blueprint.road.total_distance_km} km
                      </div>
                    </div>

                    <div style={{ padding: "0.9rem", borderRadius: "0.8rem", background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}>
                      <div style={{ fontSize: "0.74rem", color: "var(--text-muted)", fontWeight: 700 }}>HIGHWAY TOLLS &amp; ENTRY</div>
                      <div style={{ fontSize: "1.15rem", fontWeight: 800, marginBlockStart: "0.2rem" }}>
                        {money(blueprint.road.fastag_and_forest_tolls_inr)}
                      </div>
                      <div style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                        {blueprint.road.segments[0]?.highway_label ?? "Highway & Corridor Plazas"}
                      </div>
                    </div>
                  </>
                )}
              </div>

              <div className="table-scroll">
                <table className="rate-table">
                  <caption>
                    {optimization.trip_spec.transport_mode === "flight"
                      ? `Day-by-Day Airport & Local Sightseeing Transfers (${currency})`
                      : `Corridor-by-Corridor Driving, Toll & Checkpost Verification (${currency})`}
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Day</th>
                      <th scope="col">Leg &amp; Corridor</th>
                      <th scope="col">Distance / Time</th>
                      <th scope="col">
                        {optimization.trip_spec.transport_mode === "flight"
                          ? "Billing"
                          : "Toll + Fuel"}
                      </th>
                      <th scope="col">Route &amp; VRPTW Verification</th>
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
                          {optimization.trip_spec.transport_mode === "flight" ? (
                            <span style={{ fontSize: "0.78rem", color: "var(--accent-primary)", fontWeight: 700 }}>
                              Included in Transfer Estimate
                            </span>
                          ) : (
                            <>
                              {money(seg.fastag_toll_inr + seg.fuel_estimate_inr)}
                              <div style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
                                Toll {money(seg.fastag_toll_inr)} · Fuel {money(seg.fuel_estimate_inr)}
                              </div>
                            </>
                          )}
                        </td>
                        <td style={{ fontSize: "0.79rem" }}>
                          {seg.gate_alert ? (
                            <span style={{ color: "var(--gold-accent)", fontWeight: 600 }}>
                              {seg.gate_alert}
                            </span>
                          ) : (
                            <span style={{ color: "var(--accent-primary)" }}>
                              <ShieldCheck size={14} aria-hidden="true" style={{ display: "inline", marginInlineEnd: 4 }} />
                              {optimization.trip_spec.transport_mode === "flight"
                                ? "Verified Paved Transfer Corridor"
                                : "Open Multi-Lane Highway"}
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
            </>
          )}
        </main>
      </div>

      {/* Top-Layer Persistent Toast Notification (`popover="manual"`) */}
      <div className="toast-stack" role="region" aria-label="Notifications">
        <div
          id={toastPopoverId}
          ref={toastRef}
          role="status"
          aria-live="polite"
          className="share-toast"
          data-legacy-open={!supportsPopover ? String(legacyToastOpen) : undefined}
          {...(supportsPopover ? ({ popover: "manual" } as Record<string, string>) : {})}
        >
          <Link2 size={16} aria-hidden="true" color="var(--accent-primary)" />
          <span style={{ fontSize: "0.81rem", fontWeight: 600, flex: 1, wordBreak: "break-all" }}>
            {toastText}
          </span>
          <button
            type="button"
            className="btn"
            aria-label="Close notification"
            style={{ minBlockSize: "1.9rem", padding: "0.2rem 0.45rem" }}
            onClick={hideShareToast}
            {...(supportsPopover
              ? ({
                  popovertarget: toastPopoverId,
                  popovertargetaction: "hide",
                } as Record<string, string>)
              : {})}
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      </div>

      {/* Native Top-Layer Light-Dismiss Deal Breakdown Modal */}
      <DealArbitrageDialog
        stay={inspectedStay}
        currency={currency}
        fxRates={fxRates}
        onClose={() => setInspectedStay(null)}
      />
    </div>
  );
}

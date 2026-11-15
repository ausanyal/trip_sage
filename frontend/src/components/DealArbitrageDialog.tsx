"use client";

import React, { useEffect, useId, useRef } from "react";
import { CheckCircle2, ExternalLink, ShieldCheck, Sparkles, X } from "lucide-react";
import type { StayCandidate } from "@/types/trip";

interface DealArbitrageDialogProps {
  stay: StayCandidate | null;
  onClose: () => void;
}

export function DealArbitrageDialog({ stay, onClose }: DealArbitrageDialogProps) {
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (stay) {
      if (!dialog.open) {
        dialog.showModal();
      }
    } else if (dialog.open) {
      dialog.close();
    }
  }, [stay]);

  // Mandatory Safari / pre-closedBy light-dismiss backdrop click fallback
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    const handleNativeClose = () => {
      onClose();
    };
    dialog.addEventListener("close", handleNativeClose);

    let handleBackdropClick: ((event: MouseEvent) => void) | null = null;
    if (
      typeof HTMLDialogElement !== "undefined" &&
      !("closedBy" in HTMLDialogElement.prototype)
    ) {
      handleBackdropClick = (event: MouseEvent) => {
        if (event.target !== dialog) return;
        const rect = dialog.getBoundingClientRect();
        const isDialogContent =
          rect.top <= event.clientY &&
          event.clientY <= rect.top + rect.height &&
          rect.left <= event.clientX &&
          event.clientX <= rect.left + rect.width;
        if (isDialogContent) return;
        dialog.close();
      };
      dialog.addEventListener("click", handleBackdropClick);
    }

    return () => {
      dialog.removeEventListener("close", handleNativeClose);
      if (handleBackdropClick) {
        dialog.removeEventListener("click", handleBackdropClick);
      }
    };
  }, [onClose]);

  return (
    <dialog
      ref={dialogRef}
      {...({ closedby: "any" } as React.DialogHTMLAttributes<HTMLDialogElement>)}
      className="arbitrage-dialog"
      aria-labelledby={titleId}
    >
      {stay && (
        <div style={{ padding: "1.35rem", display: "flex", flexDirection: "column", gap: "1rem" }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: "0.75rem" }}>
            <div style={{ flex: 1 }}>
              <span className="badge badge-emerald" style={{ marginBlockEnd: "0.35rem" }}>
                <Sparkles size={12} aria-hidden="true" /> {stay.anomaly_badge}
              </span>
              <h2
                id={titleId}
                style={{ margin: 0, fontSize: "1.2rem", fontWeight: 800, lineHeight: 1.25 }}
              >
                {stay.name}
              </h2>
              <p style={{ margin: "0.2rem 0 0", fontSize: "0.84rem", color: "var(--text-muted)" }}>
                {stay.subtitle} · {stay.check_in} to {stay.check_out} ({stay.nights}{" "}
                {stay.nights === 1 ? "Night" : "Nights"})
              </p>
            </div>

            <form method="dialog">
              <button
                type="submit"
                className="btn"
                aria-label="Close deal breakdown dialog"
                style={{ padding: "0.45rem" }}
              >
                <X size={18} aria-hidden="true" />
              </button>
            </form>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: "0.75rem",
              padding: "0.8rem",
              borderRadius: "0.75rem",
              background: "var(--bg-elevated)",
              border: "1px solid var(--border-subtle)",
              fontSize: "0.82rem",
            }}
          >
            <div>
              <strong style={{ display: "block", color: "var(--accent-primary)" }}>
                SUV &amp; Corridor Fit
              </strong>
              <span>{stay.suv_access_note}</span>
            </div>
            <div>
              <strong style={{ display: "block", color: "var(--route-blue)" }}>
                Family Fit (Ages 8 &amp; 10)
              </strong>
              <span>{stay.kid_fit_note}</span>
            </div>
          </div>

          <div className="table-scroll">
            <table className="rate-table">
              <caption>
                True Landed Checkout Comparison ({stay.nights}{" "}
                {stay.nights === 1 ? "Night" : "Nights"} · All Taxes &amp; Fees Included)
              </caption>
              <thead>
                <tr>
                  <th scope="col">Channel</th>
                  <th scope="col">Base + Extra Bed</th>
                  <th scope="col">Platform / Clean Fee</th>
                  <th scope="col">18% GST</th>
                  <th scope="col">Promo</th>
                  <th scope="col">True Landed</th>
                  <th scope="col">Action</th>
                </tr>
              </thead>
              <tbody>
                {stay.offers.map((offer) => (
                  <tr key={offer.platform} className={offer.is_best_deal ? "winner-row" : ""}>
                    <td>
                      <div style={{ fontWeight: 700, display: "flex", alignItems: "center", gap: "0.35rem" }}>
                        {offer.is_best_deal && (
                          <CheckCircle2 size={15} aria-hidden="true" color="var(--accent-primary)" />
                        )}
                        {offer.platform}
                      </div>
                      {offer.promo_note && (
                        <div style={{ fontSize: "0.73rem", color: "var(--text-muted)" }}>
                          {offer.promo_note}
                        </div>
                      )}
                    </td>
                    <td>
                      ₹{(offer.base_total_inr + offer.extra_bed_or_addons_inr).toLocaleString("en-IN")}
                    </td>
                    <td>
                      {offer.platform_or_cleaning_fee_inr > 0
                        ? `+₹${offer.platform_or_cleaning_fee_inr.toLocaleString("en-IN")}`
                        : "₹0"}
                    </td>
                    <td>+₹{offer.taxes_gst_inr.toLocaleString("en-IN")}</td>
                    <td style={{ color: "var(--accent-primary)", fontWeight: 700 }}>
                      {offer.promo_discount_inr > 0
                        ? `−₹${offer.promo_discount_inr.toLocaleString("en-IN")}`
                        : "—"}
                    </td>
                    <td>
                      <strong style={{ fontSize: "0.95rem" }}>
                        ₹{offer.landed_total_inr.toLocaleString("en-IN")}
                      </strong>
                      <div style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
                        ₹{offer.per_night_landed_inr.toLocaleString("en-IN")}/night
                      </div>
                    </td>
                    <td>
                      <a
                        href={offer.booking_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={`btn ${offer.is_best_deal ? "btn-primary" : ""}`}
                        style={{
                          minBlockSize: "2.1rem",
                          padding: "0.25rem 0.65rem",
                          fontSize: "0.76rem",
                          textDecoration: "none",
                        }}
                      >
                        Verify on {offer.platform.split(" ")[0]}{" "}
                        <ExternalLink size={12} aria-hidden="true" />
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              flexWrap: "wrap",
              gap: "0.5rem",
              fontSize: "0.8rem",
              color: "var(--text-muted)",
            }}
          >
            <span style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
              <ShieldCheck size={15} aria-hidden="true" color="var(--accent-primary)" />
              Entity deduplication verified identical room/villa inventory across channels.
            </span>
            <form method="dialog">
              <button type="submit" className="btn">
                Done
              </button>
            </form>
          </div>
        </div>
      )}
    </dialog>
  );
}

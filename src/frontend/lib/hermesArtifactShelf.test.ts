import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ArtifactShelf } from "@/components/hermes";
import type { HermesArtifactShelfEnvelope } from "./api";

const availableShelf = {
  schema_version: "1.0",
  read_status: "available",
  as_of: "2026-07-12T01:00:00Z",
  items: [
    {
      id: "risk:2026-07-12T00:50:00Z",
      kind: "portfolio_risk",
      occurred_at: "2026-07-12T00:50:00Z",
      quality: "available",
      status: "available",
      data: {
        account_id: "default",
        currency: "USD",
        gross_value: 315.32,
        gross_pct_equity: 0.000315,
        largest_symbol: "AAPL",
        top1_gross_pct: 1,
        historical_status: "available",
        benchmark: "SPY",
        betas: [
          {
            aligned_return_count: 274,
            benchmark: "SPY",
            first_return_date: "2025-06-06",
            last_return_date: "2026-07-10",
            reason: null,
            status: "available",
            symbol: "AAPL",
            value: 0.858,
          },
        ],
        reason_codes: [],
        limitations: ["historical_relationship_not_forecast"],
      },
    },
    {
      id: "prediction:pred-20260712-0001",
      kind: "prediction",
      occurred_at: "2026-07-12T00:40:00Z",
      quality: "available",
      status: "open",
      data: {
        prediction_id: "pred-20260712-0001",
        state: "open",
        symbol: "AAPL",
        direction: "up",
        confidence: 0.7,
        horizon_date: "2026-07-19",
        rationale: "Momentum remains positive.",
        outcome_return: null,
        direction_brier: null,
      },
    },
    {
      id: "foresight:mf-20260712-0001",
      kind: "market_foresight",
      occurred_at: "2026-07-12T00:30:00Z",
      quality: "available",
      status: "available",
      data: {
        run_id: "mf-20260712-0001",
        summary: "One candidate prediction is ready for human review.",
        candidate_count: 1,
        candidates: [
          {
            id: "mfp_candidate_001",
            symbol: "MSFT",
            direction: "flat",
            confidence: 0.58,
            horizon_date: "2026-07-19",
            falsifier: "The first eligible close leaves the flat band.",
            rationale: "A bounded validation candidate.",
            entry_session_date: "2026-07-11",
            entry_close: 510.05,
            provider: "futu",
            adjustment: "qfq",
            proposal_only: true,
            requires_human_confirmation: true,
            trading_allowed: false,
          },
        ],
      },
    },
  ],
  sources: [
    {
      kind: "portfolio_risk",
      status: "available",
      latest_at: "2026-07-12T00:50:00Z",
      reason_code: null,
    },
    {
      kind: "prediction",
      status: "available",
      latest_at: "2026-07-12T00:40:00Z",
      reason_code: null,
    },
    {
      kind: "market_foresight",
      status: "available",
      latest_at: "2026-07-12T00:30:00Z",
      reason_code: null,
    },
  ],
  warnings: [],
} satisfies HermesArtifactShelfEnvelope;

describe("Hermes artifact shelf", () => {
  it("shows that an empty prediction ledger is connected but has no entries", () => {
    const shelfWithoutPredictions = {
      ...availableShelf,
      items: availableShelf.items.filter((item) => item.kind !== "prediction"),
      sources: availableShelf.sources.map((source) =>
        source.kind === "prediction"
          ? { ...source, status: "empty", latest_at: null }
          : source,
      ),
    } satisfies HermesArtifactShelfEnvelope;

    const markup = renderToStaticMarkup(
      createElement(ArtifactShelf, { envelope: shelfWithoutPredictions, locale: "en" }),
    );

    expect(markup).toContain('aria-label="Artifact source status"');
    expect(markup).toContain("Portfolio risk source");
    expect(markup).toContain("Prediction ledger");
    expect(markup).toContain("Market foresight source");
    expect(markup).toContain("empty");
  });

  it("shows prediction direction and scored outcome metrics", () => {
    const scoredPredictionShelf = {
      ...availableShelf,
      items: [
        {
          id: "prediction:pred-20260701-0001",
          kind: "prediction",
          occurred_at: "2026-07-12T00:45:00Z",
          quality: "available",
          status: "scored",
          data: {
            prediction_id: "pred-20260701-0001",
            state: "scored",
            symbol: "AAPL",
            direction: "down",
            confidence: 0.7,
            horizon_date: "2026-07-11",
            rationale: "A bounded scored prediction.",
            outcome_return: -0.025,
            direction_brier: 0.09,
          },
        },
      ],
    } satisfies HermesArtifactShelfEnvelope;

    const markup = renderToStaticMarkup(
      createElement(ArtifactShelf, { envelope: scoredPredictionShelf, locale: "en" }),
    );

    expect(markup).toContain("Direction");
    expect(markup).toContain("down");
    expect(markup).toContain("Outcome return");
    expect(markup).toContain("-2.5%");
    expect(markup).toContain("Direction Brier");
    expect(markup).toContain("0.090");
  });

  it("renders all three artifact kinds as an accessible chronological list", () => {
    const markup = renderToStaticMarkup(
      createElement(ArtifactShelf, { envelope: availableShelf, locale: "en" }),
    );

    expect(markup).toContain("Portfolio risk");
    expect(markup).toContain("Prediction · AAPL");
    expect(markup).toContain("Market foresight");
    expect(markup).toContain("Proposal only · human confirmation required");
    expect(markup).toContain('aria-label="Foresight prediction candidates"');
    expect(markup).toContain("MSFT");
    expect(markup).toContain("flat");
    expect(markup).toContain("58%");
    expect(markup).toContain("2026-07-19");
    expect(markup.match(/<article/g)).toHaveLength(3);
    expect(markup.match(/<li><article/g)).toHaveLength(3);
    expect(markup.match(/<h3/g)).toHaveLength(3);
    expect(markup.match(/<time/g)).toHaveLength(3);
    expect(markup).toContain('dateTime="2026-07-12T00:50:00Z"');
    expect(markup).toContain("available");
  });

  it("distinguishes a healthy empty shelf from a failed artifact read", () => {
    const emptyShelf = {
      ...availableShelf,
      read_status: "empty",
      as_of: null,
      items: [],
      sources: [],
      warnings: [{ source: "artifact_feed", code: "feed_not_built" }],
    } satisfies HermesArtifactShelfEnvelope;

    const markup = renderToStaticMarkup(
      createElement(ArtifactShelf, { envelope: emptyShelf, locale: "en" }),
    );

    expect(markup).toContain("No research artifacts yet");
    expect(markup).toContain("Hermes jobs can populate this read-only shelf");
    expect(markup).not.toContain("Artifacts unavailable");
  });

  it("keeps healthy artifacts visible while announcing a degraded source", () => {
    const degradedShelf = {
      ...availableShelf,
      read_status: "degraded",
      sources: availableShelf.sources.map((source) =>
        source.kind === "prediction"
          ? { ...source, status: "unavailable", reason_code: "ledger_corrupt" }
          : source,
      ),
      warnings: [{ source: "prediction", code: "ledger_corrupt" }],
    } satisfies HermesArtifactShelfEnvelope;

    const markup = renderToStaticMarkup(
      createElement(ArtifactShelf, { envelope: degradedShelf, locale: "en" }),
    );

    expect(markup).toContain("Artifact shelf is degraded");
    expect(markup).toContain("prediction · ledger_corrupt");
    expect(markup).toContain("Portfolio risk");
    expect(markup.match(/<article/g)).toHaveLength(3);
    expect(markup).toContain('role="status"');
  });

  it("shows an explicit no-usable-artifacts state when a degraded read returns no items", () => {
    const degradedEmptyShelf = {
      ...availableShelf,
      read_status: "degraded",
      as_of: null,
      items: [],
      sources: availableShelf.sources.map((source) => ({
        ...source,
        status: "unavailable",
        reason_code: "artifact_source_unreadable",
      })),
      warnings: [{ source: "artifact_feed", code: "artifact_source_unreadable" }],
    } satisfies HermesArtifactShelfEnvelope;

    const markup = renderToStaticMarkup(
      createElement(ArtifactShelf, { envelope: degradedEmptyShelf, locale: "en" }),
    );

    expect(markup).toContain("Artifact shelf is degraded");
    expect(markup).toContain("No usable artifacts are available");
    expect(markup).not.toContain('aria-label="Research artifact timeline"');
  });

  it("renders an explicit unavailable state instead of an empty shelf", () => {
    const unavailableShelf = {
      ...availableShelf,
      read_status: "unavailable",
      as_of: null,
      items: [],
      sources: availableShelf.sources.map((source) => ({
        ...source,
        status: "unavailable",
        reason_code: "artifact_source_unreadable",
      })),
      warnings: [{ source: "artifact_feed", code: "artifact_source_unreadable" }],
      apiError: "503: artifact feed is unavailable",
    } satisfies HermesArtifactShelfEnvelope;

    const markup = renderToStaticMarkup(
      createElement(ArtifactShelf, { envelope: unavailableShelf, locale: "en" }),
    );

    expect(markup).toContain("Artifacts unavailable");
    expect(markup).toContain("artifact_feed · artifact_source_unreadable");
    expect(markup).toContain('role="alert"');
    expect(markup).not.toContain("No research artifacts yet");
    expect(markup).not.toContain("<article");
  });
});

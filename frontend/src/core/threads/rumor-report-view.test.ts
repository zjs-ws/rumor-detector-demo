import assert from "node:assert/strict";
import test from "node:test";

import type { RumorReport } from "./types";

const { buildRumorReportViewModel, normalizeRumorVerdict, safePublicHttpUrl } =
  await import(new URL("./rumor-report-view.ts", import.meta.url).href);

function report(overrides: Partial<RumorReport> = {}): RumorReport {
  return {
    schema_version: "rumorbuster-report-v3",
    claim: {
      normalized_claim: "测试主张",
      subclaims: [{ id: "claim-1", text: "测试主张", material: true }],
    },
    checkability: { checkability: "checkable_now", reason: "可公开核验" },
    evidence: [],
    decision: {
      verdict: "证据不足",
      strength: "insufficient",
      decision_status: "threshold_not_met",
      accepted_evidence_ids: [],
      excluded_evidence: [],
      classifier_consistency: "not_comparable",
      explanation: "没有达到证据门槛",
    },
    ...overrides,
  };
}

void test("never maps mixed or invalid classifier values to non-rumor", () => {
  const view = buildRumorReportViewModel(
    report({
      classifier_signal: {
        status: "ok",
        label: "mixed",
        aggregate_label: "mixed",
        rationale: "auxiliary",
        subclaims: [
          {
            claim_id: "claim-1",
            text: "测试主张",
            status: "ok",
            mapped_label: "mixed",
          },
          {
            claim_id: "claim-2",
            text: "另一个主张",
            status: "invalid_output",
            mapped_label: "definitely-true",
          },
        ],
      },
    }),
  );

  assert.equal(view.subclaimRows[0]?.modelLabel, "混合标签");
  assert.equal(view.subclaimRows[1]?.modelLabel, "无效模型输出");
  assert.notEqual(view.subclaimRows[0]?.modelLabel, "非谣言风险");
  assert.notEqual(view.subclaimRows[1]?.modelLabel, "非谣言风险");
});

void test("explains why an insufficient decision was returned", () => {
  const view = buildRumorReportViewModel(
    report({
      decision: {
        verdict: "证据不足",
        strength: "insufficient",
        decision_status: "sources_found_but_not_fetched",
        accepted_evidence_ids: [],
        excluded_evidence: [],
        classifier_consistency: "not_comparable",
        explanation: "找到了候选，但没有取得正文",
      },
    }),
  );

  assert.equal(view.decisionStatusLabel, "找到候选但正文未获取");
});

void test("hides timelines with fewer than three traceable events", () => {
  const view = buildRumorReportViewModel(
    report({
      timeline: {
        timeline_status: "ready",
        note: "insufficient after client validation",
        events: [
          {
            id: "event-1",
            date: "2026-08-12",
            date_precision: "day",
            event_type: "verification",
            claim_variant: "测试主张",
            publisher: "测试机构",
            title: "测试来源",
            url: "https://example.com/evidence",
            evidence_id: "evidence-1",
            stance: "refute",
            used_for_decision: true,
          },
        ],
      },
    }),
  );

  assert.deepEqual(view.timelineEvents, []);
});

void test("builds an honest evidence publication sequence without inferring propagation", () => {
  const evidence = [
    {
      id: "newer",
      title: "较新材料",
      url: "https://example.com/newer",
      publisher: "机构乙",
      published_at: "2026-08-12",
      stance: "support" as const,
      source_level: "B" as const,
      directness: "direct" as const,
      temporal_relevance: "current",
      summary: "较新材料",
    },
    {
      id: "older",
      title: "较早材料",
      url: "https://example.com/older",
      publisher: "机构甲",
      published_at: "2024-01-02",
      stance: "refute" as const,
      source_level: "A" as const,
      directness: "direct" as const,
      temporal_relevance: "historical_match",
      summary: "较早材料",
    },
    {
      id: "unknown-date",
      title: "无日期材料",
      url: "https://example.com/unknown",
      publisher: "机构丙",
      published_at: null,
      stance: "context" as const,
      source_level: "C" as const,
      directness: "indirect" as const,
      temporal_relevance: "unknown",
      summary: "无日期材料",
    },
  ];
  const view = buildRumorReportViewModel(report({ evidence }));

  assert.deepEqual(
    view.evidenceChronology.map((item) => item.id),
    ["older", "newer"],
  );
});

void test("normalizes non-factual boundary reports without exposing an unknown verdict", () => {
  assert.deepEqual(normalizeRumorVerdict("非事实性表达"), {
    key: "not_checkable",
    label: "非事实表达",
    tone: "muted",
  });
});

void test("only renders public HTTP(S) evidence links", () => {
  assert.equal(
    safePublicHttpUrl("https://example.com/article"),
    "https://example.com/article",
  );
  assert.equal(safePublicHttpUrl("javascript:alert(1)"), null);
  assert.equal(safePublicHttpUrl("file:///etc/passwd"), null);
  assert.equal(safePublicHttpUrl("not a url"), null);
});

void test("safely adapts v1, v2 and v3 reports with missing optional fields", () => {
  for (const schemaVersion of [
    "rumorbuster-report-v1",
    "rumorbuster-report-v2",
    "rumorbuster-report-v3",
  ] as const) {
    const view = buildRumorReportViewModel(
      report({
        schema_version: schemaVersion,
        claim: null,
        checkability: null,
        timeline: null,
        research_branches: undefined,
      }),
    );

    assert.equal(view.schemaVersion, schemaVersion);
    assert.equal(view.normalizedClaim, "未提供规范化主张");
    assert.equal(view.checkabilityLabel, "未知状态");
    assert.deepEqual(view.timelineEvents, []);
    assert.deepEqual(view.branchCards, []);
  }
});

import type { RumorReport, RumorWorkflow } from "@/core/threads/types";

export interface ArchivedRumorCase {
  case_id: string;
  title: string;
  category: string;
  input: {
    claim: string;
    source_url?: string | null;
  };
  recorded_at: string;
  run_id: string;
  source_kind: "archived_real_run";
  duration_ms: number;
  degradation_codes: string[];
  all_checks_passed: boolean;
  report: RumorReport;
  workflow: RumorWorkflow;
}

"use client";

import { ArchiveIcon, CheckCircle2Icon, Clock3Icon } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { RumorReportCard } from "@/components/workspace/messages/rumor-report-card";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import archivedCasesData from "@/core/showcase/cases.json";
import type { ArchivedRumorCase } from "@/core/showcase/types";
import { cn } from "@/lib/utils";

const archivedCases = archivedCasesData as unknown as ArchivedRumorCase[];

function formatRecordedAt(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "运行时间未知";
  return parsed.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Shanghai",
  });
}

export default function ShowcasePage() {
  const [selectedId, setSelectedId] = useState(archivedCases[0]?.case_id ?? "");
  const selected = useMemo(
    () =>
      archivedCases.find((item) => item.case_id === selectedId) ??
      archivedCases[0],
    [selectedId],
  );

  return (
    <WorkspaceContainer>
      <WorkspaceHeader>历史实测案例</WorkspaceHeader>
      <WorkspaceBody className="rumor-lab-grid overflow-y-auto">
        <main className="mx-auto w-full max-w-7xl space-y-6 px-4 py-8 sm:px-6">
          <header className="rumor-glass rounded-2xl border p-5 sm:p-7">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="max-w-3xl">
                <div className="text-rb-evidence flex items-center gap-2 text-xs font-semibold tracking-[0.14em] uppercase">
                  <ArchiveIcon className="size-4" />
                  Archived real runs
                </div>
                <h1 className="mt-2 text-2xl font-bold sm:text-3xl">
                  历史实测案例
                </h1>
                <p className="text-muted-foreground mt-2 text-sm leading-6">
                  以下内容来自已保存的真实 V3
                  运行结果，用于断网、超时和答辩兜底；它们不是当前实时执行。
                </p>
              </div>
              <Badge
                className="border-rb-warning/30 text-rb-warning"
                variant="outline"
              >
                非实时结果
              </Badge>
            </div>
          </header>

          <section
            aria-label="选择历史实测案例"
            className="grid gap-3 md:grid-cols-3"
          >
            {archivedCases.map((item) => {
              const active = item.case_id === selected?.case_id;
              return (
                <Button
                  key={item.case_id}
                  className={cn(
                    "bg-card h-auto min-h-32 items-start justify-start rounded-2xl border p-4 text-left whitespace-normal shadow-sm",
                    active && "border-rb-evidence/50 bg-rb-evidence/5",
                  )}
                  variant="outline"
                  onClick={() => setSelectedId(item.case_id)}
                >
                  <span className="flex w-full flex-col items-start">
                    <span className="flex w-full items-center justify-between gap-2">
                      <Badge variant="secondary">{item.category}</Badge>
                      {item.all_checks_passed && (
                        <CheckCircle2Icon className="text-rb-evidence size-4" />
                      )}
                    </span>
                    <span className="mt-3 font-semibold">{item.title}</span>
                    <span className="text-muted-foreground mt-2 line-clamp-2 text-xs leading-5">
                      {item.input.claim}
                    </span>
                  </span>
                </Button>
              );
            })}
          </section>

          {selected && (
            <section className="space-y-4">
              <div className="bg-card flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 text-xs shadow-sm">
                <Badge className="bg-rb-evidence text-white dark:text-slate-950">
                  历史实测结果
                </Badge>
                <span className="flex items-center gap-1.5">
                  <Clock3Icon className="size-3.5" />
                  {formatRecordedAt(selected.recorded_at)}
                </span>
                <span>耗时 {(selected.duration_ms / 1000).toFixed(1)} 秒</span>
                <span className="text-muted-foreground break-all">
                  Run ID：{selected.run_id}
                </span>
              </div>
              <RumorReportCard report={selected.report} />
            </section>
          )}
        </main>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

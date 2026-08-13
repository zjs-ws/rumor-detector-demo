"use client";

import { DatabaseIcon, ScaleIcon, SearchCheckIcon } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { AuroraText } from "../ui/aurora-text";

let waved = false;

export function Welcome({
  className,
  mode,
}: {
  className?: string;
  mode?: "ultra" | "pro" | "thinking" | "flash";
}) {
  const { t } = useI18n();
  const searchParams = useSearchParams();
  const isUltra = useMemo(() => mode === "ultra", [mode]);
  const colors = useMemo(() => {
    if (isUltra) {
      return ["#efefbb", "#e9c665", "#e3a812"];
    }
    return ["var(--color-foreground)"];
  }, [isUltra]);
  useEffect(() => {
    waved = true;
  }, []);
  return (
    <div
      className={cn(
        "mx-auto flex w-full max-w-full min-w-0 flex-col items-center justify-center gap-3 overflow-x-hidden px-4 py-4 text-center sm:px-8",
        className,
      )}
    >
      {searchParams.get("mode") !== "skill" && (
        <div className="border-rb-evidence/20 bg-card/75 text-rb-evidence flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] font-semibold tracking-[0.14em] uppercase shadow-sm backdrop-blur">
          <SearchCheckIcon className="size-3.5" />
          {t.welcome.eyebrow}
        </div>
      )}
      <div className="w-full min-w-0 text-2xl leading-tight font-bold sm:text-3xl">
        {searchParams.get("mode") === "skill" ? (
          `✨ ${t.welcome.createYourOwnSkill} ✨`
        ) : (
          <div className="flex w-full min-w-0 items-start justify-center gap-2 sm:items-center">
            <div
              className={cn(
                "inline-block shrink-0",
                !waved ? "animate-wave" : "",
              )}
            >
              {isUltra ? "🚀" : "👋"}
            </div>
            <AuroraText
              className="max-w-full min-w-0 whitespace-normal"
              colors={colors}
            >
              {t.welcome.greeting}
            </AuroraText>
          </div>
        )}
      </div>
      {searchParams.get("mode") === "skill" ? (
        <div className="text-muted-foreground text-sm">
          {t.welcome.createYourOwnSkillDescription.includes("\n") ? (
            <pre className="font-sans whitespace-pre">
              {t.welcome.createYourOwnSkillDescription}
            </pre>
          ) : (
            <p>{t.welcome.createYourOwnSkillDescription}</p>
          )}
        </div>
      ) : (
        <div className="text-muted-foreground max-w-2xl text-sm leading-6">
          {t.welcome.description.includes("\n") ? (
            <pre className="font-sans whitespace-pre-wrap">
              {t.welcome.description}
            </pre>
          ) : (
            <p>{t.welcome.description}</p>
          )}
        </div>
      )}
      {searchParams.get("mode") !== "skill" && (
        <div className="text-muted-foreground mt-1 grid w-full max-w-2xl min-w-0 grid-cols-1 gap-2 text-left text-xs sm:grid-cols-3">
          {[
            { icon: DatabaseIcon, text: t.welcome.capabilities[0] },
            { icon: SearchCheckIcon, text: t.welcome.capabilities[1] },
            { icon: ScaleIcon, text: t.welcome.capabilities[2] },
          ].map(({ icon: Icon, text }) => (
            <div
              key={text}
              className="border-rb-evidence/15 bg-card/75 hover:border-rb-evidence/35 flex min-w-0 items-center gap-2 rounded-xl border px-3 py-2 shadow-sm transition-colors duration-200"
            >
              <Icon className="text-rb-evidence size-4 shrink-0" />
              <span>{text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

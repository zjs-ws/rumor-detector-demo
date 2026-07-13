import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

import { usePromptInputController } from "@/components/ai-elements/prompt-input";
import {
  formatBrowserClaimPrompt,
  parseBrowserClaimFragment,
} from "@/core/browser-import";
import { useI18n } from "@/core/i18n/hooks";

/**
 * Hook to determine if the chat is in a specific mode based on URL parameters, and to set an initial prompt input value accordingly.
 */
export function useSpecificChatMode() {
  const { t } = useI18n();
  const { thread_id: threadIdFromPath } = useParams<{ thread_id: string }>();
  const searchParams = useSearchParams();
  const promptInputController = usePromptInputController();
  const lastInitialValueRef = useRef<string | undefined>(undefined);
  const setInputRef = useRef(promptInputController.textInput.setInput);
  setInputRef.current = promptInputController.textInput.setInput;

  useEffect(() => {
    if (threadIdFromPath !== "new") {
      return;
    }

    const browserImport = parseBrowserClaimFragment(window.location.hash);
    const inputInitialValue = browserImport
      ? formatBrowserClaimPrompt(browserImport)
      : searchParams.get("mode") === "skill"
        ? t.inputBox.createSkillPrompt
        : undefined;

    if (
      !inputInitialValue ||
      inputInitialValue === lastInitialValueRef.current
    ) {
      return;
    }

    lastInitialValueRef.current = inputInitialValue;
    if (browserImport) {
      window.history.replaceState(
        window.history.state,
        "",
        `${window.location.pathname}${window.location.search}`,
      );
    }

    const timer = window.setTimeout(() => {
      setInputRef.current(inputInitialValue);
      const textarea = document.querySelector("textarea");
      if (textarea) {
        textarea.focus();
        textarea.selectionStart = textarea.value.length;
        textarea.selectionEnd = textarea.value.length;
      }
    }, 100);

    return () => window.clearTimeout(timer);
  }, [threadIdFromPath, searchParams, t.inputBox.createSkillPrompt]);
}

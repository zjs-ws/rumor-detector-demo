import { RUMORBUSTER_BASE_URL, normalizeRumorBusterBaseUrl } from "./link.js";

const form = document.querySelector("#settings-form");
const input = document.querySelector("#base-url");
const resetButton = document.querySelector("#reset-button");
const status = document.querySelector("#status");

function setStatus(message, kind = "success") {
  status.textContent = message;
  status.dataset.kind = kind;
}

chrome.storage.sync.get(
  { rumorbusterBaseUrl: RUMORBUSTER_BASE_URL },
  ({ rumorbusterBaseUrl }) => {
    input.value = rumorbusterBaseUrl;
  },
);

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const normalized = normalizeRumorBusterBaseUrl(input.value);
  if (!normalized) {
    setStatus("请输入有效的 HTTP(S) 地址。", "error");
    return;
  }
  chrome.storage.sync.set({ rumorbusterBaseUrl: normalized }, () => {
    input.value = normalized;
    setStatus("已保存。新的划词核验将使用该地址。");
  });
});

resetButton.addEventListener("click", () => {
  chrome.storage.sync.set({ rumorbusterBaseUrl: RUMORBUSTER_BASE_URL }, () => {
    input.value = RUMORBUSTER_BASE_URL;
    setStatus("已恢复本地默认地址。");
  });
});

import { buildRumorBusterUrl } from "./link.js";
import { RUMORBUSTER_BASE_URL } from "./link.js";

const MENU_ID = "rumorbuster-verify-selection";

function registerContextMenu() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: MENU_ID,
      title: "用 RumorBuster 核验：“%s”",
      contexts: ["selection"],
    });
  });
}

chrome.runtime.onInstalled.addListener(registerContextMenu);
chrome.runtime.onStartup.addListener(registerContextMenu);

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId !== MENU_ID) {
    return;
  }

  chrome.storage.sync.get(
    { rumorbusterBaseUrl: RUMORBUSTER_BASE_URL },
    ({ rumorbusterBaseUrl }) => {
      const targetUrl = buildRumorBusterUrl(
        info.selectionText,
        info.pageUrl,
        rumorbusterBaseUrl,
      );
      if (targetUrl) {
        void chrome.tabs.create({ url: targetUrl });
      }
    },
  );
});

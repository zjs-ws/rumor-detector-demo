import { buildRumorBusterUrl } from "./link.js";

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

  const targetUrl = buildRumorBusterUrl(info.selectionText, info.pageUrl);
  if (targetUrl) {
    void chrome.tabs.create({ url: targetUrl });
  }
});

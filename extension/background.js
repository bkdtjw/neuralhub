const pendingDomains = new Map();

chrome.cookies.onChanged.addListener((changeInfo) => {
  const domain = normalizeDomain(changeInfo.cookie.domain);
  if (!domain) return;
  if (pendingDomains.has(domain)) clearTimeout(pendingDomains.get(domain));
  pendingDomains.set(domain, setTimeout(() => syncDomain(domain), 1500));
});

async function syncDomain(domain) {
  pendingDomains.delete(domain);
  const config = await chrome.storage.sync.get(["serverUrl", "token", "userId"]);
  if (!config.serverUrl || !config.token) return;
  const cookies = await chrome.cookies.getAll({ domain });
  const localStorageData = await readLocalStorage(domain);
  await fetch(`${config.serverUrl.replace(/\/$/, "")}/api/cookie/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: config.userId || "default",
      domain,
      cookies,
      local_storage: localStorageData,
      token: config.token,
    }),
  });
}

async function readLocalStorage(domain) {
  const tabs = await chrome.tabs.query({ url: [`http://${domain}/*`, `https://${domain}/*`] });
  if (!tabs.length || tabs[0].id === undefined) return {};
  const results = await chrome.scripting.executeScript({
    target: { tabId: tabs[0].id },
    func: () => Object.fromEntries(Object.entries(window.localStorage)),
  });
  return results[0]?.result || {};
}

function normalizeDomain(domain) {
  return (domain || "").replace(/^\./, "").toLowerCase();
}

const fields = ["serverUrl", "userId", "token"];

chrome.storage.sync.get(fields).then((values) => {
  for (const field of fields) {
    document.getElementById(field).value = values[field] || "";
  }
});

document.getElementById("save").addEventListener("click", async () => {
  const values = {};
  for (const field of fields) {
    values[field] = document.getElementById(field).value.trim();
  }
  await chrome.storage.sync.set(values);
});

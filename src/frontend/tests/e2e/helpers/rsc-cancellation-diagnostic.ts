import type { Page, TestInfo } from "@playwright/test";

/** Opt-in bounded diagnostic; never wraps fetch or changes router behavior. */
export async function installRscCancellationDiagnostic(page: Page) {
  const events: Array<Record<string, unknown>> = [];
  if (process.env.PW_RSC_CANCEL_DIAGNOSTIC !== "1") return async (_info: TestInfo) => {};
  page.on("console", message => {
    const prefix = "E2E_RSC_CANCEL:";
    if (message.text().startsWith(prefix)) events.push(JSON.parse(message.text().slice(prefix.length)));
  });
  await page.addInitScript(() => {
    const record = (kind: string, extra = {}) => console.debug(`E2E_RSC_CANCEL:${JSON.stringify({ kind, at: Date.now(), url: location.href, ...extra })}`);
    for (const kind of ["pagehide", "pageshow", "visibilitychange"]) window.addEventListener(kind, () => record(kind));
    const abort = AbortController.prototype.abort;
    AbortController.prototype.abort = function (...args) { record("AbortController.abort", { stack: new Error().stack }); return abort.apply(this, args); };
    const cancel = ReadableStream.prototype.cancel;
    ReadableStream.prototype.cancel = function (...args) { record("ReadableStream.cancel", { stack: new Error().stack }); return cancel.apply(this, args); };
    const readerCancel = ReadableStreamDefaultReader.prototype.cancel;
    ReadableStreamDefaultReader.prototype.cancel = function (...args) { record("Reader.cancel", { stack: new Error().stack }); return readerCancel.apply(this, args); };
  });
  const session = await page.context().newCDPSession(page);
  const requests = new Map<string, string>();
  await session.send("Network.enable");
  session.on("Network.requestWillBeSent", event => {
    if (!event.request.url.includes("_rsc=")) return;
    requests.set(event.requestId, event.request.url);
    events.push({ kind: "cdp.request", url: event.request.url, request_id: event.requestId, at: event.timestamp,
      initiator: event.initiator, document_url: event.documentURL, resource_type: event.type });
  });
  session.on("Network.responseReceived", event => {
    if (requests.has(event.requestId)) events.push({ kind: "cdp.response", request_id: event.requestId, status: event.response.status, mime: event.response.mimeType, at: event.timestamp });
  });
  session.on("Network.loadingFailed", event => {
    if (requests.has(event.requestId)) events.push({ kind: "cdp.loadingFailed", request_id: event.requestId, at: event.timestamp,
      canceled: event.canceled, error: event.errorText, blocked_reason: event.blockedReason, cors: event.corsErrorStatus });
  });
  session.on("Network.loadingFinished", event => {
    if (requests.has(event.requestId)) events.push({ kind: "cdp.loadingFinished", request_id: event.requestId, at: event.timestamp, bytes: event.encodedDataLength });
  });
  return async (info: TestInfo) => {
    await session.send("Runtime.evaluate", { expression: "0" });
    await info.attach("rsc-nonfetch-diagnostic.json", { body: JSON.stringify(events, null, 2), contentType: "application/json" });
    await session.detach();
  };
}

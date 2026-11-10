import { request } from "../../api.js";

const DETECT_TIMEOUT = 120000;

function withTimeout(promise, timeout) {
  let timer;
  const timeoutPromise = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error("El análisis está tardando demasiado. Intente con otra imagen.")), timeout);
  });
  return Promise.race([promise, timeoutPromise]).finally(() => clearTimeout(timer));
}

export function detectFromPhoto(file) {
  const body = new FormData();
  body.append("file", file);
  return withTimeout(request("/vision/detect", { method: "POST", body }), DETECT_TIMEOUT);
}

export function applyPhotoProposal(proposal, diagramId = null) {
  const path = diagramId ? `/diagrams/${encodeURIComponent(diagramId)}/vision/apply` : "/vision/apply";
  return request(path, { method: "POST", body: JSON.stringify(proposal) });
}

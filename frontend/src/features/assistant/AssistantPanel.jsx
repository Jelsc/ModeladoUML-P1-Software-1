import { useEffect, useRef, useState } from "react";
import { json, request } from "../../api.js";
import { ASSISTANT_HISTORY_LIMIT, assistantActionLabels } from "./assistant.constants.js";
import { MicrophoneIcon } from "./AssistantLauncher.jsx";

const PARTIAL_TRANSCRIPTION_MS = 1800;
const SILENCE_MS = 4000;
const SPEECH_RMS_THRESHOLD = 0.025;

export function AssistantPreview({ parsed, onExecute, busy }) {
  if (!parsed?.command) return null;
  const action = assistantActionLabels[parsed.command.action] || parsed.command.action.replaceAll("_", " ");
  return <div className="assistant-preview"><span className="assistant-preview-label">Vista previa</span><b>Voy a {action}</b>{parsed.command.requires_confirmation && <small>Esta acción modifica el diagrama y requiere confirmación explícita.</small>}<button type="button" onClick={onExecute} disabled={busy}>Confirmar y ejecutar</button></div>;
}

export function AssistantPanel({ diagramId, onClose, onChanged }) {
  const historyKey = `assistant-history:${diagramId}`;
  const [recording, setRecording] = useState(false), [elapsed, setElapsed] = useState(0), [transcript, setTranscript] = useState("");
  const [parsed, setParsed] = useState(null), [error, setError] = useState(""), [busy, setBusy] = useState(false), [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState(() => { try { return JSON.parse(localStorage.getItem(historyKey) || "[]"); } catch { return []; } });
  const recorder = useRef(null), stream = useRef(null), chunks = useRef([]), cancelled = useRef(false), transcriptInput = useRef(null), chatHistory = useRef(null), followChat = useRef(true), startedAt = useRef(0);
  const audioContext = useRef(null), silenceFrame = useRef(null), partialTimer = useRef(null), partialRequest = useRef(null), requestSequence = useRef(0), stopRequested = useRef(false), finalSubmitted = useRef(false), mounted = useRef(true);
  const cleanupAnalysis = () => {
    if (silenceFrame.current !== null) cancelAnimationFrame(silenceFrame.current);
    silenceFrame.current = null;
    if (partialTimer.current !== null) clearInterval(partialTimer.current);
    partialTimer.current = null;
    const context = audioContext.current;
    audioContext.current = null;
    if (context && context.state !== "closed") context.close().catch(() => {});
  };
  const cleanupVoice = () => {
    cleanupAnalysis();
    if (recorder.current && recorder.current.state !== "inactive") recorder.current.stop();
    recorder.current = null;
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
  };
  const cancel = () => {
    cancelled.current = true;
    requestSequence.current += 1;
    cleanupVoice();
    if (!mounted.current) return;
    setRecording(false); setTranscript(""); setPrompt(""); setParsed(null);
  };
  const close = () => { cancel(); onClose(); };
  useEffect(() => { const closeOnEscape = (event) => event.key === "Escape" && close(); document.addEventListener("keydown", closeOnEscape); return () => document.removeEventListener("keydown", closeOnEscape); });
  const addMessages = (items) => { if (!mounted.current) return; setMessages((current) => { const next = [...current, ...items].slice(-ASSISTANT_HISTORY_LIMIT); try { localStorage.setItem(historyKey, JSON.stringify(next)); } catch { /* storage is optional */ } return next; }); };
  useEffect(() => { const history = chatHistory.current; if (history && followChat.current) history.scrollTop = history.scrollHeight; }, [messages, busy]);
  useEffect(() => { transcriptInput.current?.focus({ preventScroll: true }); }, []);
  useEffect(() => { const timer = recording ? setInterval(() => setElapsed(Math.floor((Date.now() - startedAt.current) / 1000)), 250) : null; return () => timer && clearInterval(timer); }, [recording]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; cancelled.current = true; requestSequence.current += 1; cleanupVoice(); }; }, []);
  const parseTranscript = async (value) => { if (!value.trim() || !mounted.current) return; setBusy(true); setError(""); try { const result = await request("/assistant/parse", json("POST", { diagram_id: diagramId, transcript: value })); if (!mounted.current || cancelled.current) return; setParsed(result.command ? { ...result, clarification: null } : result); addMessages([{ role: "user", text: value }, { role: "assistant", text: result.command ? `Interpreté: ${assistantActionLabels[result.command.action] || result.command.action.replaceAll("_", " ")}.` : result.clarification }]); } catch (e) { if (mounted.current && !cancelled.current) { setError(e.message); addMessages([{ role: "assistant", text: `No pude interpretar el pedido: ${e.message}` }]); } } finally { if (mounted.current) setBusy(false); } };
  const transcribe = async (blob, mimeType) => {
    const form = new FormData();
    form.append("audio", blob, mimeType.includes("ogg") ? "voice.ogg" : "voice.webm");
    return request("/assistant/transcribe", { method: "POST", body: form });
  };
  const finishRecording = () => {
    const activeRecorder = recorder.current;
    if (!activeRecorder || activeRecorder.state === "inactive" || stopRequested.current) return;
    stopRequested.current = true;
    requestSequence.current += 1;
    cleanupAnalysis();
    activeRecorder.stop();
    if (mounted.current) setRecording(false);
  };
  const start = async () => {
    setError(""); cancelled.current = false; stopRequested.current = false; finalSubmitted.current = false; setTranscript(""); setPrompt("");
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return setError("Este navegador no permite grabar audio. Podés escribir el pedido.");
    try {
      const nextStream = await navigator.mediaDevices.getUserMedia({ audio: true }); const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg"].find((type) => MediaRecorder.isTypeSupported(type));
      if (!mounted.current || cancelled.current) { nextStream.getTracks().forEach((track) => track.stop()); return; }
      if (!mimeType) { nextStream.getTracks().forEach((track) => track.stop()); return setError("El navegador no ofrece un formato de audio compatible."); }
      stream.current = nextStream; chunks.current = []; const nextRecorder = new MediaRecorder(nextStream, { mimeType }); recorder.current = nextRecorder;
      nextRecorder.ondataavailable = (event) => event.data.size && chunks.current.push(event.data);
      nextRecorder.onstop = async () => {
        cleanupAnalysis(); nextStream.getTracks().forEach((track) => track.stop());
        if (stream.current === nextStream) stream.current = null;
        if (recorder.current === nextRecorder) recorder.current = null;
        if (cancelled.current || finalSubmitted.current) return;
        finalSubmitted.current = true;
        const pendingPartial = partialRequest.current;
        if (pendingPartial) await pendingPartial;
        if (cancelled.current || !mounted.current) return;
        setBusy(true); setError("");
        try {
          const result = await transcribe(new Blob(chunks.current, { type: mimeType }), mimeType);
          if (cancelled.current || !mounted.current) return;
          setTranscript(result.transcript); setPrompt(result.transcript);
          requestAnimationFrame(() => transcriptInput.current?.focus({ preventScroll: true }));
          await parseTranscript(result.transcript);
        } catch (e) { if (mounted.current && !cancelled.current) setError(e.message); }
        finally { if (mounted.current) setBusy(false); }
      };
      const sessionSequence = ++requestSequence.current;
      const requestPartial = () => {
        if (nextRecorder.state !== "recording" || chunks.current.length === 0 || partialRequest.current) return;
        const accumulated = new Blob([...chunks.current], { type: mimeType });
        const pending = transcribe(accumulated, mimeType).then((result) => {
          if (mounted.current && !cancelled.current && requestSequence.current === sessionSequence) setTranscript(result.transcript);
        }).catch(() => { /* Partial audio may not be decodable; final transcription still runs. */ }).finally(() => {
          if (partialRequest.current === pending) partialRequest.current = null;
        });
        partialRequest.current = pending;
      };
      partialTimer.current = setInterval(requestPartial, PARTIAL_TRANSCRIPTION_MS);
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (AudioContextClass) {
        const context = new AudioContextClass(); const analyser = context.createAnalyser(); const source = context.createMediaStreamSource(nextStream);
        audioContext.current = context; analyser.fftSize = 2048; source.connect(analyser);
        const samples = new Uint8Array(analyser.fftSize); let speechStarted = false; let silenceStartedAt = null;
        const watchSilence = () => {
          if (cancelled.current || nextRecorder.state === "inactive") return;
          analyser.getByteTimeDomainData(samples);
          let energy = 0; for (const sample of samples) { const amplitude = (sample - 128) / 128; energy += amplitude * amplitude; }
          const rms = Math.sqrt(energy / samples.length); const now = performance.now();
          if (rms >= SPEECH_RMS_THRESHOLD) { speechStarted = true; silenceStartedAt = null; }
          else if (speechStarted) { silenceStartedAt ??= now; if (now - silenceStartedAt >= SILENCE_MS) { finishRecording(); return; } }
          silenceFrame.current = requestAnimationFrame(watchSilence);
        };
        silenceFrame.current = requestAnimationFrame(watchSilence);
      }
      nextRecorder.start(500); startedAt.current = Date.now(); setElapsed(0); setRecording(true);
    } catch { cleanupVoice(); if (mounted.current) setError("No se pudo acceder al micrófono. Revisá los permisos del navegador."); }
  };
  const stop = () => finishRecording();
  const execute = async () => { if (!parsed?.command) return; setBusy(true); setError(""); try { await request("/assistant/execute", json("POST", { diagram_id: diagramId, command: parsed.command, confirmed: true })); setParsed(null); setError(""); addMessages([{ role: "assistant", text: "Listo, apliqué el cambio en la pizarra." }]); await onChanged(); } catch (e) { setError(e.message); addMessages([{ role: "assistant", text: `No se pudo ejecutar: ${e.message}` }]); } finally { setBusy(false); } };
  const send = async (event) => { event.preventDefault(); const value = prompt.trim(); if (!value || busy) return; cancelled.current = false; setPrompt(""); setTranscript(value); await parseTranscript(value); };
  const stopCanvasInteraction = (event) => event.stopPropagation();
  return <section className="assistant-panel" role="dialog" aria-modal="false" aria-labelledby="assistant-title" tabIndex={-1} onWheelCapture={stopCanvasInteraction} onPointerDownCapture={stopCanvasInteraction} onPointerMoveCapture={stopCanvasInteraction} onPointerUpCapture={stopCanvasInteraction} onPointerCancelCapture={stopCanvasInteraction}>
    <div className="modal-heading"><div><p className="eyebrow">ASISTENTE LOCAL</p><h2 id="assistant-title">Asistente de pizarra</h2></div><button type="button" className="ghost" onClick={close} aria-label="Cerrar asistente">×</button></div>
    <p className="muted">El audio se transcribe localmente con Whisper. Gemini solo interpreta el texto y el parser determinista queda como respaldo.</p>
    <div ref={chatHistory} className="chat-history" onScroll={(event) => { const history = event.currentTarget; followChat.current = history.scrollHeight - history.scrollTop - history.clientHeight < 24; }} aria-live="polite">{messages.length === 0 && <p className="chat-empty">Probá: «creá una clase Usuario»</p>}{messages.map((message, index) => <div className={`chat-message chat-${message.role}`} key={`${index}-${message.text}`}><span>{message.role === "user" ? "Vos" : "Asistente"}</span><p>{message.text}</p></div>)}{recording && <div className="assistant-live" aria-live="polite"><p><span className="live-dot" />Escuchando · {String(Math.floor(elapsed / 60)).padStart(2, "0")}:{String(elapsed % 60).padStart(2, "0")}</p>{transcript && <p>{transcript}</p>}</div>}{busy && <p className="assistant-live">Procesando audio o pedido…</p>}</div>
    <form className="chat-form" onSubmit={send}><label className="sr-only" htmlFor="assistant-prompt">Escribí un pedido</label><textarea id="assistant-prompt" ref={transcriptInput} value={recording ? transcript : prompt} onChange={(e) => setPrompt(e.target.value)} readOnly={recording} placeholder="Escribí o dictá un pedido…" rows="2" /><div className="chat-form-actions">{recording ? <><button type="button" className="ghost" onClick={cancel}>Cancelar</button><button type="button" className="recording" onClick={stop} aria-label="Detener escucha">Detener</button></> : <button type="button" className="assistant-mic" onClick={start} disabled={busy} aria-label="Escuchar un pedido" title="Escuchar un pedido"><MicrophoneIcon /></button>}<button type="submit" disabled={busy || !prompt.trim()}>{busy ? "…" : "Enviar"}</button></div></form>
    <small className="field-hint">Podés escribir o usar el micrófono. Al detener, Whisper local confirma la transcripción final.</small>{parsed?.command && <AssistantPreview parsed={parsed} onExecute={execute} busy={busy} />}{parsed?.clarification && <p className="error" role="alert">{parsed.clarification}</p>}{error && <p className="error" role="alert">{error}</p>}
  </section>;
}

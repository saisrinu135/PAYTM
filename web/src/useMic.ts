import { useCallback, useEffect, useRef, useState } from "react";

/** Browser energy VAD. Same job as Silero VAD / config vad_silence_ms — start
 * on speech, stop after this many ms of quiet. No owner voiceprint. */
const SILENCE_MS = 1000;
const SPEECH_MS = 180;
const RMS_ON = 0.045;
const RMS_OFF = 0.02;

export type MicPhase = "idle" | "listening" | "recording";

function rms(buf: Uint8Array): number {
  let sum = 0;
  for (let i = 0; i < buf.length; i++) {
    const v = (buf[i] - 128) / 128;
    sum += v * v;
  }
  return Math.sqrt(sum / buf.length);
}

export function useMic(onUtterance: (blob: Blob) => void) {
  const rec = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const raf = useRef(0);
  const heardAt = useRef(0);
  const quietSince = useRef(0);
  const stopping = useRef(false);
  const onUtteranceRef = useRef(onUtterance);
  onUtteranceRef.current = onUtterance;

  const [phase, setPhase] = useState<MicPhase>("idle");

  const teardown = useCallback(() => {
    cancelAnimationFrame(raf.current);
    rec.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    void ctxRef.current?.close();
    ctxRef.current = null;
    heardAt.current = 0;
    quietSince.current = 0;
    stopping.current = false;
    setPhase("idle");
  }, []);

  const finish = useCallback((blob: Blob) => {
    teardown();
    if (blob.size > 0) onUtteranceRef.current(blob);
  }, [teardown]);

  const stopRecorder = useCallback(() => {
    const r = rec.current;
    if (!r || r.state === "inactive") {
      teardown();
      return;
    }
    r.onstop = () => {
      finish(new Blob(chunks.current, { type: r.mimeType || "audio/webm" }));
    };
    r.stop();
  }, [finish, teardown]);

  const tick = useCallback((analyser: AnalyserNode, buf: Uint8Array) => {
    analyser.getByteTimeDomainData(buf);
    const level = rms(buf);
    const now = performance.now();

    if (level >= RMS_ON) {
      quietSince.current = 0;
      if (!heardAt.current) heardAt.current = now;
      if (!rec.current && now - heardAt.current >= SPEECH_MS) {
        const stream = streamRef.current;
        if (!stream) return;
        const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus"
          : "audio/webm";
        const r = new MediaRecorder(stream, { mimeType: mime });
        chunks.current = [];
        r.ondataavailable = (e) => {
          if (e.data.size) chunks.current.push(e.data);
        };
        rec.current = r;
        r.start();
        setPhase("recording");
      }
    } else if (level < RMS_OFF && rec.current) {
      if (!quietSince.current) quietSince.current = now;
      if (now - quietSince.current >= SILENCE_MS && !stopping.current) {
        stopping.current = true;
        stopRecorder();
        return;
      }
    }

    raf.current = requestAnimationFrame(() => tick(analyser, buf));
  }, [stopRecorder]);

  const start = useCallback(async () => {
    if (streamRef.current) return;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    streamRef.current = stream;
    const ctx = new AudioContext();
    ctxRef.current = ctx;
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);
    heardAt.current = 0;
    quietSince.current = 0;
    stopping.current = false;
    setPhase("listening");
    const buf = new Uint8Array(analyser.fftSize);
    raf.current = requestAnimationFrame(() => tick(analyser, buf));
  }, [tick]);

  const stop = useCallback(() => {
    if (rec.current) stopRecorder();
    else teardown();
  }, [stopRecorder, teardown]);

  useEffect(() => () => teardown(), [teardown]);

  return { phase, start, stop };
}

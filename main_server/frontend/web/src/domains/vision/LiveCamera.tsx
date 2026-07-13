import { useCallback, useEffect, useRef, useState } from "react";
import {
  VISION_WEBRTC_ENABLED,
  VISION_WEBRTC_ONLY,
  connectWebRtcStream,
  defaultView,
  extractTransports,
  fetchOverlayLatestMeta,
  fetchVisionStreams,
  latestImageUrl,
  MJPEG_RECONNECT_DELAYS_MS,
  MJPEG_STALE_THRESHOLD_SEC,
  MJPEG_STALENESS_POLL_MS,
  mjpegPollIntervalMs,
  overlayMetaAgeSec,
  preferWebRtc,
  waitForFirstVideoFrame,
  viewsForSource,
} from "../vision/transport";
import type { CameraSource } from "../../types";

type Kind = "overlay" | "frame";
type TransportMode = "mjpeg" | "webrtc" | "idle";
/** 타일·배지에 쓰는 수신 경로 표시 */
type TransportDisplay = "pending" | "webrtc" | "mjpeg" | "error";
const WEBRTC_RETRY_DELAYS_MS = [5000, 15000, 30000, 60000] as const;

function transportBadgeLabel(display: TransportDisplay, mjpegPoll: boolean): string {
  switch (display) {
    case "webrtc": return "WebRTC";
    case "mjpeg": return mjpegPoll ? "MJPEG·poll" : "MJPEG";
    case "error": return "오류";
    default: return "연결중";
  }
}

export function CameraTile({
  source,
  label,
  kind,
  maxFps,
  view,
  onViewChange,
  compact = false,
}: {
  source: string;
  label: string;
  kind: Kind;
  maxFps: number;
  view: string;
  onViewChange?: (view: string) => void;
  /** 레일 융합 카드 — 타일 헤더 생략. */
  compact?: boolean;
}) {
  const [status, setStatus] = useState("연결 중");
  const [mode, setMode] = useState<TransportMode>("mjpeg");
  const [transportDisplay, setTransportDisplay] = useState<TransportDisplay>("pending");
  const [reconnectAttempt, setReconnectAttempt] = useState(0);
  const [webrtcRetryToken, setWebrtcRetryToken] = useState(0);
  const [isVisible, setIsVisible] = useState(true);
  const tileRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const cleanupRef = useRef<(() => void) | null>(null);
  const mjpegBackoffRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stalenessTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const webrtcRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const webrtcRetryAttemptRef = useRef(0);
  const streamKeyRef = useRef("");
  const lastMjpegLoadAtRef = useRef(0);
  const mjpegActiveRef = useRef(false);
  const visibleRef = useRef(true);
  const viewOptions = viewsForSource(source);

  useEffect(() => {
    visibleRef.current = isVisible;
  }, [isVisible]);

  useEffect(() => {
    const el = tileRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => setIsVisible(entry.isIntersecting),
      { threshold: 0.1 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const clearMjpegTimers = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (stalenessTimerRef.current) {
      clearInterval(stalenessTimerRef.current);
      stalenessTimerRef.current = null;
    }
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const pollMjpegFrame = useCallback(() => {
    const img = imgRef.current;
    if (!img || !source || !visibleRef.current) return;
    img.style.display = "";
    img.src = latestImageUrl(source, kind, Date.now());
  }, [kind, source]);

  const beginMjpegPoll = useCallback((attempt: number) => {
    setReconnectAttempt(attempt);
    setTransportDisplay(attempt > 0 ? "error" : "pending");
    setStatus(attempt > 0 ? `재연결 중… ${attempt}회` : "MJPEG 연결 중…");
    pollMjpegFrame();
  }, [pollMjpegFrame]);

  const scheduleMjpegReconnect = useCallback(() => {
    if (!mjpegActiveRef.current) return;
    clearMjpegTimers();
    const idx = Math.min(mjpegBackoffRef.current, MJPEG_RECONNECT_DELAYS_MS.length - 1);
    const delay = MJPEG_RECONNECT_DELAYS_MS[idx];
    mjpegBackoffRef.current += 1;
    const nextAttempt = mjpegBackoffRef.current;
    reconnectTimerRef.current = setTimeout(() => beginMjpegPoll(nextAttempt), delay);
  }, [beginMjpegPoll, clearMjpegTimers]);

  useEffect(() => {
    let cancelled = false;
    const streamKey = `${source}\0${view}`;
    if (streamKeyRef.current !== streamKey) {
      streamKeyRef.current = streamKey;
      webrtcRetryAttemptRef.current = 0;
    }

    const clearWebRtcRetry = () => {
      if (!webrtcRetryTimerRef.current) return;
      clearTimeout(webrtcRetryTimerRef.current);
      webrtcRetryTimerRef.current = null;
    };

    const scheduleWebRtcRetry = () => {
      if (!VISION_WEBRTC_ENABLED || cancelled || webrtcRetryTimerRef.current) return;
      const idx = Math.min(webrtcRetryAttemptRef.current, WEBRTC_RETRY_DELAYS_MS.length - 1);
      const delay = WEBRTC_RETRY_DELAYS_MS[idx];
      webrtcRetryAttemptRef.current += 1;
      webrtcRetryTimerRef.current = setTimeout(() => {
        webrtcRetryTimerRef.current = null;
        if (!cancelled) setWebrtcRetryToken((token) => token + 1);
      }, delay);
    };

    const beginMjpeg = (message: string, retryWebRtc = true) => {
      setMode("mjpeg");
      setTransportDisplay(imgRef.current?.naturalWidth ? "mjpeg" : "pending");
      setStatus(message);
      if (retryWebRtc) scheduleWebRtcRetry();
    };

    const failWebRtcOnly = (message: string) => {
      setMode("idle");
      setTransportDisplay("error");
      setStatus(message);
      scheduleWebRtcRetry();
    };

    const handleWebRtcLost = () => {
      if (cancelled) return;
      cleanupRef.current?.();
      cleanupRef.current = null;
      if (VISION_WEBRTC_ONLY) {
        failWebRtcOnly("WebRTC 연결 끊김 (폴백 없음)");
      } else {
        webrtcRetryAttemptRef.current = 0;
        beginMjpeg("WebRTC 연결 끊김 → MJPEG");
      }
    };

    const run = async () => {
      clearWebRtcRetry();
      cleanupRef.current?.();
      cleanupRef.current = null;

      if (!VISION_WEBRTC_ENABLED) {
        beginMjpeg("MJPEG 연결 중…", false);
        return;
      }

      setStatus("WebRTC 전송 확인 중…");
      try {
        const payload = await fetchVisionStreams(source, view);
        if (cancelled) return;
        const transports = extractTransports(payload);
        if (!preferWebRtc(transports) && !VISION_WEBRTC_ONLY) {
          beginMjpeg("WebRTC 미준비 → MJPEG");
          return;
        }
        if (!preferWebRtc(transports) && VISION_WEBRTC_ONLY) {
          setStatus("WebRTC 미준비 · offer 시도");
        }

        const video = videoRef.current;
        if (!video) {
          if (VISION_WEBRTC_ONLY) {
            failWebRtcOnly("WebRTC 실패 (video 없음)");
            return;
          }
          beginMjpeg("WebRTC 실패 → MJPEG");
          return;
        }

        setStatus("WebRTC 연결 중…");
        const cleanup = await connectWebRtcStream(source, view, video, handleWebRtcLost);
        cleanupRef.current = cleanup;
        await waitForFirstVideoFrame(video);
        if (cancelled) {
          cleanup();
          return;
        }
        webrtcRetryAttemptRef.current = 0;
        setMode("webrtc");
        setTransportDisplay("webrtc");
        setStatus("WebRTC 수신 중");
      } catch {
        if (cancelled) return;
        cleanupRef.current?.();
        cleanupRef.current = null;
        if (VISION_WEBRTC_ONLY) {
          failWebRtcOnly("WebRTC 실패 (폴백 없음)");
          return;
        }
        beginMjpeg("WebRTC 실패 → MJPEG");
      }
    };

    void run();

    return () => {
      cancelled = true;
      clearWebRtcRetry();
      cleanupRef.current?.();
      cleanupRef.current = null;
    };
  }, [source, view, webrtcRetryToken]);

  useEffect(() => {
    if (mode !== "mjpeg") {
      mjpegActiveRef.current = false;
      clearMjpegTimers();
      return;
    }

    if (!isVisible) {
      mjpegActiveRef.current = false;
      clearMjpegTimers();
      setStatus("화면 밖 — 폴링 일시정지");
      return;
    }

    mjpegActiveRef.current = true;
    mjpegBackoffRef.current = 0;
    lastMjpegLoadAtRef.current = 0;
    const pollMs = mjpegPollIntervalMs(maxFps);
    beginMjpegPoll(0);

    pollTimerRef.current = setInterval(() => {
      if (!mjpegActiveRef.current) return;
      pollMjpegFrame();
    }, pollMs);

    stalenessTimerRef.current = setInterval(() => {
      if (!mjpegActiveRef.current) return;
      const sinceLoadSec = lastMjpegLoadAtRef.current > 0
        ? (Date.now() - lastMjpegLoadAtRef.current) / 1000
        : null;
      if (sinceLoadSec !== null && sinceLoadSec >= MJPEG_STALE_THRESHOLD_SEC) {
        scheduleMjpegReconnect();
        return;
      }
      void fetchOverlayLatestMeta(source)
        .then((meta) => {
          if (!mjpegActiveRef.current) return;
          const age = overlayMetaAgeSec(meta);
          if (age !== null && age >= MJPEG_STALE_THRESHOLD_SEC) {
            scheduleMjpegReconnect();
          }
        })
        .catch(() => { /* overlay meta optional */ });
    }, MJPEG_STALENESS_POLL_MS);

    return () => {
      mjpegActiveRef.current = false;
      clearMjpegTimers();
    };
  }, [
    beginMjpegPoll,
    clearMjpegTimers,
    isVisible,
    kind,
    maxFps,
    mode,
    pollMjpegFrame,
    scheduleMjpegReconnect,
    source,
  ]);

  const handleMjpegLoad = () => {
    if (mode !== "mjpeg" || !isVisible) return;
    mjpegBackoffRef.current = 0;
    setReconnectAttempt(0);
    lastMjpegLoadAtRef.current = Date.now();
    setTransportDisplay("mjpeg");
    setStatus("MJPEG 수신 중");
  };

  const handleMjpegError = () => {
    if (mode !== "mjpeg" || !isVisible) return;
    setTransportDisplay("error");
    setStatus("stream 오류 — 재연결 시도");
    scheduleMjpegReconnect();
  };

  const tileClass = `cam-tile cam-tile--${transportDisplay}`;
  const badgeClass = `cam-transport-badge cam-transport-badge--${transportDisplay}`;
  const mjpegPoll = mode === "mjpeg";
  const badgeLabel = reconnectAttempt > 0 && mjpegPoll
    ? `${transportBadgeLabel(transportDisplay, mjpegPoll)} · ${reconnectAttempt}`
    : transportBadgeLabel(transportDisplay, mjpegPoll);

  return (
    <div ref={tileRef} className={tileClass}>
      {!compact ? (
        <div className="cam-tile-head">
          <span>{label}</span>
          <span className={badgeClass}>{badgeLabel}</span>
          <span className="mono">{source}</span>
          {viewOptions.length > 1 && onViewChange ? (
            <select className="filter compact-select" value={view} onChange={(e) => onViewChange(e.target.value)}>
              {viewOptions.map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          ) : (
            <span className="mono muted">{view}</span>
          )}
        </div>
      ) : null}
      <div className="live-stage">
        <video
          ref={videoRef}
          className={`cam-live cam-live-video${mode === "webrtc" ? " is-active" : ""}`}
          playsInline
          muted
          autoPlay
          aria-hidden={mode !== "webrtc"}
        />
        <img
          ref={imgRef}
          className="cam-live"
          alt={label}
          hidden={mode !== "mjpeg"}
          onLoad={handleMjpegLoad}
          onError={handleMjpegError}
        />
        <span className={`cam-fallback cam-fallback--${transportDisplay}`}>{status}</span>
      </div>
      {compact ? (
        <div className="cam-tile-foot">
          <span className={badgeClass}>{badgeLabel}</span>
        </div>
      ) : null}
    </div>
  );
}

function transportToolbarLabel(): string {
  if (!VISION_WEBRTC_ENABLED) return "MJPEG·poll";
  if (VISION_WEBRTC_ONLY) return "WebRTC only";
  return "WebRTC→MJPEG·poll";
}

function transportToolbarClass(): string {
  if (!VISION_WEBRTC_ENABLED) return "cam-policy-badge cam-policy-badge--mjpeg";
  if (VISION_WEBRTC_ONLY) return "cam-policy-badge cam-policy-badge--webrtc-only";
  return "cam-policy-badge cam-policy-badge--fallback";
}

export function LiveCamera({ cameras }: { cameras: CameraSource[] }) {
  const [mode, setMode] = useState<"grid" | "single">("grid");
  const [kind, setKind] = useState<Kind>("overlay");
  const [source, setSource] = useState("");
  const [views, setViews] = useState<Record<string, string>>({});
  const active = source || cameras[0]?.source_id || "";
  const activeLabel = cameras.find((c) => c.source_id === active)?.label || active;

  const viewFor = (sourceId: string) => views[sourceId] ?? defaultView(sourceId);
  const setViewFor = (sourceId: string, view: string) => {
    setViews((cur) => ({ ...cur, [sourceId]: view }));
  };

  return (
    <>
      <div className="toolbar">
        <button className={`rowbtn ${mode === "grid" ? "primary" : ""}`} onClick={() => setMode("grid")}>그리드</button>
        <button className={`rowbtn ${mode === "single" ? "primary" : ""}`} onClick={() => setMode("single")}>단일</button>
        {mode === "single" && (
          <select className="filter" value={active} onChange={(e) => setSource(e.target.value)}>
            {cameras.length === 0 ? <option value="">카메라 없음</option> :
              cameras.map((c) => <option key={c.source_id} value={c.source_id}>{c.label} ({c.source_id})</option>)}
          </select>
        )}
        <select className="filter" value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
          <option value="overlay">overlay</option>
          <option value="frame">frame</option>
        </select>
        <span className="rowcount">{cameras.length}대</span>
        <span className={transportToolbarClass()} title="빌드 정책">{transportToolbarLabel()}</span>
      </div>

      {cameras.length === 0 ? (
        <div className="status-line">카메라 없음</div>
      ) : mode === "grid" ? (
        <div className="cam-grid">
          {cameras.map((c) => (
            <CameraTile
              key={c.source_id}
              source={c.source_id}
              label={c.label}
              kind={kind}
              maxFps={8}
              view={viewFor(c.source_id)}
              onViewChange={viewsForSource(c.source_id).length > 1 ? (v) => setViewFor(c.source_id, v) : undefined}
            />
          ))}
        </div>
      ) : (
        <CameraTile
          source={active}
          label={activeLabel}
          kind={kind}
          maxFps={15}
          view={viewFor(active)}
          onViewChange={viewsForSource(active).length > 1 ? (v) => setViewFor(active, v) : undefined}
        />
      )}
    </>
  );
}

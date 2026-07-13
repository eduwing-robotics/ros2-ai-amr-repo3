/** Vision stream transport discovery + WebRTC signaling (Main proxy only). */

import { apiGet, apiSend } from "../../lib/api";

/** MJPEG 폴백 없이 WebRTC만 시도(개발·시그널링 테스트). ONLY면 ENABLED와 동일하게 WebRTC 경로 진입. */
export const VISION_WEBRTC_ONLY = import.meta.env.VITE_VISION_WEBRTC_ONLY === "true";
/** 기본 off — 켜야 WebRTC 발견·offer 시도. MJPEG는 항상 사용 가능(ONLY 제외). */
export const VISION_WEBRTC_ENABLED =
  import.meta.env.VITE_VISION_WEBRTC_ENABLED === "true" || VISION_WEBRTC_ONLY;

const WEBRTC_CONNECT_TIMEOUT_MS = 8000;

const BLOCKED_TRANSPORT_STATUS = new Set([
  "candidate",
  "fallback_required",
  "unavailable",
  "not_configured",
]);

const BLOCKED_SIDECAR_STATUS = new Set([
  "not_configured",
  "unhealthy",
  "down",
]);

export const SOURCE_VIEWS: Record<string, string[]> = {
  global_cam_01: ["full", "lift_roi"],
  tb3_1_picam: ["full"],
  tb3_2_picam: ["full"],
};

export function viewsForSource(source: string): string[] {
  return SOURCE_VIEWS[source] ?? ["full"];
}

export function defaultView(source: string): string {
  return viewsForSource(source)[0] ?? "full";
}

export interface StreamTransportSidecar {
  status?: string;
  offer_url?: string;
  whep_url?: string;
}

export interface StreamTransport {
  kind: string;
  configured?: boolean;
  healthy?: boolean;
  status?: string;
  url?: string;
  sidecar?: StreamTransportSidecar;
}

export interface VisionStreamsResponse {
  sources?: Array<{
    source_id?: string;
    view?: string;
    stream_transports?: StreamTransport[];
  }>;
  stream_transports?: StreamTransport[];
}

export interface WebRtcOfferResponse {
  sdp?: string;
  type?: RTCSdpType;
  media_only?: boolean;
  motion_command_allowed?: boolean;
  control_topics_published?: string[];
  side_effects?: Record<string, boolean>;
  status?: string;
  reason?: string;
  selected_transport?: string;
}

export async function fetchVisionStreams(source: string, view: string): Promise<VisionStreamsResponse> {
  const qs = new URLSearchParams({ source, view });
  return apiGet<VisionStreamsResponse>(`/vision/streams?${qs}`);
}

export function extractTransports(payload: VisionStreamsResponse): StreamTransport[] {
  if (payload.stream_transports?.length) return payload.stream_transports;
  const first = payload.sources?.[0];
  return first?.stream_transports ?? [];
}

/** WebRTC transport가 primary 시도 가능한지 판정. */
export function isWebRtcReadyTransport(transport: StreamTransport | undefined): boolean {
  if (!transport || transport.kind !== "webrtc") return false;
  if (transport.configured === false || transport.healthy === false) return false;

  const status = String(transport.status ?? "").toLowerCase();
  if (status === "ready") return true;
  if (status && BLOCKED_TRANSPORT_STATUS.has(status)) return false;

  const sidecarStatus = String(transport.sidecar?.status ?? "").toLowerCase();
  if (sidecarStatus && BLOCKED_SIDECAR_STATUS.has(sidecarStatus)) return false;

  return true;
}

export function preferWebRtc(transports: StreamTransport[]): boolean {
  const webrtc = transports.find((t) => t.kind === "webrtc");
  return isWebRtcReadyTransport(webrtc);
}

/** Vision offer가 SDP 대신 MJPEG 폴백을 요청하는지 판정. */
export function isOfferFallbackResponse(answer: WebRtcOfferResponse): boolean {
  const status = String(answer.status ?? "").toLowerCase();
  if (status === "fallback_required") return true;
  if (String(answer.selected_transport ?? "").toLowerCase() === "mjpeg") return true;
  const reason = String(answer.reason ?? "").toLowerCase();
  if (reason.includes("sidecar_not_configured") || reason.includes("not_configured")) return true;
  return !answer.sdp;
}

export async function postWebRtcOffer(
  source: string,
  view: string,
  offer: RTCSessionDescriptionInit,
): Promise<WebRtcOfferResponse> {
  const qs = new URLSearchParams({ view });
  return apiSend<WebRtcOfferResponse>(
    `/vision/streams/${encodeURIComponent(source)}/webrtc/offer?${qs}`,
    "POST",
    offer,
  );
}

function waitIceGathering(pc: RTCPeerConnection): Promise<void> {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      if (pc.iceGatheringState === "complete") {
        pc.removeEventListener("icegatheringstatechange", done);
        resolve();
      }
    };
    pc.addEventListener("icegatheringstatechange", done);
    setTimeout(() => {
      pc.removeEventListener("icegatheringstatechange", done);
      resolve();
    }, 2000);
  });
}

function waitConnected(pc: RTCPeerConnection, timeoutMs: number): Promise<void> {
  if (pc.connectionState === "connected") return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error("webrtc_timeout"));
    }, timeoutMs);
    const onChange = () => {
      if (pc.connectionState === "connected") {
        cleanup();
        resolve();
      } else if (pc.connectionState === "failed" || pc.connectionState === "closed") {
        cleanup();
        reject(new Error("webrtc_failed"));
      }
    };
    const cleanup = () => {
      clearTimeout(timer);
      pc.removeEventListener("connectionstatechange", onChange);
    };
    pc.addEventListener("connectionstatechange", onChange);
  });
}

/** WebRTC 미디어 연결 시도. 실패 시 throw — 호출부가 MJPEG로 폴백. */
export async function connectWebRtcStream(
  source: string,
  view: string,
  videoEl: HTMLVideoElement,
): Promise<() => void> {
  const pc = new RTCPeerConnection();
  const cleanup = () => {
    pc.close();
    if (videoEl.srcObject instanceof MediaStream) {
      videoEl.srcObject.getTracks().forEach((t) => t.stop());
    }
    videoEl.srcObject = null;
  };

  pc.ontrack = (ev) => {
    const [stream] = ev.streams;
    if (stream) videoEl.srcObject = stream;
  };

  const offer = await pc.createOffer({ offerToReceiveVideo: true });
  await pc.setLocalDescription(offer);
  await waitIceGathering(pc);

  const local = pc.localDescription;
  if (!local?.sdp) throw new Error("webrtc_no_local_sdp");

  const answer = await postWebRtcOffer(source, view, { sdp: local.sdp, type: local.type });
  if (isOfferFallbackResponse(answer)) {
    cleanup();
    throw new Error("webrtc_fallback_required");
  }
  if (answer.media_only === false || answer.motion_command_allowed) {
    cleanup();
    throw new Error("webrtc_not_media_only");
  }

  await pc.setRemoteDescription({ type: answer.type || "answer", sdp: answer.sdp! });
  await waitConnected(pc, WEBRTC_CONNECT_TIMEOUT_MS);
  await videoEl.play().catch(() => { /* autoplay policy */ });

  return cleanup;
}

/** overlay/latest 메타 — MJPEG freeze/staleness 워치독. */
export interface OverlayLatestMeta {
  staleness_sec?: number;
  age_sec?: number;
  last_frame_age_ms?: number;
  visual_state?: {
    stale?: boolean;
    staleness_sec?: number;
    age_sec?: number;
    status?: string;
  };
}

export const MJPEG_STALE_THRESHOLD_SEC = 5;
export const MJPEG_STALENESS_POLL_MS = 2000;
export const MJPEG_RECONNECT_DELAYS_MS = [1000, 2000, 4000, 10000] as const;
/** latest-image 폴링 최소 간격. */
export const MJPEG_POLL_MIN_MS = 200;

export function mjpegPollIntervalMs(maxFps: number): number {
  const fps = Math.max(1, maxFps);
  return Math.max(MJPEG_POLL_MIN_MS, Math.floor(1000 / fps));
}

/** MJPEG 스트림 대신 최신 프레임만 요청(캐시버스터). */
export function latestImageUrl(source: string, kind: "overlay" | "frame", bust: number): string {
  const qs = new URLSearchParams({ source, _t: String(bust) });
  return `/api/v1/vision/${kind}/latest/image?${qs}`;
}

export function overlayMetaAgeSec(meta: OverlayLatestMeta): number | null {
  if (typeof meta.staleness_sec === "number") return meta.staleness_sec;
  if (typeof meta.age_sec === "number") return meta.age_sec;
  if (typeof meta.last_frame_age_ms === "number") return meta.last_frame_age_ms / 1000;
  const vs = meta.visual_state;
  if (!vs) return null;
  if (typeof vs.staleness_sec === "number") return vs.staleness_sec;
  if (typeof vs.age_sec === "number") return vs.age_sec;
  if (vs.stale === true || String(vs.status ?? "").toLowerCase() === "stale") return MJPEG_STALE_THRESHOLD_SEC;
  return null;
}

export function fetchOverlayLatestMeta(source: string): Promise<OverlayLatestMeta> {
  return apiGet(`/vision/overlay/latest?source=${encodeURIComponent(source)}`);
}

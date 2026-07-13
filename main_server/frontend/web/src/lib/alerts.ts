// 관제 능동 경보(소리 · 탭 타이틀 점멸) 유틸.
// 에셋/외부 리소스 없이 WebAudio로 비프를 합성해 CSP(외부 차단) 하에서도 동작한다.
// 브라우저 autoplay 정책상 소리는 최초 사용자 제스처 이후에만 난다(그 전에는 조용히 무시).

let audioCtx: AudioContext | null = null;
let audioUnlocked = false;

function ensureCtx(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  if (!audioCtx) audioCtx = new Ctor();
  return audioCtx;
}

/** 최초 클릭·키 입력 시 오디오 컨텍스트를 언락한다(1회). 없으면 경보음만 무음, 나머지 경보는 정상. */
export function armAlertAudio(): void {
  if (audioUnlocked || typeof window === "undefined") return;
  const unlock = () => {
    const ctx = ensureCtx();
    if (ctx && ctx.state === "suspended") void ctx.resume();
    audioUnlocked = true;
    window.removeEventListener("pointerdown", unlock);
    window.removeEventListener("keydown", unlock);
  };
  window.addEventListener("pointerdown", unlock, { once: true });
  window.addEventListener("keydown", unlock, { once: true });
}

/** 짧은 경보음 2회(삐-삐). 오디오 언락 전이면 조용히 무시된다. */
export function playAlertBeep(): void {
  const ctx = ensureCtx();
  if (!ctx) return;
  if (ctx.state === "suspended") void ctx.resume();
  const now = ctx.currentTime;
  for (let i = 0; i < 2; i++) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    const t0 = now + i * 0.22;
    osc.type = "square";
    osc.frequency.setValueAtTime(880, t0);
    gain.gain.setValueAtTime(0.0001, t0);
    gain.gain.exponentialRampToValueAtTime(0.15, t0 + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.18);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t0);
    osc.stop(t0 + 0.2);
  }
}

// --- 탭 타이틀 점멸 ---

let flashTimer: number | null = null;
let baseTitle: string | null = null;
let focusBound = false;

function stopTitleFlash(): void {
  if (flashTimer !== null) {
    window.clearInterval(flashTimer);
    flashTimer = null;
  }
  if (baseTitle !== null) {
    document.title = baseTitle;
    baseTitle = null;
  }
}

function bindFocusStop(): void {
  if (focusBound || typeof window === "undefined") return;
  focusBound = true;
  window.addEventListener("focus", stopTitleFlash);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") stopTitleFlash();
  });
}

/**
 * 탭 타이틀을 경보 문구와 원제목 사이로 점멸시켜 다른 탭/창을 보던 운영자의 주의를 끈다.
 * 창을 보고 있으면(포커스+visible) 점멸하지 않는다(이미 인지 가능). 창 포커스 시 자동 정지.
 */
export function flashTitle(label: string): void {
  if (typeof document === "undefined") return;
  if (document.visibilityState === "visible" && document.hasFocus()) return;
  if (baseTitle === null) baseTitle = document.title;
  if (flashTimer !== null) window.clearInterval(flashTimer);
  let on = false;
  flashTimer = window.setInterval(() => {
    document.title = on ? (baseTitle ?? "") : `🔴 경보 · ${label}`;
    on = !on;
  }, 1000);
  bindFocusStop();
}

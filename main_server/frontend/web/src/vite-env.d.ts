/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_VISION_WEBRTC_ENABLED?: string;
  readonly VITE_VISION_WEBRTC_ONLY?: string;
  readonly VITE_API_PROXY_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

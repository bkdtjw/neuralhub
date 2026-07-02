interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_WS_BASE?: string;
  readonly VITE_AUTH_TOKEN?: string;
  readonly VITE_HOOKS_MOCK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

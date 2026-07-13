import { useEffect } from "react";

export type ToastKind = "ok" | "err" | "info";

export type ToastItem = {
  id: string;
  message: string;
  kind: ToastKind;
};

export function ToastStack({ items, onDismiss }: { items: ToastItem[]; onDismiss: (id: string) => void }) {
  return (
    <div className="toast-stack" role="status" aria-live="polite" aria-atomic="false">
      {items.map((t) => (
        <Toast key={t.id} item={t} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function Toast({ item, onDismiss }: { item: ToastItem; onDismiss: (id: string) => void }) {
  useEffect(() => {
    const timer = window.setTimeout(() => onDismiss(item.id), 4200);
    return () => window.clearTimeout(timer);
  }, [item.id, onDismiss]);

  const icon = item.kind === "ok" ? "✓" : item.kind === "err" ? "✕" : "ℹ";
  return (
    <div className={`toast toast-${item.kind}`}>
      <span className="toast-icon" aria-hidden="true">{icon}</span>
      <span className="toast-msg">{item.message}</span>
      <button type="button" className="toast-close" onClick={() => onDismiss(item.id)} aria-label="닫기">×</button>
    </div>
  );
}

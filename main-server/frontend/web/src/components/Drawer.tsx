import { useEffect, useRef, type ReactNode } from "react";

const OPERATE_SCROLL_SELECTOR = ".operator-main, .operator-right-rail";

function snapshotOperateScroll(): Map<Element, number> {
  const saved = new Map<Element, number>();
  document.querySelectorAll(OPERATE_SCROLL_SELECTOR).forEach((el) => {
    saved.set(el, (el as HTMLElement).scrollTop);
  });
  return saved;
}

function restoreOperateScroll(saved: Map<Element, number>) {
  saved.forEach((top, el) => {
    (el as HTMLElement).scrollTop = top;
  });
}

// 좌측 슬라이드오버 드로어. 운영자 지속 셸에서 맵/우레일은 고정한 채 작업 UI만 띄운다.
export function Drawer({
  title,
  onClose,
  children,
  className = "",
}: {
  title: ReactNode;
  onClose?: () => void;
  children: ReactNode;
  className?: string;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<Element | null>(document.activeElement);
  const scrollSnapshotRef = useRef<Map<Element, number>>(new Map());

  useEffect(() => {
    triggerRef.current = document.activeElement;
    scrollSnapshotRef.current = snapshotOperateScroll();
    closeRef.current?.focus({ preventScroll: true });

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && onClose) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      const el = triggerRef.current;
      if (el && "focus" in el && typeof (el as HTMLElement).focus === "function") {
        (el as HTMLElement).focus({ preventScroll: true });
      }
      restoreOperateScroll(scrollSnapshotRef.current);
    };
  }, [onClose]);

  return (
    <aside
      ref={panelRef}
      className={`drawer ${className}`.trim()}
      role="dialog"
      aria-modal="true"
      aria-label={typeof title === "string" ? title : undefined}
    >
      <div className="drawer-head">
        <div className="drawer-title">{title}</div>
        {onClose ? (
          <button ref={closeRef} className="drawer-close" onClick={onClose} aria-label="닫기" title="닫기">
            ✕
          </button>
        ) : null}
      </div>
      <div className="drawer-body">{children}</div>
    </aside>
  );
}

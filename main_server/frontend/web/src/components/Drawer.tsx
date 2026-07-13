import { useEffect, useId, useRef, type ReactNode } from "react";

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
  id,
  modal = false,
}: {
  title: ReactNode;
  onClose?: () => void;
  children: ReactNode;
  className?: string;
  id?: string;
  modal?: boolean;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<Element | null>(document.activeElement);
  const scrollSnapshotRef = useRef<Map<Element, number>>(new Map());
  const titleId = useId();

  useEffect(() => {
    triggerRef.current = document.activeElement;
    scrollSnapshotRef.current = snapshotOperateScroll();
    closeRef.current?.focus({ preventScroll: true });

    const panel = panelRef.current;
    const siblings = modal && panel?.parentElement
      ? Array.from(panel.parentElement.children).filter(
        (el) => el !== panel && !el.classList.contains("drawer-scrim"),
      )
      : [];
    const siblingInert = siblings.map((el) => el.hasAttribute("inert"));
    siblings.forEach((el) => el.setAttribute("inert", ""));

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && onClose) {
        onClose();
        return;
      }
      if (e.key !== "Tab" || !modal || !panel) return;
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )).filter((el) => !el.hasAttribute("hidden"));
      if (!focusable.length) {
        e.preventDefault();
        panel.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      siblings.forEach((el, index) => {
        if (!siblingInert[index]) el.removeAttribute("inert");
      });
      const el = triggerRef.current;
      if (el && "focus" in el && typeof (el as HTMLElement).focus === "function") {
        (el as HTMLElement).focus({ preventScroll: true });
      }
      restoreOperateScroll(scrollSnapshotRef.current);
    };
  }, [modal, onClose]);

  return (
    <aside
      id={id}
      ref={panelRef}
      className={`drawer ${className}`.trim()}
      role={modal ? "dialog" : "region"}
      aria-modal={modal ? true : undefined}
      aria-labelledby={titleId}
      tabIndex={-1}
    >
      <div className="drawer-head">
        <div id={titleId} className="drawer-title">{title}</div>
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

import { useState, type ReactNode } from "react";

// 접기 가능한 패널 (레거시 collapse-btn/chev/.panel.collapsed 스타일 재사용).
export function CollapsiblePanel({
  title,
  children,
  defaultOpen = true,
  className = "",
  onOpenChange,
}: {
  title: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
  onOpenChange?: (open: boolean) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const toggle = () => {
    setOpen((v) => {
      const next = !v;
      onOpenChange?.(next);
      return next;
    });
  };
  return (
    <div className={`panel${open ? "" : " collapsed"} ${className}`.trim()}>
      <h2 className="panel-head">
        <button className="collapse-btn" aria-expanded={open} onClick={toggle} title="접기/펼치기">
          <span className="chev">▾</span> {title}
        </button>
      </h2>
      <div className="panel-body">{children}</div>
    </div>
  );
}

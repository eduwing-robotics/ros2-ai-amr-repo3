import type { ReactNode } from "react";

// 라벨 + 컨트롤 묶음. form-grid 안에서 쓰며 span2 로 2칸 차지.
export function Field({
  label,
  children,
  span2 = false,
}: {
  label: ReactNode;
  children: ReactNode;
  span2?: boolean;
}) {
  return (
    <label className={span2 ? "span2" : undefined}>
      <span>{label}</span>
      {children}
    </label>
  );
}

import type { ButtonHTMLAttributes } from "react";

// 기존 .btn / .rowbtn 클래스 위의 얇은 래퍼. variant 로 시각 구분을 표준화한다.
// row-primary=행 안의 채움 실행(시작), ghost=행 안의 조용한 네비(펼침) — 행 액션 위계용.
type Variant = "primary" | "secondary" | "danger" | "row" | "row-primary" | "row-danger" | "ghost";

const CLS: Record<Variant, string> = {
  primary: "btn",
  secondary: "btn secondary",
  danger: "btn danger",
  row: "rowbtn",
  "row-primary": "rowbtn primary",
  "row-danger": "rowbtn danger",
  ghost: "rowbtn ghost",
};

export function Button({
  variant = "primary",
  className = "",
  ...rest
}: { variant?: Variant } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={`${CLS[variant]} ${className}`.trim()} {...rest} />;
}

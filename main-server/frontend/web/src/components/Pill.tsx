import { cell, pillKind } from "../lib/format";

// 레거시 pill() 의 React 버전. styles.css 의 .pill.* 클래스를 그대로 사용한다.
export function Pill({ status }: { status?: unknown }) {
  return <span className={`pill ${pillKind(status)}`}>{cell(status)}</span>;
}

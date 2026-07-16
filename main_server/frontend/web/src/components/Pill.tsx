import { cell, pillKind, statusLabel, statusTone } from "../lib/format";

// 레거시 pill() 의 React 버전. styles.css 의 .pill.* 클래스를 그대로 사용한다.
// 표시는 한글 라벨, 원시 코드는 title 로 유지 (UX.md §2: 내부 코드 비노출).
export function Pill({ status }: { status?: unknown }) {
  const tone = statusTone(status);
  return <span className={"pill " + pillKind(status) + " status-" + tone} data-status-tone={tone} title={cell(status)}>{statusLabel(status)}</span>;
}

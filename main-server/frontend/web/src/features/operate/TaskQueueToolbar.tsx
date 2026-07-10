import { Button } from "../../components/Button";
import type { Segment } from "./taskQueueModel";

// 2-zone 툴바: 왼쪽=뷰 전환(세그먼티드 컨트롤 한 덩어리), 오른쪽=배치 실행(행동 존).
// 순서 편집 커밋(우선순위 저장/되돌리기)은 여기 두지 않고 별도 edit-commit 바에서 처리한다.
export function TaskQueueToolbar({
  segment,
  counts,
  reorderDirty,
  autoAssignPending,
  autoAssignAndStartPending,
  onSegment,
  onAutoAssign,
  onAutoAssignAndStart,
}: {
  segment: Segment;
  counts: { queued: number; running: number; closed: number };
  reorderDirty: boolean;
  autoAssignPending: boolean;
  autoAssignAndStartPending: boolean;
  onSegment: (segment: Segment) => void;
  onAutoAssign: () => void;
  onAutoAssignAndStart: () => void;
}) {
  const autoDisabled = autoAssignPending || autoAssignAndStartPending || reorderDirty;
  const seg = (key: Segment, label: string, count?: number) => (
    <button
      type="button"
      role="tab"
      aria-selected={segment === key}
      className={segment === key ? "active" : ""}
      onClick={() => onSegment(key)}
    >
      {label}
      {count != null ? <span className="seg-count">{count}</span> : null}
    </button>
  );

  return (
    <div className="task-queue-toolbar">
      <div className="segmented" role="tablist" aria-label="작업 필터">
        {seg("all", "전체")}
        {seg("queued", "예약", counts.queued)}
        {seg("running", "진행", counts.running)}
        {seg("closed", "종료", counts.closed)}
      </div>
      <div className="task-queue-action-zone" aria-label="배치 실행">
        <Button
          variant="secondary"
          disabled={autoDisabled}
          title={reorderDirty ? "우선순위를 저장한 뒤 자동 배정하세요" : "유휴·준비된 로봇에 배정만 합니다(시작 안 함)"}
          onClick={onAutoAssign}
        >
          자동 배정
        </Button>
        <Button
          variant="primary"
          disabled={autoDisabled}
          title={reorderDirty ? "우선순위를 저장한 뒤 자동 배정하세요" : "자동 배정 후 미션 시작까지 수행합니다"}
          onClick={onAutoAssignAndStart}
        >
          ▶ 배정·시작
        </Button>
      </div>
    </div>
  );
}

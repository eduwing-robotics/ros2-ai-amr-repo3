import { Outlet, useNavigate } from "react-router-dom";
import { routePath, type ModeDef } from "../app/menus";
const CONTEXT: Record<string, { eyebrow: string; title: string; description: string; checks: string[]; glyph: string }> = {
  "admin/map": { eyebrow: "공간 모델", title: "맵 & 구역", description: "로봇이 이해하는 이동 공간과 작업 지점을 정의합니다.", checks: ["활성 맵과 좌표계", "입·출고 존과 방향", "Dock–Scan 연결"], glyph: "◇" },
  "admin/warehouse": { eyebrow: "물류 마스터", title: "창고 데이터", description: "입출고 계획이 참조하는 품목, 슬롯, 재고를 관리합니다.", checks: ["품목 식별자", "슬롯 사용 상태", "가용 재고 정합성"], glyph: "▦" },
  "admin/devices": { eyebrow: "설비 구성", title: "로봇 & 카메라", description: "운용 대상 장치와 영상 소스를 등록하고 연결 상태를 점검합니다.", checks: ["로봇 운용 여부", "카메라 귀속", "Movement 연결 점검"], glyph: "⬡" },
  "admin/system": { eyebrow: "플랫폼 진단", title: "시스템", description: "서비스 연결과 운영 데이터 저장 상태를 진단합니다.", checks: ["Main 연결", "Movement 모드", "DB 테이블 상태"], glyph: "⚙" },
  "records/events": { eyebrow: "감사 추적", title: "기록", description: "작업·장치 이벤트와 통신·변경 이력을 시간순으로 확인합니다.", checks: ["위험 이벤트", "작업·재고 이력", "통신 기록"], glyph: "≡" },
};
export function AdminShell({ mode, currentRoute }: { mode: ModeDef; currentRoute: string }) {
  const navigate = useNavigate();
  const active = mode.items.find((item) => item.route === currentRoute || item.route.startsWith(currentRoute)) ?? mode.items[0];
  const context = CONTEXT[active.route] ?? CONTEXT["admin/system"];
  return <div className="admin-shell">
    <nav className="admin-activity-rail app-activity-rail" aria-label="관리 영역"><div className="admin-rail-header"><div className="admin-rail-mark app-activity-mark" aria-hidden="true">AMR</div><div><strong>관리</strong><span>설정 및 이력</span></div></div><div className="admin-rail-destinations">{mode.items.map((item) => {
      const selected = item.key === active.key; const itemContext = CONTEXT[item.route] ?? CONTEXT["admin/system"];
      return <button key={item.key} type="button" className={`app-activity-item${selected ? " active" : ""}`} aria-current={selected ? "page" : undefined} aria-label={item.label} title={item.label} onClick={() => navigate(routePath(item.route))}><span className="admin-rail-glyph" aria-hidden="true">{itemContext.glyph}</span><span className="admin-rail-copy"><strong>{item.label}</strong><small>{itemContext.eyebrow}</small></span></button>;
    })}</div></nav>
    <aside className="admin-context-pane" aria-label={`${context.title} 안내`}><div className="admin-context-head"><span className="admin-context-eyebrow">{context.eyebrow}</span><h1>{context.title}</h1><p>{context.description}</p></div><section className="admin-context-section"><h2>관리 구성</h2><ol>{context.checks.map((check, index) => <li key={check}><span>{index + 1}</span>{check}</li>)}</ol></section><div className="admin-context-note"><strong>변경 원칙</strong><p>조회로 상태를 확인한 뒤 선택한 대상만 수정하고, 삭제는 별도 확인을 거칩니다.</p></div></aside>
    <main className="admin-workbench"><Outlet /></main>
  </div>;
}

# Color Policy — Adobe Industrial Signal

상태: Active
주 독자: Frontend 개발자·UI 디자이너
보조 독자: QA
난이도: 개발
소유: Frontend
최종 갱신: 2026-07-16 16:00 KST
구현 기준: statusTone과 공통 상태 CSS 토큰
목적: 운영·관리 화면의 상태 의미와 색상 적용 규칙을 정의한다.

## Reference

Selected Adobe Color custom palette:

- Blue: `#0673B9`
- Cyan: `#27BBD8`
- Teal: `#08A399`
- Yellow: `#F7D000`
- Orange: `#E84314`

Source: https://color.adobe.com/es/create/color-wheel?base=2&copy=true&mode=rgb&name=Copia+de+Sin+t%C3%ADtulo-4Mesa+de+trabajo+1&rgbvalues=0.023529411764705882%2C0.45098039215686275%2C0.7254901960784313%2C0.15294117647058825%2C0.7333333333333333%2C0.8470588235294118%2C0.03137254901960784%2C0.6392156862745098%2C0.9686274509803922%2C0.8156862745098039%2C0%2C0.9098039215686274%2C0.2627450980392157%2C0.0784313725490196&rule=Custom&selected=3&swatchOrder=0%2C1%2C2%2C3%2C4

Adobe Color recommends structured harmony and contrast checking. Normal text targets WCAG AA 4.5:1; palette colors are darkened where white text or small semantic text requires it.

## Semantic mapping

| Role | Palette basis | UI use |
|---|---|---|
| Operator / running | Blue | selected destination, primary action, active task step |
| Information | Cyan | passive information, transport details |
| Admin / healthy | Teal | admin selection, connected/healthy state |
| Warning | Yellow | stale, delayed, pending, operator confirmation |
| Danger | Orange | failure, E-STOP, destructive action |
| Neutral | blue-teal tinted gray | surfaces, borders, inactive controls |

## Safety rules

1. Brand accent never communicates danger.
2. Normal state stays neutral unless a health distinction is operationally necessary.
3. Warning and danger always include text plus icon/dot and a border or inset edge.
4. Danger uses a darkened orange derivative for white-text buttons; raw palette orange is reserved as a source hue.
5. Acknowledged events remain in the timeline but lose elevated emphasis.
6. Light and dark themes preserve the same role mapping.
7. Focus rings remain visible and use the active mode color; destructive controls use a danger focus ring.
8. 상태 색은 모든 화면이 `statusTone()`과 `--status-<tone>-*` 토큰을 사용한다. 작업 기록·하단 타임라인·
   사이드 작업 기록에서 상태 코드를 별도 색으로 재정의하지 않는다.
9. ESTOP 활성은 danger, 정지/해제 미확인은 warning, 단순 offline은 연결 상태 danger로 표현하며 의미를
   하나의 전역 ESTOP 상태로 합치지 않는다.

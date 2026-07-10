# Source provenance

이 문서는 import 기준 commit만 기록한다. 구현·검증 상태는 [현재 상태 진단](current-state-diagnosis.md)을 따른다.

| root path | upstream source | import baseline commit |
| --- | --- | --- |
| `main-server/` | `origin/main-server:main_server/` | `d6e342fff05abdd341316e604e72fb824117fc61` |
| `nav-server/` | `origin/nav_server:Nav-server/` | `1547308df493f1005f11b59895d4f34c8198ff64` |
| `ai-server/` | integration repository tree | branch-existing state |

이 commit은 import provenance의 기준점이며 current implementation 동치를 보장하지 않는다. baseline과 tree 차이는 다음 명령으로 확인한다.

```bash
git diff --stat d6e342fff05abdd341316e604e72fb824117fc61 -- main-server
git diff --stat 1547308df493f1005f11b59895d4f34c8198ff64 -- nav-server
git status --short
```

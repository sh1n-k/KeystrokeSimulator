# Midnight 로테이션 보조 · KeySim 연동 — 세션 핸드오프

**목적:** 다른 세션/에이전트가 이 논의를 이어서 설계·구현할 수 있도록 맥락·결정·자료 위치를 고정한다.  
**작성 기준일:** 2026-08-03  
**관련 앱:** KeystrokeSimulator (`~/Projects/KeystrokeSimulator`)  
**SimC 스냅샷:** `~/Projects/simc-apl-research/`

---

## 1. 문제 정의

- WoW Midnight에서 **Hekili류 독립 로테이션 엔진 애드온**이 API/정책으로 사실상 불가.
- Blizzard 공식 대체: **Assisted Highlight / `C_AssistedCombat` / Single-Button Assistant(SBA)**.
- **이 앱(KeySim) 사용 시 SBA는 고려 대상 아님** (GCD 페널티; 실제 스킬 키만 입력).
- KeySim 자체(화면 매칭 → 키)는 동작 가능. 병목은 **추천 신호 품질(판단 계층)** 이다.

### 사용자가 원하는 최종 그림

```
[전용 Addon]  상태를 고정 좌표 순색 박스로 표시 (계산 엔진 아님, 센서 패널)
      ↓ 화면
[KeySim]      색 감지 → 외부 이산 규칙 → 키 입력
[필러 소스]   C_AssistedCombat / Assisted Highlight (어시스트 추천)
[큰 CD]       사용자 수동 타이밍 (자동화하지 않음; 아래 §6)
```

Hekili **전면 대체**가 아니라, 어시스트 필러 + 제한된 예외 보완.

---

## 2. 핵심 기술 제약 (애드온 API)

- **Secret Values:** 전투 상태(오라 등)를 화면에 **그릴 수는** 있어도, Lua에서 값을 읽어 `if spellId == …` 식 **분기는 크게 제한**.
- 정확한 표현:
  - ❌ “버프/proc을 API로 전혀 못 읽는다”
  - ✅ “표시는 되고, **판단용으로 자유롭게 읽어 계산**하는 것은 막힌다”
- 따라서 애드온 역할 = **표시 가능 상태를 색 채널로 재전송**.  
  애드온이 full APL을 계산해 색을 고르는 미니 Hekili는 비현실.

### 외부로 판단을 옮기기

| 경로 | 평가 |
| --- | --- |
| **A. 화면 비전 + 색 박스** | 이 프로젝트에 가장 합리적 (OCR/메모리 대비) |
| B. OCR | 틱 비용·불안정 → 비추 |
| C. 메모리 읽기 | 성능↑, ToS/탐지 리스크↑ → 비추 |

데이터 수집이 핵심이며, **순색 박스 = 저비용·고신뢰 수집 버스**.

---

## 3. 합의된 아키텍처

### 3.1 계층

| 계층 | 담당 |
| --- | --- |
| 필러 | Blizzard Assisted Combat (`GetNextCastSpell` / Highlight / assisted APL) |
| 예외 신호 | 애드온 색 슬롯 (표시 가능한 buff.up, ready 등) |
| 판단·입력 | KeySim (색→키, group/priority) |
| 큰 CD 타이밍 | **사람** (자동 입력 금지) |

### 3.2 색 슬롯 프로토콜 (초안)

| 슬롯 | 의미 | KeySim |
| --- | --- | --- |
| **F** | Assist next (스킬↔팔레트 색 또는 필러 활성) | 입력 |
| **W** | 메이저 **버프 up** (사용자가 CD를 쓴 뒤 윈도우) | 입력 우선 레이어 조건 |
| **R** | 메이저 CD **ready** | **입력 안 함** (사람 눈/알림만) |
| **K** | 킥 등 긴급 (정책상 원할 때만) | 입력 가능 |
| 예비 | 스펙별 proc 등 | 표시 가능할 때만 |

**ready와 up 슬롯을 반드시 분리.** ready를 입력에 묶으면 CD 자동화가 된다.

### 3.3 KeySim 프로필 원칙

- `match_mode`: pixel(순색) 우선; exact color (tolerance 없음 → 불투명 순색·고정 UI).
- `group_id` + 낮은 `priority` = 상호 배타.
- `execute_action=False`: 조건 전용 이벤트.
- 기존 **runtime toggle** 은 “연습용 burst 모드” 등 예외 전환에만.

---

## 4. CD 운용 (확정에 가까운 권장)

**CD 키 자체는 KeySim 프로필에 넣지 않는다.**

권장 조합:

1. **필러만 자동** (Assist 색).
2. **CD는 사용자 타이밍에 수동**.
3. (선택) ready 색/아이콘 **표시만**.
4. (선택) 사용자가 CD를 눌러 buff.up 되면 **윈도우 스킬만** 필러보다 고우선 자동.

비추: CD ready 색 → 자동 입력.

---

## 5. SimC APL 조사 결과

### 5.1 자료 위치

```
~/Projects/simc-apl-research/
  SOURCE.txt                 # midnight 커밋·fetch 시각
  default/*.simc             # SimC 최적 APL
  assisted_combat/*.simc     # 게임 Assist APL
  notes/INVENTORY.md         # 파일 목록 (이번 스냅샷)
  README.md
  # 이전 세션 분석 노트(apl_metrics.csv, SELECTION_REPORT.md,
  # FINAL_CONCLUSION_KO.md)는 이 머신에 원본 없음 → 필요 시 재생성
```

- 소스: `https://github.com/simulationcraft/simc` branch **`midnight`**
- `ActionPriorityLists/{default,assisted_combat}`
- assisted 파일 공통: Assist 본문 + SimC가 붙인 `cooldowns` (주석: 일부 쿨은 Assist가 안 씀)

### 5.2 선정 방법

“사람 체감 단순함”이 아니라:

1. Assist 천장 (참고: Wowhead 11.2 Highlight ST 손실 %)
2. default APL 복잡도 (remains / target_if / variable / dot)
3. assisted 리스트 단순성
4. default↔assisted 갭이 **색(이산 플래그)로 메워지는 종류인지**

### 5.3 스펙 분류 (이 아키텍처 전용)

#### S — Top 3 (구현 1순위)

| 순위 | 스펙 | 요지 |
| --- | --- | --- |
| 1 | **Retribution** | default/assisted 짧음, HoL/AW 등 buff.up 분기, 색 채널 최적 |
| 2 | **Fury** | assisted 매우 짧음 (enrage→rampage 골격), CD+윈도우 보완 |
| 3 | **Shadow** | Assist 천장 최상위권; **ST/레이드 한정** (쐐기 멀티닷은 약함) |

#### A — 2순위

| 스펙 | 요지 |
| --- | --- |
| **Arms** | Assist 짧음, default 무거움 → Assist+수동CD 용 |
| **Destruction** | Highlight 표상 최상위이나 **default는 고복잡도**(refresh 수식·variable). full SimC 복제 금지, Assist+CD 안정형 |
| **Demonology** | 중간 |
| **Marksmanship** | ST 흐름; 스왑 약함 |

#### B — 후순위 / 대조

BM, Frost DK, UH, Frost Mage, Balance, **Devastation**, Fire, Ele, Enhance(Totemic), Surv, **Aug**(특수)

#### C — 비추

WW, Havoc, Feral, Arcane, Outlaw, Sub, Assa, Aff, Enhance(Stormbringer)

#### 역할 제외

힐 전부, 탱 **본업** (Assist가 힐/생존 핵심 미포함)

### 5.4 “쉬운 클래스” 오해 정리

| 스펙 | 인식 | 실제 (이 구조) |
| --- | --- | --- |
| **BM** | 버튼 적어 최적 | default에 BW **패킹**, assisted는 평탄 → **S 아님** |
| **Destro** | SimC도 단순 | default **복잡**; Assist 천장은 높을 수 있음 → **A, 목표=Assist+CD** |
| **Deva** | 단순 | empower 단계·DoT·DR 정렬 → 색으로 메우기 어려움 → **B** |
| **Aug** | 단순 지원 | 가치=**아군 버프 분배·팀 쿨**; 개인 색 채널과 목표 불일치 → **B/특수** |
| **Frost DK** | Highlight 표 좋음 | default hard 높음 → B/3순위 |

### 5.5 이전 추정 vs APL 확인 후

| 이전 | 확인 후 |
| --- | --- |
| Destro SimC 단순 | default 고복잡도 |
| Frost DK = S | 하향 |
| Arms/Fury 동급 | Fury assisted가 구현에 더 유리 |
| Ret 상위 | 유지·최우선 |
| BM = A 정도 | 패킹 갭 확인, 1순위 제외 |

---

## 6. 구현 로드맵 (합의된 순서)

1. **전용 애드온 스펙**  
   - 고정 그리드 순색 슬롯 (F/W/R/K)  
   - Assist next → F  
   - ready/up 분리  
   - 표시 경로만 (스마트 APL 계산 금지)
2. **KeySim 프로필 — Ret 프로토타입**  
   - F 필러만 입력  
   - CD 키 없음  
   - (선택) W 윈도우 우선 스킬  
   - R은 execute_action=false 또는 미매핑
3. **Fury** 동일 패턴 복제  
4. **Shadow ST** (레이드)  
5. 필요 시 A티어 (Arms / Destro CD 표시만 등)  
6. BM은 대조 측정용

### 성공 정의

- Real: 좋은 Assist 스펙에서 필러 안정 + CD 수동 타이밍 유지 + (선택) 윈도우 밀도  
- Unreal: 색만으로 SimC default 전체 / Hekili급 전스펙

---

## 7. KeySim 구현 메모 (코드 사실)

- Canonical: `app/*` only.
- 매칭: `pixel` / `region`, **exact color** (tolerance 없음) → 순색·고정 스케일 필수.
- 조건 체인, `group_id`, `priority`, `invert_match`, `execute_action`, runtime toggle 존재.
- 검증: `uv run -m scripts.verify`
- 상세 모듈 경계: `docs/maintainer-reference.md`

---

## 8. 다음 세션에서 바로 할 일 (제안 프롬프트)

새 세션 시작 시 예:

> `docs/midnight-rotation-handoff.md` 와 `~/PersonalProjects/simc-apl-research/notes/SELECTION_REPORT.md` 를 읽고,  
> Ret 전용: (1) 색 슬롯 팔레트·스킬 매핑 표 (2) 애드온 최소 설계 (3) KeySim 프로필 이벤트 초안  
> 을 작성해라. 큰 CD 키는 자동화하지 마라.

또는 애드온만:

> 핸드오프 §3 프로토콜대로 Midnight 호환 **표시 전용** 색 박스 애드온 최소 구현안(파일 구조·슬롯·Assist 연동)을 작성해라. secret 분기 APL은 넣지 마라.

---

## 9. 관련 문서 인덱스

| 경로 | 내용 |
| --- | --- |
| `docs/midnight-rotation-handoff.md` | **이 파일** (세션 핸드오프) |
| `docs/bm-hunter-rotation-rules.md` | 야수 사냥꾼 확정 규칙 (스펙별 문서) |
| `~/Projects/simc-apl-research/README.md` | SimC 스냅샷 안내 |
| `~/Projects/simc-apl-research/SOURCE.txt` | midnight 커밋·fetch 메타 |
| `~/Projects/simc-apl-research/notes/INVENTORY.md` | default/assisted 파일 목록 |
| `.../notes/FINAL_CONCLUSION_KO.md` 등 | 이전 분석 노트 — 미포함, 재생성 대상 |
| `docs/maintainer-reference.md` | KeySim 모듈 경계 |

---

## 10. 비범위 / 주의

- 메모리 해킹·패킷·ToS 고위험 외부 봇 설계는 이 문서 범위 밖.
- SBA 버튼 연타 자동화는 의도적으로 제외.
- Wowhead Highlight %는 **참고 천장**이지 SimC 재측정치가 아님; 순위 골격은 midnight APL 구조 분석과 일치 방향으로 사용.
- 패치 후 `simc-apl-research` 를 `midnight` 브랜치에서 다시 fetch 하면 선정 재검증 필요.

---

*이 문서는 2026-08-03 KeySim × Midnight 로테이션 논의 세션의 연속성을 위해 작성되었다.*

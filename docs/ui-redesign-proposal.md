# Keystroke Simulator UI 전면 개편 제안서

> 본 문서는 **기능 변경 없는 시각/구조 전면 개편안**이다. 코드 로직, 라우팅(모달 호출 흐름), 데이터 구조, API 계약, 상태 관리는 변경하지 않는다. **단, 사용자가 마주하는 시각 정체성·정보 아키텍처·컴포넌트 어휘는 기존과 명백히 다른 새 시스템으로 교체**한다. "기존 위젯의 색만 바꾸는" 개선이 아니다.

---

## 0. 한눈에 보는 변화 (Before → After)

| 축 | 현재(Before) | 개편(After) |
|---|---|---|
| **시각 정체성** | 시스템 기본 흰 배경 + 베이지(sort) + 파스텔(graph)의 혼합 톤 | **단일 "잉크 워크스테이션" 톤** (종이 베이스 + 잉크 텍스트 + 시그널 액센트 1색) |
| **정보 아키텍처** | 메인 윈도우 + 다중 모달 다이얼로그가 떠다님(Edit→Editor→Group→Sort) | **각 윈도우 내부가 "사이드 네비 + 워크스페이스 + 인스펙터" 3-단 IDE 패러다임** |
| **이벤트 편집기** | 3-탭 Notebook(기본/상세/조건) | **좌측 스텝 네비 + 우측 단일 캔버스**(탭 없음, 진행 단계가 항상 보임) |
| **이벤트 리스트** | 8개 컬럼 1행 + 폭 잘림 | **2-라인 셀 리스트**(제목 줄 + 메타 칩 줄) |
| **메인 윈도우** | 5개 수직 프레임 동일 비중 | **상단 컨텍스트 바 + 좌측 NavRail + 본문 + 하단 실행 도크** |
| **그래프** | 별도 모달의 정적 PNG | 시각 톤이 메인과 통합된 **워크스페이스 뷰**(호출 흐름은 그대로 모달) |
| **상태 표현** | 색(배경) 단일 축, 텍스트 4단 | **색 + 아이콘 + 라벨 3-축 StatusPill** |
| **타이포그래피** | 시스템 기본만 | **5단 위계 + 한글/영문/모노 폴백 체인 일원화** |
| **저장 피드백** | 정적 배지 | **하단 도크의 토스트 + 자동 페이드** |
| **모달 호출 흐름** | 변경 없음 | 변경 없음 (라우팅 비변경 원칙) |
| **데이터·로직** | 변경 없음 | 변경 없음 (`app/core/*`, `app/storage/*`, JSON 포맷 그대로) |

---

## 1. 비전 — "산만한 도구"에서 "전문가용 워크스테이션"으로

Keystroke Simulator는 픽셀·영역·조건 체인·그룹 우선순위·독립 스레드 같은 **고밀도 도메인 개념**을 다루는 정밀 도구다. 그러나 현재 UI는 일반적인 Tkinter 데스크톱 도구 — 흰 배경 + 시스템 기본 폰트 + 산재한 모달 — 의 인상을 준다. 도구의 정밀함과 시각 정체성이 어긋난다.

개편의 핵심 약속:
1. **한 가지 시각 언어**로 모든 윈도우(메인·Edit Profile·Event Editor·Quick·Settings·ModKeys·Importer·Sort·Graph)를 통일한다.
2. **워크플로 자체를 시각화**한다 — 진행 단계, 상태, 의존성이 텍스트가 아닌 구조로 보이게 한다.
3. **모달 카오스를 제거**한다 — 모달 호출 흐름은 코드 레벨에서 그대로지만, 각 모달 내부가 **자족적인 워크스페이스**여서 사용자가 "또 다른 창" 대신 "다른 작업 공간"으로 느낀다.
4. **저시력/색맹 사용자 배려** — 상태를 색 단일 축으로 표시하는 곳을 모두 제거하고 색+아이콘+라벨의 3-축으로 옮긴다.

---

## 2. 디자인 시스템 — 잉크 워크스테이션 (Ink Workstation)

본 개편의 시각 정체성. 한 줄 요약: **따뜻한 종이 톤 위에 잉크 텍스트 + 시그널 그린 액센트 1색**. 기존의 분산된 톤(흰 + 베이지 + 파스텔)을 모두 흡수해 일관된 단일 시스템으로 교체.

### 2.1 색상 토큰 (디폴트: Light Workstation)

새로 정의되는 디자인 토큰. 기존 상수(`STATUS_BG_*`, `BADGE_BG_*`, `SW_BG_*`, `event_graph` RGB)는 deprecate하고 토큰 alias로 단계 교체.

#### 표면 (Surface)
| 토큰 | hex | 용도 |
|---|---|---|
| `surface.paper` | `#FAF7F2` | 메인 배경(기존 베이지 톤을 베이스로 흡수) |
| `surface.panel` | `#F4F0E8` | 좌측 NavRail / 사이드 패널 |
| `surface.canvas` | `#FFFFFF` | 작업 영역(이미지 미리보기, 이벤트 리스트, 캔버스) |
| `surface.sunken` | `#EEE9DD` | 입력 필드 배경 / 비활성 영역 |
| `surface.divider` | `#D9D2C1` | 1px 디바이더 |

#### 잉크 (Ink, 텍스트/아이콘)
| 토큰 | hex | 용도 |
|---|---|---|
| `ink.primary` | `#1A1816` | 본문, 제목 |
| `ink.secondary` | `#4A463E` | 보조 텍스트 |
| `ink.muted` | `#8A8474` | 캡션, 힌트 |
| `ink.inverse` | `#FAF7F2` | 액센트 버튼 위 텍스트 |

#### 시그널 (Signal, 액센트 단일)
| 토큰 | hex | 용도 |
|---|---|---|
| `signal.base` | `#2A6B4A` | 주 액션(Start, Save), 선택 상태 |
| `signal.hover` | `#225A3D` | 호버 |
| `signal.tint` | `#E3EFE7` | 액센트의 옅은 배경 |

#### 상태 (Status — 3축 시각화 + 라벨)
색은 채도를 낮춰 통일감을 유지. 각 상태에는 **아이콘이 반드시 동반**.
| 토큰 | bg / fg | 아이콘 | 의미 |
|---|---|---|---|
| `status.ready` | `#E6F0E4` / `#1F4A2E` | ● | 준비됨 |
| `status.running` | `#FFF1D6` / `#7A5500` | ▶ | 실행 중 |
| `status.warn` | `#FFE9CC` / `#7A4500` | ⚠ | 주의 |
| `status.error` | `#F7DAD4` / `#7A2820` | ✕ | 오류 |
| `status.info` | `#E5EAF2` / `#1F3760` | ⓘ | 정보 |
| `status.disabled` | `#EAE5D8` / `#8A8474` | – | 비활성 |

#### 의미 색 (Semantic)
| 토큰 | hex | 용도 |
|---|---|---|
| `cond.active` | `#2A6B4A` (signal.base) | 조건 활성 필요 |
| `cond.inactive` | `#7A2820` | 조건 비활성 필요 |
| `cond.ignore` | `#8A8474` (ink.muted) | 무시 |
| `danger.base` | `#A33627` | 삭제, 초기화 |

#### 옵션: Dark Console (대안)
사용자가 다크 톤을 선호할 경우 동일한 의미 매핑으로 다크 팔레트 정의 가능. 본 제안은 디폴트로 Light Workstation을 채택하고, 다크 모드는 Phase 4 옵션으로 분리 (Tkinter 네이티브 ttk 테마 호환성 사전 검증 필요).

### 2.2 타이포그래피 — 5단 위계

| 단계 | 폰트 패밀리 | 크기(pt) | 용도 |
|---|---|---|---|
| `type.display` | sans bold | 18 | 윈도우 헤더, 큰 상태 라벨 |
| `type.heading` | sans semibold | 14 | 패널 헤더, 인스펙터 섹션 |
| `type.body` | sans regular | 12 | 본문, 입력 필드 |
| `type.caption` | sans regular | 11 | 보조/힌트 |
| `type.mono` | monospace | 12 | 키, 좌표, 우선순위 숫자 |

**폴백 체인** (현재 `event_graph.py:1171-1174`에서만 macOS 한글 폴백 사용 → 전체로 확대):
- 한글: AppleSDGothicNeo → AppleGothic → Malgun Gothic → Noto Sans CJK KR → 시스템 기본
- 영문: SF Pro → Segoe UI → 시스템 기본
- 모노: Menlo → Consolas → Courier New

폰트 객체는 `app/ui/theme.py`(신규)에서 한 번 로딩 후 캐싱. `i18n.py`의 `txt`/`dual_text_width` 시그니처는 비변경.

### 2.3 공간 시스템 — 4px 베이스 그리드

`padx`/`pady`는 다음 7단계만 사용. 현재 산재한 5/6/8/10 값을 정리.

| 토큰 | 값 |
|---|---|
| `space.0` | 0 |
| `space.1` | 4 |
| `space.2` | 8 |
| `space.3` | 12 |
| `space.4` | 16 |
| `space.5` | 24 |
| `space.6` | 32 |

### 2.4 형태 (Shape, Tkinter 한계 내)

Tkinter는 라운드/그림자가 네이티브로 어렵다. 다음 규칙으로 시각 위계를 만든다:
- **경계는 톤 차이로** — `surface.paper`(메인) → `surface.panel`(사이드) → `surface.canvas`(작업영역)
- **디바이더는 1px solid** `surface.divider` (`ttk.Separator` 또는 `Frame(height=1, bg=...)`)
- **칩/태그는 패딩 + 배경** (`Frame(bg=signal.tint, padx=8, pady=2)` + Label)
- **포커스 상태는 1px outline** (액센트 색)
- **선택 상태는 좌측 3px 컬러바** (NavRail/리스트 셀)

### 2.5 아이콘 어휘

이모지는 폰트 호환성이 변동적이므로 **유니코드 기호 위주**로 표준화. 기존 사용 이모지(★/⭐/🔁/🔎/💡)는 자리 유지하되 신규 화면은 아래 표를 우선.

| 의미 | 기호 | 비고 |
|---|---|---|
| 즐겨찾기 | ★ | win/mac 공통 (기존 `profile_display.py` 활용) |
| 추가 | ＋ | 전각 |
| 삭제 | ✕ | |
| 복사 | ⎘ | 안 보이는 환경에서는 텍스트 "Copy"로 폴백 |
| 편집 | ✎ | |
| 그래프 | ◇ | (네트워크 의미 추상화) |
| 정렬 | ↕ | |
| 조건 | ◐ | |
| 그룹 | ▣ | |
| 키 | ⌨ | |
| 반전 매칭 | ⇄ | |
| 독립 스레드 | ⚡ | (기존 lightning 의미 유지) |
| 활성/비활성/무시 | ● / ○ / – | 색 + 기호 3축 |

### 2.6 모션·피드백
- 자동 저장 토스트: 페이드 인 200ms → 1200ms 유지 → 페이드 아웃 200ms (`after()` 체이닝, 기존 디바운스 250ms 로직 비변경)
- 포커스 진입: `outline color` 1프레임 전환
- 버튼 누름: 배경 `signal.hover`로 전환

---

## 3. 정보 아키텍처 (IA) — IDE-Like 3단 패러다임

모든 주요 윈도우의 내부를 통일된 **3-단 골격**으로 재구성한다. **모달 호출 흐름(라우팅)은 기존 그대로** 유지하며, 각 모달의 내부 구성만 새 패러다임으로 옮긴다.

### 3.1 보편 골격

```
┌──────────────────────────────────────────────────────────────┐
│  CONTEXT BAR (현재 컨텍스트 · 검색/필터 · 언어 토글)            │
├──────┬──────────────────────────────────────────┬────────────┤
│      │                                          │            │
│ NAV  │           WORKSPACE                      │ INSPECTOR  │
│ RAIL │           (선택된 항목의 작업 영역)         │ (속성 패널) │
│      │                                          │            │
│      │                                          │            │
├──────┴──────────────────────────────────────────┴────────────┤
│  RUN DOCK (상단/하단 어디든 위치, 주 액션 + 상태 토스트)        │
└──────────────────────────────────────────────────────────────┘
```

- **Context Bar**: 윈도우 상단 32~40px. 현재 컨텍스트(예: "프로필: Quick · 12 events"), 검색, 보조 액션.
- **NavRail**: 좌측 56~200px(축소 가능). 윈도우 내부의 섹션 간 이동.
- **Workspace**: 중앙. 선택된 NavRail 항목이 결정하는 콘텐츠.
- **Inspector**: 우측 280~340px. 워크스페이스에서 선택된 항목의 속성. 없으면 숨김.
- **Run Dock**: 하단 56~72px. 주 액션(Start/Stop/Save 등) + 토스트 영역.

이 골격은 **메인 윈도우**에서 가장 완전하게 구현되고, 다른 모달은 필요한 영역만 사용한다 (예: Settings는 NavRail 없이 Workspace + 하단 액션만).

### 3.2 모달 호출 흐름 (비변경)
```
main → KeystrokeProfiles(Toplevel)
     → KeystrokeQuickEventEditor(Toplevel)
     → KeystrokeSettings(Toplevel)
     → ModificationKeysWindow(Toplevel)
     → 그래프 PNG 뷰어

KeystrokeProfiles
     → KeystrokeEventEditor(Toplevel)
     → KeystrokeImportEvents(Toplevel)
     → KeystrokeSortEvents(Toplevel)
     → GroupSelector(Toplevel)
```
이 호출 관계는 그대로다. 변경되는 것은 각 Toplevel의 **내부 시각·구성**.

---

## 4. 화면별 개편안

각 화면에 (A) 와이어프레임, (B) 변화 포인트, (C) 절대 비변경 항목을 명시한다. 와이어프레임은 시각 의도 전달용이며 실제 픽셀과 다를 수 있다.

### 4.1 메인 윈도우 (`simulator_app.py`)

#### 현재 구조
5개 수직 프레임(`status_frame` → `process_frame` → `profile_frame` → `button_frame` → `profile_button_frame`)이 동일한 시각 비중으로 쌓임 (`simulator_app.py:430–488`).

#### 개편 후 와이어프레임
```
┌─────────────────────────────────────────────────────────────────┐
│ KEYSTROKE SIMULATOR              [search…]    [한국어 ▾]  [⌨]    │  ← Context Bar
├─────┬───────────────────────────────────────────────────────────┤
│     │                                                           │
│ ▣   │  ┌── TARGET ─────────────────────────────────────────┐   │
│ Pro │  │ Process:  ▾ Google Chrome                          │   │
│ ces │  │ Profile:  ▾ ⭐ Combat-Build           [Edit]       │   │
│ s   │  └────────────────────────────────────────────────────┘   │
│     │                                                           │
│ ◇   │  ┌── STATE ──────────────────────────────────────────┐   │
│ Pro │  │ ●  READY                                          │   │
│ fil │  │    12 events · 3 groups · 0 conflicts            │   │
│ e   │  │    Press Alt+Shift to start                      │   │
│     │  └────────────────────────────────────────────────────┘   │
│ ⚙   │                                                           │
│ Set │  ┌── QUICK TOOLS ────────────────────────────────────┐   │
│ tin │  │ [Quick Event]  [ModKeys]  [Sort]  [Graph]         │   │
│ gs  │  └────────────────────────────────────────────────────┘   │
│     │                                                           │
├─────┴───────────────────────────────────────────────────────────┤
│                  [▶  S T A R T  (Alt+Shift)]      Clear Logs    │  ← Run Dock
└─────────────────────────────────────────────────────────────────┘
```

#### (B) 변화 포인트
- **좌측 NavRail** 도입(56~80px 폭). 아이콘+라벨(Process/Profile/Settings). NavRail은 메인 윈도우의 본문 카드를 스크롤·전환하는 시각적 인덱스 역할. *호출 흐름 비변경*: 클릭하면 해당 카드로 스크롤되거나 해당 다이얼로그를 연다.
- **Context Bar**(상단): 앱 이름 + 검색 입력(현재 비검색이지만 UI 자리 확보, 검색은 기능 추가가 되므로 *비활성 또는 placeholder 유지*) + 언어 토글 콤보(현재 Settings 안에 있는 것을 상단에 보조 노출).
- **본문 3개 카드**: TARGET(프로세스/프로필 선택), STATE(상태 카드), QUICK TOOLS(보조 도구 진입점). 각 카드는 `surface.canvas` + 8px 내부 여백 + 12px 외부 여백.
- **STATE 카드**: 상단에 큰 StatusPill(아이콘+라벨), 중단에 메트릭(이벤트/그룹/충돌), 하단에 단축키 힌트. 4단 텍스트를 *시각 위계화*된 3행으로 압축.
- **Run Dock**(하단 고정): 큰 PrimaryButton "START" 단독 배치. 보조(Clear Logs)는 우측 작게. 토스트(저장 메시지 등)는 도크 위 라인에 표시.
- **즐겨찾기 표시**: 프로필 콤보 항목 좌측에 ★ 칩 + bold (기존 `profile_display.FAVORITE_PREFIX` 활용).
- **실행 중 상태**: Run Dock 전체 배경이 `status.running`으로 전환, START → STOP 라벨 변경, 좌측에 ▶ 아이콘 회전 또는 정적 강조.

#### (C) 절대 비변경
- `ProcessFrame`/`ProfileFrame`/`ButtonFrame`/`ProfileButtonFrame` 클래스 자체와 시그니처, 인스턴스화 위치 — **클래스 내부 레이아웃만 카드 형태로 재구성**.
- `toggle_start_stop()`, 단축키 처리(Alt+Shift/Option+Shift, 마우스휠 W_UP/W_DN), `_load_settings_and_state`, 자동 저장 로직.
- 다이얼로그 호출 함수(`open_settings`, `open_profile`, `open_quick_events`, `open_modkeys`, `sort_profile_events`) 시그니처.

---

### 4.2 프로필 작업 윈도우 (`profiles.py`)

#### 현재 구조
LabelFrame 스택: 프로필 이름 → Runtime Toggle → 저장 상태 → 이벤트 리스트(8개 컬럼 1행) → 닫기. 모달 안에서 다시 Event Editor 모달을 띄움.

#### 개편 후 와이어프레임
```
┌────────────────────────────────────────────────────────────────────┐
│  Combat-Build  ★         12 events · 3 groups            [✕ Close] │  ← Context Bar
├──────────┬─────────────────────────────────────────────┬───────────┤
│          │  EVENTS                          [＋ Add ▾] │ DETAILS   │
│  FILTER  │  ─────────────────────────────────────────  │ ─────────│
│ ────────│  ┌─────────────────────────────────────────┐│ ◯ Boss-HP │
│ ☑ Active│  │ 01  ●  Boss-HP                         ✎││   ─────── │
│ ☑ Grouped│ │     ▣ Combat  ⌨ Q    ◐ active req      ││ Name      │
│ ☐ Cond.  │ └─────────────────────────────────────────┘│ [______]  │
│  only   │  ┌─────────────────────────────────────────┐│           │
│          │  │ 02  ●  Heal-Potion                     ✎││ Mode      │
│ GROUPS   │  │     ▣ Combat  ⌨ 1    ⇄ inverted        ││ ⦿ Pixel   │
│ ────────│  └─────────────────────────────────────────┘│ ○ Region  │
│ • Combat│  ┌─────────────────────────────────────────┐│           │
│ • Buff  │  │ 03  ○  Watch-Boss      (condition only) ✎││ Group     │
│ • —     │  │     ◐ no key            ⚡ standalone   ││ Combat ▾  │
│          │  └─────────────────────────────────────────┘│ Priority  │
│ ACTIONS  │   …                                         │ [0    ]   │
│ ────────│                                             │           │
│ [Import]│                                             │ Conditions│
│ [Sort]  │                                             │ ● Boss-HP │
│ [Graph] │                                             │ ○ Heal    │
│          │                                             │ – …       │
├──────────┴─────────────────────────────────────────────┴───────────┤
│                                            Auto-saved · just now   │  ← Run Dock
└────────────────────────────────────────────────────────────────────┘
```

#### (B) 변화 포인트
- **좌측 NavRail(FILTER / GROUPS / ACTIONS)**: 필터 체크박스, 그룹 목록(클릭 시 해당 그룹 이벤트만 본문에 표시), 액션 진입(Import/Sort/Graph). *필터·그룹 클릭은 시각적 강조만 변경이고 데이터 흐름은 그대로*; "그룹별 필터링"이 기능 추가가 된다면 NavRail에서 클릭 동작은 단순 스크롤로 대체할 수 있음 → 본 제안에서는 **시각 자리 확보만** 하고 동작은 기존 데이터를 활용하는 범위로 한정.
- **이벤트 리스트 = 2-라인 셀**:
  - 1행: 인덱스 · StatusDot(활성/비활성) · 이벤트 이름 · 편집 버튼
  - 2행(메타 칩): 그룹 칩 · 키 칩 · 조건 요약 칩 · 반전 매칭 칩 · 독립 스레드 칩
  - 셀 좌측에 3px 컬러바: 상태에 따라 `signal.base`(활성)/`ink.muted`(조건 전용)
  - 셀 호버: `surface.sunken`로 배경 전환
  - 셀 선택: 우측 인스펙터에 즉시 반영(*기존 Event Editor 모달 호출은 ✎ 버튼으로만*; 셀 클릭은 인스펙터 표시만)
- **우측 Inspector**: 선택 셀의 속성 요약을 읽기 전용으로 미리보기. 편집은 기존 Event Editor 모달을 호출하는 ✎ 버튼.
  - *인스펙터를 인라인 편집기로 만들면 라우팅 변경이 되므로 본 제안에서는 "프리뷰만"으로 한정*.
- **Run Dock**: 저장 상태 토스트("Auto-saved · just now"). 변경 중 → "Saving…", 실패 → 빨간 토스트.
- **Context Bar**: 현재 프로필 이름 + ★(즐겨찾기 토글) + 메트릭 + 닫기.
- **빈 상태**: 본문 중앙에 EmptyState 카드(아이콘 + 한 줄 안내 + "＋ Add Event" PrimaryButton).

#### (C) 절대 비변경
- 자동 저장 디바운스 250ms (`_schedule_autosave`, `profiles.py:2015`), `_profile_fingerprint`(profiles.py:76).
- `EventRow`의 변수 이름이 곧 GUI 테스트와 결합돼 있을 가능성 — 신규 셀 위젯을 **새 클래스(`EventCell`)로 분리**하고 `EventRow`는 점진 교체. 기존 호출부 영향 최소화.
- Event Editor / Importer / Sort / Graph / GroupSelector 호출 시그니처.
- JSON 직렬화 키, `held_screenshot`만 저장하는 규칙(`profile_storage.py:165–215`).

---

### 4.3 이벤트 편집기 (`event_editor.py`) — **Notebook → Stepper**

#### 현재 구조
`ttk.Notebook`에 3-탭(`tab_basic`, `tab_detail`, `tab_logic`, `event_editor.py:104–117`). 사용자는 좌→우 순서로 진행하지만 진행 안내는 탭 1에만 있다.

#### 개편 후: 좌측 Stepper + 우측 단일 캔버스
```
┌────────────────────────────────────────────────────────────────────┐
│  Edit Event: Boss-HP                                  [Save] [✕]   │  ← Context Bar
├──────────────────┬─────────────────────────────────────────────────┤
│                  │                                                 │
│  ① BASIC         │   ── BASIC ───────────────────────────────      │
│    ─────────     │                                                 │
│    Name           │   Name                                         │
│    Capture        │   ┌──────────────────────────────┐              │
│    Key            │   │ Boss-HP                       │              │
│                  │   └──────────────────────────────┘              │
│  ② ADVANCED       │                                                 │
│    Match Mode     │   Live View         Captured                   │
│    Region Size    │   ┌────────────┐    ┌────────────┐              │
│    Timing         │   │            │    │            │              │
│    Standalone     │   │  (red)     │    │  (gray)    │              │
│                  │   │            │    │            │              │
│  ③ LOGIC          │   └────────────┘    └────────────┘              │
│    Execute Type   │                                                 │
│    Group          │   Ref pixel: [▣]    Capture: 80 × 60            │
│    Conditions     │                                                 │
│                  │   ┌─ HOTKEYS ──────────────────────────┐         │
│  ────────────────│   │ ALT  move pointer · capture region │         │
│  Standalone ⚡    │   │ CTRL hold image                    │         │
│  Inverted  ⇄      │   └────────────────────────────────────┘         │
│  Cond-only ◯      │                                                 │
│                  │   Coordinates                                    │
│                  │   Area X [ ] Y [ ]   Pixel X [ ] Y [ ]          │
│                  │                                                 │
│                  │   Key  [ Q  ▾ ]                                  │
├──────────────────┴─────────────────────────────────────────────────┤
│  Step 1 of 3        ← Back            Next →               [Save]  │  ← Run Dock
└────────────────────────────────────────────────────────────────────┘
```

#### (B) 변화 포인트
- **좌측 Stepper(NavRail 변형)**: 3 단계(BASIC / ADVANCED / LOGIC)와 각 단계 내부의 세부 그룹 목록을 펼친다. 현재 위치는 ●, 완료는 ✓, 미진행은 ○. 클릭으로 점프 가능.
- **우측 단일 캔버스**: 선택 단계의 내용을 통째로 표시. 탭 전환 시 컨텐츠 교체.
- **단계 메타 칩**: NavRail 하단에 현재 이벤트의 핵심 상태(Standalone/Inverted/Cond-only) 칩을 항상 표시 → 어느 단계에 있어도 컨텍스트가 보임.
- **단축키 콜아웃**을 모든 단계에서 우측 상단에 영구 표시(현재는 BASIC 단계에만 있음).
- **이미지 미리보기 확대**: 현재 `width=10, height=5`(event_editor.py:129–131) → 픽셀 단위 라벨로 변경(예: 160×120 또는 캡처 크기에 비례). 두 미리보기에 명확한 라벨("Live"/"Captured").
- **조건 트리(LOGIC)**: 현재 `ttk.Treeview` `height=5`(event_editor.py:480) → `expand=True, fill="both"`로 확장. 행은 3축(컬러 점 + 상태 라벨 + 이벤트명).
  - 컬러 점: ● `cond.active` / ○ `cond.inactive` / – `cond.ignore`
  - 행 배경은 채도 낮춘 `status.*` 톤(현재 `#d4edda`/`#f8d7da` 교체).
- **Save/Back/Next**: Run Dock에 항상 위치. Back/Next는 Stepper 단계 이동, Save는 PrimaryButton.

#### (C) 절대 비변경
- `_setup_basic_tab()`, `_setup_detail_tab()`, `_setup_logic_tab()` 메서드의 호출 순서·내부 데이터 동작.
- 단축키 바인딩(ALT/CTRL), 캡처 콜백.
- `temp_conditions` 사전 구조, `_cycle_condition_state` 로직, `_get_existing_groups` 반환.
- 키 콤보 옵션 목록, 숫자 검증 함수.
- *Notebook을 Stepper로 바꾸는 것은 위젯 트리 변경이지만 "라우팅"이 아니라 "내부 레이아웃" 변경 — 함수 시그니처와 호출 흐름은 유지*.

---

### 4.4 빠른 이벤트 편집기 (`quick_event_editor.py`)

#### 개편 후
```
┌────────────────────────────────────────────────────────────────────┐
│  QUICK ADD                Session: 2 captured today          [✕]   │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│   ① POINT   ② CAPTURE   ③ KEY   ④ SAVE                            │
│   ━━━━━━━━━━━━━━━━━━━━━━○━━━○━━━○                                  │
│                                                                    │
│   Live View                Captured                                │
│   ┌─────────────┐          ┌─────────────┐                         │
│   │             │          │             │                         │
│   │             │          │             │                         │
│   └─────────────┘          └─────────────┘                         │
│                                                                    │
│   Position: X1 [ ] Y1 [ ]   X2 [ ] Y2 [ ]                          │
│   Size:     W  [ ] H  [ ]                                          │
│                                                                    │
│   ┌─ HOW IT WORKS ─────────────────────────┐                       │
│   │ ALT  pointer · CTRL  capture · ESC quit│                       │
│   └─────────────────────────────────────────┘                       │
│                                                                    │
├────────────────────────────────────────────────────────────────────┤
│              [Grab (Ctrl)]                  [Close (ESC)]          │
└────────────────────────────────────────────────────────────────────┘
```

#### (B) 변화 포인트
- 상단에 **4-스텝 게이지**(POINT / CAPTURE / KEY / SAVE)로 진행을 시각화 — 텍스트 단락 안내 대체.
- 이벤트 편집기 BASIC 단계와 **동일한 좌·우 미리보기 레이아웃**. "이 화면은 빠른 버전이지 다른 앱이 아니다"라는 일관성 확보.
- 단축키 콜아웃을 컴팩트한 카드로.
- 두 버튼을 Run Dock에 배치.

#### (C) 비변경
- 단축키 바인딩, 캡처/호출 시그니처, 세션 카운터.

---

### 4.5 설정 (`settings.py`)

#### 개편 후 와이어프레임
```
┌────────────────────────────────────────────────────────────────────┐
│  SETTINGS                                                  [✕]    │
├──────────────────┬─────────────────────────────────────────────────┤
│                  │                                                 │
│  ▶ START / STOP  │   START / STOP                                  │
│    LANGUAGE      │   ─────────────────────                          │
│    TIMING        │   Trigger key  [ A  ▾ ]                          │
│                  │   ☐ Use Alt+Shift                                │
│                  │                                                 │
│                  │   ┌─ NOTE ─────────────────────────────┐        │
│                  │   │ ⚠ macOS requires accessibility...  │        │
│                  │   └─────────────────────────────────────┘        │
│                  │                                                 │
├──────────────────┴─────────────────────────────────────────────────┤
│  [Reset]                                       [Cancel]  [Save]    │
└────────────────────────────────────────────────────────────────────┘
```

#### (B) 변화 포인트
- 좌측 NavRail: START/STOP · LANGUAGE · TIMING 3개 섹션. 현재 grid의 같은 화면에 모두 있는 항목을 카테고리화.
- 우측 Workspace: 선택된 섹션의 입력만 표시. 화면당 정보량 감소.
- 경고 텍스트는 `status.warn` 톤의 카드로 강조.
- Run Dock에 Reset/Cancel/Save의 위계 적용(위험/취소/주).

#### (C) 비변경
- 저장 로직, `_validate_numeric`, 콤보 옵션, 콜백 시그니처.

---

### 4.6 수정키 (`modkeys.py`)

#### 개편 후
```
┌────────────────────────────────────────────────────────────────────┐
│  MODIFIER KEYS — Combat-Build                              [✕]    │
├────────────────────────────────────────────────────────────────────┤
│   ┌─ ⎇ ALT ─────────────────────────────────────────────────┐     │
│   │  ☑ Bound to key  [ A  ▾ ]            ☐ Pass through      │     │
│   └──────────────────────────────────────────────────────────┘     │
│   ┌─ ⌃ CTRL ────────────────────────────────────────────────┐     │
│   │  ☑ Bound to key  [ S  ▾ ]            ☐ Pass through      │     │
│   └──────────────────────────────────────────────────────────┘     │
│   ┌─ ⇧ SHIFT ───────────────────────────────────────────────┐     │
│   │  ☐ Bound to key  [ —  ▾ ] (dimmed)   ☑ Pass through      │     │
│   └──────────────────────────────────────────────────────────┘     │
├────────────────────────────────────────────────────────────────────┤
│                                                       [Save Enter] │
└────────────────────────────────────────────────────────────────────┘
```

#### (B) 변화 포인트
- 각 수정키를 **카드 1개**로 시각 격리. 좌측에 큰 키캡 아이콘(⎇/⌃/⇧).
- Pass through가 켜진 카드는 전체 톤다운 + "Pass through" 칩 강조.
- Save 버튼만 우측 정렬, 보조 안내(유효키 A-Z, 0-9)는 NavRail 또는 카드 푸터에.

#### (C) 비변경
- 키 입력 처리, Pass 토글, 저장 시그니처.

---

### 4.7 이벤트 가져오기 (`event_importer.py`)

#### 개편 후
```
┌────────────────────────────────────────────────────────────────────┐
│  IMPORT EVENTS                                             [✕]    │
├────────────────────────────────────────────────────────────────────┤
│   Source profile: ▾ Backup-2025-03                                 │
│   ─────────────────────────────────────────────────────────────    │
│   [All] [None]                                  3 of 8 selected    │
│                                                                    │
│   ☑ │ 01  ●  Boss-HP                  ⌨ Q                          │
│   ☑ │ 02  ●  Heal-Potion              ⌨ 1                          │
│   ☐ │ 03  ○  Watch-Boss               (no key)                     │
│   ☑ │ 04  ●  Buff-Cycle               ⌨ E                          │
│   ☐ │ 05  ●  Auto-Pickup              ⌨ Z                          │
│    …                                                               │
├────────────────────────────────────────────────────────────────────┤
│                                              [Cancel]  [Import 3]  │
└────────────────────────────────────────────────────────────────────┘
```

#### (B) 변화 포인트
- 행을 **프로필 화면 이벤트 셀과 동일한 시각 어휘**로 — 일관성.
- 호버 시 배경 톤 전환(`surface.sunken`), 체크된 행 좌측 3px 컬러바.
- 선택 카운터를 Run Dock의 버튼 라벨에 동적으로(`Import 3`).
- "All / None" 토글을 텍스트 링크 스타일로 헤더 우측에.

#### (C) 비변경
- `_copy_event`, grab_set/transient, 콜백 시그니처.

---

### 4.8 이벤트 정렬 (`sort_events.py`)

#### 개편 후
```
┌────────────────────────────────────────────────────────────────────┐
│  SORT EVENTS — Combat-Build               drag to reorder   [✕]    │
├────────────────────────────────────────────────────────────────────┤
│   ⋮⋮ │ 01 │ ●  Boss-HP            ▣ Combat   ⌨ Q                  │
│   ⋮⋮ │ 02 │ ●  Heal-Potion        ▣ Combat   ⌨ 1                  │
│   ⋮⋮ │ 03 │ ○  Watch-Boss         ▣ —        (cond only)          │
│   ⋮⋮ │ 04 │ ●  Buff-Cycle         ▣ Buff     ⌨ E                  │
│    …                                                               │
├────────────────────────────────────────────────────────────────────┤
│                                              [Cancel]  [Save]      │
└────────────────────────────────────────────────────────────────────┘
```

#### (B) 변화 포인트
- 좌측에 **명시적 드래그 핸들(⋮⋮)** — 현재는 텍스트 영역 전체가 핫존이라 의도치 않은 드래그 우려. 핸들에서만 cursor=hand2, 다른 영역은 일반.
- 베이지 톤(`SW_BG_*`)을 디자인 토큰으로 흡수해 다른 화면과 통합 정체성.
- 이미지 미리보기는 클릭 시 모달 토스트(중앙 + 큰 크기)로 표시.

#### (C) 비변경
- 드래그 좌표/삽입 위치 계산, 저장 콜백, 윈도우 위치 복원.

---

### 4.9 이벤트 그래프 (`event_graph.py`)

#### 개편 후
- 노드 200×60 형태와 베지어 곡선 골격은 유지(검증된 자산).
- **색 톤 통합**: `EDGE_TRUE` = `cond.active` RGB, `EDGE_FALSE` = `cond.inactive` RGB, `EDGE_UNKNOWN` = `ink.muted` RGB.
- 그룹 PALETTE 8색은 채도를 균일하게 낮춰 메인 톤과 어울리도록(워크스테이션 톤 흡수).
- **범례 카드화**: 우측 범례를 1개 큰 카드 + 3개 섹션(Nodes/Edges/Groups) + 디바이더.
- **Windows 한글 폰트 폴백 추가**(현재 macOS 경로만 — `event_graph.py:1171–1174`): Malgun Gothic 경로 시도.
- **타이틀 바**를 메인 윈도우 톤과 통합(현재는 PIL 캔버스 단독).

#### (C) 비변경
- 레이아웃 알고리즘, PNG 캐싱, 데이터 입력 구조.

---

## 5. 컴포넌트 라이브러리

신규 또는 재구성될 위젯 어휘. 모두 Tkinter 표준 위젯(`tk`/`ttk`) 조합으로 실현 가능.

| 컴포넌트 | 구현 방법(Tkinter) | 용도 |
|---|---|---|
| **NavRail** | `tk.Frame(bg=surface.panel)` + 세로 `tk.Button` 리스트 + 선택 시 좌측 3px 컬러바(`Frame`) | 윈도우 내부 섹션 전환 |
| **ContextBar** | `tk.Frame(bg=surface.panel, height=40)` + 좌·우 정렬된 라벨/콤보 | 윈도우 상단 헤더 |
| **RunDock** | `tk.Frame(bg=surface.paper, height=60)` + 큰 PrimaryButton + 우측 보조 | 주 액션 + 토스트 영역 |
| **PanelCard** | `tk.Frame(bg=surface.canvas)` + `ttk.Separator` 헤더 라인 | 본문 카드 |
| **StatusPill** | `tk.Frame(bg=status.*.bg)` + 아이콘 `Label` + 텍스트 `Label` | 상태 표시 (메인/리스트) |
| **MetricChip** | `tk.Frame(bg=signal.tint or transparent, padx=6, pady=2, bd=1, relief='solid')` + Label | 그룹/키/조건 칩 |
| **EventCell** | `tk.Frame` 2행 grid(상: 인덱스+이름+버튼, 하: 메타 칩 줄) + 좌측 3px 컬러바 | 이벤트 리스트 셀 |
| **InspectorAccordion** | `tk.Frame` + 헤더 `Button`(접힘 토글) + 본문 `Frame`(grid_remove/grid) | 속성 패널 섹션 |
| **Stepper** | NavRail 변형: 각 단계 좌측에 ●/○/✓ 점 + 라벨 + 펼친 하위 항목 | 이벤트 편집기 |
| **PrimaryButton** | `ttk.Style` `Accent.TButton` (bg=signal.base, fg=ink.inverse, font=type.heading) | 주 액션 |
| **SecondaryButton** | `ttk.Style` `Outline.TButton` (bg=surface.canvas, fg=ink.primary, bd=1) | 보조 액션 |
| **DangerButton** | `ttk.Style` `Danger.TButton` (fg=danger.base, 외곽선) | 삭제/초기화 |
| **Toast** | RunDock 내부 `Label`을 `after()` 체이닝으로 페이드 — 또는 그냥 일정 시간 후 텍스트 클리어 | 자동 저장 피드백 |
| **EmptyState** | `tk.Frame` 중앙 정렬 + 큰 아이콘 Label + 안내 Label + CTA PrimaryButton | 빈 리스트 안내 |
| **DragHandle** | `tk.Label(text="⋮⋮", cursor="hand2")` — 드래그 이벤트는 핸들에서만 바인딩 | 정렬 화면 |
| **CalloutBox** | `tk.Frame(bg=status.info.bg, padx, pady)` + 아이콘 + 텍스트 | 단축키 안내 등 영구 콜아웃 |

---

## 6. 화면 골격 일관성 매트릭스

각 윈도우가 사용하는 영역.

| 윈도우 | ContextBar | NavRail | Workspace | Inspector | RunDock |
|---|:---:|:---:|:---:|:---:|:---:|
| Main | ✓ | ✓ | ✓ | – | ✓ (Start) |
| Profiles | ✓ | ✓ | ✓ | ✓ (프리뷰) | ✓ (Toast) |
| Event Editor | ✓ | ✓ (Stepper) | ✓ | – | ✓ (Save) |
| Quick Editor | ✓ | – | ✓ | – | ✓ |
| Settings | ✓ | ✓ | ✓ | – | ✓ |
| ModKeys | ✓ | – | ✓ (카드 3개) | – | ✓ |
| Importer | ✓ | – | ✓ | – | ✓ |
| Sort | ✓ | – | ✓ | – | ✓ |
| Graph | ✓ | – | ✓ (PIL 캔버스) | – | – |

이 매트릭스가 윤곽 일관성을 보장하는 골격이다. 모든 화면이 같은 시각 언어로 묶인다.

---

## 7. 단계별 로드맵

각 Phase는 독립 PR로 머지 가능. 각 단계 끝에는 GUI 수동 확인 + `uv run python run_tests.py -q`.

### Phase 1 — 디자인 시스템 기반 (1~2 PR)
1. `app/ui/theme.py` 신규: 색상·폰트·공간 토큰 정의, 폰트 객체 캐싱.
2. ttk.Style named style 정의(`Accent.TButton`, `Outline.TButton`, `Danger.TButton`, 등).
3. 기존 상수(`STATUS_BG_*`, `BADGE_BG_*`, `SW_BG_*`)를 theme 토큰의 alias로 노출(`STATUS_BG_OK = theme.status.ok.bg`).
4. 폰트 폴백 체인 일원화. macOS 외 Windows 한글 폰트도 폴백 추가.

### Phase 2 — 메인 윈도우 골격 (2 PR)
5. ContextBar + RunDock 구조 도입.
6. STATE 카드(StatusPill + 메트릭)로 4단 라벨 대체.
7. Start 버튼을 PrimaryButton + RunDock에 배치, 실행 중 시각 강조.

### Phase 3 — 프로필 작업 윈도우 (2~3 PR)
8. `EventCell` 컴포넌트 신규 구현(2-라인 셀, 메타 칩).
9. 기존 `EventRow`를 `EventCell` 호출로 점진 교체. 변수 이름 유지로 회귀 최소화.
10. Inspector 패널(읽기 전용 프리뷰) 추가. ✎ 클릭은 기존 Event Editor 모달 유지.
11. 자동 저장 토스트를 RunDock에 표시.

### Phase 4 — 이벤트 편집기 Stepper (2 PR)
12. Notebook → Stepper 위젯으로 교체. 3개 setup 메서드는 그대로 호출하되 부모 위젯만 변경.
13. 이미지 미리보기 픽셀 단위로 확대. 단축키 콜아웃을 영구화.
14. 조건 트리 3-축 시각화(컬러 점 + 라벨 + 행 배경).

### Phase 5 — 보조 윈도우 통일 (3 PR)
15. Quick Editor 4-스텝 게이지.
16. Settings NavRail 3-섹션화.
17. ModKeys 카드 3개 + Pass 강조.
18. Importer 행 시각 통합, 선택 카운터.
19. Sort 드래그 핸들 명시화.

### Phase 6 — 그래프 통합 (1 PR)
20. PIL 색·폰트 폴백을 theme 토큰과 연동.
21. Windows 한글 폰트 폴백 추가.

### Phase 7 — 옵션(미래)
22. Dark Console 테마 활성화 토글 — ttk 테마 호환성 사전 검증 필요.

---

## 8. 구현 시 주의사항

### 8.1 절대 비변경 체크리스트
- `app/core/processor.py`의 `_resolve_effective_states`(processor.py:474), 조건 체인 strict 해석, 그룹 우선순위 규칙.
- `app/core/models.py`의 `EventModel`/`ProfileModel`/`UserSettings` 필드 추가/변경.
- `app/storage/profile_storage.py`의 JSON 키, `held_screenshot`만 저장하는 규칙(profile_storage.py:165–215).
- `app/utils/i18n.py`의 `txt`/`set_language`/`normalize_language`/`dual_text_width` 시그니처.
- `app/utils/runtime_toggle.py`의 정규화/검증.
- 다이얼로그 호출 시그니처(`open_profile`, `open_settings`, `open_modkeys`, `open_quick_events`, `sort_profile_events`, Event Editor / Importer / Sort / GroupSelector 인스턴스화).
- 단축키 바인딩(Alt+Shift, Option+Shift, ALT/CTRL 캡처, W_UP/W_DN).
- `scripts/build_secure.py` hidden import, `main_secure.py` 인증 흐름.
- 자동 저장 디바운스 250ms, `_profile_fingerprint`.

### 8.2 위젯 트리 변경의 범위
"라우팅 변경 금지"의 의미는 다이얼로그 간 호출 흐름. **한 다이얼로그 내부의 위젯 트리 재배치는 허용 범위**. 예: Event Editor의 Notebook을 Stepper로 바꾸는 것은 내부 변경이며, `KeystrokeEventEditor` 클래스 시그니처와 호출자 코드는 그대로다.

### 8.3 Tkinter 실현 가능성
- 라운드 코너/그림자: 네이티브 미지원 → 톤 차이와 디바이더로 위계.
- 폰트 굵기: ttk 테마에 따라 일부 제한 → `tkinter.font.Font(weight="bold")`로 명시.
- ttk vs tk 혼용: 기존 코드와 동일하게 유지. 신규 컴포넌트는 가능하면 `ttk` 우선.
- 픽셀 단위 크기: `width=10`(문자 단위) ≠ 픽셀. 이미지 미리보기는 PhotoImage 픽셀 크기로 컨트롤.
- 메인 스레드 제약(maintainer-reference.md:62): 모든 토스트/페이드는 `widget.after()` 사용.

### 8.4 다국어
- 모든 새 텍스트는 `txt(en, ko)`.
- 너비 영향이 있는 라벨은 `dual_text_width`.
- Stepper 단계명, NavRail 라벨, 상태 라벨, 칩 라벨 — 모두 EN/KO 쌍 작성.

### 8.5 점진 적용
- 화면 클래스 단위로 PR을 나눠 회귀 범위를 좁힘.
- 신규 컴포넌트(`theme.py`, `EventCell`, `Stepper` 등)는 `app/ui/components/`(신규) 하위에 두고 기존 모듈은 import해서 사용 — 루트 모듈 추가 금지 규칙(maintainer-reference.md:44)에 저촉되지 않음.
- 기존 위젯 변수명은 가능한 한 유지(GUI 테스트 잠재 결합).

### 8.6 테스트 영향
- `uv run python run_tests.py -q` (단위/통합)는 기능 비변경이므로 그대로 통과해야 함.
- `tests/test_import_conventions.py`는 루트 레거시 모듈명 회귀를 감지 — 신규 모듈은 `app.*` 하위에 둘 것.
- GUI 테스트는 `RUN_GUI_TESTS=1`로 수동 확인.

---

## 9. 검증 불가 / 미해결 항목

본 제안서는 코드 정적 분석 기반이며, 실제 GUI 렌더 결과 없이 단정할 수 없는 항목:

1. **워크스테이션 톤이 macOS/Windows 네이티브 ttk와 어울리는지** — ttk.Style 테마(`aqua`/`vista`/`clam`)에 따라 위젯 외형이 다르게 보임. 디폴트 테마를 `clam`으로 강제할지 시스템 테마를 그대로 둘지 결정 필요.
2. **NavRail 폭/Stepper 폭**의 적정 픽셀 값 — 한국어 라벨 길이에 따라 다름. 와이어프레임 추정치 56~200px는 실측 필요.
3. **이미지 미리보기 확대 크기** — 캡처 크기가 가변(50~1000)이므로 미리보기 라벨을 비례 표시할지 고정 크기에 letterbox할지 결정 필요.
4. **다크 모드 호환** — Tkinter 네이티브 위젯(특히 Combobox, Spinbox)은 다크 톤에서 어색해질 수 있어 Phase 7 옵션은 사전 검증 후 결정.
5. **PIL 그래프 색 통합** — RGB ↔ hex 변환은 단순하지만 채도 조정이 시각적으로 적절한지는 실제 렌더 확인 필요.
6. **본 문서의 라인 번호 인용** — 코드 변경에 따라 ±수 라인 차이가 있을 수 있음. 색상 상수와 함수 위치는 작성 시점 기준 검증 완료(`STATUS_BG_*` simulator_app.py:64-69, `BADGE_BG_*` profiles.py:32-39, `SW_BG_*` sort_events.py:20-29, Notebook 3-탭 event_editor.py:104-117, 조건 트리 색 event_editor.py:487-489, 자동 저장 디바운스 profiles.py:2015, `_resolve_effective_states` processor.py:474, `held_screenshot` 규칙 profile_storage.py:165-215, macOS 폰트 폴백 event_graph.py:1171-1174, NODE_W=200/NODE_H=60 event_graph.py:23-24).
7. **검색 입력 자리** — 메인 ContextBar의 검색 placeholder는 기능 추가가 되므로 본 제안은 시각 자리만 확보. 활성화는 별도 요건.
8. **NavRail의 그룹 필터 동작** — 프로필 화면 NavRail의 그룹 클릭이 "필터링"으로 해석되면 기능 추가. 본 제안은 "해당 그룹 첫 셀로 스크롤" 정도의 기존 데이터 범위 동작으로 한정 권장. 구현 시 재정의 필요.

---

## 10. 부록 — 변화의 시각적 요약

```
BEFORE                                  AFTER
─────────────────────────                ─────────────────────────────────────────
[ Status text...        ]                ┌─ CONTEXT BAR ──────────────────────────
[ Process: [▾]  Refresh ]                │ KEYSTROKE SIMULATOR  [search] [ko ▾]
[ Profile: [▾]  Cp  Dl  ]                ├─ NAV ─ ┬─ WORKSPACE ─────────────┬───
[ Start  Quick  Set  Lg ]                │ Proc   │ TARGET / STATE / TOOLS  │
[ ModK   Edit   Sort    ]                │ Prof   │                         │
                                          │ Set    │                         │
                                          ├────────┴─────────────────────────┘───
                                          │              [▶ S T A R T]
                                          └──────────────────────────────────────


Edit Profile 모달:                       Profiles 윈도우:
[ Profile name [    ]   ]                ┌─ Combat-Build ★ · 12 events ─────[✕]
[ Runtime toggle...     ]                ├─ FILTER ──┬─ EVENTS ────[＋ Add ▾]──
[ Save: ok              ]                │ Active   │ ┌────────────────────┐ │
[ Add Event Graph Sort  ]                │ Grouped  │ │ 01 ● Boss-HP     ✎ │ │
[ [Header columns]      ]                │ Cond-only│ │   ▣Combat ⌨Q ◐... │ │
[ # ☑ ☐ Cond Grp Key Nm ]                ├──────────┤ │                    │ │
[ # ☑ ☐ Cond Grp Key Nm ]                │ GROUPS   │ │ 02 ● Heal       ✎  │ │
[ # ☑ ☐ Cond Grp Key Nm ]                │ • Combat │ │   ▣Combat ⌨1 ⇄... │ │
[                Close  ]                │ • Buff   │ │                    │ │
                                          └──────────┴─────────────────────────


Event Editor 모달 (Notebook):             Event Editor (Stepper):
┌[ Basic ][ Adv ][ Logic ]┐               ┌─ Edit Event: Boss-HP ──────[Save][✕]
│ Name [        ]         │               ├─ ① BASIC ───┬─ Live   Captured ────
│ [img] [img]             │               │   Name       │ ┌────┐  ┌────┐
│ Ref []                  │               │   Capture    │ │    │  │    │
│ AreaX AreaY PixX PixY   │               │   Key        │ └────┘  └────┘
│ Key [▾]                 │               │ ② ADVANCED  │ Ref [▣]  80×60
│ CapSize W H             │               │ ③ LOGIC     │ HOTKEYS box…
│ Hotkeys: ALT/CTRL...    │               │              │ Coord  X Y X Y
└─────────────────────────┘               │ Standalone⚡ │ Key [▾]
                                          └─────────────┴────────────────────
                                          Step 1/3   ← Back   Next →  [Save]
```

---

*문서 작성: UI **전면 개편** (기능·라우팅·데이터 비변경). 본 문서는 시각 정체성·정보 아키텍처·컴포넌트 어휘의 전환을 제시한다. 실제 적용은 Phase 단위 PR로 진행하고 각 단계마다 GUI 수동 검증 + `uv run python run_tests.py -q`로 회귀를 확인한다.*

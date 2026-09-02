# 성기사 — KeySim 로테이션 규칙

**작성일:** 2026-08-14
**상위 문서:** [`midnight-rotation-handoff.md`](midnight-rotation-handoff.md)
**근거:** `simulationcraft/simc` `midnight` 라이브 APL (2026-08-14 fetch) + Icy Veins 12.1
**전제:** AC(JustAC / Shinkili)를 필러로 두고, 이산 신호만 예외로 얹는다. 장신구·물약·종족기·차단·큰 생존 쿨은 핸드오프 §4대로 **수동**. 신성(힐)은 쓰지 않는다.

12.1 추천 영웅 특성: 징벌·보호 모두 **기사단**.

---

## A. 징벌

### A.1 기본 진단

AC 필러는 이미 빛의 망치/파멸의 재/선고·신폭풍 분기가 있다. 응징의 격노·사형 선고는 주석상 **실게임 어시스트가 안 고르는 줄**일 수 있다.
default 갭은 신성한 힘 5 소비 우선, 전쟁의 기술 2중첩 정의의 검, 창공 프록, 빛의 망치 **홀드 수식**이다. 수식은 포기하고 프록·캡만 확정한다.

### A.2 확정 규칙 (기사단)

```
1. 빛의 망치 준비/무료 (파멸의 재 직후)     → 빛의 망치
2. 신성한 힘 5                            → AC가 고른 소비기 (선고 또는 신폭풍)
3. (적 수에 따른 선고/신폭풍)              → AC 추천 추종
4. 창공의 힘                              → 천상의 폭풍
5. 창공의 유산                            → 최후의 선고
6. 전쟁의 기술 2중첩                      → 정의의 검
7. 이하 AC 추천 추종
```

| 규칙 | 근거 | 비고 |
| --- | --- | --- |
| 1 | `finishers:2` `hammer_of_light,if=!buff.hammer_of_light_free.up\|...` (긴 잔여 수식) | **준비/무료**만. 빛의 구원 홀드는 §A.3<br>⚠️ **AC 4행에 이미 있다** (`hammer_of_light,if=(ready\|free)`) → 예외 레이어 불필요 |
| 2·3 | `generators:1` `call_action_list,name=finishers,if=holy_power=5&cooldown.wake_of_ashes.remains\|buff.hammer_of_light_free.remains<gcd*2` | ⚠️ **`cooldown.wake_of_ashes.remains`(파멸의 재가 쿨 중)가 빠졌다.** 파멸의 재가 준비되면 힘 5여도 소비기로 가지 않고 `generators:3` 파멸의 재를 먼저 쓴다. 지금 규칙대로면 파멸의 재를 밀어낸다 |
| 4 | `finishers:1` `variable,name=ds_castable,value=(active_enemies>=3-(...)\|buff.empyrean_power.up)&!buff.empyrean_legacy.up` → `finishers:3` `divine_storm,if=variable.ds_castable&(...)` | 창공의 힘은 신폭풍 조건의 **일부**이고, 창공의 유산이 있으면 신폭풍이 **막힌다**<br>⚠️ **AC 17행에 이미 있다** |
| 5 | 위 `ds_castable`의 `!buff.empyrean_legacy.up` → `finishers:4` `templars_verdict` | ⚠️ **AC 5행에 이미 있다** — 오히려 AC 쪽이 더 상위(`holy_power>=5` 포함) |
| 6 | `generators:5` `blade_of_justice,if=(buff.art_of_war.up\|buff.righteous_cause.up)&(!talent.walk_into_light\|!buff.avenging_wrath.up)` | ⚠️ **중첩 조건이 없다** — "2중첩이 정점"은 APL에 근거 없음.<br>`righteous_cause` OR 절과 `walk_into_light`/응징 게이트도 누락됐다.<br>"힘 4여도 씀 / 5면 소비기가 먼저"는 맞다(`generators:1`이 `generators:5`보다 위) |

### A.3 남은 추가

| 규칙 | 근거 |
| --- | --- |
| 빛의 구원 프록 망치 — 응징/사형이 곧 끝나거나 프록이 곧 사라질 때만 | default HoL `remains` 수식. 잔여를 못 보면 **준비되면 쓰기**로 단순화 |
| 정화 도트 없음 → 정의의 검 | 오프너·신성한 불꽃 |
| 태양의 전령 + 신성한 목적 뒤 신폭풍 | 기사단은 무시해도 됨 (12.1 세트) |

### A.4 구현 불가

빛의 망치 잔여 글쿨 수식, 응징↔장신구 동기, Radiant Glory 분기, 적 수 정밀 공식.

### A.5 §4 편차

응징의 격노·사형 선고는 1~2분 쿨이다. 키심 예외 레이어에 **넣지 않는다.** 파멸의 재는 로테이션 쿨에 가깝다. AC가 추천하면 따라가도 된다.

다만 **AC 1행이 `avenging_wrath`, 2행이 `execution_sentence`** 다. F 슬롯을 그대로 추종하면 **이미 자동 입력된다.** "자동하지 않는다"가 아니라 **"필러에서 빼지 않으면 자동된다"** 가 사실이다. (BM 문서 §8과 동일 사안)

---

## B. 보호

탱 본업 생존(헌신적인 수호자, 고대 왕의 수호자, 천상의 보호막)은 수동. 여기는 **신성화 유지 + 정의의 방패 + 생성기**만.

### B.1 기본 진단

AC: 정의의 방패(망치 준비 아니면) → 응징의 방패 → 천벌 → 심판 → 신성화 없으면 → 생성기.
default는 빛의 망치·심판 디버프 정렬, 신성한 인도 5중첩 신성화, 빛의 망치 준비 중 정의의 방패 억제가 더 촘촘하다.

### B.2 확정 규칙 (기사단)

```
1. 빛의 망치 준비 AND 심판 디버프 있음      → 빛의 망치
2. 빛의 망치 준비 AND 심판 디버프 없음      → 심판 / 천벌
3. 정의의 방패 버프 꺼짐 AND 망치 준비 아님 → 정의의 방패
4. 신성화 발 아래 없음                     → 신성화
5. 선봉 프록                               → 응징의 방패
6. 이하 AC 추천 추종
```

| 규칙 | 근거 | 비고 |
| --- | --- | --- |
| 1 | `24행` `hammer_of_light,if=(!buff.undisputed_ruling.up\|buff.hammer_of_light_ready.remains<5)&debuff.judgment.up` | 망치를 심판 없이 쓰지 않음.<br>⚠️ 앞 괄호 `(!undisputed_ruling.up\|ready.remains<5)` 가 인용에서 빠져 있었다 |
| 2 | `27행` `hammer_of_wrath,if=buff.hammer_of_light_ready.up&!debuff.judgment.up`<br>`28행` `judgment,if=...(동일 조건)` | ⚠️ **천벌이 먼저다**(27 → 28). 규칙 본문의 "심판 / 천벌" 순서는 뒤집혀 있다 |
| 3 | `25행` `shield_of_the_righteous,if=!buff.hammer_of_light_ready.up\|(...)\|buff.hammer_of_light_free.up\|prev_gcd.1.divine_toll` | 망치에 힘을 남긴다<br>⚠️ **AC 4행에 이미 있다** (`if=buff.shield_of_the_righteous.down&!buff.hammer_of_light_ready.up`) → 예외 레이어 불필요 |
| 4 | — | 서 있는지가 핵심<br>⚠️ **AC 전용이다.** `consecration,if=!consecration.up` 은 AC에만 있고 default에는 `31행` `consecration,if=buff.divine_guidance.stack>=5` 뿐 → 예외 레이어 불필요 |
| 5 | `29행` `avengers_shield,if=buff.vanguard.up\|(buff.avenging_wrath.up&apex.3)` | ⚠️ `\|(buff.avenging_wrath.up&apex.3)` 절이 인용에서 빠져 있었다. `apex.3`은 BM 문서 §2와 동일하게 **미해결** — 빌드 확인 필요 |

정의의 방패는 글쿨 밖이다. 키심이 일반 스킬과 같은 그룹이면 생성기를 막을 수 있다. **별 그룹** 또는 사람이 누르는 편이 안전하다.

### B.3 남은 추가

| 규칙 | 근거 |
| --- | --- |
| 신성한 인도 5 → 신성화 | `consecration, if=buff.divine_guidance.stack>=5` |
| 축복의 확신 → 정의의 망치/축복받은 망치 | `if=buff.blessed_assurance.up` |
| 빛나는 빛 AND 체력 낮음 → 영광의 서약 | 생존. 자동은 신중 |
| 신성한 무기 (대장장이) | 응징 창이 아닐 때 |

### B.4 구현 불가

힘 3~5 풀링의 완전 재현, 신성화 발 위치(픽셀로 발밑만 가능), 파수꾼 중첩 유지.

### B.5 §4 편차

응징의 격노·파수꾼·천상의 종은 큰 쿨/정렬이다. **수동 또는 준비 표시.** AC가 응징을 넣으면 따라가지 않는 편이 안전하다.

---

## 키심 이벤트·조건

`감_` = 감지(실행 끔). `색_` = Shinkili 추천 색. `priority`는 작을수록 먼저. **적 수는 AC** (선고/신폭풍). 응징·사형은 입력 안 함.

### 징벌 (그룹 `징벌`)

| 이벤트 | 찍는 것 |
| --- | --- |
| `감_망치준비` | 빛의 망치 준비/무료 |
| `감_힘5` | 신성한 힘 5 |
| `감_창공힘` | 창공의 힘 |
| `감_창공유산` | 창공의 유산 |
| `감_전쟁2` | 전쟁의 기술 2중첩 |

| P | 이벤트 | 키 | 활성 필요 | 비활성 필요 |
| --- | --- | --- | --- | --- |
| 10 | `망치` | 빛의 망치 | `감_망치준비` | |
| 20 | `소비_힘5` | `색_선고` 또는 `색_신폭풍`이 가리킨 키 | `감_힘5` + 해당 `색_*` | |
| 40 | `신폭풍_창공` | 천상의 폭풍 | `감_창공힘` | |
| 50 | `선고_유산` | 최후의 선고 | `감_창공유산` | |
| 60 | `정검_전쟁` | 정의의 검 | `감_전쟁2` | `감_힘5` |
| 90 | `색_*` | AC가 고른 키 | 해당 `색_*` | |

### 보호 (그룹 `보호`, 정방만 `보호_정방`)

| 이벤트 | 찍는 것 |
| --- | --- |
| `감_망치준비` | 빛의 망치 준비 |
| `감_심판디버프` | 대상 심판 디버프 |
| `감_정방꺼짐` | 정의의 방패 버프 없음 |
| `감_신성화없음` | 발 아래 신성화 없음 |
| `감_선봉` | 선봉 프록 |

| P | 그룹 | 이벤트 | 키 | 활성 필요 | 비활성 필요 |
| --- | --- | --- | --- | --- | --- |
| 10 | 보호 | `망치` | 빛의 망치 | `감_망치준비` `감_심판디버프` | |
| 20 | 보호 | `심판_망치전` | 심판 / 천벌 | `감_망치준비` | `감_심판디버프` |
| 10 | 보호_정방 | `정방` | 정의의 방패 | `감_정방꺼짐` | `감_망치준비` |
| 30 | 보호 | `신성화` | 신성화 | `감_신성화없음` | |
| 40 | 보호 | `응방_선봉` | 응징의 방패 | `감_선봉` | |
| 90 | 보호 | `색_*` | AC가 고른 키 | 해당 `색_*` | |

---

## 스킬명 대조

| 영문 | 한국어 | 줄임 |
| --- | --- | --- |
| Avenging Wrath | 응징의 격노 | 응징 |
| Execution Sentence | 사형 선고 | 사형 |
| Wake of Ashes | 파멸의 재 | 파멸 |
| Hammer of Light | 빛의 망치 | 망치 |
| Final Verdict / Templar's Verdict | 최후의 선고 | 선고 |
| Divine Storm | 천상의 폭풍 | 신폭풍 |
| Blade of Justice | 정의의 검 | 정검 |
| Judgment | 심판 | — |
| Hammer of Wrath | 천벌의 망치 | 천벌 |
| Divine Toll | 천상의 종 | — |
| Crusader Strike | 성전사의 일격 | 성일 |
| Templar Strike / Slash | 기사단의 일격 / 베기 | — |
| Art of War | 전쟁의 기술 | — |
| Empyrean Power | 창공의 힘 | — |
| Empyrean Legacy | 창공의 유산 | — |
| Light's Deliverance | 빛의 구원 | — |
| Holy Power | 신성한 힘 | 힘 |
| Shield of the Righteous | 정의의 방패 | 정방 |
| Avenger's Shield | 응징의 방패 | 응방 |
| Consecration | 신성화 | — |
| Hammer of the Righteous | 정의의 망치 | — |
| Blessed Hammer | 축복받은 망치 | — |
| Word of Glory | 영광의 서약 | 영서 |
| Shining Light | 빛나는 빛 | — |
| Vanguard | 선봉 | — |
| Divine Guidance | 신성한 인도 | — |
| Blessed Assurance | 축복의 확신 | — |
| Sentinel | 파수꾼 | — |
| Sacred Weapon | 신성한 무기 | — |
| Templar | 기사단 | — |
| Herald of the Sun | 태양의 전령 | — |
| Lightsmith | 대장장이 | — |

---

> **개정 이력**
>
> - 2026-08-14 초판 — midnight 라이브 APL + Icy Veins 12.1. 이산 플래그만 확정.
> - 2026-08-14 키심 표 추가. 적 수는 AC. 힘 5 소비 스킬은 `색_*`.
> - 2026-08-14 검증 — 로컬 재fetch본(`f50a2121bf89`)과 한 줄씩 대조. 근거 인용에 리스트·행 번호 표기. 확정된 것만 반영:
>   §A.2 규칙 2 `cooldown.wake_of_ashes.remains` 누락, 규칙 6 "2중첩" 무근거·조건 누락, §A.5 편차 서술 반전,
>   §B.2 규칙 1 앞 괄호 누락·규칙 2 순서 반전·규칙 5 `apex.3` 절 누락, AC 중복 규칙 표시(징벌 1·4·5, 보호 3·4).
>
> **미확정(손대지 않음):** `apex.3`의 정확한 의미.

# 죽음의 기사 — KeySim 로테이션 규칙

**작성일:** 2026-08-14
**상위 문서:** [`midnight-rotation-handoff.md`](midnight-rotation-handoff.md)
**근거:** `simulationcraft/simc` `midnight` 라이브 APL (2026-08-14 fetch) + Icy Veins 12.1
**전제:** AC(JustAC / Shinkili)를 필러로 두고, 이산 신호만 예외로 얹는다. 장신구·물약·종족기·차단·큰 생존 쿨은 핸드오프 §4대로 **수동**. **적 수는 AC.**

핸드오프에서 냉기·부정은 B(후순위)다. default가 변수·중첩·대상 선택이 많아 **SimC 전체를 따라가지 않는다.** 목표는 AC + 프록/캡.

---

## A. 냉기

### A.1 기본 진단

AC 골격은 이미 프록형이다: 살육의 기계 → 절멸(광역은 서리 낫), **서리파멸 → 냉기의 일격, 서리 → 울부짖는 한기**.
⚠️ AC 실제 순서는 `frost_strike,if=buff.frostbane.up`(11행)이 `howling_blast,if=buff.rime.up`(12행)보다 **위**다. 아래 규칙 2·3의 순서는 이와 반대다.

⚠️ **신드라고사의 숨결도 AC 본문에 있다** — assisted_combat **3행** `breath_of_sindragosa`(조건 없음). `actions.cooldowns`에 중복 등재돼 있을 뿐 "어시스트가 안 고르는 줄"이 아니다.
default 갭은 **살육 2중첩 우선**, 칼날얼음 5 → 냉기의 일격, 룬/룬마력 풀링, 기둥·숨결·고룡 정렬이다. 풀링·정렬은 포기한다.

### A.2 확정 규칙

```
1. 살육의 기계 2중첩                       → 절멸
   (AC가 서리 낫을 주면 그 키 — 적 수는 AC)
2. 서리                                     → 울부짖는 한기
3. 서리파멸                                 → 냉기의 일격
4. 이하 AC 추천 추종
```

| 규칙 | 근거 | 비고 |
| --- | --- | --- |
| 1 | `single_target:83` `obliterate,if=buff.killing_machine.react=2\|(buff.killing_machine.react&rune>=3)`<br>`aoe:35` `frostscythe,if=buff.killing_machine.react=2&active_enemies>=variable.frostscythe_priority` | AC는 `up`만. **2중첩을 먼저** 쓴다. 광역 스킬은 AC 색<br>⚠️ `\|(buff.killing_machine.react&rune>=3)` 절이 인용에서 빠져 있었다 — 1중첩이어도 룬 3 이상이면 쓴다 |
| 2 | AC 12행 `howling_blast,if=buff.rime.up` | ⚠️ **AC 전용 인용이다** — 예외 레이어에 둘 근거가 아니다.<br>AC에서 이 줄은 규칙 3(서리파멸)보다 **아래**다 |
| 3 | AC 11행 `frost_strike,if=target.distance<=8&buff.frostbane.up` | ⚠️ **AC 전용 인용.** AC에서는 규칙 2보다 **위**이므로 P20/P30 순서가 뒤집혀 있다 |

### A.3 남은 추가

| 규칙 | 근거 |
| --- | --- |
| 칼날얼음 5 → 냉기의 일격 | `single_target:85` `frost_strike,target_if=max:(...),if=debuff.razorice.react=5&talent.shattering_blade&!variable.rp_pooling` — 대상 디버프 중첩. `&!variable.rp_pooling`이 인용에서 빠져 있었다 |
| 냉기의 기둥 켜짐 AND 고룡 준비 → 서리 고룡의 분노 | AC에도 있음. 기둥 안 정렬 보험 |
| 룬 무기 강화 — 살육 없거나 1중첩 | AC에 있음. 숫자(룬마력)와 겹침 |

### A.4 구현 불가

숨결용 룬마력 풀링, 룬 풀링(`rune_pooling`), 기둥·숨결 동기, 대상별 칼날얼음 `target_if`, 절멸/서리 낫 임계 변수.

### A.5 §4 편차

냉기의 기둥은 로테이션 창에 가깝다. AC가 추천하면 따라가도 된다. 신드라고사의 숨결·서리 고룡의 분노는 키심 예외 레이어에 **넣지 않는다.**

다만 **AC 본문 2·3·6행이 `frostwyrms_fury`·`breath_of_sindragosa`·`frostwyrms_fury`** 다. F 슬롯을 그대로 추종하면 **이미 자동 입력된다.** "수동"이 아니라 **"필러에서 빼지 않으면 자동된다"** 가 사실이다. (BM 문서 §8과 동일 사안)

---

## B. 부정

### B.1 기본 진단

AC 실제 순서: 소환 → 역병 없으면 돌발 → **역병 확산 시 돌발** → 죽음의 군대 → 어둠의 변신 → **금단의 지식**으로 고리·전염병 → 하급 구울 3+면 스컬지 → **영혼 수확자 2줄** → 고름 낫 → 화농 → **갑작스러운 파멸**로 고리·전염병 → 스컬지/고름/고리.

⚠️ **갑작스러운 파멸 고리는 고름 낫·화농보다 아래(13행)** 다. 금단의 지식(6행)과 묶어 앞에 둔 것은 잘못이며, 영혼 수확자 2줄이 누락돼 있었다.
default는 `spending_rp`·`epidemic_prio` 변수, 어둠의 변신 창 안 화농, 고름 낫 잔여 3초, 군대·변신 정렬이 무겁다.

### B.2 확정 규칙

```
1. 갑작스러운 파멸                          → AC가 고른 소비기 (고리 또는 전염병)
2. 고름 낫 버프                             → 고름 일격
3. 하급 구울 준비 3+                        → 스컬지의 일격
4. 치명적인 역병 없음                       → 돌발 열병
5. 어둠의 변신 켜짐 AND 화농 준비           → 화농
6. 이하 AC 추천 추종
```

| 규칙 | 근거 | 비고 |
| --- | --- | --- |
| 1 | `single_target:68` `death_coil,if=buff.sudden_doom.react` / 광역은 전염병 | 스킬 선택은 AC 색<br>⚠️ **P10은 잘못이다.** AC(13행)에서도 default(`single_target:66` 화농이 68행보다 위)에서도 **고름 낫·화농보다 아래**다. AC에도 이미 있다 |
| 2 | `single_target:64` `festering_strike,if=talent.festering_scythe&fight_remains>10&(buff.festering_scythe.up&(buff.festering_scythe.remains<=3\|buff.festering_scythe_tt.remains<3)\|...)` | 잔여 3초 홀드는 관측 어려움 → **버프 on이면 쓰기** (의도적 단순화) |
| 3 | AC 8행 `scourge_strike,if=buff.lesser_ghoul_ready.stack>=3` | ⚠️ **AC 전용 인용** — 예외 레이어에 둘 근거가 아니다 |
| 4 | AC 2행 `outbreak,if=!dot.virulent_plague.ticking` | ⚠️ **AC 전용 인용** — 예외 레이어에 둘 근거가 아니다 |
| 5 | `single_target:69` `putrefy,if=buff.dark_transformation.up`<br>`single_target:66` `...&runic_power.deficit>10` / `aoe:36` | 창 안 화농. 인용 정확 |

### B.3 남은 추가

| 규칙 | 근거 |
| --- | --- |
| 수확 버프 → 영혼 수확자 | AC `soul_reaper, if=buff.reaping.up` |
| 금단의 지식 → 소비기 | AC에도 있음 |

### B.4 구현 불가

`spending_rp` / `epidemic_prio` 변수, 고름 낫 잔여 초, 군대·변신·가르고일 정렬, `target_if=min:health.pct`.

### B.5 §4 편차

죽음의 군대·어둠의 변신은 큰 쿨이다. **수동 또는 준비 표시.** AC가 넣으면 따라갈지는 선택.

---

## C. 혈기

탱 본업 생존(흡혈, 얼음같은 인내력, 대마법 지대)은 수동. 여기는 **뼈의 보호막 + 프록 + 필러**만.

### C.1 기본 진단

AC 실제 순서: 체력 50% 이하 죽음의 일격 → 춤추는 룬 무기 → 죽음과 부패 → 사신의 징표 → 뼈 보호막 ≤6 골수분해 → 뼈 보호막 없음 골수분해 → **말살 골수분해** → 산레인/흡혈의 일격 심장 강타 → **피의 끓어오름** → 룬마력 80 일격 → **소모** → 심장 강타 → 죽음의 손길.
default는 영웅 트리(사신/산레인) 리스트, 룬마력 deficit, 뼈 보호막 잔여 초가 더 촘촘하다.

### C.2 확정 규칙

```
1. 뼈의 보호막 없음 또는 6중첩 이하         → 골수분해
2. 말살                                     → 골수분해
3. 흡혈의 일격 또는 산레인의 선물           → 심장 강타
4. 이하 AC 추천 추종
```

| 규칙 | 근거 | 비고 |
| --- | --- | --- |
| 1 | AC 5·6행 `marrowrend,if=buff.bone_shield.stack<=6` / `.down`<br>default `deathbringer:36` `if=!buff.bone_shield.up\|buff.bone_shield.remains<3\|buff.bone_shield.stack<6`<br>default `sanlayn:60` `if=buff.bone_shield.stack<6` | 잔여 3초는 관측 어려움. **중첩·없음**만<br>⚠️ **AC 전용 인용.** 그리고 default 임계는 `<6`(6 미만)로 AC의 `<=6`과 1중첩 다르다 |
| 2 | AC 7행 · default `deathbringer:34` `marrowrend,if=buff.exterminate.up` | ⚠️ **AC에도 이미 있다** |
| 3 | AC 8·9행 `heart_strike,if=buff.gift_of_the_sanlayn.up` / `if=buff.vampiric_strike.up`<br>default `sanlayn:64` `heart_strike,if=buff.vampiric_strike.up` | ⚠️ **AC에도 이미 있다.** AC 순서는 산레인 → 흡혈의 일격 (규칙 본문과 반대이나 OR이라 무해) |

⚠️ **§C.2 규칙 1·2·3이 모두 AC에 이미 있다.** 현재 혈기 확정 규칙에는 AC가 못 하는 항목이 하나도 없다 — 예외 레이어를 둘지 재검토가 필요하다.

죽음의 일격(체력 50%·룬마력 80)은 **AC에 이미 있음.** 키심이 체력으로 덮지 않는다.

### C.3 남은 추가

| 규칙 | 근거 |
| --- | --- |
| 진홍빛 스컬지 → 죽음과 부패 | 산레인 `any_dnd, if=buff.crimson_scourge` |
| 끓는 점 → 피의 끓어오름 | `blood_boil, if=buff.boiling_point.up` |

### C.4 구현 불가

룬마력 deficit 수식, 뼈 보호막 잔여 초, 사신/산레인 리스트 전환, 춤추는 룬 무기 전투 시간 정렬.

### C.5 §4 편차

춤추는 룬 무기·흡혈은 큰 쿨/생존이다. **수동.** AC의 춤추는 룬 무기를 따라갈지는 선택.

---

## 키심 이벤트·조건

`감_` = 감지(실행 끔). `색_` = Shinkili 추천 색. `priority`는 작을수록 먼저. **적 수는 AC** (서리 낫 vs 절멸, 고리 vs 전염병).

### 냉기 (그룹 `냉기`)

| 이벤트 | 찍는 것 |
| --- | --- |
| `감_살육2` | 살육의 기계 2중첩 |
| `감_서리` | 서리 |
| `감_서리파멸` | 서리파멸 |

| P | 이벤트 | 키 | 활성 필요 |
| --- | --- | --- | --- |
| 10 | `절멸_살육2` | AC가 고른 키 (절멸 또는 서리 낫) | `감_살육2` + 해당 `색_*` |
| 20 | `한기_서리` | 울부짖는 한기 | `감_서리` |
| 30 | `냉일_파멸` | 냉기의 일격 | `감_서리파멸` |
| 90 | `색_*` | AC가 고른 키 | 해당 `색_*` |

기둥·숨결·고룡은 입력 안 함.

### 부정 (그룹 `부정`)

| 이벤트 | 찍는 것 |
| --- | --- |
| `감_갑작파멸` | 갑작스러운 파멸 |
| `감_고름낫` | 고름 낫 버프 |
| `감_구울3` | 하급 구울 준비 3+ |
| `감_역병없음` | 치명적인 역병 없음 |
| `감_변신` | 어둠의 변신 |

| P | 이벤트 | 키 | 활성 필요 |
| --- | --- | --- | --- |
| 10 | `소비_파멸` | `색_고리` 또는 `색_전염병` | `감_갑작파멸` + 해당 `색_*` |
| 20 | `고름_낫` | 고름 일격 | `감_고름낫` |
| 30 | `스컬지_구울3` | 스컬지의 일격 | `감_구울3` |
| 40 | `돌발_역병` | 돌발 열병 | `감_역병없음` |
| 50 | `화농_변신` | 화농 | `감_변신` |
| 90 | `색_*` | AC가 고른 키 | 해당 `색_*` |

군대·변신은 입력 안 함(또는 준비 표시만).

### 혈기 (그룹 `혈기`)

| 이벤트 | 찍는 것 |
| --- | --- |
| `감_뼈없음` | 뼈의 보호막 없음 또는 ≤6 |
| `감_말살` | 말살 |
| `감_흡혈일격` | 흡혈의 일격 |
| `감_산레인` | 산레인의 선물 |

| P | 이벤트 | 키 | 활성 필요 |
| --- | --- | --- | --- |
| 10 | `골수_뼈` | 골수분해 | `감_뼈없음` |
| 20 | `골수_말살` | 골수분해 | `감_말살` |
| 30 | `심장_프록` | 심장 강타 | `감_흡혈일격` 또는 `감_산레인` |
| 90 | `색_*` | AC가 고른 키 | 해당 `색_*` |

죽음의 일격·춤추는 룬 무기·흡혈은 입력 안 함(AC/수동).

---

## 스킬명 대조

| 영문 | 한국어 | 줄임 |
| --- | --- | --- |
| Obliterate | 절멸 | — |
| Frost Strike | 냉기의 일격 | 냉일 |
| Howling Blast | 울부짖는 한기 | 한기 |
| Killing Machine | 살육의 기계 | 살육 |
| Rime | 서리 | — |
| Frostbane | 서리파멸 | — |
| Pillar of Frost | 냉기의 기둥 | 기둥 |
| Breath of Sindragosa | 신드라고사의 숨결 | 숨결 |
| Frostwyrm's Fury | 서리 고룡의 분노 | 고룡 |
| Empower Rune Weapon | 룬 무기 강화 | — |
| Frostscythe | 서리 낫 | — |
| Glacial Advance | 빙하 진군 | — |
| Remorseless Winter | 냉혹한 겨울 | — |
| Reaper's Mark | 사신의 징표 | — |
| Razorice | 칼날얼음 | — |
| Outbreak | 돌발 열병 | 돌발 |
| Festering Strike | 고름 일격 | 고름 |
| Scourge Strike | 스컬지의 일격 | 스컬지 |
| Death Coil | 죽음의 고리 | 고리 |
| Epidemic | 전염병 | — |
| Dark Transformation | 어둠의 변신 | 변신 |
| Army of the Dead | 죽음의 군대 | 군대 |
| Sudden Doom | 갑작스러운 파멸 | — |
| Soul Reaper | 영혼 수확자 | — |
| Putrefy | 화농 | — |
| Festering Scythe | 고름 낫 | — |
| Virulent Plague | 치명적인 역병 | 역병 |
| Death Strike | 죽음의 일격 | 죽격 |
| Marrowrend | 골수분해 | 골수 |
| Heart Strike | 심장 강타 | 심장 |
| Bone Shield | 뼈의 보호막 | 뼈보 |
| Blood Boil | 피의 끓어오름 | 피끓 |
| Death and Decay | 죽음과 부패 | 죽부 |
| Dancing Rune Weapon | 춤추는 룬 무기 | 춤룬 |
| Vampiric Blood | 흡혈 | — |
| Vampiric Strike | 흡혈의 일격 | — |
| Exterminate | 말살 | — |
| Gift of the San'layn | 산레인의 선물 | 산레인 |
| Death's Caress | 죽음의 손길 | — |
| Crimson Scourge | 진홍빛 스컬지 | — |

---

> **개정 이력**
>
> - 2026-08-14 초판 — midnight 라이브 APL + Icy Veins 12.1. 이산 플래그만 확정. 적 수는 AC.
> - 2026-08-14 검증 — 로컬 재fetch본(`f50a2121bf89`)과 한 줄씩 대조. 근거 인용에 리스트·행 번호 표기. 확정된 것만 반영:
>   §A.1 숨결이 AC 본문 3행(편차 서술 반전)·서리↔서리파멸 순서 반전, §A.2 규칙 1 `\|(killing_machine.react&rune>=3)` 누락,
>   §A.3 `!variable.rp_pooling` 누락, §A.5 편차 서술 반전,
>   §B.1 AC 순서 오류(갑작파멸 위치·영혼 수확자 누락), §B.2 규칙 1 우선순위가 AC/default와 반대,
>   §C.1 AC 순서 3건 누락, §C.2 규칙 1 default 임계 `<6` vs AC `<=6`,
>   AC 중복 규칙 표시(냉기 2·3, 부정 1·3·4, **혈기 1·2·3 전부**).
>
> **수정 없음:** §B.2 규칙 2(단순화를 문서가 명시), 규칙 5(인용 정확), §C.3(인용 정확).
>
> **미확정(손대지 않음):** `variable.frostscythe_priority` / `variable.rune_pooling` / `variable.spending_rp` 의 실제 값 — 빌드 의존.

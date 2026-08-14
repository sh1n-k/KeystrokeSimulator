# 야수 사냥꾼 (BM) — KeySim 로테이션 규칙

**작성일:** 2026-08-14
**상위 문서:** [`midnight-rotation-handoff.md`](midnight-rotation-handoff.md) — 아키텍처·색 슬롯 프로토콜·CD 운용 원칙은 그쪽을 따른다.
**근거:** `simulationcraft/simc` `midnight` 브랜치 **라이브 재확인 (2026-08-14)** + Icy Veins / Wowhead 12.1 교차 확인
로컬 스냅샷(`~/PersonalProjects/simc-apl-research/`, 커밋 `543891d`, fetch 2026-08-03)은 `default` 쪽이 **이미 낡았다** — 재fetch 필요. `assisted_combat` 쪽은 라이브와 동일.
**전제:** AC(JustAC) 추천을 기본 필러로 두고 그 위에 예외 레이어를 얹는 핸드오프 §3.3 구조.

---

## 1. 기본 진단

Assisted Combat APL은 조건이 붙은 줄이 **Wild Thrash 두 줄뿐**이고 나머지는 "쿨 돌면 누른다"이다.
default APL과의 갭은 거의 전부 **야수의 격노(30초) 창에 맞춘 뱅킹 로직**으로 수렴한다.
핸드오프 §5.4의 "BM: default에 BW 패킹, assisted는 평탄 → S 아님" 판정과 일치한다.

---

## 2. 확정 규칙

```
1. 격노 쿨 1.5초 이내 OR 날사 2중첩            → 날사
2. 적 2~3마리 AND 난타 쿨 완료                 → 난타
3. 포효 준비                                   → 살상
4. 동맹 up AND 격노 쿨 1.5초 초과
   AND (포효 쿨 4초 초과 OR 살상 2중첩 근접)   → 살상
5. 격노 쿨 1.5초 이내 AND 위 전부 불가         → 대기
6. 이하 AC 추천 추종
```

| 규칙 | 근거 (라이브 `actions.st`) | 비고 |
| --- | --- | --- |
| 1 | 1순위 `barbed_shot, if=cooldown.bestial_wrath.remains<gcd\|full_recharge_time<gcd` — `bestial_wrath`(2순위)보다 위 | 한 줄에 **조건 둘**이 OR로 들어 있다. `remains<gcd`는 **패킹**(충전 개수 무관 — 1충전이어도 사용), `full_recharge_time<gcd`는 **오버캡 방지**. 둘을 하나로 뭉뚱그리지 말 것 |
| 2 | 3순위 `wild_thrash, if=active_enemies>1` — 살상보다 위, 격노 게이트 없음 | AC는 `active_enemies>3`(4마리 이상)에서만 사용 → **2~3마리 구간이 비어 있다** |
| 3 | 4순위 `kill_command, if=howl_summon.ready` — 조건 이것뿐 | 포효가 준비되면 동맹도 격노 게이트도 필요 없다 |
| 4 | 5순위 `kill_command, if=(cooldown.bestial_wrath.remains>full_recharge_time+gcd&buff.natures_ally.react\|!apex.3)&(buff.howl_of_the_pack_leader_cooldown.remains>4\|cooldown.kill_command.charges_fractional>1.8)` | 게이트가 **둘**이다. 앞 괄호 = 격노 뱅킹 + 동맹, 뒤 괄호 = **포효 뱅킹**. 2중첩(`charges_fractional>1.8`)은 **뒤 괄호만 푼다** — 동맹 요구는 남는다 |
| 5 | 8순위 `cobra_shot, if=cooldown.bestial_wrath.remains>gcd` 가 실패하면 SimC도 idle | 격노 직전이라도 난타·포효 살상·송곳니 코브라는 **차단되지 않는다**(해당 줄에 격노 게이트가 없음). 대기는 최하위 폴백이다 |

**`!apex.3` 주의.** 규칙 4의 앞 괄호는 `... & 동맹 | !apex.3` 이므로, **정점 3을 찍지 않은 빌드에서는 격노 게이트와 동맹 요구가 통째로 풀린다**(살상 무조건). 정점 3을 찍은 일반 빌드에서는 동맹이 필요하다. 프로필 확정 전 본인 빌드에서 확인할 것.

---

## 3. 핵심 비대칭 — 날사와 살상은 방향이 반대

| | 격노 직전 | 근거 |
| --- | --- | --- |
| 날사 | **비우고 들어간다** | `barbed_shot, if=cooldown.bestial_wrath.remains<gcd` — 격노보다 위, 충전 조건 없음 |
| 살상 | **아끼고 들어간다** | `kill_command, if=cooldown.bestial_wrath.remains>full_recharge_time+gcd&...` — 2중첩(=`full_recharge_time` 0)이어도 격노 1.5초 이내면 누르지 않음 |

APL이 왜 이렇게 배치됐는지(메커니즘)는 확인되지 않았다. 격노는 `Modifies Damage/Healing Done 20%`로 사냥꾼 본체 스킬에도 적용되므로 "날사는 격노 버프를 안 받는다"는 설명은 성립하지 않는다. **추정으로 채우지 말고 위 두 줄의 사실만 근거로 쓸 것.**

---

## 4. Wild Thrash 사실 메모

| 항목 | 값 |
| --- | --- |
| Wild Thrash 재사용 대기시간 | 8초 |
| 야수 회전베기 지속시간 | 10초 (12.1에서 8초 → 10초 상향) |
| 겹침 | 2초 |

- AC의 `buff.beast_cleave.down` / `remains<=2` 두 줄은 겹침이 정확히 2초이므로 **"쿨 돌면 즉시"와 동치**다. AC의 타이밍 판정 자체는 정확하고, 결함은 타겟 수 임계뿐이다.
- 따라서 **회전베기 잔여시간 색 슬롯은 불필요**하다. Wild Thrash 쿨만 보면 된다.
- Wild Thrash는 유지기가 아니라 딜기(공격력 191%, 2대상 이상 시 ×3)다. 버프 만료까지 늦추면 주기가 8초 → 10초가 되어 **캐스트 수가 20% 줄고, 얻는 것은 없다**(유지율은 양쪽 다 100%). 구 일제 사격의 감각을 적용하지 말 것.

---

## 5. 예외

**어둠 순찰자 광역(`actions.drcleave`).** 날사가 격노(2순위) 아래 5순위이므로 이 구간에서는 규칙 1을 끈다.

진입 조건은 `talent.black_arrow&(active_enemies>2|talent.beast_cleave&active_enemies>1)` 이다 — **회전베기 특성이 있으면 2타겟부터** drcleave로 들어간다(3타겟 아님). 단일 대상과 무리의 지도자는 해당 없음.

---

## 6. 남은 추가 항목

| 순위 | 규칙 | 대응 default 줄 |
| --- | --- | --- |
| 1 | 부패 잔여 2GCD 미만 → 통곡 | 단일 `wailing_arrow, if=buff.withering_fire.remains<execute_time+2*gcd`<br>광역은 `+gcd`(1GCD) |
| 2 | 부패 up AND 살상 충전 여유 → 검화 | `black_arrow, if=buff.withering_fire.up&cooldown.kill_command.full_recharge_time>gcd` |
| 3 | 송곳니 3중첩 이상 → 코브라 | 단일 `cobra_shot, if=buff.cobra_fang.stack>=3`<br>어둠 순찰자 `if=buff.cobra_fang.stack>3`<br>광역 `if=buff.cobra_fang.up&buff.beast_cleave.remains` |

> 항목 3은 **Hogstrider(멧돼지 기수) 조건을 대체한 것**이다. 라이브 `actions.cleave`에서 `hogstrider` 줄은 삭제되고 송곳니로 교체됐다.

---

## 7. 구현 불가 / 자동화 제외

| 항목 | 사유 |
| --- | --- |
| `target_if=min:dot.barbed_shot.remains` (날사 타겟 스와핑) | 타겟 전환 필요 — KeySim 범위 밖 |
| `full_recharge_time`, `charges_fractional<1.4` (살인 코브라 분기) | 연속값 — 이산 색 플래그로 옮기기 어려움 |
| 격노 2GCD 전 난타 선행 정렬 | 미래 예측 필요, default APL도 미모델링 → 수동 판단 |
| 장신구 · 물약 · 종족특성 | 핸드오프 §4 원칙 유지 (전부 `cooldown.bestial_wrath.ready` 정렬) |
| 차단 · 생존기 · 소환수 관리 · 사냥꾼의 징표 | 상황 판단 |

---

## 8. 핸드오프 §4 원칙과의 편차 (결정 필요)

AC는 `bestial_wrath`를 **조건 없이 2순위**로 추천한다. 따라서 F 슬롯을 그대로 추종하는 프로필은 **야수의 격노를 자동 입력하게 된다.** 핸드오프 §4의 "CD 키 자체는 프로필에 넣지 않는다 / ready를 입력에 묶지 않는다"와 어긋나므로, 의도적 예외로 둘지 필러에서 격노를 제외할지 결정이 필요하다.

---

## 9. 스킬명 대조

한국어는 와우 클라이언트(Wowhead KO) 표기. 줄임은 이 문서·프로필에서 쓰는 말.

| 영문 | 한국어 | 줄임 |
| --- | --- | --- |
| Barbed Shot | 날카로운 사격 | 날사 |
| Bestial Wrath | 야수의 격노 | 격노 |
| Kill Command | 살상 명령 | 살상 |
| Cobra Shot | 코브라 사격 | 코브라 |
| Wild Thrash | 마구잡이 난타 | 난타 |
| Beast Cleave | 야수의 회전베기 | 회전베기 |
| Howl of the Pack Leader | 무리의 지도자의 포효 | 포효 |
| Nature's Ally | 자연의 동맹 | 동맹 |
| Cobra Fang | 코브라 송곳니 | 송곳니 |
| Arcane Shot | 신비한 사격 | 신사 |
| Stampede! | 쇄도! | 쇄도 |
| Black Arrow | 검은 화살 | 검화 |
| Wailing Arrow | 죽음의 통곡 | 통곡 |
| Withering Fire | 부패의 사격 | 부패 |
| Pack Leader | 무리의 지도자 | — |
| Dark Ranger | 어둠 순찰자 | — |
| Hogstrider | 멧돼지 기수 | — |

---

> **개정 이력**
>
> - 2026-08-14 초판 — 로컬 스냅샷(fetch 2026-08-03) 기준.
> - 2026-08-14 개정 — `midnight` 브랜치 라이브 재확인. `actions.st` 1순위에 오버캡 조건 병합, `kill_command` 2줄 분리(`howl_summon.ready` 신설), `cobra_fang` 신설, `actions.cleave`에서 `hogstrider` 삭제·`bestial_wrath` 위치 이동·`prev.wild_thrash` 제거를 반영. §2·§3·§5·§6·§7 수정.
>
> `assisted_combat` APL은 두 시점 모두 동일하므로 AC 관련 분석(§1·§4)은 영향 없다.
> 로컬 `simc-apl-research` 스냅샷은 `default` 쪽이 낡았다 — 재fetch 후 `SOURCE.txt` 갱신 필요.

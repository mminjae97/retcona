# Claim extraction results

How the extractor (`backend/pipeline/extract_claims.py`) does on the novel passages of `eval/passages.jsonl`, and what each change to it did. Every change is measured here, so the effect of a rule is on record. Data and scoring: [README.md](README.md).

## Setup common to all rounds

| | |
|---|---|
| Machine | CPU, 6 threads (about 13 s for the 45 passages, models loaded) |
| Models | NER `ml/ner/runs/klue`, QA `ml/qa/runs/klue` (null margin -10) |
| Data | 45 passages, 47 lines of text · 52 gold items, 4 pending (to be left for the author), 6 mutable (not extracted yet) |
| Scoring | an item is right when subject (a pending claim: its candidates), attribute and value all match; extra = false positive, missed = gold the extractor didn't find |

## Round 1 — 2026-10-06: the extractor as merged (#40 – #46)

| | right | extra | missed | precision | recall | F1 |
|---|---|---|---|---|---|---|
| all (strict) | 32 | 0 | 24 | 1.000 | 0.571 | 0.727 |
| attribute and value only | 32 | 0 | 24 | 1.000 | 0.571 | 0.727 |

By attribute: origin 3/3, scars 3/4, age 6/8, eye color 13/21, height 1/3, hair color 5/12, location features 1/5; the 6 mutable ones are all missed (not extracted yet).

By kind of case (right / right + missed): origin 2/2, scars 2/2, age 2/2, multi-attribute 2/2, NER-only names 3/3, particle on a name 1/1, possessive 1/1, disguise 2/2, pending 4/5, alias 3/6, basic 4/5, dialogue 3/5, pronoun-gender 2/3, pronoun-he 7/15, pronoun-she 8/16, scenes 8/15, location 1/5, plural 0/2, multi-subject 0/2, figurative 0/1.

**The extractor never claims what it shouldn't here, and misses about 4 in 10 of what it should.** No false positive on the passages built to produce them (someone else's eyes, a line of dialogue, snow, footprints, "열심히 살았다", a place only passed through, a "그녀" for a character the text doesn't name), and where it does claim, it's about the right character every time (the two tables are the same). What it loses is recall, mostly after a pronoun.

### Where the 24 misses are

Looking at the question asked and the answer the QA model gave for each:

- **The question names someone the sentence doesn't (10)**: after a pronoun or an alias the sentence says "그녀의 은빛 머리카락이…" or "철수형의 눈동자는…" and the question is "세린의 머리색은?" / "김철수의 눈 색깔은?"; the model answers "no answer" to a question about a person the context doesn't mention (p02, p04, p08, p18, p34, p39 ×2, p41, p43, p44). It's the largest loss, and across every attribute, so it'll cost the mutable ones too.
- **A place's features (4)**: "특징은?" is a poor question for a sentence like "벨로스 성은 산 위에 우뚝 서 있었다"; the QA model answers for 1 of 5 (p16, p38 ×2, p45).
- **By design (6)**: two names in a sentence with no possessor (p23, 2 items), a plural "그들" (p29, 2), "그녀의" in a sentence that names someone else (p42), and a pronoun three sentences from its name (p35: the window is two; design doc 7.1.1 says two or three).
- **The QA model's own limits (2)**: a figurative value ("칠흑 같았다", p24) and a height said as a verb ("키가 컸다", p14).
- **A cue's color word is out of reach (1)**: "그의 눈이 어둠 속에서 붉게 번뜩였다" has it four words after the noun, the window is three (p03).
- **A body part taken for another person (1)**: in "카엘은 … 오른손의 흉터를 문질렀다" the possessor "오른손" isn't a character, so the cue is skipped as "somebody else's" (p39).

### What to try next, in order of what it should be worth

1. Ask the QA model about what the sentence says: the pronoun or alias as written ("그녀의 머리색은?"), or the sentence with the name put in for the pronoun. (10)
2. Take the place's features from the sentence itself instead of asking for them. (up to 4)
3. Treat a body part ("오른손의", "왼팔의") as no possessor at all; a longer window for a cue's color word; how far back a pronoun looks. (1 + 1 + 1)
4. Extract the mutable attributes (6, once there's a question for each).

The set is small (one or two items is noise), so each of these is judged by the whole table and by `--errors`, not by one number.

## Round 2 — 2026-10-06: ask about the person the sentence names

The largest loss of round 1 (10 of 24 misses): after a pronoun or an alias the sentence says "그녀의 은빛 머리카락이…" or "철수형의 눈동자는…" and the question named the card, "세린의 머리색은?"; the QA model answers "no answer" about a person its context doesn't mention. Four ways to give it a context that does were tried, each on top of the first change below.

| Change | right | extra | missed | precision | recall | F1 |
|---|---|---|---|---|---|---|
| round 1 (the question always names the card) | 32 | 0 | 24 | 1.000 | 0.571 | 0.727 |
| **alias:** name the person as the clause writes it ("철수형", "공주") | 35 | 0 | 21 | 1.000 | 0.625 | 0.769 |
| + **pronoun as written:** "그녀의 머리색은?" | 38 | 1 | 18 | 0.974 | 0.679 | 0.800 |
| + **name for the pronoun:** the clause with "세린" put in for "그녀" | 41 | 1 | 15 | 0.976 | 0.732 | 0.837 |
| + **the sentence before:** the nearest of the two before it that names the person, then the clause | 42 | 1 | 14 | 0.977 | 0.750 | 0.848 |
| + **both** of those | **43** | 1 | **13** | 0.977 | **0.768** | **0.860** |

Kept: the alias change and the last (both). Each costs nothing in precision but the one extra, which is a case that was hidden before (below).

By attribute, round 1 → round 2 (right / right + missed): hair color 5/12 → **12/12**, age 6/8 → **8/8**, eye color 13/21 → 14/21, height 1/3 → 2/3. By case: alias 3/6 → **6/6**, dialogue 3/5 → **5/5**, pronoun-he 7/15 → 13/15, pronoun-she 8/16 → 15/16, scenes 8/15 → 13/15, namesake 1/2 → **2/2**, figurative 0/1 → **1/1** (the QA model reads "칠흑 같았다" fine once it's asked about the right person).

### The one extra: a "그녀" for a character the text doesn't name

p36, "레온은 문을 열었다. 그녀의 눈이 푸르게 빛났다.": the "그녀" is someone else, and the extractor says Leon's eyes are blue. In round 1 it was there too, but the QA model happened to answer "no answer" (the question named Leon, the sentence didn't); now that it's asked about the right person, the rule shows. It's the single-candidate rule (a lone candidate isn't held against the pronoun, so that a wrong gender setting can't make claims vanish). With the genders the author set, 레온 is male and "그녀" says otherwise. Holding a lone candidate to the pronoun would fix it and cost the claims of an author who set a gender wrong; design doc 7.1.1 says "gender included" for exactly one fit.

### What's left of the 13 misses

- **A place's features (4)**: p16, p38 ×2, p45.
- **By design (6)**: two names in a sentence with no possessor (p23 ×2), a plural "그들" (p29 ×2), "그녀의" in a sentence that names someone else (p42), a pronoun three sentences from its name (p35).
- **A cue's color word out of reach (1)**: p03. **A height said as a verb (1)**: p14 ("키가 컸다"). **A body part taken for another person (1)**: p39 ("오른손의 흉터").

The 6 mutable ones are still all missed.

### What to try next

1. A place's features from the sentence itself instead of a question. (up to 4)
2. A body part ("오른손의", "왼팔의") is no possessor; a longer window for a cue's color word. (2)
3. Decide the single-candidate rule above. (removes the 1 extra)
4. Extract the mutable attributes. (6)

## Round 3 — 2026-10-06: a place's features from the sentence

The QA model answered "특징은?" for 1 of 5 places (round 2 misses: p16 ×1, p38 ×2, p45): the question has no answer shape for a sentence like "벨로스 성은 산 위에 우뚝 서 있었다". A place's features are said of it in the sentence it is the topic of, so they are now read off it: what follows the topic particle, up to a comma ("검은 숲은 늘 안개로 덮여 있었다" -> "늘 안개로 덮여 있었다"). Not taken where it isn't a description of the place: a quote after the place, an object ("병사들을 삼켰다"), or a character before the end of it ("레온이 지켰다").

| | right | extra | missed | precision | recall | F1 |
|---|---|---|---|---|---|---|
| round 2 | 43 | 1 | 13 | 0.977 | 0.768 | 0.860 |
| **round 3: features from the sentence** | **47** | **0** | **9** | **1.000** | **0.839** | **0.913** |

Features 1/5 -> **5/5**, and no extra on the place passages that must give none (a place only passed through: the `location-passing` tag). The set is small and the rule was written looking at its three place passages, so 5/5 says the rule does what it was made to do, not how it does on other prose; what it takes for a description (anything after the topic that has no quote, object or character) will take some sentences that aren't ("벨로스 성은 폐허가 되었다" is an event). The author reads a place's claims on the result screen like any other. Known limits of the rule: it takes the text up to the first comma, so a value can end on a connective ("안개가 짙었고"); and a clause with a word in -을/-를 is refused whether it's an object ("병사들을") or the adnominal ending ("없을 만큼"), since telling them apart takes a morphological analyzer, so it errs on the side of no claim. Features are read only from a place that is the topic (은/는); "멀리 벨로스 성이 보였다" says nothing of the place, and it's where the QA model used to be the filter.

### The extra of round 2 is gone, and the rule behind it stays

p36 ("레온은 문을 열었다. 그녀의 눈이 푸르게 빛났다.") is no longer an extra. That's the change of the review rounds of #48, not of this round: a clause whose pronoun is the other gender than the card's is read without the sentence before, so the QA model has no name to answer about. It's not a rule: a QA model that answered anyway would bring it back. **Decided: the single-candidate rule stays as it is** (a lone candidate isn't held against the pronoun, so that a wrong gender setting can't make claims vanish), and p36 stays the known limit.

### What's left of the 9 misses

- **By design (6)**: two names in a sentence with no possessor (p23 ×2), a plural "그들" (p29 ×2), "그녀의" in a sentence that names someone else (p42), a pronoun three sentences from its name (p35).
- **A cue's color word out of reach (1)**: p03. **A height said as a verb (1)**: p14 ("키가 컸다"). **A body part taken for another person (1)**: p39 ("오른손의 흉터").

The 6 mutable ones are still all missed.

### What to try next

1. A body part ("오른손의", "왼팔의") is no possessor; a longer window for a cue's color word. (2)
2. Extract the mutable attributes. (6)

## Round 4 — 2026-10-06: a place's change of state is a state, not a feature

A sentence like "벨로스 성은 폐허가 되었다" was read as the place's features (round 3's known limit): once the card says "높은 산 위에 서 있었다", the later sentence would be judged against it as a contradiction, when the story only changed the place. A place's predicate that says it changed or is in a changed state ("폐허", "불타", "무너", "멸망", "...가 되었다" and the like) is now taken as its **state** instead, and the merge step records it in `location_state_history` for the episode, as a character's hairstyle or outfit is in `character_state_history`; the judge compares only features (`GEO_ATTR_KEYS`) with the card, so a state is never held against it.

8 passages (p46-p53, tag `location-state`) were added to the set: a place gone to ruin, burned away, and one described and then collapsed (a feature and a state), and three that must stay features although they hold a word of the rule or look like a change: "함락된 적 없는 요새", "무너지지 않았다", "교역의 중심이 되었다". All 9 items right (the first version of the rule, with the word list alone and a broad "...가 되었다", got 4 of 7 with 3 extra on these), and the whole set is now **56 right / 0 extra / 9 missed** (precision 1.000, recall 0.862, F1 0.926). The rule and the passages were written together, so this says the rule does what it's made for, not how it does on other prose. Where the word has to be: the last two words of the predicate, or its last word where that is "...였다" ("몰락한 왕가의 거처였다", "잿더미 위에 세워진 도시였다" describe; "폐허였다" is a state), and a denial ("않", "적 없", "못", "안", "리 없", "아니") anywhere in it means a feature; also two passages for the noun cases (p52, p53). A change that is denied ("않", "적 없", "리 없", "아니", and "안"/"못" before the verb), only about to happen or tried ("듯", "뻔", "시도", "려고", "나섰"), likened ("같았", "처럼", "마치"), wished or waited for ("꿈", "바랐", "기다렸", "원했"), or not managed ("못했") or a role ("중심이 되었다"), is a feature, not a state. The denial is looked for from the word before the state word on, so a denial in an earlier clause ("막으려 했으나 결국 함락되었다") doesn't veto it; "-하였다" is not a noun the place is, and "성 안 전체가" is not a denial.

Not done: comparing a later episode's sentence with the place's latest state (a city described again after it fell), which is stage 4 (the state-history accumulation of design doc §7); the state's story time (`story_timestamp`) stays empty; a clause that holds both ("늘 안개에 싸인 채 불타 사라졌다") is stored as a state only; the state recorded for an episode is the last one it says, in the order the text says them (a flashback after it, "그 시절 벨로스 성은 함락되었다", would be the one recorded; which is earlier in the story is for stage 4), so a place that falls and is rebuilt in the same episode ends as rebuilt; the word list is short, so a change said in other words than the list has (it has "폐허", "불타", "무너", "황량해졌", "시들었", "재건" and the like) is still read as a feature, a state word that is the subject of another thing in the clause ("마을은 사람들이 모두 사라졌다") is taken as the place's own, and a state word that comes more than two words (three after "버렸다", "있었다") before the end of the predicate isn't found; the noun "안" ("마을 안 불탔다") looks like the adverb "안" ("안 무너졌다") when it is within the last two words, and is taken as a denial, so that change is read as a feature.

## Round 5 — 2026-10-08: the topic's body part, a body part as no possessor, two reaches

Four rules of the backlog, each measured on the set. The first four rows are on the 53 passages of round 4; the last adds p54 (one more item the new rule gets right) and p55 (a guard with nothing to find), so the set is now **55 passages**.

| | right | extra | missed | precision | recall | F1 |
|---|---|---|---|---|---|---|
| round 4 | 56 | 0 | 9 | 1.000 | 0.862 | 0.926 |
| + **color word counted from after the noun's particle** ("그의 눈이 어둠 속에서 붉게", p03) | 57 | 0 | 8 | 1.000 | 0.877 | 0.934 |
| + **a body part is no possessor** ("오른손의 흉터", p39) | 58 | 0 | 7 | 1.000 | 0.892 | 0.943 |
| + **a pronoun looks back three sentences**, not two (p35) | 59 | 0 | 6 | 1.000 | 0.908 | 0.952 |
| + **the topic owns the body part** (p54, p55 added) | 60 | 0 | 6 | 1.000 | 0.909 | 0.952 |

- **The topic owns the body part.** In "레온은 붉은 눈동자로 카엘을 노려보았다." two names and no possessor used to mean no claim. Now the sentence's one topic (은/는/이/가) is the owner when the cue comes before the others and each of them is acted on (을/를, 에게/한테). Left as no claim: a cue that describes the other ("붉은 눈의 카엘을", "눈이 푸른 카엘을": any word between the cue and the other name that is an adnominal ending, "눈이 푸른 소녀 세린을", or the cue's own 의), the cue after the other name ("레온은 카엘을 붉은 눈동자로 ..."), a co-subject ("레온과 세린은 ..."); p55 is a guard for the first.
- **A body part is no possessor.** "오른손의", "왼팔의" and the like (a whole word, so "후손의" is still a person; 배, 등, 목, 볼, 발 are left out, as they are as often a ship or a thing) fall through to the sentence's own subject. "노인의 오른손의 흉터" is still the old man's.
- **The color word after the noun** is counted from the word after the noun's own ("눈이" is not a word of the three), which is what the window was meant to be.
- **A pronoun looks back three sentences** (design doc: two or three). Between two or more registered candidates this still ends as a choice for the author, so more reach costs a question, not a wrong claim. With exactly one candidate there is no question: a lone character three sentences back now gets the claim ("레온은 문을 열었다. 바람이 불었다. 방은 어두웠다. 그의 눈이 붉게 빛났다."), as one two back always did, which is a wrong claim if the pronoun is somebody the text doesn't name. The author reads every claim on the result screen. Four sentences back is still nothing.
- **Found on the way:** the QA model answered "왼팔" to "카엘의 흉터는?" for "왼팔의 상흔", which would have been a claim of scars = '왼팔'. An answer that is only body parts (listed, with a direction or a place word: "왼쪽 뺨과 이마", "뺨 위에") is now refused as a scar's value; that sentence is a miss, not a false claim.

Known limit of the "describes the other" guard: it reads every word between the cue and the other name that ends in a final ㄴ/ㄹ, after the last word with a particle of its own, as an adnominal ("푸른", "한"; so the 문 of "문 앞에서 세린을" is not one, but "문 세린을" would be), except the object particles 을/를, 만 and a few adverbs (번, 순간, 잠깐, 동안); other nouns or adverbs with such an ending in the phrase right before the name can still make the guard refuse, which costs recall, not precision; telling them apart takes a morphological analyzer. The topic rule is for the body (eyes, hair, scars, height) only. A "그/이/저" before a body part ("그 손의 흉터", "그 오른쪽 어깨의 흉터") is somebody already mentioned, so no claim; and a body part's "X의" goes to the sentence's own subject only when that is the topic of the sentence ("노인은 레온에게 오른손의 흉터를 보여주었다" is nobody's of the registered). A sentence with no registered name and a body part's "X의" is linked back only by a pronoun ("그는 오른손의 흉터를"), not as a dropped subject: "노인은 오른손의 흉터를 보였다" may be somebody the text doesn't register. The "의" of the guard counts only on the cue's own word ("눈의"), not a later "앞의". The nearest two sentences are searched first; the third one back only where they name nobody, so a far name never turns a clear owner into a choice. A color three words after the noun counts only as a predicate ("눈은 어둠 속에서도 붉게"), not as the modifier of another noun ("눈이 마주친 순간 붉은 노을이"). In the "describes the other" guard, a word before 번/뒤/후/때/채/듯/사이/직후/적 and the adverb "온" are not modifiers of the name ("노려본 뒤 세린을", "온 힘을 다해 세린을"). Another subject between the topic and a body part's "X의" is read from 은/는/이/가, 도, 만 and 께서 ("노인도", "노인만"), except the connective of a verb ("웃었지만", "웃어도") and a few conjunctions; a noun the guesswork takes for a verb connective is missed (recall, not precision). A modifier is skipped too ("깊은 숨을", "떨리는 손으로": -하는/-되는/-있는/-없는, ㄹ+리는, and -은 after ㅂ ㅍ ㄲ ㅆ ㄺ ㄻ ㄼ), but only stems that are not names ("마리는" stays a subject); other adnominals are still read as subjects, which costs recall, not precision. The topic rule for two names checks the same thing: no other subject between the topic and the cue ("레온은 웃었고 노인은 붉은 눈동자로 세린을" is nobody's of the registered). A registered name marked 이/가 after a word marked 은/는 is the subject of a clause under that one, not the sentence's topic ("노인은 레온이 오자 오른손의 흉터를"); that also drops "숲은 고요했고 레온이 ..." (recall). Common adverbs and times are not subjects ("오늘도", "이번에도", "말없이", "깊이", "같이"), and a few adverbs with a final ㄴ are not modifiers of the name ("온", "얼른", "순식간", "가만", "일순"); both are short lists. The topic rule also leaves out a cue that is the object of the topic's verb ("레온은 은빛 머리카락을 쓰다듬으며 세린에게", "흉터를 치료해 주며", and so "세린은 오른손의 흉터를 레온에게 보여주었다" too): stroked, treated or shown, the body part may be either one's; what the topic looks or acts with ("붉은 눈동자로") stays the topic's. The color window keeps a color noun in ㄹ ("은발") as its third word. These lists stand in for a part-of-speech tagger; a morphological analyzer (e.g. kiwipiepy, no LLM) is the follow-up that would replace them. 와/과/도 do not end the phrase of a modifier ("눈이 붉은 소녀들과 세린을"), so a "문과 세린을" is read as a modifier too (recall).

Still missed (6): a plural and a pair ("레온과 세린은 눈이 푸르렀다", p23/p29, by design), "그녀의" in a sentence that names someone else (p42, by design), a height said as a verb (p14); the 6 mutable ones, not extracted yet. A value that is a verb stem ("붉었다" -> '붉') is still cut at the stem, which the gold accepts but a card shows as it is.

The set is small and these rules were written looking at its passages, so this says the rules do what they were made for, not how they do on other prose. Precision stays 1.000.

# Ground truth: Claudictive beta interviews (SYNTHETIC)

Rendered from `GROUND-TRUTH.json`, which is authoritative. Invented data; nothing is real speech.

## Summary

| Topic | Raised in | Volunteered in | Followed up in |
|---|---|---|---|
| Between-rounds dead time (hidden signal) | 8/12 | 8 | 0 |
| Control A: overlay covers the HUD | 5/12 | 5 | 5 |
| Control B: hotkey collision | 2/12 | 2 | 0 |

Topics the interviewer asked about (a guide question, an off-script question or a pitch). A correct detector keeps them out of "raised without being asked": none is volunteered in 3 or more interviews.

| Topic | Occurrences | Prompted | Volunteered | Raised in | Volunteered in |
|---|---|---|---|---|---|
| voice | 21 | 21 | 0 | 12/12 | 0 |
| themes | 14 | 12 | 2 | 12/12 | 2 |
| price | 21 | 21 | 0 | 12/12 | 0 |

Guide questions really asked: 109 across the 12 interviews (91 in the ten Hebrew ones).

## Topics

- **between_rounds_aside**: THE HIDDEN SIGNAL. The interviewee mentions, in passing, the dead time between rounds or matches (matchmaking queue, loading screen, lobby, waiting to respawn, draft/picking phase, warmup) as when they actually talk to Claude or already alt-tab to check things. Never followed up: the next interviewer turn moves to a scripted question.
- **control_a_overlay_covers_hud**: CONTROL A (followed up). The overlay window opens on top of part of the game HUD (minimap, kill feed, hotbar, clock). Every time it is raised, the interviewer asks a follow-up that engages it. A correct 'missed' detector must NOT flag this topic.
- **control_b_hotkey_collision**: CONTROL B (below the noise floor). The default Claudictive hotkey collides with another binding (Discord push-to-talk, a game's quick-save). Raised in only 2 interviews, not followed up; a detector with a 3-interview floor must NOT surface it.

## Per interview

| File | Persona | Turns | Length | Between-rounds | Control A | Control B |
|---|---|---|---|---|---|---|
| `transcripts/01-yoni.txt` | Indie game developer (Unity, solo studio), plays League of Legends most evenings | 54 | 00:17:02 | turn 16 (missed) | - | - |
| `transcripts/02-maya.txt` | Backend engineer at a fintech (Go, Kubernetes), plays Overwatch 2 ranked a few nights a week | 50 | 00:19:03 | turn 16 (missed) | turn 18 (followed up) | - |
| `transcripts/03-itay.txt` | Computer-science student (third year), competitive Valorant player (Immortal rank), uses Claude Code for coursework | 46 | 00:21:03 | turn 26 (missed) | - | - |
| `transcripts/04-shira.txt` | QA automation engineer (Playwright, Python), plays Apex Legends with a regular squad | 46 | 00:18:03 | - | turn 16 (followed up) | - |
| `transcripts/05-daniel.txt` | Engineering team lead (8 reports, SaaS company; spent five years in the US so the interview is mostly in English), plays EA Sports FC Ultimate Team late at night | 50 | 00:20:03 | turn 16 (missed) | - | - |
| `transcripts/06-noa.txt` | Data scientist at a health-tech startup (Python, notebooks, long training jobs), plays Rocket League 2v2 | 46 | 00:19:03 | turn 16 (missed) | - | turn 12 (missed) |
| `transcripts/07-avi.txt` | Freelance full-stack developer and father of two, very little free time, plays Fortnite with his 11-year-old son on weekends | 48 | 00:16:03 | - | turn 16 (followed up) | - |
| `transcripts/08-tamar.txt` | Mobile developer (Kotlin and Swift) at an agency, long-time Dota 2 player | 52 | 00:22:02 | turn 18 (missed) | - | - |
| `transcripts/09-omer.txt` | DevOps engineer (Terraform, AWS), casual player of Minecraft survival and Stardew Valley | 48 | 00:17:03 | - | turn 16 (followed up) | - |
| `transcripts/10-lior.txt` | Frontend developer (React, TypeScript) at a remote-first US startup, works in English all day, plays Counter-Strike 2 premier | 46 | 00:18:03 | turn 16 (missed) | - | - |
| `transcripts/11-gal.txt` | Gameplay programmer at a mid-size mobile game studio (C++, Unreal), plays PUBG Battlegrounds with coworkers after work | 56 | 00:23:03 | turn 16 (missed) | turn 20 (followed up) | - |
| `transcripts/12-roni.txt` | Bootcamp graduate looking for a first junior job, casual player of single-player RPGs (Baldur's Gate 3, The Sims 4) | 50 | 00:15:02 | - | - | turn 14 (missed) |

## The asides and what the interviewer said next

### transcripts/01-yoni.txt, Between-rounds, turn 16

> Yoni: בעיקר כשאני מחכה בqueue, זה כמו חמש דקות של כלום ואני ממילא בוהה במסך.

Next interviewer turn (17): מעולה, מעולה. ואיזה features היית רוצה שנוסיף?

Followed up: **no**

### transcripts/02-maya.txt, Between-rounds, turn 16

> Maya: בין round לround אני ממילא עושה alt-tab לבדוק אם הpipeline עבר, אז ככה זה יותר נוח.

Next interviewer turn (17): מעולה. איזה features חסרים לך?

Followed up: **no**

### transcripts/02-maya.txt, Control A, turn 18

> Maya: יש פעם אחת שהחלון פשוט כיסה לי את הkill feed ואת חצי מהHUD, ולא ראיתי שמישהו מגיע מאחורה.

Next interviewer turn (19): רגע, מה זאת אומרת כיסה? תספרי לי בדיוק מתי זה קרה.

Followed up: **yes**

### transcripts/03-itay.txt, Between-rounds, turn 26

> Itay: אחרי שאני מת ואני מחכה לround הבא, יש לי שלושים-ארבעים שניות שאני רק צופה בחברים, אז אני זורק לו שאלה.

Next interviewer turn (27): מעולה. והחלק הכי פחות אהוב?

Followed up: **no**

### transcripts/04-shira.txt, Control A, turn 16

> Shira: החלון. הוא נפתח בדיוק על הminimap בפינה, ובApex אם אתה לא רואה את הring אתה מת.

Next interviewer turn (17): רגע, תסבירי לי. מתי זה קרה בפעם האחרונה? מה בדיוק ראית?

Followed up: **yes**

### transcripts/05-daniel.txt, Between-rounds, turn 16

> Daniel: Mostly it's while the game is loading, the loading in FC takes forever, so I'm already checking Slack on my phone anyway.

Next interviewer turn (17): Great. What features would you like to see?

Followed up: **no**

### transcripts/06-noa.txt, Between-rounds, turn 16

> Noa: בין משחק למשחק, כשהוא מחפש match, אני ממילא מציצה בnotebook במסך השני, אז זה פשוט יותר נוח לשאול אותו.

Next interviewer turn (17): מעולה. ואיזה features את רוצה?

Followed up: **no**

### transcripts/06-noa.txt, Control B, turn 12

> Noa: הhotkey. הdefault שלכם זה אותו key שיש לי לpush-to-talk בDiscord, אז כל פעם שדיברתי עם החבר שלי נפתח החלון.

Next interviewer turn (13): הבנתי. מעולה. בואי נעבור לשאלה הבאה. כמה פעמים בשבוע את משתמשת?

Followed up: **no**

### transcripts/07-avi.txt, Control A, turn 16

> Avi: כן, פעם אחת פתחתי אותו והוא כיסה לי את המפה בפינה, והבן שלי צעק עליי שאני לא רואה את הסטורם.

Next interviewer turn (17): חח, רגע, מה זאת אומרת כיסה? איפה בדיוק הוא נפתח?

Followed up: **yes**

### transcripts/08-tamar.txt, Between-rounds, turn 18

> Tamar: האמת שאני כותבת לו בעיקר בqueue ובpicking phase, יש שם זמן מת ואני לא צריכה לעשות כלום.

Next interviewer turn (19): מעולה. בואי נדבר על features. מה היית רוצה שנוסיף?

Followed up: **no**

### transcripts/09-omer.txt, Control A, turn 16

> Omer: הוא מכסה את הhotbar. החלון נפתח למטה באמצע, בדיוק על הinventory bar.

Next interviewer turn (17): רגע, תראה לי, מה זאת אומרת מכסה? באיזה מצב זה קרה?

Followed up: **yes**

### transcripts/10-lior.txt, Between-rounds, turn 16

> Lior: Honestly between rounds I check Slack anyway, and the warmup before a match too, so I just open Claude there instead.

Next interviewer turn (17): Great. What features would you like?

Followed up: **no**

### transcripts/11-gal.txt, Between-rounds, turn 16

> Gal: בPUBG יש את הlobby ואת המטוס, זה דקה וחצי שאתה סתם יושב, אז שם אני כותב לו.

Next interviewer turn (17): מעולה. איזה features היית רוצה?

Followed up: **no**

### transcripts/11-gal.txt, Control A, turn 20

> Gal: כן, הדבר הכי מעצבן, החלון יושב בדיוק על הminimap בפינה הימנית למטה. בPUBG זה המפה שלך, בלי זה אתה עיוור.

Next interviewer turn (21): רגע, מה זאת אומרת יושב על הminimap? מתי זה קרה לך? תתאר לי.

Followed up: **yes**

### transcripts/12-roni.txt, Control B, turn 14

> Roni: כן, הhotkey שלכם זה אותו מקש שיש לי בBG3 לquick save. אז כל פעם ששמרתי, נפתח החלון. ולהפך.

Next interviewer turn (15): מעולה. בואי נעבור לשאלה הבאה. כמה פעמים את משתמשת?

Followed up: **no**

## Prompted or volunteered

The rules the answer key follows (`prompted_policy` in the JSON):

- **prompted**: An interviewee turn is PROMPTED when it answers an interviewer question or pitch about its topic, and VOLUNTEERED otherwise.
- **pitch**: A pitch or a leading question about a topic ('wouldn't voice be amazing mid-fight?') counts as asking about it.
- **broad**: A broad question asks only for what it names: 'what features would you like?' asks about every feature wish; 'what do you usually do with it?' asks WHAT, not WHEN, WHERE or WHY; an open question ('anything bothering you?', 'your favourite part?', 'anything to add?') names nothing, so what comes up in answer to it was volunteered.
- **continuation**: A bare 'anything else?' / 'what else?' continues the question before it: in the middle of the features talk it asks for more features.
- **guide_s6**: s6 (voice) counts as asked only where voice was asked about neutrally; a pitch about voice is a pitch, recorded under pitches.

Every planted aside and control line above is VOLUNTEERED; the question it answers, and why that question does not ask about it, is in the JSON (`answers_turn`, `why_not_prompted`).

### `transcripts/01-yoni.txt`

- Guide questions asked: s1 (turn 3), s2 (turn 9), s3 (turn 13), s4 (turn 15), s5 (turn 17), s7 (turn 29), s8 (turn 33), s9 (turn 39), s10 (turn 51)
- Not asked: s6
- Pitches: turn 19 (voice, in_match); turn 35 (price)
- voice: turn 18 prompted by 17 (s5 features); turn 20 prompted by 19 (pitch)
- themes: turn 22 prompted by 21 ('anything else?' continues s5)
- price: turn 34 prompted by 33 (s8 pay); turn 36 prompted by 35 (pitch (price anchor))
- between-rounds: turn 16 VOLUNTEERED, answers turn 15 (s4 'what do you do with it?' asks WHAT, not WHEN)

### `transcripts/02-maya.txt`

- Guide questions asked: s1 (turn 3), s2 (turn 9), s3 (turn 13), s4 (turn 15), s5 (turn 17), s7 (turn 31), s8 (turn 37), s9 (turn 41), s10 (turn 47)
- Not asked: s6
- Pitches: turn 29 (mobile_app); turn 35 (in_match)
- Off-script questions on a topic: turn 39 (price)
- voice: turn 28 prompted by 27 ('more features?' continues s5)
- themes: turn 28 prompted by 27 ('more features?' continues s5)
- price: turn 38 prompted by 37 (s8 pay); turn 40 prompted by 39 (off-script 'what would make you pay more?')
- between-rounds: turn 16 VOLUNTEERED, answers turn 15 (s4 asks WHAT, not WHEN)
- control A: turn 18 VOLUNTEERED, answers turn 17 (s5 asks for features; a complaint is not a feature wish)

### `transcripts/03-itay.txt`

- Guide questions asked: s1 (turn 3), s2 (turn 9), s3 (turn 13), s5 (turn 17), s8 (turn 29), s9 (turn 35), s10 (turn 43)
- Not asked: s4, s6, s7
- Pitches: turn 19 (voice, in_match); turn 21 (voice); turn 31 (voice, price)
- voice: turn 22 prompted by 21 (pitch); turn 32 prompted by 31 (pitch (voice and price))
- themes: turn 24 prompted by 23 ('anything else?' continues the features talk (s5))
- price: turn 30 prompted by 29 (s8 pay); turn 32 prompted by 31 (pitch (voice and price))
- between-rounds: turn 26 VOLUNTEERED, answers turn 25 ('your favourite part?' names nothing)

### `transcripts/04-shira.txt`

- Guide questions asked: s1 (turn 3), s2 (turn 7), s3 (turn 11), s4 (turn 13), s5 (turn 25), s7 (turn 31), s8 (turn 35), s9 (turn 37), s10 (turn 43)
- Not asked: s6
- Pitches: turn 29 (mobile_app, in_match); turn 39 (in_match)
- Off-script questions on a topic: turn 27 (themes)
- voice: turn 26 prompted by 25 (s5 features)
- themes: turn 28 prompted by 27 (off-script 'what about themes?')
- price: turn 36 prompted by 35 (s8 pay)
- control A: turn 16 VOLUNTEERED, answers turn 15 ('what bothers you most?' names nothing)

### `transcripts/05-daniel.txt`

- Guide questions asked: s1 (turn 3), s2 (turn 9), s3 (turn 13), s4 (turn 15), s5 (turn 17), s7 (turn 25), s8 (turn 29), s9 (turn 33), s10 (turn 47)
- Not asked: s6
- Pitches: turn 19 (voice, in_match); turn 41 (mobile_app)
- Off-script questions on a topic: turn 23 (themes); turn 31 (price)
- voice: turn 18 prompted by 17 (s5 features); turn 20 prompted by 19 (pitch)
- themes: turn 24 prompted by 23 (off-script 'what about themes?')
- price: turn 30 prompted by 29 (s8 pay); turn 32 prompted by 31 (off-script 'how much?')
- between-rounds: turn 16 VOLUNTEERED, answers turn 15 (s4 asks WHAT, not WHEN)

### `transcripts/06-noa.txt`

- Guide questions asked: s1 (turn 3), s2 (turn 9), s3 (turn 13), s4 (turn 15), s5 (turn 17), s8 (turn 27), s7 (turn 31), s9 (turn 33), s10 (turn 43)
- Not asked: s6
- Pitches: turn 21 (voice); turn 23 (voice); turn 29 (price)
- Off-script questions on a topic: turn 37 (themes)
- voice: turn 20 prompted by 19 ('more?' continues s5); turn 22 prompted by 21 (pitch (leading))
- themes: turn 38 prompted by 37 (off-script 'what about the design?')
- price: turn 28 prompted by 27 (s8 pay); turn 30 prompted by 29 (pitch (price anchor))
- between-rounds: turn 16 VOLUNTEERED, answers turn 15 (s4 asks WHAT, not WHEN)
- control B: turn 12 VOLUNTEERED, answers turn 11 ('was anything hard?' asks about the install)

### `transcripts/07-avi.txt`

- Guide questions asked: s1 (turn 3), s2 (turn 9), s3 (turn 11), s4 (turn 13), s5 (turn 25), s7 (turn 35), s8 (turn 37), s9 (turn 41), s10 (turn 45)
- Not asked: s6
- Pitches: turn 43 (in_match)
- Off-script questions on a topic: turn 33 (themes)
- voice: turn 30 prompted by 29 ('more features?' continues s5)
- themes: turn 34 prompted by 33 (off-script 'what about themes?')
- price: turn 38 prompted by 37 (s8 pay)
- control A: turn 16 VOLUNTEERED, answers turn 15 ('anything bothering you?' names nothing)

### `transcripts/08-tamar.txt`

- Guide questions asked: s1 (turn 3), s2 (turn 9), s3 (turn 13), s4 (turn 15), s5 (turn 19), s6 (turn 23), s7 (turn 27), s8 (turn 33), s9 (turn 37), s10 (turn 49)
- Not asked: -
- Pitches: turn 25 (voice, in_match); turn 31 (reminder); turn 35 (price)
- voice: turn 24 prompted by 23 (s6 voice); turn 26 prompted by 25 (pitch)
- themes: turn 22 prompted by 21 ('more?' continues s5)
- price: turn 34 prompted by 33 (s8 pay); turn 36 prompted by 35 (pitch (price anchor))
- between-rounds: turn 18 VOLUNTEERED, answers turn 17 ('how do you feel about its speed?' asks about speed)

### `transcripts/09-omer.txt`

- Guide questions asked: s1 (turn 3), s2 (turn 9), s3 (turn 11), s4 (turn 13), s5 (turn 25), s6 (turn 27), s7 (turn 33), s8 (turn 35), s9 (turn 39), s10 (turn 45)
- Not asked: -
- Pitches: turn 29 (voice)
- Off-script questions on a topic: turn 31 (themes); turn 37 (price)
- voice: turn 28 prompted by 27 (s6 voice); turn 30 prompted by 29 (pitch (leading))
- themes: turn 32 prompted by 31 (off-script 'what about themes?'); turn 46 VOLUNTEERED by 45 (s10 'anything to add?' names nothing)
- price: turn 36 prompted by 35 (s8 pay); turn 38 prompted by 37 (off-script 'how much?')
- control A: turn 16 VOLUNTEERED, answers turn 15 ('anything bothering you?' names nothing)

### `transcripts/10-lior.txt`

- Guide questions asked: s1 (turn 3), s2 (turn 9), s3 (turn 13), s4 (turn 15), s5 (turn 17), s7 (turn 23), s8 (turn 27), s9 (turn 29), s10 (turn 43)
- Not asked: s6
- Pitches: turn 21 (voice, in_match); turn 37 (themes)
- voice: turn 20 prompted by 19 ('what else?' continues s5); turn 22 prompted by 21 (pitch)
- themes: turn 36 VOLUNTEERED by 35 ('the thing you like least?' names nothing); turn 38 prompted by 37 (pitch)
- price: turn 28 prompted by 27 (s8 pay)
- between-rounds: turn 16 VOLUNTEERED, answers turn 15 (s4 asks WHAT, not WHEN)

### `transcripts/11-gal.txt`

- Guide questions asked: s1 (turn 3), s2 (turn 9), s3 (turn 11), s4 (turn 15), s5 (turn 17), s7 (turn 35), s8 (turn 37), s9 (turn 41), s10 (turn 53)
- Not asked: s6
- Pitches: turn 29 (transparent_window); turn 33 (voice, in_match)
- Off-script questions on a topic: turn 39 (price); turn 45 (themes)
- voice: turn 32 prompted by 31 ('more features?' continues s5); turn 34 prompted by 33 (pitch)
- themes: turn 46 prompted by 45 (off-script 'what about themes?')
- price: turn 38 prompted by 37 (s8 pay); turn 40 prompted by 39 (off-script 'how much?')
- between-rounds: turn 16 VOLUNTEERED, answers turn 15 (s4 asks WHAT, not WHEN)
- control A: turn 20 VOLUNTEERED, answers turn 19 ('anything else?' continues s5; a complaint is not a feature wish)

### `transcripts/12-roni.txt`

- Guide questions asked: s1 (turn 3), s2 (turn 11), s3 (turn 15), s4 (turn 17), s5 (turn 19), s6 (turn 21), s7 (turn 35), s8 (turn 37), s9 (turn 41), s10 (turn 47)
- Not asked: -
- Pitches: turn 23 (voice); turn 39 (price)
- voice: turn 22 prompted by 21 (s6 voice); turn 24 prompted by 23 (pitch (leading))
- themes: turn 20 prompted by 19 (s5 features)
- price: turn 38 prompted by 37 (s8 pay); turn 40 prompted by 39 (pitch (price anchor))
- control B: turn 14 VOLUNTEERED, answers turn 13 ('anything else?' continues the install question)

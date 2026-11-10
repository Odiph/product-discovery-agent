# Ground truth: Claudictive beta interviews (SYNTHETIC)

Rendered from `GROUND-TRUTH.json`, which is authoritative. Invented data; nothing is real speech.

## Summary

| Topic | Raised in | Followed up in |
|---|---|---|
| Between-rounds dead time (hidden signal) | 8/12 | 0 |
| Control A: overlay covers the HUD | 5/12 | 5 |
| Control B: hotkey collision | 2/12 | 0 |

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

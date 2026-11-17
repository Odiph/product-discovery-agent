# Ground truth: Shmuber Eats beta interviews (SYNTHETIC)

Rendered from `GROUND-TRUTH.json`, which is authoritative. Invented data; nothing is real speech.

## Summary

| Topic | Raised in | Volunteered in | Followed up in |
|---|---|---|---|
| One-off first order (hidden signal) | 8/12 | 8 | 0 |
| Control A: swap wrong for the recipe | 5/12 | 5 | 5 |
| Control B: logged out at checkout | 2/12 | 2 | 0 |
| Carrying heavy shopping (NOT planted, found by the model run) | 6/12 | 6 | 0 |

Topics the interviewer asked about (a guide question, an off-script question or a pitch). A correct detector keeps them out of "raised without being asked": none is volunteered in 3 or more interviews.

| Topic | Occurrences | Prompted | Volunteered | Raised in | Volunteered in |
|---|---|---|---|---|---|
| substitutions | 24 | 24 | 0 | 12/12 | 0 |
| delivery window | 22 | 20 | 2 | 12/12 | 2 |
| pass price | 23 | 23 | 0 | 12/12 | 0 |

Guide questions really asked: 115 across the 12 interviews. Pitches: 11.

## Topics

- **first_order_trigger_aside**: THE HIDDEN SIGNAL. The interviewee mentions, in passing, that their FIRST order was set off by a one-off situation (a sick child, a car in the garage, a house move, a work deadline, a sprained ankle, a newborn, a snowstorm, guests arriving that night), not a wish to change how they shop, and that once it passed they went back to their usual store. No hypothesis predicts it, and it undercuts the substitution bet. Never followed up: the next interviewer turn moves to a guide question.
- **control_a_odd_swap_for_recipe**: CONTROL A (followed up). The interviewee volunteers that the picker's replacement was wrong for the dish they were cooking (a coconut drink for curry coconut milk, cake flour for pizza dough, spicy tortillas for small children, margarine for buttercream, smoked salmon slices for a baked fillet). Every time, the interviewer asks a follow-up that engages it. A correct 'missed' detector must NOT flag this topic.
- **control_b_logged_out_at_checkout**: CONTROL B (below the noise floor). The app logged the interviewee out at the moment of paying. Raised in only 2 interviews, not followed up; a detector with a 3-interview floor must NOT surface it.
- **substitutions**: PROMPTED guide topic: substituted items in general (guide question s5, its follow-on questions and one pitch).
- **delivery_window**: PROMPTED guide topic: the two-hour delivery window (guide question s7 and its follow-on questions). Volunteered twice.
- **pass_price**: PROMPTED guide topic: a monthly delivery pass and its price (guide question s8, price anchors and follow-on questions).
- **carrying_heavy_shopping**: NOT PLANTED, found by the first model run (2026-11-17) and then keyed by hand: the interviewee names not having to carry heavy shopping (water, rice, bags on the bus, stairs) as a reason to order or as what they value. Always volunteered, never followed up. Two of its lines (02 t4, 07 t8) are also planted first-order asides, told as 'I could not carry it home'. Driver-courtesy remarks (01 t32, 07 t28) are not counted.

## Per interview

| File | Persona | Turns | Length | One-off first order | Control A | Control B |
|---|---|---|---|---|---|---|
| `transcripts/01-priya.txt` | Nurse, married with two boys (7 and 10); her husband works hospital shifts, she does a Saturday big shop | 44 | 00:17:12 | turn 10 (missed) | - | - |
| `transcripts/02-marcus.txt` | Warehouse shift supervisor, lives with his partner and her 15-year-old daughter; shops at a discount store on the drive home | 42 | 00:16:08 | turn 4 (missed) | - | - |
| `transcripts/03-elena.txt` | Chemistry master's student sharing a fourth-floor flat with three flatmates; cooks one big curry a week | 44 | 00:19:21 | - | turn 10 (followed up) | - |
| `transcripts/04-tomasz.txt` | Keen home cook, lives with his wife and her brother; recently moved flats | 44 | 00:20:37 | turn 10 (missed) | turn 32 (followed up) | - |
| `transcripts/05-aisha.txt` | Management consultant living alone, travels half the month; shops at a small store under her office | 42 | 00:18:04 | turn 14 (missed) | - | turn 12 (missed) |
| `transcripts/06-kenji.txt` | Architect, both parents work full time, four-year-old twins; orders every week and shares the in-app list | 44 | 00:22:31 | - | turn 36 (followed up) | - |
| `transcripts/07-rosa.txt` | Retired, lives with her retired husband and minds two grandchildren after school; shops at a weekly market | 42 | 00:15:42 | turn 8 (missed) | - | - |
| `transcripts/08-dev.txt` | New father (ten-week-old son), lives with his partner; they used to do one big Sunday shop together | 44 | 00:20:16 | turn 6 (missed) | - | - |
| `transcripts/09-fatima.txt` | Runs a household of six on a tight budget; monthly wholesale trip plus a weekly supermarket shop | 42 | 00:21:49 | - | turn 16 (followed up) | - |
| `transcripts/10-liam.txt` | PE teacher living with his girlfriend, a nurse, on opposite hours; cycles to the supermarket | 42 | 00:16:47 | turn 28 (missed) | - | - |
| `transcripts/11-grace.txt` | Retired primary-school teacher living alone, no car; her daughter, two hours away, asked her to try the app | 52 | 00:22:58 | - | turn 10 (followed up) | turn 16 (missed) |
| `transcripts/12-omar.txt` | Lives with his wife, their 8-year-old son and his mother-in-law, who runs the kitchen; Friday shop at a butcher and supermarket | 44 | 00:18:33 | turn 10 (missed) | - | - |

## The planted lines and what the interviewer said next

### transcripts/01-priya.txt, One-off first order, turn 10

> Priya: My little one had a proper fever that week and I could not drag him round a supermarket, so I sat on the sofa with him and did the whole thing on my phone. Once he was better we were straight back to Saturdays at the big shop, to be honest.

Next interviewer turn (11): Great. Let's move on. How often do you order groceries online?

Followed up: **no**

### transcripts/02-marcus.txt, One-off first order, turn 4

> Marcus: The only reason your app was even on my phone is the clutch went on the car and it sat in the garage for a week waiting on parts, and I wasn't carrying six bags home on the bus. Got the car back and that was that, discount place on the way home again.

Next interviewer turn (5): Great, great. And how did you hear about Shmuber Eats?

Followed up: **no**

### transcripts/03-elena.txt, Control A, turn 10

> Elena: instead of the coconut milk in a tin they'd given me a carton of the coconut drink, the thin one you put in cereal, which for a curry is just water, it splits.

Next interviewer turn (11): Wait, the drink instead of the tin? What did you do with the curry?

Followed up: **yes**

### transcripts/04-tomasz.txt, One-off first order, turn 10

> Tomasz: this was the week we got the keys to the new flat, boxes up to the ceiling, I had no idea where the nearest shop even was, and our car was still parked at Ana's parents'. Now we've unpacked, I know there's a really decent market ten minutes' walk away, so that's where I go.

Next interviewer turn (11): Okay. Let's move on. How often do you order groceries online?

Followed up: **no**

### transcripts/04-tomasz.txt, Control A, turn 32

> Tomasz: I'd asked for strong bread flour for the pizza dough, and they swapped it for a bag of self-raising cake flour, which, for pizza, it puffs up like a sponge.

Next interviewer turn (33): Oh no. Self-raising for pizza dough? What happened with the pizza?

Followed up: **yes**

### transcripts/05-aisha.txt, One-off first order, turn 14

> Aisha: It was the week before a big client deadline, I was at my desk from seven till midnight, I genuinely could not leave the flat. When the project shipped I went straight back to grabbing things at lunch from the little shop under the office.

Next interviewer turn (15): Great. Tell me about the last time an item in your order was substituted.

Followed up: **no**

### transcripts/05-aisha.txt, Control B, turn 12

> Aisha: at checkout it logged me out, right when I pressed pay, and I had to log in again and the basket was half empty.

Next interviewer turn (13): Okay. Let's move on. How often do you order groceries online?

Followed up: **no**

### transcripts/06-kenji.txt, Control A, turn 36

> Kenji: I'd asked for plain flour tortillas, and the picker swapped them for chili-lime ones, the spicy red kind, for taco night with two four-year-olds.

Next interviewer turn (37): Chili-lime for the twins? How did that go?

Followed up: **yes**

### transcripts/07-rosa.txt, One-off first order, turn 8

> Rosa: I'd turned my ankle stepping off the bus and I was on crutches for nearly three weeks, I couldn't carry a thing. Now I'm walking properly again I'm at the market on Tuesdays like always.

Next interviewer turn (9): Great, great. Walk me through your last order, from opening the app to putting things away.

Followed up: **no**

### transcripts/08-dev.txt, One-off first order, turn 6

> Dev: When we brought him home from the hospital neither of us was leaving the flat, we were basically zombies for a couple of weeks, so that's when the app came out. These days Mira takes him out in the pram to the shops in the afternoon, it gets her out of the house, so we just do that.

Next interviewer turn (7): Great, great. Walk me through your last Shmuber Eats order, from opening the app to putting things away.

Followed up: **no**

### transcripts/09-fatima.txt, Control A, turn 16

> Fatima: I'd written unsalted butter for the buttercream, and the picker sent a tub of margarine instead, the soft one for toast, and the icing just slid off the cake.

Next interviewer turn (17): Oh no, margarine for buttercream? What did you do?

Followed up: **yes**

### transcripts/10-liam.txt, One-off first order, turn 28

> Liam: That was the two days the whole street was snowed in, the buses stopped, I wasn't getting the bike out in that, so it was the app or eating tins. Once the roads were clear I was back on the bike to the high street.

Next interviewer turn (29): Great, great. Would you recommend Shmuber Eats to a friend?

Followed up: **no**

### transcripts/11-grace.txt, Control A, turn 10

> Grace: But instead of a salmon fillet they sent a packet of smoked salmon slices, the kind for sandwiches, and you can't bake those, they'd just turn to leather.

Next interviewer turn (11): Smoked slices for a baked fillet? What did you end up making?

Followed up: **yes**

### transcripts/11-grace.txt, Control B, turn 16

> Grace: When I got to the very end, to pay, it threw me out, it logged me out completely, and I had to ring my daughter to remember my password.

Next interviewer turn (17): Okay. Great. Let's move on. How often do you order groceries online?

Followed up: **no**

### transcripts/12-omar.txt, One-off first order, turn 10

> Omar: Leila's cousins rang at four in the afternoon to say they were driving up from the coast and would be with us for dinner, all six of them, and there was no time to go out and also cook. Friday mornings with her mother at the butcher is still how we do it, that was a one-time rescue.

Next interviewer turn (11): Great. Let's move on. How often do you order groceries online?

Followed up: **no**

## The unplanted theme: carrying heavy shopping

Not planted. The first model run grouped it as its headline topic, and it was then keyed by hand from the transcripts.

- `transcripts/02-marcus.txt` turn 4: It's me, my partner Dana and her daughter, she's fifteen. I do the shopping mostly, I stop at the discount place on my way home from the warehouse. The only reason your app was even on my phone is the clutch went on the car and it sat in the garage for a week waiting on parts, and I wasn't carrying six bags home on the bus. Got the car back and that was that, discount place on the way home again. (next: Great, great. And how did you hear about Shmuber Eats?; followed up: no. Also a planted one-off first order line.)
- `transcripts/03-elena.txt` turn 8: It was on the student discount site. A big first-order discount, so I thought, okay, let's actually try it properly. We're on the fourth floor, no lift, and I'm tired of hauling water bottles up the stairs. (next: Great. Walk me through your last order, from opening the app to putting things away.; followed up: no.)
- `transcripts/03-elena.txt` turn 36: Not carrying the water up. That's the whole thing for me. (next: Haha. And what did you like least?; followed up: no.)
- `transcripts/07-rosa.txt` turn 8: My granddaughter put it on my phone. I'd turned my ankle stepping off the bus and I was on crutches for nearly three weeks, I couldn't carry a thing. So she said, Grandma, just press here. Now I'm walking properly again I'm at the market on Tuesdays like always. (next: Great, great. Walk me through your last order, from opening the app to putting things away.; followed up: no. Also a planted one-off first order line.)
- `transcripts/09-fatima.txt` turn 14: Maybe once a month now. For the heavy things. Rice, oil, water. (next: Okay. How do you keep track of what you need between orders?; followed up: no.)
- `transcripts/09-fatima.txt` turn 32: For the heavy things, yes. For fresh, I still like to choose myself. (next: Great. What did you like most?; followed up: no.)
- `transcripts/09-fatima.txt` turn 34: Not carrying the rice. Twenty kilos, with four children, that is a job. (next: And what did you like least?; followed up: no.)
- `transcripts/11-grace.txt` turn 38: Not standing at the bus stop with heavy bags in the rain. (next: And what do you like least?; followed up: no.)
- `transcripts/12-omar.txt` turn 14: Easy. Twelve big bottles, and the driver carried them in. My back thanked him. (next: Great. Tell me about the last time an item in your order was substituted.; followed up: no.)

## Asked, pitched and prompted, per interview

Which guide questions the interviewer really asked (the answer key for `coverage`), where they pitched, and for every mention of the three guide topics whether it answered a question or pitch about it.

### `transcripts/01-priya.txt`

- Guide questions asked: s1 (turn 5), s2 (turn 7), s3 (turn 9), s4 (turn 11), s5 (turn 15), s6 (turn 19), s7 (turn 23), s8 (turn 27), s9 (turn 31), s10 (turn 41)
- Not asked: -
- Pitches: turn 29 (pass_price)
- Off-script questions on a topic: turn 17 (substitutions); turn 25 (delivery_window)
- substitutions: turn 16 prompted by 15 (s5 substitutions); turn 18 prompted by 17 (off-script follow-on question)
- delivery window: turn 24 prompted by 23 (s7 delivery window); turn 26 prompted by 25 (off-script follow-on question)
- pass price: turn 28 prompted by 27 (s8 delivery pass); turn 30 prompted by 29 (pitch (price anchor))
- one-off first order: turn 10 VOLUNTEERED, answers turn 9 (s3 asks HOW the order went, not WHY they ordered)

### `transcripts/02-marcus.txt`

- Guide questions asked: s1 (turn 3), s2 (turn 5), s3 (turn 7), s4 (turn 13), s5 (turn 15), s6 (turn 19), s7 (turn 23), s8 (turn 25), s9 (turn 31), s10 (turn 39)
- Not asked: -
- Pitches: turn 21 (shared_list); turn 27 (pass_price)
- Off-script questions on a topic: turn 17 (substitutions)
- substitutions: turn 16 prompted by 15 (s5 substitutions); turn 18 prompted by 17 (off-script follow-on question)
- delivery window: turn 24 prompted by 23 (s7 delivery window); turn 34 VOLUNTEERED by 33 ('what would make you use it more?' names nothing)
- pass price: turn 26 prompted by 25 (s8 delivery pass); turn 28 prompted by 27 (pitch (price anchor))
- one-off first order: turn 4 VOLUNTEERED, answers turn 3 (s1 asks who does the shopping, not why they first ordered)

### `transcripts/03-elena.txt`

- Guide questions asked: s1 (turn 5), s2 (turn 7), s3 (turn 9), s4 (turn 15), s5 (turn 19), s6 (turn 23), s7 (turn 25), s8 (turn 29), s9 (turn 33), s10 (turn 41)
- Not asked: -
- Off-script questions on a topic: turn 21 (substitutions); turn 27 (delivery_window)
- substitutions: turn 20 prompted by 19 (s5 substitutions); turn 22 prompted by 21 (off-script follow-on question)
- delivery window: turn 26 prompted by 25 (s7 delivery window); turn 28 prompted by 27 (off-script follow-on question)
- pass price: turn 30 prompted by 29 (s8 delivery pass)
- control A: turn 10 VOLUNTEERED, answers turn 9 (s3 asks how the order went, not about swaps)

### `transcripts/04-tomasz.txt`

- Guide questions asked: s1 (turn 5), s2 (turn 7), s3 (turn 9), s4 (turn 11), s5 (turn 15), s6 (turn 19), s7 (turn 23), s8 (turn 25), s9 (turn 39), s10 (turn 41)
- Not asked: -
- Off-script questions on a topic: turn 17 (substitutions); turn 27 (pass_price)
- substitutions: turn 16 prompted by 15 (s5 substitutions); turn 18 prompted by 17 (off-script follow-on question)
- delivery window: turn 24 prompted by 23 (s7 delivery window)
- pass price: turn 26 prompted by 25 (s8 delivery pass); turn 28 prompted by 27 (off-script follow-on question)
- one-off first order: turn 10 VOLUNTEERED, answers turn 9 (s3 asks HOW the order went, not WHY they ordered)
- control A: turn 32 VOLUNTEERED, answers turn 31 ('what did you like least?' names nothing)

### `transcripts/05-aisha.txt`

- Guide questions asked: s1 (turn 5), s2 (turn 7), s3 (turn 9), s4 (turn 13), s5 (turn 15), s6 (turn 19), s7 (turn 21), s8 (turn 25), s9 (turn 29), s10 (turn 39)
- Not asked: -
- Pitches: turn 27 (pass_price)
- Off-script questions on a topic: turn 17 (substitutions); turn 23 (delivery_window)
- substitutions: turn 16 prompted by 15 (s5 substitutions); turn 18 prompted by 17 (off-script follow-on question)
- delivery window: turn 22 prompted by 21 (s7 delivery window); turn 24 prompted by 23 (off-script follow-on question)
- pass price: turn 26 prompted by 25 (s8 delivery pass); turn 28 prompted by 27 (pitch (price anchor))
- one-off first order: turn 14 VOLUNTEERED, answers turn 13 (s4 asks HOW OFTEN, not WHY they ordered)
- control B: turn 12 VOLUNTEERED, answers turn 11 ('was anything confusing?' names nothing)

### `transcripts/06-kenji.txt`

- Guide questions asked: s1 (turn 5), s3 (turn 7), s4 (turn 9), s6 (turn 13), s5 (turn 17), s7 (turn 21), s8 (turn 25), s9 (turn 29), s10 (turn 41)
- Not asked: s2
- Pitches: turn 19 (substitutions); turn 27 (pass_price)
- Off-script questions on a topic: turn 23 (delivery_window)
- substitutions: turn 18 prompted by 17 (s5 substitutions); turn 20 prompted by 19 (pitch (leading))
- delivery window: turn 22 prompted by 21 (s7 delivery window); turn 24 prompted by 23 (off-script follow-on question)
- pass price: turn 26 prompted by 25 (s8 delivery pass); turn 28 prompted by 27 (pitch (price anchor))
- control A: turn 36 VOLUNTEERED, answers turn 35 ('have you ever contacted support?' asks about support, not swaps)

### `transcripts/07-rosa.txt`

- Guide questions asked: s1 (turn 5), s2 (turn 7), s3 (turn 9), s4 (turn 15), s5 (turn 17), s7 (turn 21), s8 (turn 23), s10 (turn 39)
- Not asked: s6, s9
- Off-script questions on a topic: turn 19 (substitutions); turn 25 (pass_price)
- substitutions: turn 18 prompted by 17 (s5 substitutions); turn 20 prompted by 19 (off-script follow-on question)
- delivery window: turn 22 prompted by 21 (s7 delivery window)
- pass price: turn 24 prompted by 23 (s8 delivery pass); turn 26 prompted by 25 (off-script follow-on question)
- one-off first order: turn 8 VOLUNTEERED, answers turn 7 (s2 asks how they heard of it, not why they ordered)

### `transcripts/08-dev.txt`

- Guide questions asked: s1 (turn 5), s3 (turn 7), s4 (turn 11), s5 (turn 13), s6 (turn 17), s7 (turn 21), s8 (turn 25), s2 (turn 29), s9 (turn 31), s10 (turn 41)
- Not asked: -
- Pitches: turn 27 (pass_price)
- Off-script questions on a topic: turn 15 (substitutions); turn 23 (delivery_window)
- substitutions: turn 14 prompted by 13 (s5 substitutions); turn 16 prompted by 15 (off-script follow-on question)
- delivery window: turn 22 prompted by 21 (s7 delivery window); turn 24 prompted by 23 (off-script follow-on question)
- pass price: turn 26 prompted by 25 (s8 delivery pass); turn 28 prompted by 27 (pitch (price anchor))
- one-off first order: turn 6 VOLUNTEERED, answers turn 5 (s1 asks who does the shopping, not why they first ordered)

### `transcripts/09-fatima.txt`

- Guide questions asked: s1 (turn 5), s2 (turn 7), s3 (turn 9), s4 (turn 13), s6 (turn 15), s5 (turn 21), s7 (turn 25), s8 (turn 27), s9 (turn 31), s10 (turn 39)
- Not asked: -
- Pitches: turn 29 (pass_price)
- Off-script questions on a topic: turn 23 (substitutions)
- substitutions: turn 22 prompted by 21 (s5 substitutions); turn 24 prompted by 23 (off-script follow-on question)
- delivery window: turn 26 prompted by 25 (s7 delivery window); turn 40 VOLUNTEERED by 39 (s10 'anything I didn't ask about?' names nothing)
- pass price: turn 28 prompted by 27 (s8 delivery pass); turn 30 prompted by 29 (pitch (price anchor))
- control A: turn 16 VOLUNTEERED, answers turn 15 (s6 asks how they track needs, not about swaps)

### `transcripts/10-liam.txt`

- Guide questions asked: s1 (turn 5), s2 (turn 7), s3 (turn 9), s4 (turn 13), s5 (turn 15), s7 (turn 19), s8 (turn 23), s9 (turn 29), s10 (turn 39)
- Not asked: s6
- Pitches: turn 25 (pass_price)
- Off-script questions on a topic: turn 17 (substitutions); turn 21 (delivery_window)
- substitutions: turn 16 prompted by 15 (s5 substitutions); turn 18 prompted by 17 (off-script follow-on question)
- delivery window: turn 20 prompted by 19 (s7 delivery window); turn 22 prompted by 21 (off-script follow-on question)
- pass price: turn 24 prompted by 23 (s8 delivery pass); turn 26 prompted by 25 (pitch (price anchor))
- one-off first order: turn 28 VOLUNTEERED, answers turn 27 ('what did you like most?' names nothing)

### `transcripts/11-grace.txt`

- Guide questions asked: s1 (turn 5), s2 (turn 7), s3 (turn 9), s4 (turn 17), s5 (turn 19), s6 (turn 23), s7 (turn 27), s8 (turn 31), s9 (turn 35), s10 (turn 49)
- Not asked: -
- Pitches: turn 25 (shared_list)
- Off-script questions on a topic: turn 21 (substitutions); turn 29 (delivery_window); turn 33 (pass_price)
- substitutions: turn 20 prompted by 19 (s5 substitutions); turn 22 prompted by 21 (off-script follow-on question)
- delivery window: turn 28 prompted by 27 (s7 delivery window); turn 30 prompted by 29 (off-script follow-on question)
- pass price: turn 32 prompted by 31 (s8 delivery pass); turn 34 prompted by 33 (off-script follow-on question)
- control A: turn 10 VOLUNTEERED, answers turn 9 (s3 asks how the order went, not about swaps)
- control B: turn 16 VOLUNTEERED, answers turn 15 ('was anything else difficult?' names nothing)

### `transcripts/12-omar.txt`

- Guide questions asked: s1 (turn 5), s2 (turn 7), s3 (turn 9), s4 (turn 11), s5 (turn 15), s6 (turn 19), s7 (turn 23), s8 (turn 27), s10 (turn 41)
- Not asked: s9
- Pitches: turn 29 (pass_price)
- Off-script questions on a topic: turn 17 (substitutions); turn 25 (delivery_window)
- substitutions: turn 16 prompted by 15 (s5 substitutions); turn 18 prompted by 17 (off-script follow-on question)
- delivery window: turn 24 prompted by 23 (s7 delivery window); turn 26 prompted by 25 (off-script follow-on question)
- pass price: turn 28 prompted by 27 (s8 delivery pass); turn 30 prompted by 29 (pitch (price anchor))
- one-off first order: turn 10 VOLUNTEERED, answers turn 9 (s3 asks HOW the order went, not WHY they ordered)

## Prompted policy

- **prompted**: An interviewee turn is PROMPTED when it answers an interviewer question or pitch about its topic, and VOLUNTEERED otherwise.
- **pitch**: A pitch or a leading question about a topic ('wouldn't it be great if we texted you before swapping anything?', 'what about 9.99 a month?') counts as asking about it.
- **broad**: A broad question asks only for what it names: 'walk me through your last order' asks HOW the order went, not WHY they ordered or what was swapped; 'how often do you order?' asks HOW OFTEN, not WHY; 'who does the shopping?' and 'how did you hear about it?' ask only that; an open question ('what did you like most?', 'what did you like least?', 'was anything confusing?', 'anything I didn't ask about?') names nothing, so what comes up in answer to it was volunteered.
- **continuation**: A follow-on question that names the topic ('did you know about the swap before the bags came?', 'would a two-hour slot work on a normal day?') asks about it, and is recorded under off_script_topic_questions.
- **guide_s5**: s5 (substitutions) counts as asked only where substitutions were asked about neutrally; a pitch about swaps is a pitch, recorded under pitches.

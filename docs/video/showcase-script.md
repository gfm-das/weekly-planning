# Showcase video for other missions: script and storyboard

**Purpose:** show other missions **everything** Weekly Planning can do, so they can decide to install it.
**Mood:** playful but professional. Light humour about the paperwork we escape, never about people, never about the Church or its teachings.
Think friendly tour guide, not stand-up comedian: one gentle joke per scene at most, and every joke is about a spreadsheet, a sticky note or a Sunday-evening scramble.
**Length:** about 6 to 7 minutes in 25 scenes of 10 to 25 seconds (a 90-second trailer can be cut from scenes 1, 2, 4, 9, 13, 18, 24, 25).
**Format:** 16:9, 1080p, captions burned in, chapter markers per scene.
**Data:** recorded from the **demo site** (task 26: a static copy of the portal with made-up data and a "Demo, fake data" banner), so every name, area and number is fake. No real names, photos, faces or addresses anywhere. Check each frame.

**Voice and style:** a single warm narrator, a smile in the voice. On-screen text is short (6 words or fewer) so it can be translated. A running gag allowed: a small "sticky note" mascot that is replaced by the feature in each scene (it ends the video, retired, with a tiny paper hat).

## Scene list (one scene per feature)

| # | Feature | Picture (demo site) | Voice-over | On-screen text |
|---|---|---|---|---|
| 1 | Cold open | A desk piled with sticky notes, three spreadsheets and a phone buzzing; the sticky notes whoosh away | "Every mission has a Sunday-evening scramble. This is how we cancel it." | "Say goodbye to the scramble." |
| 2 | The portal at a glance | The sign-in page, then the sidebar with its sections | "Meet Weekly Planning: one portal for the whole mission." | "One portal. Every role." |
| 3 | Sign-in and roles | Sign-in; the menu changes as three different roles are shown (missionary, leader, manager) | "Everyone sees exactly what is theirs. Not a button more, not a button less." | "Each role sees its own world." |
| 4 | Weekly Planning | A plan opens with the six key indicators first; goals; an action plan | "Planning starts with what matters: the key indicators, then your goals and your plan." | "Key indicators first." |
| 5 | Companions together | Two cursors editing one plan, a "Saved" tick | "Two companions, one plan, no overwriting. Typing at the same time is allowed." | "Plan together." |
| 6 | New Members | A person's card pre-filled from last week; two fields changed | "People who are with us week after week keep their answers. You only change what changed." | "Answers start from last week." |
| 7 | Submit and unlock | The Submit button; a locked plan; a leader's scoped unlock | "Submitting is deliberate. Unlocking is deliberate too, and only by the right person." | "Submit. Lock. Unlock with care." |
| 8 | Call-ins | A leader's Call-ins by zone and district, notes, "Complete" | "Call-ins collect the whole picture for leaders, from one page, with notes that stay put." | "Leaders see it all." |
| 9 | Overview and glimpse | The Overview: the mission glimpse appears in about a second, then tasks, calendar, announcements | "Open the Overview and the mission's heartbeat is there before you finish blinking." | "The numbers, at once." |
| 10 | Calendar | A month view; an event aimed at "Zone Leaders" | "A calendar that knows who it is for." | "Right event, right people." |
| 11 | Announcements | An announcement with attachment; read counts | "Announcements that say who has read them. Finally." | "Seen by whom? Now you know." |
| 12 | Reminders | A push reminder on a phone | "Gentle reminders, so the plan is not a Sunday surprise." | "A nudge, not a nag." |
| 13 | Dashboards | A key-indicator dashboard; a zone filter; full screen | "Dashboards that anyone can read. Pick a zone and the story changes." | "Charts that answer." |
| 14 | Archetypal Health | A mission row, "Go deeper", "What it means", a note | "Archetypal Health reads the numbers for you and says what to try next." | "Numbers, explained." |
| 15 | Presentations: library and Studio | The library; Studio editing a slide; adding a chart | "Build a meeting deck in minutes, with charts that show live numbers." | "Decks in minutes." |
| 16 | Presenting | Present mode, presenter view, PDF export, screen mirroring panel | "Present it, show it on a second screen, or export a PDF for those who weren't there." | "Present. Mirror. Export." |
| 17 | Whiteboard | A shared board, a chart pinned on it, two cursors | "A whiteboard for the ideas that don't fit a form." | "Think out loud." |
| 18 | 14 languages | The interface switching through several languages, including right-to-left | "Fourteen languages, including right-to-left ones, and a phone that behaves." | "14 languages." |
| 19 | Phone | The same page on a phone, thumbs only | "Everything on the phone. Because that is where missionaries are." | "Pocket-sized." |
| 20 | DA Management | The Data Analysts' page: accounts, planning questions | "Behind the scenes, Data Analysts keep accounts, planning questions and places in order." | "A control room for data." |
| 21 | Imports with Undo | A roster upload, an Import history batch, before/after, Undo | "Upload a roster and see the before and the after. Changed your mind? Undo." | "Every import can be undone." |
| 22 | Data uploads and places | An area-data upload, the places page | "Bring in more data, and keep zones, districts and areas tidy." | "Data in, tidy." |
| 23 | Wiki and DBeaver / Jupyter | The wiki's search; DBeaver and a notebook showing a chart (fake data) | "A built-in wiki with answers. And for the data minds, direct database access with a notebook ready to go." | "Answers and analysis." |
| 24 | Install and updates | The installer's form, a health check with all rows OK, the Updates page | "One command to install. Releases that update themselves, with a safety net. Nightly backups, because we like sleeping." | "Install in one command." |
| 25 | Closing | The sticky-note mascot retires with a tiny paper hat; the logo; where to download and the demo link | "Weekly Planning. Free, open, and ready for your mission." | "[DOWNLOAD / DEMO ADDRESS]" |


## Rules for the tone
- Playful: wordplay on paperwork, a running mascot, quick cuts, a bright music bed.
- Professional: calm pace, accurate claims, nothing that implies the portal replaces people's judgement, nothing about real missions or real people.
- Respect: no jokes about languages, countries, roles or missionaries themselves. Humour is aimed at spreadsheets, sticky notes and clocks.
- Claims must be true of the current release: re-check each scene against the release notes before recording (for example, features still in progress in the current round are left out or labelled "coming soon").

## How to produce it
1. Record each scene from the demo site with a scripted headless-browser walk-through (1920x1080, 30 fps), one clip per scene, so a scene can be re-recorded when the portal changes.
2. Voice-over: record per scene; captions from the script; translate the on-screen text through the portal's own 14 languages if subtitled versions are wanted.
3. Assemble and caption with `ffmpeg`; music bed at -18 dB under the voice.
4. Check: no real names, no live addresses, the "Demo, fake data" banner visible in at least the first and last scenes.
5. Publish the finished video where the owner decides, and link it from the wiki and the public README (the links point to this script until the video exists).

## Open questions for the owner (ASK)
1. Is the playful tone right for the Church context? Should the mascot stay, and should the video avoid naming the Church at all?
2. Which features must NOT be shown to other missions (for example, anything the owner considers specific to this mission)?
3. Where will the video be hosted, and in how many languages should it be subtitled?
4. Final address for the download card and for the demo (placeholders until the demo site is published, which needs the owner's go).

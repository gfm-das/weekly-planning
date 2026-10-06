---
title: Roster
slug: roster
lead: is the transfer-roster import in DA Management that updates who serves where and which places are open.
summary: Roster Import in DA Management.
status: full
navboxes: [admin]
infobox_title: Roster
icon: "👥"
infobox_rows: ["Where|DA Management → Roster Import", "Who|AP, President, Data Analyst", "Effect|Assignments + open places"]
tags: [admin, roster]
---

## Usage

1. Open **DA Management → Roster Import**.
2. Upload the transfer roster file (preview first).
3. Review mappings and warnings, then **Apply**.
4. Check **Import history** if you need to Undo.

### What a roster does

- Updates missionary and leadership assignments (effective-dated).
- Can **reopen** zones/districts/areas the roster names.
- Decides which areas are open from who serves there.
- **Wins over** a hand-made close in [Places](management.html).

Do **not** upload the roster during a brand-new install setup form — do it afterwards in DA Management (planned installer behaviour).

## How it works

Transactional import with before/after row records for Undo. Historical labels can map to current area ids via Area mappings.

## Permissions

DA Management users only.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Unexpected reopen of a closed place | Expected if roster named it — close again only if still correct, knowing the next roster may reopen |
| Preview errors | Fix mappings / area names; do not Apply until clean |

## History

| Date | Note |
| --- | --- |
| Ongoing | Core DA Management feature |
| Round 12 | Explicit “roster wins” rule with Places |

## See also

- [Management (Places)](management.html)
- [Accounts](accounts.html)
- [Uploads / Importer](uploads-importer.html)

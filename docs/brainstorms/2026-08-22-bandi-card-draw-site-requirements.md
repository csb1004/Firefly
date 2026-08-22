---
date: 2026-08-22
topic: bandi-card-draw-site
---

# Youngho Gacha Site Requirements

## Summary

Build a Railway-hosted, web-first card drawing and collection service tied to global Discord accounts. The first release includes daily draws, pity counters, collection-based YP rankings, gifts, live bilateral trades, administration, and Bandi bot DM links.

---

## Problem Frame

The Bandi community needs a collectible-card experience that remains usable across Discord servers and after a user leaves a server. The website is the product surface; Discord supplies identity and Bandi supplies optional DM links without becoming a second implementation of the product.

---

## Key Decisions

- **Global Discord identity.** A Discord user has one account, inventory, pity state, and ranking position across the service; Discord servers are not a product boundary.
- **Web-first experience.** Drawing, collection management, rankings, gifts, live trades, and administration happen on the website so visual reveals and transactional state have one authoritative surface.
- **Collection YP.** A card type contributes its YP once while the user owns at least one copy; duplicate quantity does not multiply YP.
- **Full first release.** The initial release is not reduced to drawing and collection; every capability in this document is required before it is considered complete.
- **Live negotiation.** Trades require both users to be online in the same live room, while gifts transfer immediately without recipient approval.
- **Current-probability transparency.** Users see their current per-card probabilities and pity progress, but not a public history of probability changes.

---

## Actors

- A1. **Player:** A Discord-authenticated user who draws, collects, ranks, gives, and trades cards.
- A2. **Trade partner:** Another online player participating in the same live trade room.
- A3. **Administrator:** The Discord account identified by the Bandi bot's existing `SPECIAL_USER_ID` value.
- A4. **Bandi bot:** Sends best-effort Discord DM notifications with links to relevant website pages.
- A5. **Discord:** Authenticates players and supplies stable account identity plus current profile information.

---

## Requirements

**Account and access**

- R1. Players must sign in through Discord OAuth without a site password.
- R2. The stable numeric Discord user ID must identify the player's single global site account.
- R3. A previously authenticated account must retain full site access after leaving every server that contains Bandi.
- R4. The first successful login must require acknowledgement that Bandi DM notifications may fail without a mutual server or when Discord privacy settings block DMs.
- R5. The first-login warning must not appear again after acknowledgement.
- R6. Only the Discord account matching Bandi's `SPECIAL_USER_ID` may access administrative functions.
- R7. Players must be searchable among registered site accounts by Discord username, display name, or numeric Discord ID.
- R8. Ambiguous searches must show a selectable list containing avatar, display name, and `@username`.
- R69. A registered player's Discord username, global display name, and avatar must refresh immediately on successful login and through a Bandi bot background sync at least every six hours; the latest values must appear consistently in search, rankings, profiles, and the 5-star feed even when the player shares no server with Bandi.

**Daily draw and pity**

- R9. Each player may draw once per KST day, with eligibility resetting at 05:00 KST.
- R10. Unused daily draws must not carry over.
- R11. Cards must have one rarity from 1 through 5 stars.
- R12. The default rarity probabilities must be 45% for 1 star, 30% for 2 stars, 19.3% for 3 stars, 5.1% for 4 stars, and 0.6% for 5 stars; the administrator may change them later.
- R13. A player must receive a 4-star-or-higher card no later than the tenth draw since their last 4-star-or-higher result.
- R14. A player's 5-star probability must increase by 6 percentage points per draw from draw 74 through draw 89 since their last 5-star result.
- R15. A player must receive a 5-star card no later than draw 90 since their last 5-star result.
- R16. Receiving a 4-star card must reset the 4-star guarantee counter.
- R17. Receiving a 5-star card must reset both the 4-star and 5-star guarantee counters.
- R18. The draw screen must show the remaining draws until the 4-star-or-higher guarantee and the 5-star guarantee.
- R19. All active cards within a rarity must have equal selection weight unless the administrator assigns card-specific weights.
- R20. The probability view must show each active card's final probability for the signed-in player's current pity state.
- R21. The service must not permit a draw configuration that can select a rarity with no active card.
- R22. A successful draw must atomically consume that day's eligibility, award exactly one card, update pity, update YP when applicable, and create a 5-star feed event when applicable.

**Card presentation and collection**

- R23. Each card must have an administrator-supplied image, name, rarity, YP value, and optional selection weight.
- R24. Rarity colors must be white for 1 star, green for 2 stars, blue for 3 stars, purple for 4 stars, and gold for 5 stars.
- R25. Card borders and visual accents must use the card's rarity color.
- R26. The bottom of each card must show its rarity using one to five luminous star-shaped vector icons.
- R27. The inventory must stack duplicate cards and show the owned quantity.
- R28. A card type must contribute its YP exactly once while its owned quantity is at least one.
- R29. A player's total YP must decrease when they transfer their last copy of a card type.
- R30. A player's total YP must increase when they receive their first copy of a card type.
- R31. Draws of 1 through 3 stars must use a short rarity-colored card reveal.
- R32. A 4-star draw must use a short purple burst reveal distinct from lower rarities.
- R33. A 5-star draw must use a longer warp-style reveal that transitions to gold before revealing the card.
- R34. Every reveal must be skippable and must have a reduced-motion alternative with less flashing and movement.

**Global ranking and 5-star feed**

- R35. The ranking must be a single global leaderboard ordered by each player's current collection YP.
- R36. Server-specific rankings and server membership filters must not appear.
- R37. A ranking entry must open the selected player's profile and expose available gift or live-trade actions.
- R38. The site footer must show the 20 most recent 5-star draws with KST draw time, username, and card name.
- R39. The 5-star feed must provide a separate view for older events.
- R40. Feed usernames must link to the player's profile, and card names must link to card details.

**Gifts and live trades**

- R41. Players must be able to enable or disable incoming trade invitations and incoming gifts independently.
- R42. Both incoming settings must default to enabled for new accounts.
- R43. A player may send a gift to a registered player regardless of whether the recipient is online.
- R44. A gift must show the card, quantity, and resulting YP impact before final confirmation.
- R45. A confirmed gift must transfer immediately without recipient approval.
- R46. Live-trade invitations may be sent only to players currently online and accepting trade invitations.
- R47. A live trade room must show both players' offered cards and quantities alongside access to their own inventories.
- R48. Either player may add or remove cards and quantities from their offer before completion.
- R49. Either player may send a general request for more cards or request a specific card and quantity from the partner's inventory.
- R50. A specific-card request must remain advisory; only the owning player may add that card to their offer.
- R51. Either player may reject the trade or leave the room, immediately ending the session without transferring cards.
- R52. Any offer change must clear both players' acceptance states.
- R53. A trade must complete only when both players accept the same unchanged pair of offers.
- R54. Trade completion must exchange both offers atomically and recalculate both players' collection YP.
- R55. Cards placed in an active offer must be unavailable to gifts or other trade rooms until the session ends.

**Bandi bot integration**

- R56. Bandi must attempt to DM relevant website links for incoming live-trade invitations, received gifts, and completed trades.
- R57. DM delivery must be best-effort and must not block or roll back a valid site action when Discord rejects the message.
- R58. The site must not create a separate notification inbox as a fallback for failed DMs.
- R59. Active website sessions must still receive live trade invitations on the website because trading requires both players to be online.

**Administration**

- R60. The administrator must have a separate UI for adding cards and editing their image, name, rarity, YP, and selection weight.
- R61. Editing a card's YP must update every affected player's ranking total.
- R62. The administrator must be able to exclude a card from future draws while preserving existing ownership, trading, and YP effects.
- R63. The administrator must be able to permanently delete a card from all inventories, active offers, rankings, and related 5-star feed events.
- R64. Permanent deletion must preview affected players and total copies before execution.
- R65. Permanent deletion must require the administrator to type the card name as a final confirmation.
- R66. The administrator must be able to configure rarity probabilities and card-specific weights through the administrative UI.
- R67. Administrative configuration must prevent invalid probability totals and undrawable active pools.
- R68. Probability changes must retain an internal audit record even though players only see current probabilities.

---

## Key Flows

- F1. Discord sign-in
  - **Trigger:** A visitor chooses Discord login.
  - **Actors:** A1, A5
  - **Steps:** Discord authenticates the user; the site creates or refreshes the global account; a first-time player acknowledges the DM warning.
  - **Outcome:** The player enters the site without a password and retains access independently of server membership.
  - **Covered by:** R1-R8

- F2. Daily draw
  - **Trigger:** An eligible player starts today's draw.
  - **Actors:** A1
  - **Steps:** The site evaluates pity and current probabilities; awards one active card; runs the matching reveal; updates inventory, pity, YP, and the 5-star feed.
  - **Outcome:** Today's eligibility is consumed exactly once and the player sees the updated guarantee counts.
  - **Covered by:** R9-R34, R38-R40

- F3. Immediate gift
  - **Trigger:** A player selects a recipient, card, and quantity and confirms the preview.
  - **Actors:** A1, A4
  - **Steps:** The site transfers the cards; recalculates both YP totals; Bandi attempts to DM the recipient.
  - **Outcome:** The recipient owns the gift immediately even if the DM fails.
  - **Covered by:** R41-R45, R56-R58

- F4. Live trade
  - **Trigger:** A player invites an online player who accepts trade invitations.
  - **Actors:** A1, A2, A4
  - **Steps:** Both enter a trade room; add cards; use general or specific requests; review the offers; accept the unchanged deal.
  - **Outcome:** Both offers exchange atomically, or nothing transfers if either player rejects, leaves, disconnects, or changes an accepted offer.
  - **Covered by:** R46-R59

- F5. Card administration
  - **Trigger:** A3 opens the administrative card UI.
  - **Actors:** A3
  - **Steps:** The administrator adds or edits cards, changes probabilities, excludes a card, or confirms permanent deletion after reviewing impact.
  - **Outcome:** Draw pools, inventories, and rankings reflect the selected administrative action without partial updates.
  - **Covered by:** R60-R68

---

## Acceptance Examples

- AE1. **Covers R9, R10, R22.** Given a player drew at 04:59 KST, when the clock reaches 05:00 KST, then the player becomes eligible for one new draw and no additional missed draws are credited.
- AE2. **Covers R13, R16-R18.** Given nine consecutive draws without a 4-star-or-higher result, when the player performs the tenth draw, then the result is at least 4 stars and the displayed 4-star guarantee counter resets.
- AE3. **Covers R14, R15, R17-R18.** Given a player has made 73 draws without a 5-star result, when they continue drawing, then the 5-star chance is 6.6% at draw 74, rises by 6 percentage points per draw through 96.6% at draw 89, and reaches 100% at draw 90.
- AE4. **Covers R17.** Given both pity counters have progress, when the player receives a 5-star card, then both counters reset and both remaining-draw indicators show their full intervals.
- AE5. **Covers R27-R30.** Given a player owns five copies of a 100 YP card, when they gift four copies, then their total YP is unchanged; when they gift the last copy, then their total YP decreases by 100.
- AE6. **Covers R37, R46.** Given a player opens another user's profile from the ranking, when the target is offline, then gifting remains available but starting a live trade is unavailable.
- AE7. **Covers R48, R52-R54.** Given both players accepted a trade, when either player changes any offered card or quantity before completion, then both acceptance states clear and no transfer occurs until both accept again.
- AE8. **Covers R51, R55.** Given cards are committed to an active trade room, when either player disconnects or leaves, then the trade ends without transfer and all committed cards become available again.
- AE9. **Covers R56-R59.** Given both users are online on the website but Discord blocks the recipient's DM, when a live-trade invitation is sent, then the website still presents the live invitation and no fallback inbox entry is created.
- AE10. **Covers R62, R63.** Given players own a card, when the administrator excludes it from draws, then ownership and YP remain; when the administrator permanently deletes it, then all copies and related YP and feed events disappear.
- AE11. **Covers R19-R21, R66-R67.** Given an administrator assigns unequal weights within a rarity, when a player views probabilities, then each card shows its resulting current chance and the configuration cannot be activated if its pool is undrawable.
- AE12. **Covers R31-R34.** Given reduced motion is enabled, when a player draws a 5-star card, then the card still receives a distinct gold reveal without the full warp movement or intense flashing.

---

## Success Criteria

- A player can complete every player-facing flow on desktop and mobile without using a Discord command.
- Concurrent draw attempts cannot grant more than one card within the same KST eligibility window.
- A completed gift or trade never leaves card quantities, YP totals, or offers partially updated.
- Current rankings always equal the sum of YP for distinct card types each player presently owns.
- Players can distinguish all five rarities by borders and star count without relying on color alone.
- The administrator can operate the card pool and probabilities without editing application files.
- Discord DM failures remain visible to operations but do not break completed site actions.

---

## Scope Boundaries

**Outside this product's identity**

- Discord server-specific accounts, inventories, ranks, roles, or views
- Password authentication or a separate site identity
- Currency, card purchasing, auctions, or a public marketplace
- A fallback website notification inbox

**Deferred for later**

- Pickup banners and limited-time card pools
- Public probability-change history
- Additional administrator accounts or role-based administration

---

## Dependencies and Assumptions

- Railway must provide durable shared storage suitable for accounts, inventories, pity state, trades, audit events, and rankings; the bot's current local JSON memory is not assumed to be the website data store.
- Discord OAuth must provide the stable user ID and profile fields needed for account creation and refresh.
- Bandi's bot-authenticated Discord `Get User` request must refresh registered profiles by stable Discord ID without relying on shared-server membership; temporary failures retain the last known profile and are retried within the next sync cycle.
- Username and display-name search covers users who have registered with this site; it is not a directory of every Discord account.
- Bandi may be unable to DM users who share no server with the bot or whose privacy settings reject DMs.
- Uploaded card images are supplied and managed by the administrator.

---

## Outstanding Questions

**Deferred to planning**

- Choose the brief network-reconnection tolerance before a live trade room is treated as disconnected.
- Choose image upload limits and the crop behavior for inconsistent source aspect ratios.

---

## Sources and Research

- `firefly/config.py` defines the existing `SPECIAL_USER_ID` used for administrator identity.
- `railpack.json` shows the existing Railway start command for the Bandi bot.
- Discord documents error `50278` for messages blocked because the bot and user have no mutual guild: <https://docs.discord.com/developers/topics/opcodes-and-status-codes>.
- Discord's User resource documents username, global display name, avatar, and `Get User` by user ID: <https://docs.discord.com/developers/resources/user>.
- Discord documents that ordinary bot DM commands require a mutual guild: <https://docs.discord.com/developers/interactions/application-commands>.
- The Malrang Online interaction reference describes live trade rooms with reject, request-more, and accept controls: <https://www.namu.moe/w/%EB%A7%90%EB%9E%91%EC%9D%B4%20%EC%98%A8%EB%9D%BC%EC%9D%B8>.

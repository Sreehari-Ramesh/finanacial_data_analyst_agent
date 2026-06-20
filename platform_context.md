# Platform Context

## What this platform is
An Indian online betting and gaming platform that supports sports betting,
live casino, and card games. It operates on a white-label model where multiple brands
can run on the same infrastructure, each with their own agent network and client base.

## Products offered
- **Sports betting** — bet on match outcomes (cricket, football, etc.) via market and session markets
- **Live Teen Patti** — Indian card game played live with a dealer
- **Baccarat** — live dealer card game
- **Casino** — standard online casino games
- **Live casino providers** — Ezugi, Vacuum Play, Viking Play, World Casino (third-party live dealer integrations)
- **Lottery** — number-based lottery games
- **Binary markets** — fixed-odds binary outcome betting
- **Sportsbook** — traditional sportsbook with pre-match and live betting

## How the business works
- The platform runs on a **commission model** — agents earn a percentage of client losses
- Clients are organised in a **hierarchy**: White Label → Admin → Super Agent → Master Agent → Agent → Sub-Agent → Client
- Each agent manages a book of clients and is responsible for their credit and exposure
- Clients are given a **credit reference** (credit limit) and can bet up to their **exposure limit**
- Financial settlements happen in both **Points (Pts)** and **Indian Rupees (Rs)**

## Betting terminology
- **Market bet** — a bet on the overall match result
- **Session bet** — a bet on a specific innings milestone (e.g. total runs in 10 overs)
- **Exposure** — the maximum payout the platform is liable for on open/unsettled bets
- **Commission** — the percentage cut taken from client winnings by the agent or platform
- **Chips / Points** — internal platform currency used for betting; has a rupee equivalent
- **P&L (Profit & Loss)** — tracked separately for market bets, session bets, and casino
- **DWM** — Deposit minus Withdrawal; a common metric to measure net client cash flow

## Sports data hierarchy

Sports data is organised in a strict parent-child hierarchy. Always traverse from the
top level down when filtering; never skip levels.

```
tblSport
  └── tblTournament  (linked via appSportId)
        └── tblMatch  (linked via appTournamentId)  ← also called "events" in the DB
              └── tblBet / tblClientBet  (linked via appMatchId)
                    └── tblMarketType  (linked via appMarketId)
```

**Key terminology rule:** In this database, a "match within a tournament" is stored as
an event. The terms **match** and **event** are interchangeable — both refer to rows
in `tblMatch`. When a user asks "show me events for IPL" or "matches in tournament X",
query `tblMatch` filtered by the relevant `appTournamentId`.

### Typical join path for sport-level queries
```sql
tblSport s
  JOIN tblTournament t  ON t.appSportId      = s.appSportId
  JOIN tblMatch m        ON m.appTournamentId = t.appTournamentId
  JOIN tblBet b          ON b.appMatchId      = m.appMatchId
  JOIN tblClientBet cb   ON cb.appBetId       = b.appBetId
```

### When to use each table
| Goal | Table |
|------|-------|
| List sports available | tblSport |
| Find tournaments for a sport | tblTournament (filter by appSportId) |
| Find matches/events in a tournament | tblMatch (filter by appTournamentId) |
| Find market types for a match | tblMarketType (filter by appMatchId or appMarketId) |
| Bet-level detail | tblBet + tblClientBet (filter by appMatchId) |
| P&L summary | tblMarketwisePLSummary (appTPGameRefID IS NULL for sports) |

---


## Shared Sports + Casino Data Model

The platform stores both sportsbook events and casino games inside the same four-level hierarchy:

```
tblSport
  └── tblTournament
        └── tblMatch
              └── tblBet
```

This means a casino game is not modelled as a completely separate top-level object. Instead, a casino game is usually represented as a `tblBet` row under a synthetic sport such as `ExchGame`, often under a tournament such as `vkingPlay`. The same hierarchy is therefore used for both:
- resolving a sportsbook bet to its readable Sport → Tournament → Event → Market
- listing casino games under the casino sport and enriching them with provider/game metadata

**Important reasoning rule:** one tree, two readings. For sport lookups, read downward from a known sport/tournament/match/bet path. For casino catalogue lookups, filter the same tree to the synthetic casino sport and then enrich the result with provider/game details.

## Casino Provider / Game Resolution

Casino provider and game names are not reliably stored in `tblBet.appBetName`. For casino rows, `appBetName` may be only a generic slot label. To get the real readable casino game information, use this enrichment path:

```
tblClientBet.appTableCode
  → tblAngularCasinoGame.gameCode
  → tblAngularCasinoGame.appProviderID
  → tblProvider.appProviderID
```

### Key casino lookup rules
- `tblBet` still represents the casino game slot in the shared hierarchy
- `tblClientBet.appTableCode` is the bridge from betting data to the casino catalogue
- `tblAngularCasinoGame.Name` gives the readable game name
- `tblProvider.appProviderName` gives the casino provider / studio name
- do not assume casino names are cleanly available in `tblBet.appBetName`

### Config-driven casino sport id
Do not hard-code the casino sport id. Read it from `tblWebsiteSetting` using:
- `appKey = 'ExchGameSportID'`

This makes casino queries more robust if the configured sport id changes.

## Query Rules / Good to Know

### Canonical sports event lookup pattern
When you have a known `appBetId` and need the human-readable event context, use the shared hierarchy:

```sql
SELECT
  s.appSport,
  t.appTournament,
  m.appMatch AS appEvent,
  m.appDate,
  b.appBetName AS appMarketName
FROM tblSport s
JOIN tblTournament t ON t.appSportId = s.appSportId
JOIN tblMatch m ON m.appTournamentId = t.appTournamentId
JOIN tblBet b ON b.appMatchId = m.appMatchId
WHERE b.appBetId = @BetId;
```

### Canonical casino catalogue lookup pattern
When listing casino games, first filter the shared hierarchy to the casino sport, then enrich the rows with provider/game data from `tblClientBet`, `tblAngularCasinoGame`, and `tblProvider`.

### Why `GROUP BY appBetID` with `MIN(...)` is used
A casino bet can sometimes match more than one catalogue row. Grouping by `appBetID` and using `MIN(...)` for provider/game fields forces exactly one deterministic row per bet and avoids duplicate fan-out after the join.

### Reporting / SQL Server notes
- `WITH (NOLOCK)` may be used in catalogue/reporting reads to reduce blocking, but it can read uncommitted or temporarily duplicated rows
- `appBetId` and `appBetID` refer to the same identifier in SQL Server because identifier casing is not significant here
- for money or month-based reporting, prefer date-range filters over `MONTH(column)` and `YEAR(column)` when possible
- for example, total successful deposit for May 2026 is better written as:

```sql
SELECT ROUND(ISNULL(SUM(d.appAmount), 0), 2) AS total_deposit
FROM tblDeposit AS d
WHERE d.appStatus = 3
  AND d.appCreatedDate >= '2026-05-01'
  AND d.appCreatedDate < '2026-06-01';
```

## Enums

### Login / user type
- appLoginType: Admin=1, Agent=2, Client=3, Operator=4, Caller=6, AgentOperator=7
- appUserType: 1 = parent/agent user, 3 = client/player
- Clients and players refer to the same entity throughout the database

### BetStatus (used in tblBet and tblClientBet)
- Open=1, InActive=2, Suspended=3, Closed=4, Settled=5, InPlay=6,
  OverLimitSuspended=7, ReopenBet=8, BallStart=9, Cancel=10
- Active/live bets: status IN (1, 6, 8, 9) — Open, InPlay, ReopenBet, BallStart
- Completed bets: status = 5 (Settled)
- Cancelled/void bets: status = 10 (Cancel)

## Key tables and their purpose

### tblClient
Primary client/player table. Contains all client details including balance, exposure,
commission rates, access flags, and contact info.
- appClientId — primary key for client records; use this as the join key across all
  client-related queries
- appUserId — references tblUser.appUserId for the parent/agent user of this client
  (no database FK enforced, but logically linked)
Clients and players refer to the same entity throughout the database.

### tblUser
Contains user records for the full hierarchy (agents, operators, admins).
- appUserId — primary key for user records
- appUserType=1 is a parent/agent; appUserType=3 is a client
When joining tblClient to tblUser, match on tblClient.appUserId = tblUser.appUserId.

### tblBet
Contains bet definitions — the market name, the match it belongs to, and bet status.
- appStatus uses BetStatus enum: Settled=5 for completed bets, Cancel=10 for void bets
- Use appMatchID to join with tblMatch for match details

### tblClientBet
Contains details of bets placed by clients including profit, betID, matchID, and status.
- appStatus uses BetStatus enum: filter status=5 (Settled) for settled bets,
  status IN (1,6,8,9) for currently active bets
- Joining tblClient with tblClientBet answers most queries about client betting activity

### tblDeletedMarketBets
Contains market bets that were cancelled or deleted. Join on appClientID and appBetID
to find bets cancelled by a specific client.

### tblMarketwisePLSummary
Contains P&L summary per market or game.
- appOwnPL — P&L of the queried user/client (negative = loss, positive = profit)
- appProfitLoss — P&L from the platform perspective
- appTPGameRefID = NULL → sports data; appTPGameRefID IS NOT NULL → casino data
Use this table for most betting P&L queries. Also useful for finding top winners/losers.

### tblSport
Top of the sports hierarchy. Contains one row per sport (cricket, football, tennis, etc.).
- appSportId — primary key; used to filter tblTournaments to a specific sport
- Use this table when the user asks "which sports are available" or filters by sport name

### tblTournament
Second level of the hierarchy. Each row is a tournament belonging to one sport.
- appTournamentId — primary key; used to filter tblMatch to a specific tournament
- appSportId — foreign key to tblSport
- Examples: IPL, English Premier League, Wimbledon
- Use this table when the user specifies a tournament or competition name

### tblMatch
Third level of the hierarchy. Each row is a match/event within a tournament.
**Important:** In this database, matches within a tournament are referred to as "events".
The words "match" and "event" are interchangeable — both map to rows in tblMatch.
- appMatchId — primary key; join key for tblBet, tblClientBet, tblMarketType
- appTournamentId — foreign key to tblTournament
- Use this table when filtering by sport, tournament, date, or specific match/event
- When a user says "events for IPL" → filter tblMatch by the relevant appTournamentId

### tblMarketType
Fourth level — defines the types of markets available on a match (e.g. Match Winner,
Over/Under, Both Teams to Score).
- appMarketId — primary key
- appMatchId — foreign key to tblMatch
- Use this table when the user asks about market types, bet types, or wants to
  filter results to a specific kind of market within a match

### tblDeposit
Contains all deposit transaction records.
- Deposit Status: Incomplete=1, InProgress=2, Success=3, Failed=4, Invalid=5, Expired=6, Fraud=7
- Deposit Type: PaymentGateway=1, Manual=2, ByAdmin=3

### tblWithdraw
Contains all withdrawal transaction records.
- Withdraw Status: Verified=1, InProgress=2, Success=3, Failed=4, Requested=5, ToVerify=6, Unverified=7
- Withdraw Type: PaymentGateway=1, Manual=2, ByAdmin=3

### tblDepositWithdrawCount
Contains the count of deposits and withdrawals per user or client. Useful for
frequency-based queries without scanning the full deposit/withdraw tables.
- appUserType controls how appUserID is interpreted (polymorphic FK):
  - appUserType=1 → appUserID refers to tblUser.appUserId (agent/user record)
  - appUserType=3 → appUserID refers to tblClient.appClientId (client/player record)
- Always filter by appUserType when joining to avoid mixing user and client rows

### tblTransaction
Contains transaction records including win amounts. Join using appUserID and appUserType
to retrieve transactions for a specific user or user category.

### tblFinalTransaction
Contains account statement data. Use appCalAmountPts for account statement queries.

### tblWalletTransaction
Contains daily wallet transactions and daily P&L per client.
Always filter with appBetID <> 0 to exclude non-bet entries and get accurate
betting-related wallet movement.

### tblBank
Contains bank names and their active/inactive status.

### tblBankDetail
Links bank account details to clients. Contains account holder name, bank name,
and active status per client. Join on appClientID.

### tblAction
Defines action types tracked within the platform.
- appActionName values: Register, EmailVerification, KYC, Deposit, Withdraw, Login,
  ForgotPassword, UpdateMobileNoNew, ChangeMobileNoOld, ChangeBank
- appActionEnumID: 1–10 (matching the order above)

### tblActionStatus
Defines the status of each action.
- appActionStatusName: InProgress=1, Success=2, Failed=3

### tblCampaign
Contains campaign/bonus details. appCampaignName represents the bonus type offered
to users. Campaign start and end dates are available in this table.

### tblCampaignSubscription
Tracks which clients have subscribed to a particular campaign/bonus.

### tblClientLocation
Contains location/geographic details for clients.

## Common query patterns
- **DWM (Deposit minus Withdrawal)** — join tblDeposit and tblWithdraw on clientID,
  sum successful deposits (status=3) minus successful withdrawals (status=3)
- **Client betting activity** — join tblClient + tblClientBet
- **Sports vs casino P&L** — use tblMarketwisePLSummary filtering appTPGameRefID IS NULL (sports) or IS NOT NULL (casino)
- **Event/match queries** — join tblMatch with tblTournament and tblSport; remember "events" = rows in tblMatch
- **Sport → tournament → match drill-down** — tblSport → tblTournament (appSportId) → tblMatch (appTournamentId) → tblBet (appMatchId)
- **Market type breakdown for a match** — join tblMatch + tblMarketType on appMatchId
- **Account statement** — use tblFinalTransaction (appCalAmountPts)
- **Daily wallet movement** — use tblWalletTransaction WHERE appBetID <> 0

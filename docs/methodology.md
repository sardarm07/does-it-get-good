# Methodology

How `getgood` turns IMDb's ratings into its answers. Every threshold named here lives in
`src/getgood/config.py`, with a line on why it has the value it has; `make validate`
scores the results against hand-made labels (see the end).

## The data

**IMDb's files.** IMDb publishes its non-commercial datasets daily. `getgood` uses three:
`title.basics` (titles, types, years, genres), `title.episode` (which episode belongs to
which series, with season and episode numbers) and `title.ratings` (each title's average
rating and vote count). They hold today's numbers only: no history, no air dates and no
breakdown of votes by star.

**Scope.** A series or miniseries is in scope when it has 6 or more rated, numbered
episodes (season and episode 1 or more) and isn't a talk show, news, reality TV or a game
show, where "gets good" means little. In IMDb's files of 2026-10-09 that's 24,779 series
and 685,056 rated episodes.

**Checks.** A sync stops before using a file whose columns changed, whose row count moved
more than 2% from the last good file (allowing 2% per 30 days between them), with more than
0.1% of season or episode numbers unreadable, or with ratings from fewer than 5 votes. The
new tables are compared with the last ones too: the number of series in scope may move 3%,
and 1% of titles may lose votes, per 30 days.

**History.** Review bombs are about change over days, and IMDb keeps no history. The
Internet Archive saved copies of `title.ratings.tsv.gz` on most days since 2022-02-22.
Each copy is dated by IMDb's own Last-Modified header, since the archive usually saves the
previous day's file, checked like IMDb's own files, and kept as that day's ratings for the
in-scope titles. Days the archive missed are gaps, mostly in 2022: every change is divided
by the days between copies, and gaps longer than 3 days are reported.

## Verdicts

**1. Damping.** An episode with 12 votes says far less than one with 12,000, so every
rating is pulled toward the show's vote-weighted mean C before anything else:

    x = (v × r + k × C) / (v + k),  k = 10

Ten votes move an episode halfway to C; a thousand barely move it.

**2. Stretches.** The damped ratings are split into flat stretches with PELT (Killick,
Fearnhead and Eckley, 2012), which finds the split with the lowest total cost exactly:

- a stretch costs the sum of squared distances of its ratings from its mean;
- each break costs 3σ² ln n, where n is the number of episodes and σ, the typical
  episode-to-episode noise, is the median jump between neighbours divided by
  0.6745 × √2 (its value for Gaussian noise), and at least 0.05 since ratings are rounded
  to 0.1;
- a break at a season premiere costs half, since shows change most between seasons;
- a stretch has at least 3 episodes.

With these, pure noise stays one stretch about 9 times in 10.

**3. The turn.** Read in order:

| Verdict | When |
| --- | --- |
| Steady | The episodes form one stretch. |
| Good from the start | The first stretch is within 0.1 of the show's median, or above 8.1 (the 75th percentile of show medians). It's "even better" from the first later stretch that rises 0.3 above every stretch before it and holds there for 6 or more episodes. |
| Gets good | The first stretch that steps up 0.3 or more from the one before, reaches the show's median (within 0.1), and stays 0.3 above that earlier level for 6 or more episodes. A short peak isn't a turn. |
| No clear turn | Anything else: the show opens below its level and never steps up to it. |

A turn is high confidence when its jump is at least 2σ and the episodes before it have a
median of 100 or more votes, medium when the jump is at least σ, and low otherwise. A
verdict without a jump takes its confidence from the show's median votes per episode: 100
or more is high, 20 or more medium.

**4. Slumps.** A later stretch at least 0.4 below the mean of every episode before it.
Measuring against everything before, not just the previous stretch, means a long decline
still counts. Back-to-back slumping stretches are one slump. A slump has recovered when a
later stretch returns to within 0.1 of the level before it.

**5. Low points.** An episode more than 3σ below its stretch's level.

## Contested episodes

From today's numbers alone, any show can have episodes where votes piled up. An episode
with 500 or more votes is compared with up to 3 episodes on each side in its season, which
need a median of 200 or more votes. It's contested when it has at least twice their median
votes (three times for a season premiere or finale, which draw extra votes anyway) and
rates at least 0.5 below their median. Today's numbers can't date it or tell a review bomb
from honest backlash, so it's never called a bomb.

## Review bombs

Three checks find flags in the history; flags close together form events.

**The daily check.** For every title with 500 or more votes, each day's new votes per day
are compared with the title's own pace over its previous 28 history days (at least 7):

    z = (new votes − median) / (1.4826 × MAD + 1)

The median and the median absolute deviation (MAD) shrug off earlier spikes, and the + 1
keeps a title that gains almost nothing each day from turning one stray vote into a surge.
A surge is z of 8 or more, with at least the larger of 50 votes or 2% of the title's total
that day. Its kind comes from the rating that day, compared in tenths so 8.3 − 8.5 is
exactly −0.2:

- a drop of 0.2 or more is a **review bomb**;
- a rise of 0.2 or more is a **boost**;
- otherwise it's a **vote surge**.

The new votes' own average can be worked out from the rating and votes before and after,
but IMDb rounds ratings to 0.1, which leaves an error of about 0.1 × votes ÷ new votes. It's
shown when that error is under 1 point. It can't find a bomb the rating change misses:
being 3 points below the old rating with 1 point of error already moves the rating by 0.3.

Two kinds of day aren't judged against the title's own pace:

- the title's first 14 days in the history, which have no pace yet;
- days when the title is **arriving**: its votes grow fivefold within 14 days either side,
  counting the last day before a gap in the history. Shows rated before their release
  surge on release day with their hype ratings falling, which isn't a bomb. Releases
  measured 7 to 450 times over; the biggest bomb on a small show, 2.9.

**The launch check.** An episode in its first 14 days has no pace of its own, so it's
compared with its season's other episodes at the same age, for episodes the history saw
arrive (it holds a day within 3 days before the episode's first). On each of days 1 to 13,
twice their median votes and a rating 0.5 or more below their median is a review bomb, the
bar a contested episode clears; a season's last episode needs three times their votes,
since finales draw extra votes anyway. Season premieres are left out on both sides: they
always draw more votes, and lower ratings, from people who don't go on.

**The page check.** A show bombed at its premiere has no siblings to compare with, but
bombers rate the series page without watching, so the page falls below its own episodes.
For a series page the history saw arrive, each of days 1 to 13 compares the page with its
episodes' vote-weighted rating that day. Most pages sit below their episodes anyway, since
episode ratings come mostly from fans: across 703 launches with 1,000 or more page votes,
the median page ended its first two weeks 0.4 below, and a quarter 0.8 or more below. So a
page is flagged only when it rates 0.5 or more below its episodes and the gap would take
10,000 or more low votes to open, the 1s it would take to drag the page from its episodes'
rating to its own:

    votes × (episodes' rating − page's rating) / (episodes' rating − 1)

Of 120 launches with 8,000 or more page votes in their first two weeks, the five that the
press documented as bombs (She-Hulk, The Rings of Power, Velma, The Acolyte and Ironheart)
needed 12,800 to 40,400; every other needed 6,000 or fewer.

**Events.** Flags on one show no more than 2 days apart are one event, which is a review
bomb if any flag is, otherwise a boost if any flag is. It's series-wide when it touches the
series page or 3 or more episodes. Its size is the votes beyond the usual: daily surges add
up, while a launch or page flag's lead counts once per title, since it repeats each day. `getgood bombs` lists the biggest, newest first; reading every show, it only
looks at titles with 500 or more votes today, since votes only grow.

**What it can't see.** IMDb's files have no breakdown of votes by star, so a bomb whose
votes IMDb's own weighting absorbs, or that moves a big title's rating by less than 0.2,
is a vote surge at most. A bomb in a gap of the archive's copies, or before 2022-02-22,
isn't seen at all, and neither is a bomb that grows a small show's votes fivefold. Low
ratings that come at the usual pace aren't a burst either: a season rated low from its
first day on fewer votes than the last, or an episode whose rating slides for weeks.

## Validation

`make validate` scores everything against labels in `validation/`, which are hand-written
facts about shows, not IMDb data:

| Measure | How | Target |
| --- | --- | --- |
| Turning points | 30 shows with a well-known turn, slump or low point, which must land within 3 episodes (1 for a low point) | 24 of 30 |
| Known bombs | 10 review bombs since 2022 that the press documented, which need a review-bomb event on their titles within their dates; those the history has no days for are reported, not scored | 8 of 10 |
| Precision | Review-bomb events drawn at random from the whole history (`make review`) and marked by hand as real or misread | 70% real |
| Coverage | In-scope series that get a verdict | 95% |
| Search | Labelled shows found first when their name is typed in lower case | 30 of 30 |
| Speed | `getgood show`, from starting to printing the answer, for the most-voted series, the longest, and the most-voted that began after the history did | Under 2 s |

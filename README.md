# Scout

Scout is a personal intelligence service that reads the AI/tech world for you
twice a day — arXiv, AI-industry news, FT headlines, hard-filtered UK politics,
hackathons and jobs — ranks every item against a plain **interest list** with
the Anthropic API, and emails you a short brief with one neutral line per item
on what it is and why it's notable. It never repeats itself, tracks opportunity
deadlines and reminds you as they approach, and sends a synthesis digest on
Sunday evenings.

One sentence: *read the AI/tech world for me twice a day and show me the
handful of things worth my time.*

By design it knows nothing about you: the only "profile" is a list of topics
(`profile.yaml`), the only state it keeps is which items it already showed you
(so nothing repeats), cached scores, and deadlines you've asked it to track.

## Prerequisites

- A cheap always-on Linux VPS (DigitalOcean/Hetzner/Fly.io basic box, ~$4–6/mo)
- Python 3.11+
- A Gmail account with 2-Step Verification turned on
- An Anthropic API key (<https://console.anthropic.com>)

## Server setup

```bash
# 1. Provision the box, then set its timezone to yours so cron matches your day
sudo timedatectl set-timezone Europe/London

# 2. Install
sudo mkdir -p /opt/scout && sudo chown "$USER" /opt/scout
git clone <your-repo-url> /opt/scout
cd /opt/scout
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# 3. Secrets
cp .env.example .env
nano .env    # fill in the three values — see below
```

`.env` needs exactly three values:

| Variable | What it is |
|---|---|
| `ANTHROPIC_API_KEY` | Your own key from console.anthropic.com |
| `EMAIL_ADDRESS` | The Gmail address Scout sends from **and** to (both are you) |
| `EMAIL_APP_PASSWORD` | A Gmail **App Password** — *not* your real password |

**Making a Gmail App Password:** Google Account → Security → 2-Step
Verification (must be on) → App passwords → create one named `scout` → paste
the 16-character code into `.env` (spaces don't matter).

Then make Scout yours:

- **`profile.yaml`** — the interest list the ranking runs against. Three
  tiers (high/medium/low); adding or removing a topic line is the whole
  tuning mechanism. No personal data goes in here — none is needed.
- **`config.yaml`** — sources on/off and their feeds, item caps, keywords,
  model choice, reminder windows. All commented.

## Run each mode manually first

```bash
cd /opt/scout
venv/bin/python scout.py morning     # the main brief
venv/bin/python scout.py evening     # the delta since morning
venv/bin/python scout.py weekly      # the Sunday synthesis
```

Useful flags: `--dry-run` (fetch + rank, write the brief to
`logs/last_brief.html`, send nothing, change no state) and `--force` (resend
even if that mode already ran today). Watch `logs/scout.log` — every run logs
what it fetched, what it filtered, and the estimated API cost (a normal day is
cents).

## Schedule it

`crontab deploy/scout.crontab` installs the schedule in one command — or
`crontab -e` and add exactly these three lines (times are yours to change;
the server timezone is already Europe/London from setup):

```cron
0 7 * * *   cd /opt/scout && /opt/scout/venv/bin/python scout.py morning
0 18 * * *  cd /opt/scout && /opt/scout/venv/bin/python scout.py evening
30 18 * * 0 cd /opt/scout && /opt/scout/venv/bin/python scout.py weekly
```

That's the whole deployment. The laptop can stay shut — you read the emails
on your phone. Skipped runs self-heal: fetchers pull "since the last
successful run", never "since now − 12h", so nothing is missed or
double-sent.

## Tuning

| What | Where |
|---|---|
| Interests (three tiers) | `profile.yaml` → `interests` |
| Sources on/off, feed URLs | `config.yaml` → `sources` |
| Pre-filter + politics keywords | `config.yaml` → `ranking.prefilter_keywords`, `sources.uk_politics.keywords` |
| Ranking / weekly model | `config.yaml` → `ranking.model`, `ranking.weekly_model` |
| Items per brief, score floor | `max_items_morning`, `max_items_evening`, `min_score_to_show` |
| Deadline reminder windows | `deadline_reminder_days` |
| Manual opportunities to track | `config.yaml` → `sources.opportunities.manual` |

## Honest limits

- **FT and politics are headlines-only by design.** Scout reads open RSS
  (title + standfirst + link) and never fetches article bodies or logs into
  anything. You read FT pieces in your own logged-in session.
- **Opportunities/jobs are best-effort, not comprehensive.** Hackathon feeds
  are whatever listing sites expose publicly; job watching covers the
  configured Greenhouse boards (Anthropic by default) filtered by title
  keywords. Extend the lists in config; use `manual:` for anything else.
- **Feed URLs rot.** The defaults are real at time of writing, but if a
  publisher moves a feed the brief footer will tell you ("Heads up: X failed
  to fetch") — swap the URL in `config.yaml`. Anthropic has no official RSS
  feed, so its coverage comes from the careers watch and the other primaries.
- **It costs a little.** A few £/month for the VPS, cents/day for ranking.

## Privacy rules (enforced in code, not just promised)

- Secrets live in `.env`, are git-ignored, never logged, and are sent only to
  `api.anthropic.com` and Gmail SMTP.
- The only thing sent to the API besides item headlines is the topic list in
  `profile.yaml`. The ranking prompt explicitly tells the model it knows
  nothing about the reader and must not speculate.
- Email goes only to your own address; no other recipient is accepted from
  anywhere.
- Only public data is read. Nothing paywalled, nothing behind a login, no
  work/internal data of any kind.
- Local state (`data/scout.db`) holds item IDs, scores, run logs and
  deadlines — nothing personal. Delete the file any time for a clean slate.

## Project layout

```
scout.py        entry point — morning|evening|weekly
profile.yaml    the interest list; drives all ranking
config.yaml     non-secret settings
sources/        arxiv, ft_rss, ai_news, uk_politics, opportunities (+ shared rss)
prefilter.py    cheap keyword cut before any API spend
rank.py         Anthropic ranking + weekly synthesis
pipeline.py     the per-run sequence; failure isolation
brief.py        brief assembly       templates/   email templates
mailer.py       Gmail SMTP delivery  deadlines.py deadline parsing + reminders
store.py        SQLite state (data/scout.db)
tests/          pytest suite
```

Run the tests with `venv/bin/pip install -r requirements-dev.txt &&
venv/bin/python -m pytest tests/`.

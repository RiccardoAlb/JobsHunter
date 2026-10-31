<p align="center"><img src="branding/JobsHunter.png" alt="JobsHunter logo" width="140"></p>

<h1 align="center">JobsHunter</h1>

<p align="center"><a href="README.md">Italiano</a> | <b>English</b></p>

<p align="center">A personal radar for job postings, running locally on your computer: macOS, Windows and Linux, for any field and in several countries.</p>

> **Not affiliated** with Adzuna, Jooble, LinkedIn or Indeed: read the [Disclaimer](#disclaimer). License **MIT** (see [License](#license)). Version 0.4.0.
> Your data and keys stay yours, no account and no telemetry. The interface and the messages of the program are in Italian; this document is in English.

## Get started in a minute

**A. Download the package (no Python to install).** From version 0.4.0 the project's [Releases](https://github.com/RiccardoAlb/JobsHunter/releases) page offers one package per system,
and it **already contains its own Python**: unzip it and open it.

| System | File | Then |
|---|---|---|
| macOS (Apple Silicon) | `JobsHunter-<version>-macOS-arm64.zip` | drag `JobsHunter.app` into Applications, on first launch right-click, **Open** |
| Windows 10/11 | `JobsHunter-<version>-Windows-x64.zip` (or the `...-Setup.exe` installer) | open `JobsHunter.exe`; if a warning appears: **More info**, **Run anyway** |
| Linux | `jobshunter_<version>_amd64.deb` or `_arm64.deb`, or `JobsHunter-<version>-Linux-x86_64.AppImage` | `sudo apt install ./jobshunter_...deb` (Debian, Ubuntu and derivatives) or `chmod +x` and run the AppImage |

The packages are not signed or notarized: the warnings and the SHA256 hash check are explained in [Download](#download).

**B. From source** (needs Python 3.11 or later; if it is missing, `./jh` and `jh.bat` say so and offer to install it, asking for confirmation):

```bash
# macOS and Linux
git clone https://github.com/RiccardoAlb/JobsHunter.git jobshunter
cd jobshunter
./jh setup
./jh gui
```

```bat
REM Windows (PowerShell or Command Prompt)
git clone https://github.com/RiccardoAlb/JobsHunter.git jobshunter
cd jobshunter
jh.bat setup
jh.bat gui
```

`setup` creates the `.venv` environment and installs the libraries (it asks before downloading). On first launch a guide walks you through. Details: [Installation](#installation).

![The list of postings](docs/screenshots/01-lista.png)

---

## Contents

1. [What it is for](#what-it-is-for)
2. [Search profiles and countries](#search-profiles-and-countries)
3. [How it works](#how-it-works)
4. [Download](#download)
5. [Installation](#installation)
6. [Configuration](#configuration)
7. [Usage](#usage)
8. [First run](#first-run)
9. [Customising the score](#customising-the-score)
10. [Reports for Obsidian](#reports-for-obsidian)
11. [Mac app](#mac-app)
12. [Automatic scans](#automatic-scans)
13. [Security and privacy](#security-and-privacy)
14. [Project status and next steps](#project-status-and-next-steps)
15. [Known limits](#known-limits)
16. [Project layout](#project-layout)
17. [Troubleshooting](#troubleshooting)
18. [Development and tests](#development-and-tests)
19. [Notes on sources and credits](#notes-on-sources-and-credits)
20. [Disclaimer](#disclaimer)
21. [License](#license)

---

## What it is for

Looking for a job by hand means opening ten websites, re-reading the same postings, missing the new ones and finding out later that they were closed.
JobsHunter does the repetitive work for you:

- **searches by profile**: you say what job you want, where and at what level (internships included), and it searches several sources and countries;
- **scores** every posting per profile, rewarding what you look for and penalising the rest;
- **removes duplicates** (the same posting on several sites): it proposes pairs with a percentage, you decide;
- **checks that the posting is still open**, and hides the closed ones;
- **filters** by distance from a city, work mode, contract type, company, city and gross annual salary (RAL);
- **tracks your applications**: stages (HR, technical, offer), outcomes, history and reminders;
- **works on its own**: scheduled scans even with the app closed, notifications and a "news since your last visit" box;
- **writes a report** with the full text of the postings and the link to apply.

### What it looks like

| | |
|---|---|
| ![A posting with CV affinity](docs/screenshots/02-scheda-affinita-cv.png) | ![The applications tracker](docs/screenshots/03-candidature.png) |
| A posting: status, text, and how much it resembles your CV (explained 0-100 affinity). | Applications, with stages, outcome and follow-up reminders. |
| ![Duplicate pairs to review](docs/screenshots/04-duplicati.png) | ![The first-run guide](docs/screenshots/07-guida-primo-avvio.png) |
| Duplicates: the program proposes, you decide. | The first-run guide, in seven steps. |
| ![Light theme](docs/screenshots/08-tema-chiaro.png) | ![Settings, about and credits](docs/screenshots/06-impostazioni-informazioni.png) |
| Light theme (there is a dark one too). | Settings and credits. |

The screenshots use invented data (`scripts/demo_server.py`): no real posting, company or person.

## Search profiles and countries

A **profile** says what you are looking for: a kind of job, the countries, the level, the contract type and, if you want, a city with its radius.
You can keep several on: at each scan the sources receive the searches of all profiles (without duplicates) and every posting gets a score **for each profile**.
In the list, "Profile: all" shows the best score; choosing a profile shows its own.

**Profile types (presets).** Cybersecurity (Blue, Red, Sysadmin), Sysadmin and IT support, Software development, Data and analysis, Administration and office,
Sales and marketing, or **Custom**: you write the jobs yourself (e.g. "nurse", "forklift operator"). For custom profiles every title becomes a search and a keyword:
the whole phrase weighs a lot, single words less, and very generic words ("engineer", "software", "manager") weigh very little, so "Mechanical Engineer" does not look
relevant for "backend software engineer". It also recognises feminine and plural forms (infermiere, infermiera, infermieri) and ignores accents.
The titles you write in a profile of an existing type are **added** to the type's own.

**Categories.** In cybersecurity profiles BLUE, RED, PURPLE, SYSADM, SEC remain. In the others the category is the name of the preset group (for example BACKEND,
FRONTEND, SALES); in custom ones it is the title you wrote, in capitals. The list's category filter and `./jh list -t NAME` accept any name: if it does not exist, the list is simply empty.

**Level.** `any`: no preference (for cybersecurity the historical tuning of your `config.toml` stays: penalty for senior roles, bonus for juniors); `junior`: penalises senior
roles and rewards junior, internship and first job; `mid`: penalises managerial roles and juniors; `senior`: rewards senior roles and penalises juniors. Internship bonuses only apply
if the profile has "Also search internships" on.

**Countries.** Italy, United Kingdom, Germany, France, Spain, Netherlands, Austria, Switzerland, Belgium, Poland, United States, Canada, Australia, Brazil, India, Mexico,
New Zealand, Singapore, South Africa. Adzuna uses the **same key** for all of them; searches are in the language of the country when the profile type has one (otherwise English).
**Jooble** instead only works for its own country: in `[sources.jooble]` the `hosts` map says which host to use for each, for example `hosts = { it = "it.jooble.org", gb = "uk.jooble.org" }`.
**A country without a Jooble host is not searched on Jooble** (Adzuna searches it anyway). Arbeitnow is only used if Germany is among the countries; RemoteOK and Remotive only if the profile accepts remote work.

**City.** With a city, only its radius is searched (in the country the city belongs to) and nearby postings get the "home" bonus; without a city the whole country is searched. The profile's city is
chosen in the **Search** tab. In **Settings**, "Home city" and "Radius" remain as historical values (for the Cybersecurity profile created at first run and for the list's "Radius" filter); they do not
change the city of already existing profiles by themselves.

**Currency.** A profile has no currency: the "minimum RAL" filter is **always in euros**. A posting with a salary in pounds, dollars, francs or zloty is recognised as such but, for that filter,
counts as "RAL not stated" (so a UK search will show the RAL as unknown for pounds).

**Search tab.** List of profiles (name, type, countries, place, On/Off switch, "Search now", number of visible postings), **+ New profile** with the editor and the **preview**: it shows the searches
that will be made, the main keywords and an **estimate of requests** for each active source. The estimate grows with countries and titles: if Adzuna limits requests (error 403 or 429) the source stops at the
first refusal so as not to make the block worse, and should be retried later. With many countries, reduce titles or countries.

**Limits.** Profile name: up to 80 characters, unique (case-insensitive). Custom: at least one title. Radius: 1 to 3000 km. Extra keywords: weight 1 to 15. The last profile cannot be deleted.

**When a new or edited profile sees postings.** Creating or editing a profile re-scores only the postings **already stored** (offline) and discards those older than `max_age_days` (45 days). Postings that no
profile had found relevant were never saved: you need a new scan to see them. Turning a profile off hides its postings (it does not delete them).

**From the terminal** (the profile name must be written **in full**, case-insensitive):

```bash
./jh profiles list
./jh profiles add --name "Nurses in Bari" --preset custom --title infermiere --title OSS --city Bari --km 60
./jh profiles add --name "Dev UK and DE" --preset software_dev --country gb --country de --seniority junior
./jh profiles show "Nurses in Bari"
./jh profiles off "Dev UK and DE"          # off: not searched and its postings are hidden (turn back on with "on")
./jh profiles rm "Dev UK and DE"
./jh scan --profile "Nurses in Bari"       # only that profile (repeatable)
./jh list --profile "Nurses in Bari"
```

**Migration.** At the first run after the upgrade the program creates the **Cybersecurity** profile from your `config.toml` (home city, radius, internships) and links all the postings already collected to it,
with the same scores as before. For the cybersecurity preset the keywords, blacklist and penalties of `config.toml` still apply.

### Personal categories per profile
Every profile can have **its own categories**: a name (up to 16 characters, uppercase) and the words that recognise it (1 to 20 words of 2 to 40 characters; up to 12 categories per profile).
They show up as filter chips in the list, only when they have postings, and decide each posting's label.
- **Example, nurse:** `EMERGENCY = emergency room, triage`; `WARD = ward, inpatient`; `HOME CARE = home care`.
- **Example, cook:** `KITCHEN = cook, chef, sous chef`; `PASTRY = pastry chef, patisserie`; `FLOOR = waiter, barista`.
- **Where:** Search tab, profile editor, "Categorie" section (add, edit with the pencil, delete with the x). "Add a category from the known profile types" starts from the presets' categories;
  "Ripristina quelle del preset" (restore the preset's) puts them back. In the first-run guide, for a custom profile, the optional "Categorie" field (`cook, pastry chef`) creates one category per entry.
  From the terminal: `./jh profiles add --category "KITCHEN=cook,chef"` and `./jh profiles categories NAME [--add|--remove|--set|--clear|--restore-preset]`.
- **Presets** copy their categories into the new profile (same terms and weights as before, so the same scores). Profiles created earlier have none and behave exactly as before.
- **Scoring:** the base score stays the one from titles, extra words and exclusions. A personal category that recognises a posting adds **at most +4** (word in the title) or **+2** (text only), never the sum,
  and only if the posting is already relevant: it never lets a posting in by itself. With no matching category the label is `ALTRO` (reserved name).
- With "Profilo: tutti" (all profiles) the chips and the filter show the categories of every active profile. Changing a profile's type replaces the old type's categories with the new one's.
- Saving different categories recomputes the categories of that profile's already stored postings (status and applications untouched) after a safety copy of the database in `backups/`.
- Names and words are plain text: no HTML, and words are matched literally (never as regular expressions).

## How it works

```
 PROFILES                SOURCES                LOCATION FILTER       SCORE                  ARCHIVE (SQLite)
 what you look for,    +-----------+          +------------+        +--------------+       +---------------------+
 where, level   -----> | Adzuna    | raw      | countries  | -----> | per profile: | ----> | postings and status |
 (searches per         | Jooble    | postings | and city   |        | keywords,    | new   | coordinates, RAL    |
  source and country)  | Arbeitnow | -------> | of profile,|        | bonuses,     |       | proposed duplicates |
                       | RemoteOK  |          | remote     |        | penalties    |       | applications        |
                       | Greenhouse|          +------------+        +--------------+       | scan history        |
                       | Lever ... |                                                       +----------+----------+
                       +-----------+                                                                  |
                                                                                                      v
   Scan: by hand or on its own, even with the app closed          Mac app, GUI, CLI, .md reports (Obsidian), notifications
   After each scan: duplicates, closed postings, news
```

### 1. Sources
Each source is a small class in `jobshunter/sources/boards.py` that returns a list of postings in a common format. If one source breaks (network, wrong key), the others carry on.

| Source | What it gives | Key | Notes |
|---|---|---|---|
| **Adzuna** | Italian market, full text downloadable from the page | free | Main source for Italy |
| **Jooble** | Aggregator, preview only (snippet) | free, **500 requests** | Separate section in the GUI |
| Arbeitnow | Europe (mostly Germany) | no | Not very useful for Italy |
| RemoteOK, Remotive | Remote work | no | |
| Greenhouse, Lever | Company career pages for cybersecurity firms (list in `config.toml`) | no | Mostly US companies. Queried **only by cybersecurity-type profiles** |

**Internships:** besides job searches, Adzuna and Jooble run dedicated searches ("stage cyber security", "tirocinio sicurezza informatica", "internship cybersecurity", "stage sistemista"), first page only. Turn them
off in Settings ("Also search internships") or with `[search] internships = false`; the searches can be changed with `internship_queries` in the source's section.

Adzuna and Jooble search by **profile and country** (see [Search profiles](#search-profiles-and-countries)): with a city in the profile the search covers its radius, without a city the whole country. The searches
of different profiles are merged without duplicates.

### 2. The location filter
A posting passes if its location contains an area you care about, or if it is remote. Remote work limited to unhelpful countries (e.g. "Remote - USA") is discarded (`[location] exclude`).

### 3. The score
Each posting gets a score from `config.toml`:

- every **keyword** has a weight; in the **title** it counts **x3**, only in the description **x1** (once);
- keywords are grouped in categories: **BLUE** (SOC, SIEM, incident response...), **RED** (pentest, red team...), **SYSADM** (sysadmin, Active Directory...), **SEC** (generic cybersecurity);
- the posting's category is the one with the highest score; if RED and BLUE are both high it becomes **PURPLE**;
- in the **title**, **bonuses** (junior, trainee, tier 1, **stage**, **tirocinio**, internship...) and **penalties** (senior, lead, manager...) apply;
- titles in the **blacklist** (sales, marketing, recruiter...) are discarded;
- postings near home get a bonus (only if already relevant, so as not to reward just any job);
- below `min_score` (default 15) the posting is not saved; postings older than `max_age_days` are ignored.

### CV comparison
Optional and **entirely local**: no network, no external service, no model. You upload the CV from Settings ("Your CV"), from the optional step of the first-run guide, or from the terminal
(`./jh cv set cv.pdf`). Formats: PDF with text, `.docx`, `.txt`, `.md` (max 5 MB, 40 pages); a scanned PDF (image only) cannot be read: paste the text instead. Only the **text** of the CV is kept, in `cv.json`
in the data folder (permissions 600); it never appears in logs, API, errors, reports or exports. "Delete the CV" really deletes the file and the comparisons.
- **Skills:** `jobshunter/skills.py` has a vocabulary of over 300 skills (cyber, systems, networks, cloud, development, data, healthcare, office, sales, logistics, soft skills, languages) with Italian and English aliases,
  whole-word and cautious matching (C, R, Go, AI only in sensible contexts). You can remove wrong ones or add some by hand; to extend the vocabulary write `skills_extra.json` in the data folder: `{"Terraform": ["terraform", "iac"]}`.
- **0-100 score** (a second indicator, the main score does not change): coverage of the required skills (weight x3 if in the title, up to +1.5 if repeated), a mild penalty for missing ones, level coherence (years in the CV
  against internship/junior/senior or "N years" in the text), required language. With few skills or only a preview (Jooble, text under 300 characters, Adzuna snippet) the score is cautious (cap 60) and says so ("~").
- **Where it shows:** sortable "CV" column and "CV affinity" filter in the list, "Why this score" block in the posting (in common in green, missing in grey, notes). From the terminal: `./jh cv show | match | clear`,
  `./jh list --cv-min 60 --by-cv`.
- It recomputes on its own (in the background) only if the CV, the vocabulary or the posting text changes.

### 4. The archive
Everything ends up in a SQLite file (`jobshunter.db`). A posting's identity is a hash of company, title and location: the same row is never saved twice. Each posting has a **status**: `new`, `seen`, `applied`, `discarded`.

### 5. Duplicates (the user decides)
The same job often shows up on several sites with small differences ("Acme Italia" and "ACME Group", "Milano" and "Italia"). After each scan the program **proposes** the suspicious pairs with a **similarity percentage**:

- same city (or a generic location on one side, with a small penalty; "Milan" and "Milano" are the same);
- similar company (normalised: without S.p.A., Srl, GmbH, "Italia", "Group", accents...);
- similar title, read **word by word**: "(m/f)", "H/F", "Cuoco/a", "Sr." and "Senior" do not count, nor does a tail such as "- Roma" or "(EMEA)", while "Frontend" against "Backend" or "customers" against "suppliers"
  are different jobs; the percentage drops if the **level** changes (Junior/Senior, L1/L2, Specialist/Expert), because they are different positions and must not be merged.

**Known limits of duplicates.** Translations of the same title ("Sviluppatore" / "Developer") are not recognised. Typos in short words (Manger, Jave) stay different on purpose: merging them would also merge different
jobs (Driver / Diver). Companies with very different names (brand and legal name sharing no words) are not linked. Two cities with the same beginning but different (Frankfurt / Frankfurt (Oder), Birmingham /
Birmingham, Alabama) are never the same place. With the new algorithm the **Duplicates** tab proposes **many more pairs** than before (on the real test data from 8 to about 26 after a scan): they are only proposals, you decide.

To be fast (5,000 postings in under a second) it only compares plausible pairs, that is, from the same company or from companies with nearly identical names.

The proposals appear in the **Duplicates** tab of the GUI: tick the box to confirm, or choose "Not a duplicate". Decisions are saved. A confirmed duplicate **disappears** from the list and reports (it stays in the database).
At 100% similarity confirmation is automatic but can be undone (`[dedupe] auto_confirm_percent`, set 101 to turn it off).

### 6. Radius from a city
Postings only have the name of the place, not coordinates. JobsHunter derives them **offline** (the `geonamescache` dataset, cities above 15,000 inhabitants, Italian names included) and computes the **straight-line**
distance. In the GUI the **Radius...** button lets you pick city and kilometres; from the terminal use `--city` and `--km`. Generic locations ("Italia", "Remote") have no distance: they can be included or not.

> The radius **filters what the scan already collected**; it does not launch a new search in that city.

### 7. Applications
Besides postings, JobsHunter keeps track of the **applications you sent**, one per row in the **Applications** tab:

- a **four-stage slider**: *Sent, HR interview, Technical interview, Offer*. Drag it or click a label; every step is recorded with its date;
- the **outcome** is separate from the stage: *In progress, Accepted, Rejected, Withdrawn, No answer*. So you know at which stage you were rejected; **Reopen** restores a closed application;
- a **history** with dates, notes, contact person and a **follow-up** date (it turns red when overdue);
- you can add applications **by hand** (for example one sent outside JobsHunter) with **+ New application**;
- if you press **Mark as applied** on a posting, the application is created on its own (once per posting).

Applications live in two database tables (`applications` and `app_events`) and are never deleted by a scan. Deleting requires a double confirmation in the details panel.

### Saved postings
Every posting has a **bookmark** (☆/★) in the list and in the details panel: one click saves it, another removes it. The **★ Saved (n)** filter in the filter bar
shows only the saved ones, most recent first, even if they are no longer online in the meantime (then the label *non più online*, "no longer online", appears).
Saving is independent of the posting's status (new, seen, applied) and of the profile: changing profile or recomputing scores does not touch it, and **Mark as applied** works on a saved
posting too. If you discard a saved posting the page asks for confirmation and removes it from Saved. If two postings are recognised as duplicates, the bookmark moves to the one that stays;
if the pair is later undone, no bookmark is lost. The bookmark is stored in the local database (`saved_at` column), is included in backups and the CSV export, and never leaves your computer.
Service interface: `POST /api/jobs/<uid>/save` and `/unsave`, `saved=1` filter on `/api/jobs`, `saved` count in `/api/stats`.

### 8. Filters and derived data
Postings have no precise fields for RAL, work mode or city: JobsHunter **derives them from the text** (module `meta.py`) and stores them in the database, so they can be filtered:

- **RAL:** reads different formats ("40.000 € - 50.000 €", "26,500-31,000 EUR", "22.816,92 €", "28k", "1.000 €/month" which becomes 12,000 €) and converts them to **gross annual euros**. It discards currencies other than euro and
  hourly or daily pay, where annualising would be a guess. The "minimum RAL" filter compares with the **maximum** of the range (26,500-31,000 passes with a 30,000 minimum). Fewer than one posting in three states the RAL.
- **Work mode:** *remote, hybrid, on site* or *not stated*. Cautious rules: "full remote" and "100% remoto" mean remote; "ibrido", "hybrid" and "smart working" mean hybrid; if the text mentions both remote and the
  office, it is hybrid; if unclear, it stays "not stated" (about three postings in four): that is why the panel always shows how many postings have each value, and "not stated" is a separate choice.
- **Contract type:** *internship*, *apprenticeship*, *fixed term*, *permanent*, *other* (agency work, VAT number) or not stated. An **internship** is recognised from the title ("Stage", "Tirocinio", "Intern", "Trainee") or from
  strong statements in the text ("paid internship", "we offer an internship", "intern"); conditional phrases such as "in case of internship" do not count and a senior title is never an internship. The other types are
  rarely declared by the posting: most stay "not stated".
- **City:** the name in the first part of the location ("Milano, Provincia di Milano" becomes Milano; some districts such as Ostiense become Roma). "Italia", "Remote" or a region are a **generic location**.
- **Company:** compared on the normalised name, so "Exprivia" also finds "Exprivia S.p.A.".

If you change the rules in `meta.py`, raise `META_VERSION`: at the next start the already stored postings are re-evaluated.

### 9. Still open?
A posting may already be closed when you read it. JobsHunter checks it and tells you whether **you can still apply**:

- **What counts as closed:** only reliable signals: the posting page **removed** (HTTP 404 or 410), or a **deadline** declared by the page and already past. A site block (403 or 429) does **not** mean closed: it stays "not verified".
  Adzuna also states the deadline (`validThrough`): when present you see it in the details.
- **When it checks:** when you open a posting (with the same request that downloads the full text), before a report, after each scan on the best N postings (`auto_check_after_scan`, default 20), with the
  **Check postings** button (those in the list) or from the terminal with `./jh check`.
- **What happens to closed ones:** they disappear from list, counters, notifications and reports (which states how many it excluded). The **Closed (n)** button shows them dimmed, with "closed"; in the details there is **Recheck**.
  Open postings show "open". A check is valid for `recheck_hours` hours (default 24).
- **Verifiable sources:** Adzuna (page), Greenhouse and Lever (public APIs). For other sources only the removed page is recognised. **Jooble is not verifiable** (its pages are protected by anti-bot systems, which are not bypassed): check on the site.
- **Slowly, to avoid being blocked:** one request every 2 seconds, in batches, and at the first site block the check stops and does not insist for about ten minutes. Adzuna uses a protection that limits close-together requests: if you
  see "the site is limiting requests", wait and retry later.

### 10. Full text and reports
Adzuna only gives a preview through the API, but the posting page contains the full text: the program downloads it **only for the postings that end up in the report** (pausing between requests) and saves it. For Jooble the preview plus the
link stays, because its pages are protected by anti-bot systems and are **not bypassed**.

---

## First run

At the first opening, if there are no postings, keys or profiles of yours yet, a full-screen **guided procedure** appears, in six steps (with a progress bar, a *Back* button and *Skip the guide*). Whoever already uses the app never sees
it on its own: the guide only opens if `onboarding_done` is missing **and** there are no postings, applications, scans, keys or user-created profiles (the automatically created Cybersecurity profile, if never edited, does not count).

1. **Welcome:** what the app does, everything stays on your computer, no account.
2. **What job you want:** a kind of job (preset) or up to 8 freely written titles, experience level, "also search internships".
3. **Where:** country, home city (with offline suggestions), radius, remote work.
4. **Sources:** without keys only the free sources work (Arbeitnow, RemoteOK, Remotive), with their limits explained. Adzuna (recommended, free) is explained in three steps with the link to the site, the *Application ID* and
   *Application Key* fields and the **Test the key** button (a single request; outcomes: ok, invalid key, no network, blocked with "retry in a few minutes"; at most one test every 5 seconds). Jooble is optional. *Continue without keys* is always available.
5. **Last choices (optional):** report folder (suggested `~/Documents/JobsHunter`), daily automatic search, notifications.
6. **Summary:** estimate of requests, **Start the first scan** with progress and, at the end, the number of postings found and *See the postings*. With zero results it explains what to try (Adzuna key, simpler titles, wider area) and lets you go back to the right step.

(The guide now has seven steps: the optional CV step was added between 5 and 6.) As soon as the guide ends, on the main page a **card tutorial** starts **only once**: one bubble at a time highlights a button and says what it is for
(search, categories, filters, postings, score, status, bookmark and Saved, Search, Applications, Scan, Settings). Use *Next*/*Back* or the arrow keys; skip with *Skip* or Esc; steps whose element is not there
(for example an empty list) are skipped. Reopen it from **Settings, "Rivedi il tutorial"** (the button label is Italian, like the rest of the interface). Whether it was seen is remembered in the app settings (`POST /api/tutorial/seen`), not in the browser.

You can reopen it any time from **Settings, "Redo the guide"**: your current choices are already filled in and only the profile created by the guide and the
settings you touched are updated; other profiles and postings stay intact. Everything is validated by the server too, with the same rules as Settings and the Search tab, and applied atomically (if something goes wrong,
`settings.json` returns as it was). Keys never appear in logs or responses.

Service interface (`jobshunter/gui/app.py`, logic in `jobshunter/onboarding.py`): `GET /api/onboarding`, `POST /api/onboarding/test-adzuna`, `/estimate` (checks and estimates without saving), `/complete`, `/skip`.

## Download

[Back to "Get started in a minute"](#get-started-in-a-minute). If you do not have Python you can download a ready-made package from the project's **Releases** page on GitHub, open it and use JobsHunter. The packages are **unsigned
and not notarized** (the author has no Apple Developer account and no Windows certificate): that is why the system shows a warning on first launch, explained below.
The code is public and every file has its SHA256 hash (`SHA256SUMS.txt`) so you can check it is the one built from this repository's code.

| System | File | What to do |
|---|---|---|
| macOS (Apple Silicon) | `JobsHunter-<version>-macOS-arm64.zip` | unzip, drag `JobsHunter.app` into Applications |
| Windows 10/11 (x64) | `JobsHunter-<version>-Windows-x64.zip` (folder with `JobsHunter.exe`) or `JobsHunter-<version>-Windows-x64-Setup.exe` (per-user installer, no administrator, if present in the release) | unzip and open `JobsHunter.exe`, or run the installer |
| Linux (amd64 and arm64) | `jobshunter_<version>_amd64.deb` and `jobshunter_<version>_arm64.deb` (Debian, Ubuntu and derivatives); `JobsHunter-<version>-Linux-x86_64.AppImage` (x86_64, if present in the release) | `sudo apt install ./jobshunter_<version>_<arch>.deb`, or `chmod +x` the AppImage and run it |

Your **data** (postings, applications, CV, keys) never lives inside the package: it stays in the user folders listed in [Where the data lives](#where-the-data-lives),
so you can move, update or delete the program without losing it. On first launch, with no `config.toml`, the program creates one from the bundled example file.

**macOS.** The Mac says it "cannot verify the developer" because the app is not notarized. On first launch right-click `JobsHunter.app`, choose **Open**, then **Open** again;
or go to System Settings, **Privacy & Security**, and press **Open Anyway**. After the first time it opens normally. Check the hash: `shasum -a 256 JobsHunter-<version>-macOS-arm64.zip`.
Intel Mac build: not provided.

**Windows.** SmartScreen may say "Windows protected your PC" because the executable is not signed: press **More info**, then **Run anyway**. Check the hash in PowerShell:
`Get-FileHash .\JobsHunter-<version>-Windows-x64.zip -Algorithm SHA256` and compare with `SHA256SUMS.txt`. The native window uses WebView2 (already on Windows 11; Windows 10 needs Microsoft's
"WebView2 Runtime"); if it is missing the app opens in the browser.

**Linux.** The `.deb` installs with `sudo apt install ./jobshunter_<version>_amd64.deb` (or `_arm64.deb` on ARM computers, for example a 64-bit Raspberry Pi or an ARM VM) and is removed with `sudo apt remove jobshunter`: it puts the program in `/opt/jobshunter`, the `jobshunter` command in `/usr/bin` and an entry in the applications menu.
Your data stays in `~/.local/share/jobshunter` even after removal. The AppImage (x86_64 only) is not installed: `chmod +x JobsHunter-<version>-Linux-x86_64.AppImage` and run it; if your system has no FUSE use `./JobsHunter-<version>-Linux-x86_64.AppImage --appimage-extract-and-run`.
For now on Linux **the native window is not included** (it would need the system's GTK and WebKit): `jobshunter` opens the page in the **default browser**, same program and same interface. Built on Ubuntu 22.04: you need a C library (glibc) 2.35 or newer (Debian 12, Ubuntu 22.04 and later are fine).

**What has been tried.** The release CI checks the Linux packages with the `--smoke` test (for the `.deb`: install, run, remove) and its result should be checked in each release draft; the Linux packages have not yet been tried by hand on a real machine. The macOS package was built and checked with the `--smoke` test (it starts the packaged program, checks the page and API, uses no network); the test on a real Windows machine is in progress and until it is done it should be treated as not yet tried.
The scheduled scan from the package runs the package's executable with `--scan-once`.
To build the packages yourself: `packaging/build_mac.sh`, `packaging/build_windows.ps1` and `packaging/build_linux.sh`; to make a release: [docs/RELEASING.md](docs/RELEASING.md).

## Installation

[Back to "Get started in a minute"](#get-started-in-a-minute). This is the **from source** route; the ready-made packages (which need no Python) are in [Download](#download).
You need **Python 3.11 or later**. JobsHunter runs from source on **macOS**, **Windows** and **Linux**; the native window and the automatic scan depend on the system (see the table below).

`./jh` and `jh.bat` check that Python 3.11+ is there (they try `python3.13`, `python3.12`, `python3.11`, `python3`, `python`; on Windows `py -3.13`, `-3.12`, `-3.11`, `-3`, `python`).
If it is missing or too old they say what is needed and **ask for confirmation** (`[s/N]`, "s" = yes) before installing anything: Windows `winget install -e --id Python.Python.3.13 --scope user`
(without winget they open the download page and download nothing themselves), macOS `brew install python@3.13` (without Homebrew, the download page), Linux `apt`, `dnf` or `pacman` with `sudo`
(you type the password yourself in your own terminal). Without an interactive terminal they print the message and exit with an error: they never install silently. After installing you may need to reopen the terminal.

### macOS and Linux

```bash
git clone https://github.com/RiccardoAlb/JobsHunter.git jobshunter
cd jobshunter
./jh setup
./jh gui
```

### Windows (PowerShell or Command Prompt)

```bat
git clone https://github.com/RiccardoAlb/JobsHunter.git jobshunter
cd jobshunter
jh.bat setup
jh.bat gui
```

`setup` creates `.venv` if missing and installs `requirements.txt` (it asks before downloading; `./jh setup --yes` gives the consent in advance). If you run `./jh gui` without a `.venv`, it offers to run `setup`.
If you prefer doing it by hand: `python3 -m venv .venv` and `.venv/bin/pip install -r requirements.txt` (on Windows `py -3 -m venv .venv` and `.venv\Scripts\python.exe -m pip install -r requirements.txt`).
On first launch `config.toml` is created automatically from the example file (`config.example.toml`).

`jh.bat` is the same as `./jh`: it uses `.venv\Scripts\python.exe` and does not depend on the current folder. `python -m jobshunter ...` works everywhere.
In `config.toml` paths on Windows use single quotes (`dir = 'D:\Work\Reports'`) or forward slashes (`D:/Work/Reports`): double quotes treat `\` as a special character.

Then open `config.toml` and enter your keys (see below), or use the guided first run.

> Use `./jh` and not the "editable" install (`pip install -e .`): on macOS, if the folder is on the Desktop or synced with iCloud, the system may hide the file that makes the package importable and the `jobshunter` command stops working. `./jh` does not need it.

### Where the data lives

From source the data lives in the project folder (or in `JOBSHUNTER_HOME`, if you set it). In the windowed app (`./jh app`) it lives in the system's app folder:

| System | Data | Logs |
|---|---|---|
| macOS | `~/Library/Application Support/JobsHunter` | `~/Library/Logs/JobsHunter` |
| Windows | `%APPDATA%\JobsHunter` | `%LOCALAPPDATA%\JobsHunter\Logs` |
| Linux | `$XDG_DATA_HOME/jobshunter` (or `~/.local/share/jobshunter`) | `$XDG_STATE_HOME/jobshunter` (or `~/.local/state/jobshunter`) |

Database, settings, keys and CV are private to the user: mode `600` on macOS and Linux; on Windows through `icacls` (access only for your user, best effort: if it fails it is written to the log). On Windows this cannot be guaranteed the way it is on Unix: keep the data in your own user folder. Your user is identified by SID (works with local, Microsoft, domain and workgroup accounts) and no other account, not even SYSTEM, stays on the list: system backup programs may therefore be unable to read the data files.

### What works on each system

| Feature | macOS | Windows | Linux |
|---|---|---|---|
| Command line (`jh`, `jh.bat`) and GUI in the browser (`gui`) | yes (tested) | being verified (see `docs/phase7_status.md`) | not yet tried on a real Linux |
| Native window (`app`, pywebview: `pip install -r requirements-gui.txt`) | yes (tested) | WebView2: not yet tried | GTK or Qt: not yet tried |
| Without pywebview | `app` opens the browser | `app` opens the browser | `app` opens the browser |
| Automatic scan | LaunchAgent (tested) | Task Scheduler (`schtasks`): tested only with fake commands | `systemd --user` timer, or `cron` if missing: tested only with fake commands |
| Notifications | `osascript` (tested) | Windows toast via PowerShell: not yet tried | `notify-send`, if present: not yet tried |
| Open the folder from the app | Finder | File Explorer | `xdg-open` |

Where something is not proven on a system we say so: the automated tests simulate Windows and Linux (paths, permissions, scheduling with fake commands) but they do not replace a try on a real machine.

### Security notices at first start

- **Windows:** at first start Windows Firewall may ask whether to allow Python on the network: JobsHunter listens **only on 127.0.0.1**, so you can cancel / choose the private network and nothing needs to be opened. SmartScreen may warn about an unsigned app (only for future packages: from source it does not happen).
- **macOS:** the app is neither signed nor notarised: the first start may ask you to confirm it in System Settings, Privacy and Security.
- **Linux:** nothing special; the native window needs the system GTK or Qt packages (see `requirements-gui.txt`).

## Configuration

Everything lives in `config.toml` (start from `config.example.toml`). The file contains your keys: **do not share it** (it is already excluded by `.gitignore`).

### API keys

| Service | Where to get it | Where to put it |
|---|---|---|
| **Adzuna** | <https://developer.adzuna.com> (free registration, "Application ID" and "Application Keys") | `[sources.adzuna] app_id`, `app_key`, then `enabled = true` |
| **Jooble** | form on the site of **your country**, e.g. <https://it.jooble.org/api/about> | `[sources.jooble] api_key`, `host`, then `enabled = true` |

Important notes:
- the Jooble key only works **for its own country**: for Italy the `host` is `it.jooble.org`;
- Jooble has a default limit of **500 requests**: it uses one per search (the estimate is in the profile preview), so reduce titles and countries if you want them to last; with several countries you need one host each (`hosts`);
- instead of the file you can use the environment variables `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `JOOBLE_API_KEY`.

### Main sections

| Section | What it controls |
|---|---|
| `[general]` | database, minimum score, maximum age, **scan duration cap** (`max_scan_seconds`, default 300) |
| `[location]` | useful areas, excluded countries, remote, "home" names and proximity bonus |
| `[notify]` | [ntfy](https://ntfy.sh) notifications: set an unguessable `topic` to turn them on |
| `[sources.*]` | which sources to enable and their settings (queries, city, radius, companies) |
| `[keywords.*]` | keywords and weights per category (BLUE, RED, SYSADM, SEC) |
| `[penalties]`, `[bonus]` | what lowers or raises the score from the title, and the blacklist |
| `[report]` | report folder (you can point it at your Obsidian vault) |
| `[net]` | `contact` and `user_agent`: how JobsHunter introduces itself to sites (see [User-Agent](#user-agent-and-respect-for-sites)) |
| `[search]` | `internships`: also search internships (dedicated searches) |
| `[dedupe]` | duplicate thresholds |
| `[availability]` | `recheck_hours` (validity of a check) and `auto_check_after_scan` (how many postings to check after the scan, 0 = never) |

**To change for yourself:** `home` and `radius_km` (in the Adzuna/Jooble sections, empty in the example: without a city the whole country is searched), `[location] home_names` (the "near home" places, empty in the example),
`include` and the `queries`, which in the example are about cybersecurity and sysadmin roles. Many of these choices can also be made from the GUI (Search tab and Settings).

### User-Agent and respect for sites
Every outgoing request introduces itself with a declared name, **never as a browser**:

```
JobsHunter/0.4.0 (+personal job search tool; contact: you@example.org)
```

The contact is optional (an email or the project address) and is set in `[net] contact` or in Settings, "Advanced, network" block; with `[net] user_agent` you replace the whole header. If a site refuses requests (HTTP 403 or 429)
JobsHunter **does not insist and does not try to get around anything**: the posting stays "not verified" (never "closed") and the source stops. No identity rotation, no browser impersonation.

## Usage

### GUI

```bash
./jh gui              # opens http://127.0.0.1:8765
./jh gui --port 9000  # another port
```

- **Scan** starts the collection, **Stop** interrupts it (sources already finished stay saved).
- **Postings / Jooble / Applications / Duplicates**: the four tabs. Jooble is separate because it only has the preview; Applications is the progress tracker.
- **Filters**: type (BLUE, RED...), "Near home", "Only new", **Radius...** (distance from a city), **Filters...** (work mode, contract type, city, company, minimum RAL), **Only internships** (shortcut), minimum score, search.
  In the list, next to the location, distance and mode appear when known. Filters are saved; the x resets them.
- **Check postings** checks that the postings in the list are still open; **Closed (n)** shows the closed ones.
- **Click on a posting**: panel with the full text, salary, status (open or closed) and the buttons *Open and apply*, *Mark as applied*, *Discard*, *Put back in new*.
- **Generate report**: creates the Markdown file with the current filters.
- **Light/dark theme** with the button next to "Generate report". Keys: `j`/`k` to scroll, `Esc` to close.

### Command line

```bash
./jh scan                         # collects postings (Ctrl+C to stop)
./jh list                         # the best ones, by score
./jh list -t blue -s 40           # only Blue team with score 40+ (for other profiles: -t GROUPNAME)
./jh list --near                  # only near home
./jh list --city Roma --km 80     # within 80 km of Rome
./jh list --mode remote --mode hybrid           # only remote or hybrid
./jh list --where Milano --ral-min 30000        # in Milan, RAL up to at least 30,000 EUR
./jh list --contract internship                 # only internships
./jh list --company exprivia --no-unknown-ral   # one company, only with stated RAL
./jh list --source jooble         # only Jooble previews
./jh show <ID>                    # detail (marks it as seen)
./jh open <ID>                    # opens the posting in the browser
./jh mark <ID> applied            # applied | discarded | seen | new
./jh check                        # checks which postings are still open (in batches, slowly)
./jh check <ID> --force           # rechecks one posting
./jh list --closed                # also shows the closed ones
./jh report --new -s 40           # Markdown report with the new ones
./jh report --city Milano --km 60 --no-generic
./jh stats                        # summary by category
./jh export jobs.csv              # exports to CSV
```

`<ID>` is the first 6 characters shown in the ID column of `list`. With `-c path/config.toml` you can use a different configuration file.

| Option | Commands | Meaning |
|---|---|---|
| `-t, --type` | list, report | red, blue, sysadm, sec, purple |
| `-s, --min-score` | list, report | minimum score (report: 30 by default) |
| `-n, --limit` | list, report | how many postings (report: 20 by default) |
| `--near` | list, report | only near home (radius of `home`) |
| `--new` | report | only postings not yet seen |
| `--source` | list, report | `main` (default), `jooble`, `all` |
| `--city`, `--km`, `--no-generic` | list, report | radius from a city; exclude generic locations |
| `--company` | list, report | only this company (also part of the name) |
| `--where` | list, report | only this city (repeatable; `generica` = generic location) |
| `--mode` | list, report | `remote`, `hybrid`, `onsite`, `unknown` (repeatable) |
| `--ral-min`, `--no-unknown-ral` | list, report | minimum RAL in euros; exclude postings without RAL |
| `--contract` | list, report | `internship`, `apprenticeship`, `fixed`, `permanent`, `other`, `unknown` (repeatable) |
| `--closed` | list | also show postings verified as closed |
| `-n`, `--force` | check | how many postings to check; also recheck recent and closed ones |
| `-o, --out-dir` | report | output folder |

## Customising the score

For profiles that are not cybersecurity, extra keywords, words to exclude and level are set in the editor of the **Search** tab. Below is the tuning of the **cybersecurity** type, which lives in `config.toml`.

Adding a skill is one line in `config.toml`. Example: you want to reward "Elastic" and "Sigma" in the Blue team:

```toml
[keywords.blue]
label = "BLUE"
terms = { "soc analyst" = 12, "siem" = 8, "elastic" = 6, "sigma" = 6 }
```

To look for more senior roles, remove the penalties on `senior`/`lead` in `[penalties]`. To exclude a kind of posting add a word to `blacklist`. After each change run `./jh scan` again: the postings the scan finds again are
re-scored with the new rules.

## Reports for Obsidian

`./jh report` (or the button in the GUI) creates an `.md` file with:

- a clickable **index** (score, type, role, company, location, salary);
- for each posting a **Details** box (location, score, salary, date, keywords, source, ID);
- the **link to apply** and a `- [ ] Applied` checkbox;
- the **full text** of the posting.

To have the files land directly in your vault, set the folder in `[report]`:

```toml
[report]
dir = "/path/to/your/vault/Postings"
```

The file name contains the filters used and the time, so two reports never overwrite each other.

## Mac app

Besides the terminal and the browser, JobsHunter can be packaged as a real **macOS app**: `JobsHunter.app`, with a native window, a Dock icon and the logo as icon. The engine (Python) runs inside the app, so you do not need the terminal.

```bash
./build_mac_app.sh     # builds, signs and installs ~/Applications/JobsHunter.app (requires macOS)
./jh app               # alternatively: opens the same window without packaging (needs `pip install -r requirements-mac.txt`, i.e. pywebview)
```

- **Where the data lives:** `~/Library/Application Support/JobsHunter/` (database, `config.toml`, `settings.json`). Logs are in `~/Library/Logs/JobsHunter/app.log`.
- **Coming from the old name (JobHunter):** at the first start the data in `~/Library/Application Support/JobHunter/` is **copied** (never moved) into the new folder, after checking the database integrity; the original stays as it is. If both
  folders exist the new one is used; if the copy fails the app carries on with the old one. The old LaunchAgent (`local.jobhunter.scan`) is also removed and, if automatic scanning was on, a new one is installed. The build script does not touch the old
  `JobHunter.app`: once you have checked that the new app works, remove it with `./scripts/remove_old_app.sh` (it asks for confirmation and leaves your data).
- **First run:** the app creates the configuration on its own. In the **Settings** tab you enter the Adzuna and Jooble keys, the home city and radius, the report folder (your Obsidian vault) and the ntfy topic. Keys are never shown again: the tab
  only says "set". Changes are saved in `settings.json` (restricted permissions) and do not touch `config.toml`.
- **Bringing the data you already have** (database, configuration and keys of the project) into the app:
  ```bash
  ./jh app-import          # copies, does not move; without --force it does not overwrite an existing database
  ```
- **Posting links** open in the default browser, not inside the window.
- **Signing:** the app is signed "ad hoc", enough to use it on the Mac where you built it. To distribute it to others without Gatekeeper warnings you need a Developer ID certificate and notarisation (Apple Developer Program).
- **Why the script builds outside the project:** if the folder is synced with iCloud (Desktop or Documents), files receive attributes that prevent signing. The script uses `~/Library/Caches/JobsHunterBuild`.
- **Reducing the size:** of the cities archive (GeoNames) only the needed file is included; the app weighs about 70 MB.

## Automatic scans

JobsHunter can search on its own, even with the app closed, and tell you when there is news. It uses the system's own tool: a **LaunchAgent** on macOS, **Task Scheduler** (`schtasks`, a per-user task "JobsHunter scan", no administrator rights) on Windows, a **`systemd --user` timer** on Linux (or **cron**, with a line marked `# JobsHunter`, if systemd is missing). If none is available it says so. On Windows and Linux it is tested only with fake commands.

- **How to turn it on:** Settings, **Automatic scan** block: tick "on", choose the times (1 to 4 per day, for example `09:00, 18:30`) or "every N hours", and press **Apply**. From the terminal: `./jh schedule on --at "09:00, 18:30"`,
  `./jh schedule status`, `./jh schedule off`.
- **How it works:** it creates a macOS task (LaunchAgent, `~/Library/LaunchAgents/local.jobshunter.scan.plist`) that at that time launches the app without a window (`JobsHunter --scan-once`, in development `./jh scan-auto`). If the Mac is
  asleep at the planned time, it starts on wake. It is turned off from the same Settings, which also remove the file. At start the app realigns the task if you rebuilt or moved the app.
- **What it does on each round:** reads the sources, computes duplicates, checks that the best postings are still open (`auto_check_after_scan`), records the scan in the **history** (visible in Settings) and, if there are new postings,
  sends a macOS **notification** with the best ones. With an [ntfy](https://ntfy.sh) topic in Settings it also reaches your phone.
- **One scan at a time:** a file lock prevents the automatic scan and the Scan button from working together; the second waits its turn (it does not start and says so).
- **News since your last visit:** when you open the app a box shows how many new postings arrived, how many were found closed and how many possible duplicates need review. "See the new ones" filters them, "Mark as read" resets the count.
- **Good to know:** notifications appear under the name "Script Editor" (macOS's way for notifications without a signed app); if you do not see them, check System Settings, Notifications. Outside the Mac app, if the project is in Desktop
  or Documents, macOS may prevent a background task from reading it: for the scheduled scan use the installed app.

## Security and privacy

- **Everything stays local**: database, reports and keys are on your computer.
- **The GUI only listens on `127.0.0.1`** and refuses requests that do not come from there: it checks `Host` and `Origin` on every request that changes data and refuses those the browser declares cross-site; request bodies are limited
  (256 KB, 6 MB only for the CV); the page has a restrictive CSP policy and loads nothing from other sites. **It has no password**: do not expose it on the internet (if you put it on a server, reach it only through a VPN or private network).
- **Secrets:** keys, settings, CV and database live in files with `600` permissions; they never appear in responses, in logs (httpx requests are not logged) or in reports. CSV export neutralises "formulas" (`=`, `+`, `-`, `@`).
  No shell command uses user data.
- Posting texts come from external sites and are shown as **plain text**, never as HTML.
- The **Adzuna posting links** (in the database and in reports) contain your application ID (`utm_source=...`). It is not the secret key, but if you share a report or `jobshunter.db` remove it first or avoid sharing.
- `config.toml` contains personal keys: do not commit or share it. If a key gets out, regenerate it on the service's site.

## Project status and next steps

**Done**
- **Phase 0, base:** collection from Adzuna, Jooble and free sources; score; duplicates; reports for Obsidian; filters (radius, mode, contract, RAL, company, city); open-posting check; internships; applications tracker; Mac app with native window.
- **Phase 1, automatic scans:** scheduling with LaunchAgent even with the app closed, notifications, history and news since last visit.
- **Phase 2, general search:** search profiles (presets and free titles), 19 countries, Search tab with request preview, currency, rewritten duplicate detection (fast and more precise), automatic migration of existing data. Built with one agent writing the code and
  another testing it independently (4 rounds, 15 problems found, 14 fixed).
- **Phase 3, first run:** guided procedure (now seven steps, with the optional CV) for non-technical users (job, area, explained Adzuna keys with key test, report folder, first scan with progress), reopenable from Settings. See [First run](#first-run).
- **Phase 4, CV comparison:** explained 0-100 affinity, all local. See [CV comparison](#cv-comparison). The first-run guide now has seven steps (the CV is the sixth, optional).
- **Phase 6, personal categories per profile:** name and words per category, filters in the list, editable copy of the presets' categories, optional field in the guide,
  `./jh profiles categories` commands. See [Personal categories per profile](#personal-categories-per-profile) and `docs/phase6_status.md`.
- **Phase 5, polish for publication (0.2.0):** **honest and configurable User-Agent**, rename to **JobsHunter** with safe migration of data and scheduling, removal of personal data (`scripts/check_publishable.py`), disclaimer and credits,
  `THIRD_PARTY_NOTICES.md`, English README, screenshots, GitHub CI, final security review. See `CHANGELOG.md`.

**To do, in this order**
1. A CV analysis with a language model would remain strictly optional (not in this phase).
2. **Publication:** **MIT license already chosen**, still to do: repository name and description, check the attributions on the services' sites (see [Disclaimer](#disclaimer)), automatic data backup before any future migration.
3. Ideas in the queue: user-editable lists for duplicates (company forms, abbreviations, city names), email alerts for LinkedIn and Indeed, exporting follow-ups and interviews to a calendar, application statistics, Intel Mac build, signing and notarisation.

**For whoever continues the work (even months from now)**
- **Test rules:** never use real data (every test has a temporary `JOBSHUNTER_HOME` and `HOME` and a fake launchctl: `tests/conftest.py` guarantees it); **no network request to Adzuna, Jooble or other job sites in tests** (Adzuna blocks with HTTP 403 after a few
  close-together requests): fake sources and simulated responses are used; do not kill processes you did not start.
- **Duplicates:** labelled test sets are in `tests/data/`; a "blind" set stops measuring once the developer has seen it, so for every check a new set must be written and kept out of the project until the end. Automatic confirmation (100%) must stay 100% precise.

## Known limits

- **LinkedIn and Indeed are not used**: they have no public search API and forbid scraping. For those sources the clean way is email alerts (not implemented yet).
- **Jooble** only gives the preview; the full text is read on the site. The key works for one country only and has a limit of 500 requests.
- **Adzuna** limits close-together requests (HTTP 403): checks and reports go slowly (one request every 2 seconds) and stop at the first refusal. With many countries and profiles requests grow: see the estimate in the profile preview.
- The **full text** is only downloaded for Adzuna postings. The report takes about 2 seconds per posting to download or check: this is intended.
- **Profiles in other countries:** for a free profile the titles must be written in the language of the country ("Krankenpfleger" for Germany): the search uses the title as is. The Greenhouse and Lever sources use the career pages listed in
  `config.toml` (cybersecurity companies) and are only queried by cybersecurity-type profiles.
- **Duplicates:** the program proposes and you decide; automatic confirmation (100%) is precise, but some duplicates are **not proposed**: translations (Sviluppatore / Developer), rare abbreviations and company forms, city names in other
  languages (St. Gallen / Sankt Gallen), typos in short words. This is an accepted limit (the risk is one more duplicate to look at, never a posting hidden by mistake).
- **RAL:** the filter is always in euros; salaries in other currencies count as "not stated". A little over one posting in four states the RAL.
- The **radius** uses straight-line distance and recognises cities above 15,000 inhabitants; smaller places stay "without distance" unless the posting also gives the province.
- The macOS package is for **Apple Silicon** and is not notarized (security warnings on first launch, see [Download](#download)); Windows and Linux are new and not yet tried thoroughly on real machines (see the table in Installation).
- Scores are heuristic: they help order, not judge whether a job is right for you.

## Project layout

```
jobshunter/
+-- jh                      # launcher (does not depend on the package install)
+-- packaging/              # package building (PyInstaller, per-system scripts, Windows installer, smoke test)
+-- build_mac_app.sh        # builds and installs JobsHunter.app
+-- scripts/                # check_publishable.py, gen_third_party.py, demo_server.py, take_screenshots.py, remove_old_app.sh
+-- docs/screenshots/       # GUI screenshots (invented data)
+-- THIRD_PARTY_NOTICES.md  # licenses of the libraries and data credits
+-- CHANGELOG.md, CONTRIBUTING.md, SECURITY.md
+-- .github/workflows/ci.yml
+-- tests/                  # automated tests (pytest)
|   +-- builder/            #   phase 2 tests written with the code
|   +-- qa/                 #   independent testing (API, migration, duplicates, robustness, security)
|   +-- data/               #   labelled sets and test data (synthetic)
+-- run_app.py              # entry point of the packaged app
+-- config.example.toml     # example configuration, to copy into config.toml
+-- requirements.txt
+-- branding/               # original logo and the script that generates the icons
+-- jobshunter/
    +-- cli.py              # terminal commands (click + rich)
    +-- scanner.py          # runs the scan, with Stop and duration cap
    +-- autoscan.py         # scan with lock, history and notifications (even without a window)
    +-- scheduler.py        # macOS LaunchAgent: scheduled scan
    +-- settings.py         # paths, settings editable from the GUI (settings.json)
    +-- macapp.py           # native window (pywebview) and bridge to macOS
    +-- sources/            # the sources (Adzuna, Jooble, Arbeitnow, ...)
    +-- profiles.py         # search profiles, presets, countries, queries per source
    +-- onboarding.py       # first-run guided procedure (state, key test, validation, application)
    +-- rescore.py          # re-scores postings already stored for a profile
    +-- scoring.py          # location filter and score (historical and per profile)
    +-- db.py               # SQLite archive, statuses, duplicates, radius filter
    +-- dedupe.py           # duplicate detection with percentage
    |                       # (applications live in db.py: tables applications and app_events)
    +-- geo.py              # city -> coordinates (offline) and distances
    +-- meta.py             # annual RAL, work mode and city derived from the text
    +-- fulltext.py         # downloads the full text of a posting
    +-- availability.py     # checks whether a posting is still open (slowly and without false "closed")
    +-- report.py           # Markdown report for Obsidian
    +-- notify.py           # ntfy notifications
    +-- net.py              # HTTP client and declared User-Agent (all requests go through here)
    +-- migrate.py          # safe migration from the old name (data copy, database check)
    +-- gui/                # Flask server and single page (static/index.html)
```

To add a **new source**: create a class in `sources/boards.py` with a `fetch()` method returning a list of `Job`, call `self.check()` between requests (so Stop and the duration cap work), register it in `REGISTRY` and add its
`[sources.name]` section to `config.toml`. Use `self.http()` for requests: it carries the declared User-Agent.

## Troubleshooting

| Problem | Cause and solution |
|---|---|
| `ModuleNotFoundError: jobshunter` with the `jobshunter` command | Use `./jh`: the "editable" install can break on macOS (hidden file). |
| `Adzuna: chiavi mancanti` (keys missing) | Enter `app_id` and `app_key` in `config.toml` (or the environment variables). |
| Jooble returns American postings or error 403 | Key and `host` must match the same country (e.g. `it.jooble.org`). |
| Jooble postings have no full text | Normal: read the posting from the link (their pages are protected by anti-bot systems). |
| The GUI does not start: port in use | Another copy is already running: use `--port` or close it (`lsof -nP -iTCP:8765 -sTCP:LISTEN`). |
| The Mac app does not open or closes immediately | Look at `~/Library/Logs/JobsHunter/app.log`. If you changed the code, rebuild it with `./build_mac_app.sh`. |
| The GUI shows an old version | Stop the server (Ctrl+C), restart it and reload the page with Cmd+Shift+R. |
| The favicon does not change | Browser cache: raise the `?v=` number in the icon links in `static/index.html`. |
| "The site is limiting requests" (HTTP 403) | Adzuna blocks requests that are too close together. Wait a few minutes or hours and retry; it is not a closed posting. JobsHunter does not bypass blocks (it introduces itself by its own name, see [User-Agent](#user-agent-and-respect-for-sites)). |
| No posting near your city | Normal: collect more data, widen the radius or change `home` and the `queries` in the sources. |

## Development and tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q                      # the whole suite (over 1,500 tests)
python scripts/check_publishable.py                # no secrets, personal paths or emails; personal data ignored by Git
.venv/bin/python tests/qa/measure_dedupe.py        # duplicate precision and recall, and wrong pairs
```

Tests make no network requests (the test harness forbids them, DNS included): they use a fake source and simulated responses. They cover score, contract type, open-posting check, automatic scan (lock, history, notifications), scheduling, profiles
and countries, data migration, duplicates and the APIs. If you add a feature, add the test too.

- `tests/` holds the base and phase 1 tests (`test_*.py`), and `tests/test_phase5.py` (User-Agent, rename, migration, LaunchAgent, publication checks).
- `tests/builder/` are the tests written together with the phase 2 code (profiles, sources with fake network, scan, duplicates).
- `tests/qa/` is the independent testing: profiles and APIs, data migration, robustness, concurrency, security and the labelled duplicate sets (`tests/data/*.json`: main, holdout and three blind sets). Proofs of the known duplicate limits are
  marked "expected failure" (xfail); **the proof that automatic confirmation is 100% precise is mandatory**.
- If you change `dedupe.py`, measure again with `measure_dedupe.py` and write a new blind set for verification: the existing ones are now "seen".
- Continuous integration (`.github/workflows/ci.yml`) runs the tests on macOS and Linux (Linux does not block yet) and the publication check.

## Notes on sources and credits

- It uses the sources **respecting their terms**: personal keys, spaced-out requests, no bypassing of anti-bot protections. It is not meant for mass collection.
- **Adzuna** and **Jooble** are third-party services, subject to their own terms and limits.
- City coordinates come from **GeoNames** (CC BY 4.0 license), through the `geonamescache` package.
- The licenses of the libraries in use are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- The project is **not affiliated** with Adzuna, Jooble, LinkedIn or Indeed.

## Disclaimer

- **No affiliation.** JobsHunter is an independent project: it is **not affiliated with, sponsored or endorsed** by Adzuna, Jooble, LinkedIn, Indeed or the other services mentioned. Names and trademarks belong to their owners.
- **Respect the API terms.** Keys are personal and free: use them within the terms of use of Adzuna and Jooble (for example Jooble's request cap) and do not share them. The program spaces out requests and stops at the first refusal; it does not
  bypass anti-bot protections. LinkedIn and Indeed are not used.
- **Personal use.** It is meant for one person's job search, on their own computer; not for mass collection, for reselling posting data or for building a service. The content of the postings remains with its owners.
- **Data stays local.** Database, applications, CV, keys and reports are on your computer. No telemetry, no account. The only outgoing requests go to the posting sources, the posting pages (to check them or read their text) and ntfy.sh if you turn on notifications.
- **No warranty.** Scores are heuristic and the "open/closed" checks are cautious but not infallible: always check the original posting before applying.
- **Adzuna: personal use allowed; commercial products require a written agreement.** See [Adzuna's terms](https://developer.adzuna.com/docs/terms_of_service).
  Every Adzuna posting is labelled "Jobs by Adzuna" (list, detail panel, Markdown report, CSV export) linking to <https://www.adzuna.co.uk>. The label is stylised text only
  (at least 116x23 px): **replace it with the official logo from adzuna.co.uk/press.html after checking the terms** (the logo is not in the repository).
- **Full text from the Adzuna page: optional feature.** The API only gives a preview; the full text (and the "open/closed" check) is read from the public posting page, which is **not covered by the API terms**.
  Turn it off in Settings, "Download the full text of Adzuna postings" (default: on; `full_text = false` under `[sources.adzuna]`).
- **Attributions and credits:**
  - **GeoNames** (<https://www.geonames.org>), **CC BY 4.0** license, through the `geonamescache` package: coordinates of cities above 15,000 inhabitants.
  - **Adzuna**: postings come from the Adzuna API (<https://developer.adzuna.com>); the app shows "Jobs by Adzuna" with the link to the site in Settings, About.
  - **Jooble** (<https://jooble.org/api/about>): posting previews through its API.
  - Third-party libraries and their licenses are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- **To verify before publishing** (cannot be checked offline): the **current** terms of use and attribution rules of Adzuna ("Jobs by Adzuna" text or logo, link to the site, limits on requests and on data retention) and of Jooble, and GeoNames' conditions. If they
  require a different or more visible attribution, update it in Settings, About and here.

## License

Released under the **MIT** license (file [LICENSE](LICENSE)): you may use, copy and modify the code, keeping the author's name and the license notice. The software comes with no warranty. The license covers this project's code, not the data of the connected services (Adzuna, Jooble and the others), which stay under their own terms.
To contribute see [CONTRIBUTING.md](CONTRIBUTING.md); to report security problems see [SECURITY.md](SECURITY.md).

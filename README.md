# dscfind
SP26 DSC190 Final Project

`dscfind` is a command-line search engine for UCSD's data science course
materials. It crawls [dsc-courses.github.io](https://dsc-courses.github.io),
follows the links to individual course websites, harvests the resources they
point to (lectures, assignments, readings, notebooks, exams, ...), and lets you
search all of it from your terminal with ranked results — so reviewing a topic
no longer means clicking through a dozen course pages by hand.

## Installation

```bash
uv add "git+https://github.com/<your-username>/dscfind.git"
```

This exposes a `dscfind` command. (You can also clone the repo and run it with
`uv run dscfind` from inside the project.)

## Usage

Everything happens in two steps: build a local index once, then search it as
often as you like.

**1. See what courses exist:**

```bash
dscfind courses
```

Lists every course found on dsc-courses.github.io with its most recent offering.

**2. Build the index** (crawls course websites — do this once, then refresh
occasionally):

```bash
# Index one or more specific courses (fast, recommended):
dscfind index -c "DSC 152" -c "DSC 80"

# Index the most recent offering of *every* course:
dscfind index

# Include every past offering, and crawl deeper:
dscfind index -c "DSC 80" --all-offerings --max-pages 40
```

Useful flags: `--max-pages N` (pages crawled per site, default 25), `--delay S`
(seconds between requests, default 0.5, to stay polite).

**3. Search:**

```bash
# Basic keyword search across everything you've indexed:
dscfind search logistic regression

# Restrict to a course and limit the number of results:
dscfind search "partial f-test" -c "DSC 152" -n 5

# Jump straight to the top hit in your browser:
dscfind search ar arima time series --open
```

Results are ranked with BM25 over each resource's title, type, course, and the
heading it appeared under, so the most relevant lectures/assignments float to
the top.

**Where is my index?**

```bash
dscfind where
```

Prints the path to the cached index (a plain JSON file under `~/.dscfind/`, or
wherever `DSCFIND_HOME` points). Delete it to start fresh.

## How it works

`crawl.py` parses the index page into courses and offering links, then does a
bounded breadth-first crawl of each course site, pulling out every meaningful
hyperlink. `index.py` stores those as records in a JSON file. `search.py` ranks
them with a small from-scratch BM25 implementation. `cli.py` wires it together
with [click](https://click.palletsprojects.com/) and
[rich](https://rich.readthedocs.io/).

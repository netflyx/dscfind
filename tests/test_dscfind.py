"""Tests for the pure parsing / ranking logic (no network needed)."""

from pathlib import Path

import pytest

from dscfind.crawl import extract_links, guess_kind, parse_index
from dscfind.index import Record, load_index, save_index
from dscfind.search import BM25, tokenize

FIX = Path(__file__).parent / "fixtures"


# --- index parsing --------------------------------------------------------- #
def test_parse_index_finds_courses():
    courses = parse_index((FIX / "index.html").read_text(), "https://dsc-courses.github.io")
    codes = {c.code for c in courses}
    assert {"DSC 152", "DSC 80", "COGS 18"} <= codes


def test_parse_index_groups_and_offerings():
    courses = {c.code: c for c in
               parse_index((FIX / "index.html").read_text(), "https://dsc-courses.github.io")}
    dsc80 = courses["DSC 80"]
    assert dsc80.most_recent.label == "Spring 2026 (Rahman)"
    assert len(dsc80.offerings) == 3            # 1 recent + 2 previous
    assert courses["COGS 18"].group == "Undergraduate COGS"


def test_parse_index_resolves_relative_and_absolute_urls():
    courses = {c.code: c for c in
               parse_index((FIX / "index.html").read_text(), "https://dsc-courses.github.io")}
    assert courses["DSC 152"].most_recent.url == "https://dsc-courses.github.io/dsc152-2026-sp"


# --- course page extraction ------------------------------------------------ #
def test_extract_links_pulls_resources_and_skips_junk():
    page = "https://dsc-courses.github.io/dsc152-2026-sp/"
    links, to_crawl = extract_links((FIX / "course.html").read_text(), page)
    titles = {l.title for l in links}
    assert "Lecture 1: Linear Regression" in titles
    assert "Homework 2" in titles
    assert "Course Textbook" in titles
    assert "here" not in titles          # junk anchor dropped
    assert "email" not in titles         # mailto dropped


def test_extract_links_resolves_relative_urls():
    page = "https://dsc-courses.github.io/dsc152-2026-sp/"
    links, _ = extract_links((FIX / "course.html").read_text(), page)
    lec1 = next(l for l in links if l.title.startswith("Lecture 1"))
    assert lec1.url == "https://dsc-courses.github.io/dsc152-2026-sp/lectures/lec01.pdf"


@pytest.mark.parametrize("anchor,url,expected", [
    ("Lecture 5: Trees", "x/lec05.pdf", "lecture"),
    ("Homework 3", "hw/hw03.ipynb", "assignment"),
    ("Practice Midterm", "exam.pdf", "exam"),
    ("Course Reading", "notes.html", "reading"),
])
def test_guess_kind(anchor, url, expected):
    assert guess_kind(anchor, url) == expected


# --- search ---------------------------------------------------------------- #
def _records():
    return [
        Record("DSC 152", "Applied Stats", "SP26", "u", "Lecture 1: Linear Regression",
               "u1", "lecture", "Week 1"),
        Record("DSC 152", "Applied Stats", "SP26", "u", "Lecture 2: Logistic Regression",
               "u2", "lecture", "Week 2"),
        Record("DSC 80", "Practice DS", "SP26", "u", "Hypothesis Testing lab",
               "u3", "lab", "Week 3"),
    ]


def test_tokenize():
    assert tokenize("A/B Testing, v2!") == ["a", "b", "testing", "v2"]


def test_search_ranks_relevant_first():
    hits = BM25(_records()).search("logistic regression")
    assert hits[0].record.title == "Lecture 2: Logistic Regression"


def test_search_course_filter():
    hits = BM25(_records()).search("testing", course="DSC 80")
    assert len(hits) == 1 and hits[0].record.course_code == "DSC 80"


def test_search_empty_query():
    assert BM25(_records()).search("") == []


# --- index round-trip ------------------------------------------------------ #
def test_index_save_load(tmp_path):
    p = tmp_path / "index.json"
    save_index(_records(), p)
    loaded, meta = load_index(p)
    assert len(loaded) == 3
    assert meta["count"] == 3
    assert loaded[0].title == "Lecture 1: Linear Regression"

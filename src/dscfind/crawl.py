"""Fetching and parsing logic.

The network-touching code is deliberately tiny (``fetch``). Everything else is a
pure function that takes HTML text in and gives structured data out, so the
parsing can be unit-tested without a network connection.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "dscfind/0.1 (+https://github.com/dsc-courses/dsc-courses.github.io)"

# Anchor text this short or this generic carries no search value.
_JUNK_ANCHORS = {
    "", "here", "link", "this", "click here", "previous", "next", "home",
    "back", "top", "more", "read more", "github", "edit", "source",
}

# File extensions we treat as concrete downloadable resources.
_RESOURCE_EXTS = {
    ".pdf": "pdf", ".ipynb": "notebook", ".pptx": "slides", ".ppt": "slides",
    ".key": "slides", ".zip": "archive", ".csv": "data", ".tsv": "data",
    ".py": "code", ".r": "code", ".md": "page",
}

# Words in anchor text / url that hint at the kind of material.
_KIND_HINTS = [
    (re.compile(r"\b(lecture|lec\b|slides?|deck)\b", re.I), "lecture"),
    (re.compile(r"\b(lab|discussion|section)\b", re.I), "lab"),
    (re.compile(r"\b(hw|homework|assignment|project|ps\d|problem set)\b", re.I), "assignment"),
    (re.compile(r"\b(exam|quiz|midterm|final|practice)\b", re.I), "exam"),
    (re.compile(r"\b(reading|textbook|notes?|reference)\b", re.I), "reading"),
    (re.compile(r"\b(video|recording|podcast)\b", re.I), "video"),
]


@dataclass
class Offering:
    label: str        # e.g. "Spring 2026 (Chi)"
    url: str


@dataclass
class Course:
    code: str         # e.g. "DSC 152"
    name: str         # e.g. "Applied Statistical Data Analysis and Inference"
    group: str        # "Undergraduate DSC", "Undergraduate COGS", "Graduate DSC"
    offerings: list[Offering] = field(default_factory=list)

    @property
    def most_recent(self) -> Offering | None:
        return self.offerings[0] if self.offerings else None


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    retry = Retry(total=2, backoff_factor=0.4,
                  status_forcelist=(429, 500, 502, 503, 504))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


def fetch(url: str, session: requests.Session | None = None,
          timeout: int = 15) -> str | None:
    """Return the HTML text at ``url`` or ``None`` on any failure / non-HTML."""
    session = session or make_session()
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    ctype = resp.headers.get("Content-Type", "")
    if "html" not in ctype and "<html" not in resp.text[:2000].lower():
        return None
    return resp.text


# --------------------------------------------------------------------------- #
# Parsing the top-level index page
# --------------------------------------------------------------------------- #
def parse_index(html: str, base_url: str) -> list[Course]:
    """Parse the dsc-courses.github.io landing page into a list of Courses."""
    soup = BeautifulSoup(html, "lxml")
    group = "Undergraduate DSC"
    courses: list[Course] = []

    for tag in soup.find_all(["h2", "h3"]):
        text = tag.get_text(" ", strip=True)
        # Drop the leading "#anchor-slug" that the theme injects into headings.
        text = re.sub(r"^#?\S*\s*", "", text) if text.startswith("#") else text
        text = text.strip()
        if not text:
            continue

        if tag.name == "h2":
            low = text.lower()
            if "cogs" in low:
                group = "Undergraduate COGS"
            elif "graduate" in low:
                group = "Graduate DSC"
            elif "undergraduate" in low:
                group = "Undergraduate DSC"
            continue

        # h3 == a course heading like "DSC 152 Applied Statistical ..."
        m = re.match(r"([A-Z]{2,5})\s*(\d+[A-Z]{0,2})\s+(.*)", text)
        if not m:
            continue
        code = f"{m.group(1)} {m.group(2)}"
        name = m.group(3).strip()
        course = Course(code=code, name=name, group=group)

        # Offerings live in the sibling block(s) until the next heading.
        for sib in tag.find_all_next():
            if sib.name in ("h2", "h3"):
                break
            if sib.name == "a" and sib.get("href"):
                label = sib.get_text(" ", strip=True)
                url = urljoin(base_url, sib["href"])
                if label and not url.startswith("#"):
                    course.offerings.append(Offering(label=label, url=url))
        courses.append(course)

    return courses


# --------------------------------------------------------------------------- #
# Parsing an individual course website
# --------------------------------------------------------------------------- #
def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def guess_kind(anchor: str, url: str) -> str:
    blob = f"{anchor} {url}"
    for pat, kind in _KIND_HINTS:
        if pat.search(blob):
            return kind
    path = urlparse(url).path.lower()
    for ext, kind in _RESOURCE_EXTS.items():
        if path.endswith(ext):
            return kind
    return "page"


def _same_site(url: str, root: str) -> bool:
    """True if ``url`` is on the same host and under the course's path prefix."""
    ru, rr = urlparse(url), urlparse(root)
    if ru.netloc != rr.netloc:
        return False
    prefix = rr.path.rsplit("/", 1)[0] if "." in rr.path.rsplit("/", 1)[-1] else rr.path
    prefix = prefix.rstrip("/")
    return ru.path.startswith(prefix) if prefix else True


@dataclass
class Link:
    title: str
    url: str
    kind: str
    context: str   # nearest heading or the page <title>, for search recall


def extract_links(html: str, page_url: str) -> tuple[list[Link], list[str]]:
    """From one course page, return (indexable links, same-site pages to crawl)."""
    soup = BeautifulSoup(html, "lxml")
    page_title = _clean(soup.title.get_text()) if soup.title else ""

    links: list[Link] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        url = urljoin(page_url, href)
        anchor = _clean(a.get_text())
        if anchor.lower() in _JUNK_ANCHORS or len(anchor) < 2:
            continue
        if url in seen:
            continue
        seen.add(url)

        # Nearest preceding heading gives helpful context (e.g. "Week 3").
        heading = a.find_previous(["h1", "h2", "h3", "h4"])
        context = _clean(heading.get_text()) if heading else page_title
        links.append(Link(title=anchor, url=url,
                           kind=guess_kind(anchor, url), context=context))

    # Same-site sub-pages worth visiting (schedule, syllabus, weeks, ...).
    to_crawl = [
        urljoin(page_url, a["href"])
        for a in soup.find_all("a", href=True)
        if not a["href"].startswith(("#", "mailto:", "javascript:", "tel:"))
        and _same_site(urljoin(page_url, a["href"]), page_url)
        and urlparse(urljoin(page_url, a["href"])).path.lower().rstrip("/").endswith(
            ("", "/", ".html")
        )
        and not urlparse(urljoin(page_url, a["href"])).path.lower().endswith(
            (".pdf", ".ipynb", ".zip", ".pptx", ".csv", ".png", ".jpg")
        )
    ]
    return links, to_crawl


def crawl_course(offering_url: str, *, max_pages: int = 25, delay: float = 0.5,
                 session: requests.Session | None = None,
                 on_page=None) -> list[Link]:
    """BFS over a single course website, returning all indexable links found."""
    session = session or make_session()
    queue = [offering_url]
    visited: set[str] = set()
    all_links: dict[str, Link] = {}

    while queue and len(visited) < max_pages:
        page = queue.pop(0)
        norm = page.split("#")[0]
        if norm in visited:
            continue
        visited.add(norm)
        if on_page:
            on_page(norm)

        html = fetch(norm, session=session)
        if delay:
            time.sleep(delay)
        if not html:
            continue

        links, sub_pages = extract_links(html, norm)
        for link in links:
            all_links.setdefault(link.url, link)
        for sp in sub_pages:
            if sp.split("#")[0] not in visited:
                queue.append(sp)

    return list(all_links.values())

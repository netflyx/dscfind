"""The ``dscfind`` command-line interface."""

from __future__ import annotations

import sys
import webbrowser

import click
from rich.console import Console
from rich.table import Table

from . import INDEX_URL, __version__
from .crawl import Course, crawl_course, fetch, make_session, parse_index
from .index import Record, index_path, load_index, save_index
from .search import BM25

console = Console()
err = Console(stderr=True)


def _load_courses() -> list[Course]:
    html = fetch(INDEX_URL)
    if not html:
        err.print(f"[red]Could not reach {INDEX_URL}[/red]")
        raise SystemExit(1)
    return parse_index(html, INDEX_URL)


def _match(courses: list[Course], wanted: tuple[str, ...]) -> list[Course]:
    if not wanted:
        return courses
    norm = {w.replace(" ", "").lower() for w in wanted}
    return [c for c in courses
            if c.code.replace(" ", "").lower() in norm
            or any(c.code.replace(" ", "").lower().startswith(w) for w in norm)]


@click.group(help="Search UCSD data science course materials from your terminal.")
@click.version_option(__version__, prog_name="dscfind")
def main() -> None:
    pass


@main.command("courses")
def courses_cmd() -> None:
    """List every course found on dsc-courses.github.io."""
    courses = _load_courses()
    table = Table(title="UCSD DSC course websites", show_lines=False)
    table.add_column("Code", style="cyan", no_wrap=True)
    table.add_column("Name")
    table.add_column("Most recent offering", style="green")
    for c in courses:
        recent = c.most_recent.label if c.most_recent else "—"
        table.add_row(c.code, c.name, recent)
    console.print(table)
    console.print(f"\n[dim]{len(courses)} courses.[/dim]")


@main.command("index")
@click.option("-c", "--course", "wanted", multiple=True,
              help="Course code(s) to index, e.g. -c 'DSC 152'. Repeatable. "
                   "Omit to index the most recent offering of every course.")
@click.option("--all-offerings", is_flag=True,
              help="Index every past offering, not just the most recent one.")
@click.option("--max-pages", default=25, show_default=True,
              help="Max pages to crawl per course website.")
@click.option("--delay", default=0.5, show_default=True,
              help="Seconds to wait between requests (be polite).")
def index_cmd(wanted: tuple[str, ...], all_offerings: bool,
              max_pages: int, delay: float) -> None:
    """Crawl course websites and (re)build the local search index."""
    courses = _match(_load_courses(), wanted)
    if not courses:
        err.print("[red]No matching courses. Try `dscfind courses`.[/red]")
        raise SystemExit(1)

    session = make_session()
    records: list[Record] = []
    targets: list[tuple[Course, object]] = []
    for c in courses:
        offs = c.offerings if all_offerings else (
            [c.most_recent] if c.most_recent else [])
        for off in offs:
            targets.append((c, off))

    console.print(f"Indexing [bold]{len(targets)}[/bold] course offering(s)…\n")
    seen_urls: set[str] = set()
    for course, off in targets:
        console.print(f"  [cyan]{course.code}[/cyan] · {off.label}")
        links = crawl_course(off.url, max_pages=max_pages, delay=delay,
                             session=session)
        added = 0
        for link in links:
            if link.url in seen_urls:
                continue
            seen_urls.add(link.url)
            records.append(Record(
                course_code=course.code, course_name=course.name,
                offering=off.label, offering_url=off.url,
                title=link.title, url=link.url,
                kind=link.kind, context=link.context,
            ))
            added += 1
        console.print(f"      [dim]{added} resources[/dim]")

    path = save_index(records)
    console.print(f"\n[green]Indexed {len(records)} resources[/green] → {path}")


@main.command("search")
@click.argument("query", nargs=-1, required=True)
@click.option("-c", "--course", default=None,
              help="Limit results to a course code, e.g. -c 'DSC 152'.")
@click.option("-n", "--limit", default=10, show_default=True,
              help="Number of results to show.")
@click.option("--open", "open_first", is_flag=True,
              help="Open the top result in your web browser.")
def search_cmd(query: tuple[str, ...], course: str | None,
               limit: int, open_first: bool) -> None:
    """Search the local index. Run `dscfind index` first."""
    records, meta = load_index()
    if not records:
        err.print("[yellow]The index is empty. Build it with "
                  "`dscfind index` (optionally `-c \"DSC 152\"`).[/yellow]")
        raise SystemExit(1)

    q = " ".join(query)
    hits = BM25(records).search(q, limit=limit, course=course)
    if not hits:
        console.print(f"No results for [bold]{q}[/bold].")
        return

    table = Table(title=f'Results for "{q}"', show_lines=False)
    table.add_column("#", style="dim", width=3)
    table.add_column("Course", style="cyan", no_wrap=True)
    table.add_column("Kind", style="magenta", no_wrap=True)
    table.add_column("Title")
    table.add_column("URL", style="blue")
    for i, hit in enumerate(hits, 1):
        r = hit.record
        table.add_row(str(i), r.course_code, r.kind, r.title, r.url)
    console.print(table)
    if meta.get("built_at"):
        console.print(f"[dim]index built {meta['built_at']} · "
                      f"{meta.get('count', len(records))} resources[/dim]")

    if open_first:
        webbrowser.open(hits[0].record.url)


@main.command("where")
def where_cmd() -> None:
    """Print the path to the local index file."""
    p = index_path()
    console.print(str(p))
    if not p.exists():
        console.print("[yellow](does not exist yet — run `dscfind index`)[/yellow]")


if __name__ == "__main__":
    main()

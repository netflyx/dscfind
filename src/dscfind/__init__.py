"""dscfind: a command-line search engine for UCSD data science course materials.

It crawls https://dsc-courses.github.io, follows the links to individual course
websites, harvests the resources they link to (lectures, assignments, readings,
notebooks, ...), caches everything locally, and lets you search it from the
terminal with ranked results.
"""

__version__ = "0.1.0"

INDEX_URL = "https://dsc-courses.github.io"

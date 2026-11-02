# SPDX-License-Identifier: AGPL-3.0-or-later
"""`Open Library`_ is an open, editable library catalog, building towards a web
page for every book ever published.

.. _Open Library: https://openlibrary.org

Configuration
=============

The service sometimes takes a very long time to respond, the ``timeout`` may
need to be adjusted.

.. code:: yaml

  - name: openlibrary
    engine: openlibrary
    shortcut: ol
    timeout: 10


Implementations
===============

"""

# Local compatibility patch for SearXNG 2026.10.11-ad46ebd7d.
# Upstream: https://github.com/searxng/searxng/blob/ad46ebd7d/searx/engines/openlibrary.py
# Retains upstream AGPL-3.0-or-later. See searxng/README.md.
from datetime import datetime
import re
import typing as t

from urllib.parse import urlencode
from dateutil import parser

from searx.result_types import EngineResults

if t.TYPE_CHECKING:
    from searx.extended_types import SXNG_Response
    from searx.search.processors import OnlineParams

about = {
    "website": "https://openlibrary.org",
    "wikidata_id": "Q1201876",
    "require_api_key": False,
    "use_official_api": False,
    "official_api_documentation": "https://openlibrary.org/developers/api",
}

paging = True
categories = ["general", "books"]

base_url = "https://openlibrary.org"
search_api = "https://openlibrary.org/search.json"
"""The engine uses the API at the endpoint search.json_.

.. _search.json: https://openlibrary.org/dev/docs/api/search
"""
results_per_page = 5


def request(query: str, params: "OnlineParams") -> None:
    args = {
        "q": query,
        "page": params["pageno"],
        "limit": results_per_page,
        # A discovery hit needs identity and its opening sentence. Asking for
        # every edition's ISBN/date/subjects inflates both upstream work and JSON.
        # Detailed editions remain Django's bounded official-API lookup.
        "fields": "key,title,author_name,first_sentence,first_publish_year",
    }
    params["url"] = f"{search_api}?{urlencode(args)}"
    logger.debug("REST API: %s", params["url"])


def response(resp: "SXNG_Response") -> EngineResults:
    res = EngineResults()
    json_data = resp.json()
    if not isinstance(json_data, dict) or not isinstance(json_data.get("docs"), list):
        raise ValueError("invalid_openlibrary_response")
    for item in json_data["docs"]:
        if (not isinstance(item, dict) or not isinstance(item.get("title"), str)
                or not isinstance(item.get("key"), str)
                or not re.fullmatch(r"/?(?:works/OL\d+W|books/OL\d+M)", item["key"])):
            continue
        cover = ""
        if isinstance(item.get("lending_identifier_s"), str):
            cover = f"https://archive.org/services/img/{item['lending_identifier_s']}"

        published = _texts(item.get("publish_date"))
        if published:
            published_dates = [date for date in map(_parse_date, published) if date]
            # A nonempty list of unparseable dates is not a datetime.
            # Preserve the first_publish_year fallback instead of passing a list
            # to ResultContainer.normalize_result_fields (strftime).
            published = min(published_dates, key=lambda date: (date.year, date.month, date.day)) if published_dates else None

        if not published:
            published = _parse_date(str(item.get("first_publish_year")))

        content = " / ".join(_texts(item.get("first_sentence")))
        res.add(
            res.types.Paper(
                url=f"{base_url}/{item['key'].lstrip('/')}",
                title=item["title"],
                content=content,
                isbn=_texts(item.get("isbn"))[:5],
                authors=_texts(item.get("author_name")),
                thumbnail=cover,
                publishedDate=published,
                tags=_texts(item.get("subject"))[:10] + _texts(item.get("place"))[:10],
            )
        )
    return res


def _texts(value):
    if isinstance(value, str):
        return [value]
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _parse_date(date: str) -> datetime | None:
    if not date:
        return None
    try:
        return parser.parse(date)
    except (ValueError, TypeError, OverflowError):
        return None

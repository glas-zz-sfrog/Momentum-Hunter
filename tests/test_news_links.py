from __future__ import annotations

import unittest

from momentum_hunter.app import format_news_html
from momentum_hunter.models import Candidate, NewsItem


class NewsLinksTests(unittest.TestCase):
    def test_news_html_renders_clickable_external_link(self) -> None:
        candidate = Candidate(
            ticker="TEST",
            news=[
                NewsItem(
                    headline="Test beats earnings",
                    source="Finviz",
                    url="https://example.com/test",
                    summary="Potential earnings catalyst.",
                )
            ],
        )

        html = format_news_html(candidate)

        self.assertIn("<a href='https://example.com/test'>Test beats earnings</a>", html)
        self.assertIn("(Finviz)", html)
        self.assertIn("Potential earnings catalyst.", html)

    def test_news_html_escapes_headline_source_summary_and_url(self) -> None:
        candidate = Candidate(
            ticker="TEST",
            news=[
                NewsItem(
                    headline="<b>Injected</b>",
                    source="<Source>",
                    url="https://example.com/?q='bad'&x=<tag>",
                    summary="<script>alert(1)</script>",
                )
            ],
        )

        html = format_news_html(candidate)

        self.assertIn("&lt;b&gt;Injected&lt;/b&gt;", html)
        self.assertIn("&lt;Source&gt;", html)
        self.assertIn("https://example.com/?q=&#x27;bad&#x27;&amp;x=&lt;tag&gt;", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<b>Injected</b>", html)
        self.assertNotIn("<script>alert(1)</script>", html)


if __name__ == "__main__":
    unittest.main()

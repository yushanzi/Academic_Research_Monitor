import unittest
from unittest.mock import Mock, patch

from access.open_access import OpenAccessDocumentAccessProvider
from models import ensure_paper


class AccessInfoTests(unittest.TestCase):
    def test_resolve_discovers_pdf_link_from_meta_tag(self):
        html = """
        <html>
          <head>
            <meta name="citation_pdf_url" content="/content/test.full.pdf">
            <meta property="og:url" content="https://example.com/paper">
          </head>
          <body><article>%s</article></body>
        </html>
        """ % "".join(f"<p>{'word ' * 120}</p>" for _ in range(30))
        response = Mock()
        response.headers = {"content-type": "text/html; charset=utf-8"}
        response.text = html
        response.url = "https://example.com/paper"
        response.raise_for_status.return_value = None

        with patch("access.open_access.requests.get", return_value=response):
            access_info = OpenAccessDocumentAccessProvider().resolve(
                ensure_paper({
                    "url": "https://example.com/paper",
                    "landing_page_url": "https://example.com/paper",
                    "doi": "10.1000/test",
                })
            )

        self.assertEqual(access_info.download_url, "https://example.com/content/test.full.pdf")
        self.assertEqual(access_info.entry_url, "https://example.com/paper")
        self.assertTrue(access_info.open_access)

    def test_resolve_promotes_full_text_when_html_body_is_long_enough(self):
        html = "<html><body><article>" + "".join(f"<p>{'word ' * 120}</p>" for _ in range(30)) + "</article></body></html>"
        response = Mock()
        response.headers = {"content-type": "text/html; charset=utf-8"}
        response.text = html
        response.url = "https://example.com/paper"
        response.raise_for_status.return_value = None

        with patch("access.open_access.requests.get", return_value=response):
            access_info = OpenAccessDocumentAccessProvider().resolve(
                ensure_paper({
                    "url": "https://example.com/paper",
                    "landing_page_url": "https://example.com/paper",
                    "doi": "10.1000/test",
                })
            )

        self.assertTrue(access_info.full_text_available)
        self.assertEqual(access_info.evidence_level, "full_text")
        self.assertEqual(access_info.effective_access_mode, "open_access")
        self.assertTrue(access_info.entry_url)

    def test_resolve_falls_back_to_abstract_only_without_html_text(self):
        response = Mock()
        response.headers = {"content-type": "application/pdf"}
        response.text = ""
        response.url = "https://example.com/paper"
        response.raise_for_status.return_value = None

        with patch("access.open_access.requests.get", return_value=response):
            access_info = OpenAccessDocumentAccessProvider().resolve(
                ensure_paper({
                    "url": "https://example.com/paper",
                    "doi": "10.1000/test",
                })
            )

        self.assertFalse(access_info.full_text_available)
        self.assertEqual(access_info.evidence_level, "abstract_only")
        self.assertEqual(access_info.effective_access_mode, "abstract_only")

    def test_resolve_uses_arxiv_pdf_fallback(self):
        html = "<html><head></head><body></body></html>"
        response = Mock()
        response.headers = {"content-type": "text/html; charset=utf-8"}
        response.text = html
        response.url = "https://arxiv.org/abs/1234.5678"
        response.raise_for_status.return_value = None

        with patch("access.open_access.requests.get", return_value=response):
            access_info = OpenAccessDocumentAccessProvider().resolve(
                ensure_paper({
                    "url": "https://arxiv.org/abs/1234.5678",
                    "landing_page_url": "https://arxiv.org/abs/1234.5678",
                    "source": "arXiv",
                })
            )

        self.assertEqual(access_info.download_url, "https://arxiv.org/pdf/1234.5678.pdf")
        self.assertTrue(access_info.open_access)

    def test_resolve_uses_biorxiv_pdf_fallback_from_doi(self):
        html = "<html><head><meta name='citation_abstract' content='short abstract text'></head><body></body></html>"
        response = Mock()
        response.headers = {"content-type": "text/html; charset=utf-8"}
        response.text = html
        response.url = "https://www.biorxiv.org/content/10.1101/2026.01.01.123456v1"
        response.raise_for_status.return_value = None

        with patch("access.open_access.requests.get", return_value=response):
            access_info = OpenAccessDocumentAccessProvider().resolve(
                ensure_paper({
                    "url": "https://doi.org/10.1101/2026.01.01.123456",
                    "doi": "10.1101/2026.01.01.123456",
                    "source": "bioRxiv",
                })
            )

        self.assertEqual(
            access_info.download_url,
            "https://www.biorxiv.org/content/10.1101/2026.01.01.123456v1.full.pdf",
        )
        self.assertTrue(access_info.open_access)

    def test_resolve_uses_science_pdf_fallback_from_doi(self):
        html = "<html><head></head><body></body></html>"
        response = Mock()
        response.headers = {"content-type": "text/html; charset=utf-8"}
        response.text = html
        response.url = "https://www.science.org/doi/10.1126/science.abc123"
        response.raise_for_status.return_value = None

        with patch("access.open_access.requests.get", return_value=response):
            access_info = OpenAccessDocumentAccessProvider().resolve(
                ensure_paper({
                    "url": "https://www.science.org/doi/10.1126/science.abc123",
                    "doi": "10.1126/science.abc123",
                    "source": "Science",
                })
            )

        self.assertEqual(access_info.download_url, "https://www.science.org/doi/pdf/10.1126/science.abc123")
        self.assertTrue(access_info.open_access)


    def test_resolve_downloads_pdf_when_html_has_no_full_text(self):
        html = """
        <html>
          <head><meta name="citation_pdf_url" content="/content/test.full.pdf"></head>
          <body><section id="abstract">short abstract</section></body>
        </html>
        """
        html_response = Mock()
        html_response.headers = {"content-type": "text/html; charset=utf-8"}
        html_response.text = html
        html_response.url = "https://example.com/paper"
        html_response.raise_for_status.return_value = None

        pdf_response = Mock()
        pdf_response.headers = {"content-type": "application/pdf"}
        pdf_response.content = b"%PDF-1.4 fake"
        pdf_response.text = ""
        pdf_response.url = "https://example.com/content/test.full.pdf"
        pdf_response.raise_for_status.return_value = None

        with patch("access.open_access.requests.get", side_effect=[html_response, pdf_response]) as mock_get:
            with patch(
                "access.open_access.extract_text_from_pdf_bytes",
                return_value=("word " * 500),
            ) as mock_extract:
                access_info = OpenAccessDocumentAccessProvider().resolve(
                    ensure_paper({
                        "url": "https://example.com/paper",
                        "landing_page_url": "https://example.com/paper",
                        "doi": "10.1000/test",
                    })
                )

        self.assertTrue(access_info.full_text_available)
        self.assertEqual(access_info.evidence_level, "full_text")
        self.assertEqual(access_info.download_url, "https://example.com/content/test.full.pdf")
        mock_extract.assert_called_once_with(b"%PDF-1.4 fake")
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_get.call_args_list[0].args[0], "https://example.com/paper")
        self.assertEqual(mock_get.call_args_list[1].args[0], "https://example.com/content/test.full.pdf")

    def test_resolve_keeps_abstract_only_when_pdf_text_is_too_short(self):
        html = """
        <html>
          <head><meta name="citation_pdf_url" content="/content/test.full.pdf"></head>
          <body><section id="abstract">short abstract</section></body>
        </html>
        """
        html_response = Mock()
        html_response.headers = {"content-type": "text/html; charset=utf-8"}
        html_response.text = html
        html_response.url = "https://example.com/paper"
        html_response.raise_for_status.return_value = None

        pdf_response = Mock()
        pdf_response.headers = {"content-type": "application/pdf"}
        pdf_response.content = b"%PDF-1.4 fake"
        pdf_response.text = ""
        pdf_response.url = "https://example.com/content/test.full.pdf"
        pdf_response.raise_for_status.return_value = None

        with patch("access.open_access.requests.get", side_effect=[html_response, pdf_response]):
            with patch("access.open_access.extract_text_from_pdf_bytes", return_value="too short"):
                access_info = OpenAccessDocumentAccessProvider().resolve(
                    ensure_paper({
                        "url": "https://example.com/paper",
                        "landing_page_url": "https://example.com/paper",
                        "doi": "10.1000/test",
                    })
                )

        self.assertFalse(access_info.full_text_available)
        self.assertEqual(access_info.evidence_level, "abstract_only")
        self.assertEqual(access_info.effective_access_mode, "open_access")
        self.assertTrue(access_info.open_access)

    def test_resolve_skips_pdf_download_when_html_full_text_is_already_sufficient(self):
        html = """
        <html>
          <head><meta name="citation_pdf_url" content="/content/test.full.pdf"></head>
          <body><article>%s</article></body>
        </html>
        """ % "".join(f"<p>{'word ' * 120}</p>" for _ in range(30))
        html_response = Mock()
        html_response.headers = {"content-type": "text/html; charset=utf-8"}
        html_response.text = html
        html_response.url = "https://example.com/paper"
        html_response.raise_for_status.return_value = None

        with patch("access.open_access.requests.get", return_value=html_response) as mock_get:
            with patch("access.open_access.extract_text_from_pdf_bytes") as mock_extract:
                access_info = OpenAccessDocumentAccessProvider().resolve(
                    ensure_paper({
                        "url": "https://example.com/paper",
                        "landing_page_url": "https://example.com/paper",
                        "doi": "10.1000/test",
                    })
                )

        self.assertTrue(access_info.full_text_available)
        self.assertEqual(access_info.evidence_level, "full_text")
        self.assertEqual(mock_get.call_count, 1)
        mock_extract.assert_not_called()

    def test_resolve_keeps_abstract_only_when_pdf_download_fails(self):
        html = """
        <html>
          <head><meta name="citation_pdf_url" content="/content/test.full.pdf"></head>
          <body><section id="abstract">short abstract</section></body>
        </html>
        """
        html_response = Mock()
        html_response.headers = {"content-type": "text/html; charset=utf-8"}
        html_response.text = html
        html_response.url = "https://example.com/paper"
        html_response.raise_for_status.return_value = None

        with patch(
            "access.open_access.requests.get",
            side_effect=[html_response, Exception("download failed")],
        ):
            access_info = OpenAccessDocumentAccessProvider().resolve(
                ensure_paper({
                    "url": "https://example.com/paper",
                    "landing_page_url": "https://example.com/paper",
                    "doi": "10.1000/test",
                })
            )

        self.assertFalse(access_info.full_text_available)
        self.assertEqual(access_info.evidence_level, "abstract_only")
        self.assertEqual(access_info.effective_access_mode, "open_access")
        self.assertTrue(access_info.open_access)

    def test_resolve_does_not_treat_long_arxiv_abstract_as_full_text(self):
        html = """
        <html>
          <body>
            <blockquote class="abstract">%s</blockquote>
          </body>
        </html>
        """ % ("word " * 800)
        response = Mock()
        response.headers = {"content-type": "text/html; charset=utf-8"}
        response.text = html
        response.url = "https://arxiv.org/abs/1234.5678"
        response.raise_for_status.return_value = None

        with patch("access.open_access.requests.get", return_value=response):
            access_info = OpenAccessDocumentAccessProvider().resolve(
                ensure_paper({
                    "url": "https://arxiv.org/abs/1234.5678",
                    "landing_page_url": "https://arxiv.org/abs/1234.5678",
                    "source": "arXiv",
                })
            )

        self.assertFalse(access_info.full_text_available)
        self.assertEqual(access_info.evidence_level, "abstract_only")
        self.assertEqual(access_info.download_url, "https://arxiv.org/pdf/1234.5678.pdf")

    def test_resolve_does_not_treat_biorxiv_abstract_section_as_full_text(self):
        html = """
        <html>
          <body>
            <div class="section abstract">%s</div>
          </body>
        </html>
        """ % ("<p>%s</p>" % ("word " * 800))
        response = Mock()
        response.headers = {"content-type": "text/html; charset=utf-8"}
        response.text = html
        response.url = "https://www.biorxiv.org/content/10.1101/2026.01.01.123456v1"
        response.raise_for_status.return_value = None

        with patch("access.open_access.requests.get", return_value=response):
            access_info = OpenAccessDocumentAccessProvider().resolve(
                ensure_paper({
                    "url": "https://www.biorxiv.org/content/10.1101/2026.01.01.123456v1",
                    "landing_page_url": "https://www.biorxiv.org/content/10.1101/2026.01.01.123456v1",
                    "source": "bioRxiv",
                    "doi": "10.1101/2026.01.01.123456",
                })
            )

        self.assertFalse(access_info.full_text_available)
        self.assertEqual(access_info.evidence_level, "abstract_only")

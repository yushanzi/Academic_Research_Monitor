import tempfile
import unittest
from unittest.mock import Mock, patch

from access.open_access import OpenAccessDocumentAccessProvider, _is_pdf_response
from access.oa_resolver import OALocationCandidate
from models import AccessInfo, ensure_paper


def _fetch_result(response=None, *, ok=True, error=""):
    result = Mock()
    result.ok = ok
    result.error = error
    result.as_response.return_value = response if ok else None
    return result


class AccessInfoTests(unittest.TestCase):
    def test_is_pdf_response_rejects_html_challenge_pages_with_pdf_urls(self):
        response = Mock()
        response.headers = {"content-type": "text/html; charset=utf-8"}
        response.content = b"<!doctype html><html><body>challenge</body></html>"
        response.url = "https://example.com/file.pdf"

        self.assertFalse(_is_pdf_response(response, "https://example.com/file.pdf"))

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

        with patch("access.open_access.fetch_url_with_retries", return_value=_fetch_result(response)):
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

        with patch("access.open_access.fetch_url_with_retries", return_value=_fetch_result(response)):
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

        with patch("access.open_access.fetch_url_with_retries", return_value=_fetch_result(response)):
            access_info = OpenAccessDocumentAccessProvider().resolve(
                ensure_paper({
                    "url": "https://example.com/paper",
                    "doi": "10.1000/test",
                })
            )

        self.assertFalse(access_info.full_text_available)
        self.assertEqual(access_info.evidence_level, "abstract_only")
        self.assertEqual(access_info.effective_access_mode, "open_access")
        self.assertTrue(access_info.open_access)

    def test_resolve_uses_arxiv_pdf_fallback(self):
        html = "<html><head></head><body></body></html>"
        response = Mock()
        response.headers = {"content-type": "text/html; charset=utf-8"}
        response.text = html
        response.url = "https://arxiv.org/abs/1234.5678"
        response.raise_for_status.return_value = None

        with patch("access.open_access.fetch_url_with_retries", return_value=_fetch_result(response)):
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

        with patch("access.open_access.fetch_url_with_retries", return_value=_fetch_result(response)):
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
        self.assertEqual(access_info.access_route, "publisher")

    def test_resolve_prefers_biorxiv_pdf_before_doi_landing_page(self):
        pdf_response = Mock()
        pdf_response.headers = {"content-type": "application/pdf"}
        pdf_response.content = b"%PDF-1.4 fake"
        pdf_response.text = ""
        pdf_response.url = "https://www.biorxiv.org/content/10.1101/2026.01.01.123456v1.full.pdf"
        pdf_response.raise_for_status.return_value = None

        with patch(
            "access.open_access.fetch_url_with_retries",
            return_value=_fetch_result(pdf_response),
        ) as mock_fetch:
            with patch(
                "access.open_access.extract_text_from_pdf_bytes",
                return_value=("word " * 500),
            ):
                access_info = OpenAccessDocumentAccessProvider().resolve(
                    ensure_paper({
                        "url": "https://doi.org/10.1101/2026.01.01.123456",
                        "doi": "10.1101/2026.01.01.123456",
                        "source": "bioRxiv",
                    })
                )

        self.assertEqual(mock_fetch.call_count, 1)
        self.assertEqual(
            mock_fetch.call_args_list[0].args[0],
            "https://www.biorxiv.org/content/10.1101/2026.01.01.123456v1.full.pdf",
        )
        self.assertTrue(access_info.full_text_available)
        self.assertTrue(access_info.open_access)

    def test_resolve_science_uses_external_oa_candidate(self):
        pdf_response = Mock()
        pdf_response.headers = {"content-type": "application/pdf"}
        pdf_response.content = b"%PDF-1.4 fake"
        pdf_response.text = ""
        pdf_response.url = "https://repository.example.org/paper.pdf"
        pdf_response.raise_for_status.return_value = None

        candidate = OALocationCandidate(
            landing_page_url="https://repository.example.org/record",
            pdf_url="https://repository.example.org/paper.pdf",
            source_display_name="Repository",
            source_type="repository",
            version="publishedVersion",
            is_best_oa=True,
        )

        with patch("access.open_access.resolve_open_access_locations", return_value=[candidate]):
            with patch("access.open_access.fetch_url_with_retries", return_value=_fetch_result(pdf_response)) as mock_fetch:
                with patch("access.open_access.extract_text_from_pdf_bytes", return_value=("word " * 500)):
                    access_info = OpenAccessDocumentAccessProvider().resolve(
                        ensure_paper({
                            "url": "https://www.science.org/doi/abs/10.1126/science.abc123",
                            "doi": "10.1126/science.abc123",
                            "source": "Science",
                        })
                    )

        self.assertEqual(mock_fetch.call_count, 1)
        self.assertEqual(mock_fetch.call_args_list[0].args[0], "https://repository.example.org/paper.pdf")
        self.assertTrue(access_info.open_access)
        self.assertTrue(access_info.full_text_available)
        self.assertEqual(access_info.download_url, "https://repository.example.org/paper.pdf")
        self.assertEqual(access_info.access_route, "repository")
        self.assertIn("外部开放获取副本", access_info.access_note)

    def test_resolve_science_can_fall_back_from_candidate_pdf_to_candidate_landing_page(self):
        pdf_challenge = Mock()
        pdf_challenge.headers = {"content-type": "text/html; charset=utf-8"}
        pdf_challenge.content = b"<!doctype html><html><body>challenge</body></html>"
        pdf_challenge.text = "<!doctype html><html><body>challenge</body></html>"
        pdf_challenge.url = "https://repository.example.org/paper.pdf"
        pdf_challenge.raise_for_status.return_value = None

        landing_html = "<html><body><article>" + "".join(f"<p>{'word ' * 120}</p>" for _ in range(30)) + "</article></body></html>"
        landing_response = Mock()
        landing_response.headers = {"content-type": "text/html; charset=utf-8"}
        landing_response.content = landing_html.encode("utf-8")
        landing_response.text = landing_html
        landing_response.url = "https://repository.example.org/record"
        landing_response.raise_for_status.return_value = None

        candidate = OALocationCandidate(
            landing_page_url="https://repository.example.org/record",
            pdf_url="https://repository.example.org/paper.pdf",
            source_display_name="Repository",
            source_type="repository",
            version="publishedVersion",
            is_best_oa=True,
        )

        with patch("access.open_access.resolve_open_access_locations", return_value=[candidate]):
            with patch(
                "access.open_access.fetch_url_with_retries",
                side_effect=[_fetch_result(pdf_challenge), _fetch_result(landing_response)],
            ):
                access_info = OpenAccessDocumentAccessProvider().resolve(
                    ensure_paper({
                        "url": "https://www.science.org/doi/abs/10.1126/science.abc123",
                        "doi": "10.1126/science.abc123",
                        "source": "Science",
                    })
                )

        self.assertTrue(access_info.open_access)
        self.assertTrue(access_info.full_text_available)
        self.assertEqual(access_info.entry_url, "https://repository.example.org/record")
        self.assertEqual(access_info.download_url, "https://repository.example.org/paper.pdf")
        self.assertEqual(access_info.access_route, "repository")

    def test_resolve_science_stays_abstract_only_without_external_oa_candidate(self):
        with patch("access.open_access.resolve_open_access_locations", return_value=[]):
            with patch("access.open_access.fetch_url_with_retries") as mock_fetch:
                access_info = OpenAccessDocumentAccessProvider().resolve(
                    ensure_paper({
                        "url": "https://www.science.org/doi/abs/10.1126/science.abc123",
                        "doi": "10.1126/science.abc123",
                        "source": "Science",
                    })
                )

        mock_fetch.assert_not_called()
        self.assertFalse(access_info.open_access)
        self.assertFalse(access_info.full_text_available)
        self.assertEqual(access_info.evidence_level, "abstract_only")
        self.assertEqual(access_info.download_url, "")
        self.assertEqual(access_info.access_route, "none")

    def test_resolve_reports_external_candidate_when_repository_access_fails(self):
        candidate = OALocationCandidate(
            landing_page_url="https://doi.org/10.5281/zenodo.19312376",
            pdf_url="",
            source_display_name="Zenodo",
            source_type="repository",
            version="",
            is_best_oa=True,
        )

        with patch("access.open_access.resolve_open_access_locations", return_value=[candidate]):
            with patch("access.open_access.fetch_url_with_retries", return_value=_fetch_result(None, ok=False, error="blocked")):
                access_info = OpenAccessDocumentAccessProvider().resolve(
                    ensure_paper({
                        "url": "https://doi.org/10.1021/acs.jctc.6c01183",
                        "doi": "10.1021/acs.jctc.6c01183",
                        "source": "ACS - Journal of Chemical Theory and Computation",
                    })
                )

        self.assertFalse(access_info.open_access)
        self.assertFalse(access_info.full_text_available)
        self.assertEqual(access_info.access_route, "none")
        self.assertIn("Zenodo", access_info.access_note)
        self.assertIn("当前环境未能稳定访问", access_info.access_note)
        self.assertIn("metadata/abstract-first", access_info.access_note)

    def test_resolve_acs_prefers_publisher_access_when_browser_session_is_configured(self):
        candidate = OALocationCandidate(
            landing_page_url="https://doi.org/10.5281/zenodo.19312376",
            pdf_url="",
            source_display_name="Zenodo",
            source_type="repository",
            version="",
            is_best_oa=True,
        )
        landing_html = "<html><body><article>" + "".join(f"<p>{'word ' * 120}</p>" for _ in range(30)) + "</article></body></html>"
        landing_response = Mock()
        landing_response.headers = {"content-type": "text/html; charset=utf-8"}
        landing_response.content = landing_html.encode("utf-8")
        landing_response.text = landing_html
        landing_response.url = "https://pubs.acs.org/doi/10.1021/acs.jctc.6c01183"
        landing_response.raise_for_status.return_value = None

        with tempfile.NamedTemporaryFile() as storage_state:
            provider = OpenAccessDocumentAccessProvider(
                source_settings={
                    "acs": {
                        "browser_storage_state": storage_state.name,
                    }
                }
            )
            with patch("access.open_access.resolve_open_access_locations", return_value=[candidate]):
                with patch("access.open_access.fetch_url_with_retries", return_value=_fetch_result(landing_response)):
                    access_info = provider.resolve(
                        ensure_paper({
                            "url": "https://doi.org/10.1021/acs.jctc.6c01183",
                            "doi": "10.1021/acs.jctc.6c01183",
                            "source": "ACS - Journal of Chemical Theory and Computation",
                        })
                    )

        self.assertTrue(access_info.open_access)
        self.assertTrue(access_info.full_text_available)
        self.assertEqual(access_info.access_route, "publisher")
        self.assertIn("浏览器会话", access_info.access_note)

    def test_resolve_acs_tries_publisher_session_even_without_external_candidates(self):
        landing_html = "<html><body><article>" + "".join(f"<p>{'word ' * 120}</p>" for _ in range(30)) + "</article></body></html>"
        landing_response = Mock()
        landing_response.headers = {"content-type": "text/html; charset=utf-8"}
        landing_response.content = landing_html.encode("utf-8")
        landing_response.text = landing_html
        landing_response.url = "https://pubs.acs.org/doi/10.1021/acs.jctc.6c01183"
        landing_response.raise_for_status.return_value = None

        with tempfile.NamedTemporaryFile() as storage_state:
            provider = OpenAccessDocumentAccessProvider(
                source_settings={
                    "acs": {
                        "browser_storage_state": storage_state.name,
                    }
                }
            )
            with patch("access.open_access.resolve_open_access_locations", return_value=[]):
                with patch("access.open_access.fetch_url_with_retries", return_value=_fetch_result(landing_response)):
                    access_info = provider.resolve(
                        ensure_paper({
                            "url": "https://doi.org/10.1021/acs.jctc.6c01183",
                            "doi": "10.1021/acs.jctc.6c01183",
                            "source": "ACS - Journal of Chemical Theory and Computation",
                        })
                    )

        self.assertTrue(access_info.open_access)
        self.assertTrue(access_info.full_text_available)
        self.assertEqual(access_info.access_route, "publisher")
        self.assertIn("浏览器会话", access_info.access_note)

    def test_resolve_acs_prefers_repository_full_text_over_publisher_abstract_only(self):
        candidate = OALocationCandidate(
            landing_page_url="https://repository.example.org/record",
            pdf_url="https://repository.example.org/paper.pdf",
            source_display_name="Repository",
            source_type="repository",
            version="publishedVersion",
            is_best_oa=True,
        )
        publisher_access = AccessInfo(
            entry_url="https://pubs.acs.org/doi/10.1021/acs.jctc.6c01183",
            download_url="https://pubs.acs.org/doi/pdf/10.1021/acs.jctc.6c01183",
            landing_page_url="https://pubs.acs.org/doi/10.1021/acs.jctc.6c01183",
            full_text_available=False,
            full_text="",
            open_access=True,
            effective_access_mode="open_access",
            evidence_level="abstract_only",
            access_route="publisher",
            access_note="已通过浏览器会话访问到出版方落地页。",
        )
        repository_access = AccessInfo(
            entry_url="https://repository.example.org/record",
            download_url="https://repository.example.org/paper.pdf",
            landing_page_url="https://repository.example.org/record",
            full_text_available=True,
            full_text="word " * 500,
            open_access=True,
            effective_access_mode="open_access",
            evidence_level="full_text",
            access_route="repository",
            access_note="已通过外部开放获取副本获取全文。",
        )

        with tempfile.NamedTemporaryFile() as storage_state:
            provider = OpenAccessDocumentAccessProvider(
                source_settings={
                    "acs": {
                        "browser_storage_state": storage_state.name,
                    }
                }
            )
            with patch("access.open_access.resolve_open_access_locations", return_value=[candidate]):
                with patch("access.open_access._resolve_from_publisher_urls", return_value=publisher_access):
                    with patch("access.open_access._resolve_from_location_candidates", return_value=repository_access):
                        access_info = provider.resolve(
                            ensure_paper({
                                "url": "https://doi.org/10.1021/acs.jctc.6c01183",
                                "doi": "10.1021/acs.jctc.6c01183",
                                "source": "ACS - Journal of Chemical Theory and Computation",
                            })
                        )

        self.assertEqual(access_info.access_route, "repository")
        self.assertTrue(access_info.full_text_available)


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

        with patch(
            "access.open_access.fetch_url_with_retries",
            side_effect=[_fetch_result(html_response), _fetch_result(pdf_response)],
        ) as mock_fetch:
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
        self.assertEqual(mock_fetch.call_count, 2)
        self.assertEqual(mock_fetch.call_args_list[0].args[0], "https://example.com/paper")
        self.assertEqual(mock_fetch.call_args_list[1].args[0], "https://example.com/content/test.full.pdf")

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

        with patch(
            "access.open_access.fetch_url_with_retries",
            side_effect=[_fetch_result(html_response), _fetch_result(pdf_response)],
        ):
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

        with patch("access.open_access.fetch_url_with_retries", return_value=_fetch_result(html_response)) as mock_fetch:
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
        self.assertEqual(mock_fetch.call_count, 1)
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
            "access.open_access.fetch_url_with_retries",
            side_effect=[_fetch_result(html_response), _fetch_result(None, ok=False, error="download failed")],
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

        with patch("access.open_access.fetch_url_with_retries", return_value=_fetch_result(response)):
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

        with patch("access.open_access.fetch_url_with_retries", return_value=_fetch_result(response)):
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

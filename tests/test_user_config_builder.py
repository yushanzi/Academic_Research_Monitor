import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock

from user_config_builder import build_config_from_document, interpret_user_document, load_document_text


class UserConfigBuilderTests(unittest.TestCase):
    def _template(self) -> dict:
        with open("config.template.json", "r", encoding="utf-8") as f:
            return json.load(f)

    def test_build_config_from_document_uses_llm_output_and_keeps_defaults(self):
        provider = Mock()
        provider.complete.side_effect = [
            json.dumps(
                {
                    "interest_description": "Focus on protein structure prediction and generative models for drug discovery.",
                    "topics": ["protein structure prediction", "generative biology", "drug discovery"],
                    "must_have": ["experimental validation"],
                    "exclude": ["review article"],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "core_topics": ["protein structure prediction", "generative biology"],
                    "synonyms": ["de novo protein design"],
                    "summary": "Track protein structure prediction and generative biology.",
                },
                ensure_ascii=False,
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "instances" / "protein-monitor" / "config.json"
            config = build_config_from_document(
                template=self._template(),
                document_text="我想关注蛋白质结构预测和生成模型。",
                config_path=str(output_path),
                user_name="protein-monitor",
                email_recipient="user@example.com",
                provider=provider,
            )
            profile_path = Path(tmp) / "instances" / "protein-monitor" / "interest_profile.json"
            with open(profile_path, "r", encoding="utf-8") as f:
                payload = json.load(f)

        self.assertEqual(config["user"]["name"], "protein-monitor")
        self.assertEqual(config["output_dir"], "output/protein-monitor")
        self.assertEqual(config["email"]["recipient"], "user@example.com")
        self.assertNotIn("topics", config)
        self.assertNotIn("interest_description", config)
        self.assertNotIn("must_have", config)
        self.assertNotIn("exclude", config)
        self.assertNotIn("interest_profile_confirmed", config)
        self.assertNotIn("relevance_scoring", config)
        self.assertTrue(payload["confirmed"])
        self.assertEqual(payload["profile"]["core_topics"], ["protein structure prediction", "generative biology"])
        self.assertEqual(payload["profile"]["must_have"], ["experimental validation"])
        self.assertEqual(payload["profile"]["exclude"], ["review article"])
        self.assertEqual(payload["profile"]["summary"], "Track protein structure prediction and generative biology.")
        self.assertEqual(config["schedule"]["cron"], "0 8 * * *")
        self.assertIn("sources", config)

    def test_interpret_user_document_falls_back_to_heuristic_sections(self):
        text = """
        研究方向:
        - AI for biology
        - protein design

        must have:
        - wet lab validation
        - in vivo evidence

        排除:
        - review article
        - dataset paper
        """

        parsed = interpret_user_document(text, provider=None)

        self.assertEqual(parsed["topics"], ["AI for biology", "protein design"])
        self.assertEqual(parsed["must_have"], ["wet lab validation", "in vivo evidence"])
        self.assertEqual(parsed["exclude"], ["review article", "dataset paper"])
        self.assertEqual(
            parsed["interest_description"],
            "Focus topics: AI for biology, protein design; Prioritize: wet lab validation, in vivo evidence; Exclude: review article, dataset paper",
        )

    def test_interpret_user_document_can_heuristically_infer_constraints_from_freeform(self):
        text = """
        我想关注 AI for biology，尤其是有实验验证和 in vivo 证据的工作。
        不想看 review，也不想看 dataset paper。
        """

        parsed = interpret_user_document(text, provider=None)

        self.assertEqual(parsed["must_have"], ["experimental validation", "in vivo evidence"])
        self.assertEqual(parsed["exclude"], ["review article", "dataset paper"])

    def test_build_config_from_document_writes_confirmed_profile_file(self):
        provider = Mock()
        provider.complete.side_effect = [
            json.dumps(
                {
                    "interest_description": "Focus on protein design.",
                    "topics": ["protein design"],
                    "must_have": [],
                    "exclude": [],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "core_topics": ["protein design"],
                    "synonyms": [],
                    "summary": "Track protein design.",
                },
                ensure_ascii=False,
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "instances" / "protein-monitor" / "config.json"
            config = build_config_from_document(
                template=self._template(),
                document_text="关注蛋白质设计。",
                config_path=str(output_path),
                user_name="protein-monitor",
                email_recipient="user@example.com",
                provider=provider,
            )
            profile_path = Path(tmp) / "instances" / "protein-monitor" / "interest_profile.json"
            with open(profile_path, "r", encoding="utf-8") as f:
                payload = json.load(f)

        self.assertTrue(payload["confirmed"])
        self.assertEqual(payload["profile"]["core_topics"], ["protein design"])
        self.assertEqual(payload["profile"]["summary"], "Track protein design.")
        self.assertNotIn("topics", config)
        self.assertNotIn("relevance_scoring", config)

    def test_load_document_text_supports_docx(self):
        with tempfile.TemporaryDirectory() as tmp:
            docx_path = Path(tmp) / "interest.docx"
            with zipfile.ZipFile(docx_path, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body>
                        <w:p><w:r><w:t>关注方向</w:t></w:r></w:p>
                        <w:p><w:r><w:t>蛋白质设计</w:t></w:r></w:p>
                      </w:body>
                    </w:document>""",
                )

            loaded = load_document_text(str(docx_path))

        self.assertEqual(loaded, "关注方向\n蛋白质设计")


if __name__ == "__main__":
    unittest.main()

from unittest.mock import patch

from django.test import SimpleTestCase

from .llm import LLMUnavailable
from .views import _answer_pdf_question


class PdfChatLLMTests(SimpleTestCase):
    def test_pdf_question_uses_open_llm_when_available(self):
        pdf_text = (
            "Data structures organize data for efficient access. "
            "A stack follows last in first out behavior. "
            "A queue follows first in first out behavior."
        )

        with patch("core.views.answer_from_context", return_value="A stack uses LIFO ordering.") as mocked_llm:
            answer, source = _answer_pdf_question(pdf_text, "What is stack behavior?", "notes.pdf")

        self.assertEqual(answer, "A stack uses LIFO ordering.")
        self.assertEqual(source, "open_llm")
        mocked_llm.assert_called_once()

    def test_pdf_question_falls_back_when_open_llm_is_unavailable(self):
        pdf_text = (
            "Normalization reduces data redundancy in relational databases. "
            "It organizes tables and relationships to improve consistency."
        )

        with patch("core.views.answer_from_context", side_effect=LLMUnavailable("offline")):
            answer, source = _answer_pdf_question(pdf_text, "What does normalization reduce?", "db.pdf")

        self.assertEqual(source, "fallback")
        self.assertIn("reduces data redundancy", answer)

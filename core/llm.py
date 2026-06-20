import json
import urllib.error
import urllib.request

from django.conf import settings


class LLMUnavailable(Exception):
    pass


def answer_from_context(question, context, note_name):
    if not getattr(settings, "OPEN_LLM_ENABLED", True):
        raise LLMUnavailable("Open LLM integration is disabled.")

    provider = getattr(settings, "OPEN_LLM_PROVIDER", "ollama").lower()
    if provider != "ollama":
        raise LLMUnavailable(f"Unsupported open LLM provider: {provider}")

    return _answer_with_ollama(question, context, note_name)


def _answer_with_ollama(question, context, note_name):
    endpoint = getattr(settings, "OLLAMA_ENDPOINT", "http://localhost:11434/api/chat")
    model = getattr(settings, "OLLAMA_MODEL", "llama3.2:3b")
    timeout = getattr(settings, "OLLAMA_TIMEOUT_SECONDS", 45)
    print("running with llama")

    prompt = (
        "You are an academic tutor helping a student understand a PDF note.\n"
        "Answer the question using only the provided PDF context. "
        "If the context does not contain enough information, say that the answer is not available in the selected PDF. "
        "Be clear, concise, and explain important terms when useful.\n\n"
        f"Selected PDF: {note_name}\n\n"
        f"PDF context:\n{context}\n\n"
        f"Student question: {question}"
    )
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": "You answer as a helpful tutor. Do not invent facts outside the supplied PDF context.",
            },
            {"role": "user", "content": prompt},
        ],
        "options": {
            "temperature": 0.2,
            "num_predict": 500,
        },
    }

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise LLMUnavailable(str(exc)) from exc

    answer = body.get("message", {}).get("content", "").strip()
    if not answer:
        raise LLMUnavailable("The model returned an empty answer.")

    return answer

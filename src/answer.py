"""Answer questions about the Saudi Labor Law with article citations."""
import os
import sys
import time
from google.genai import errors
from google import genai

from hybrid import HybridSearch
import re

HELP_EN = ("I answer questions about the Saudi Labor Law and check employment contracts against it. "
           "Ask about probation, leave, wages, working hours, termination, or end-of-service pay, "
           "in English or Arabic.")
HELP_AR = ("أجيب عن أسئلة نظام العمل السعودي وأراجع عقود العمل وفقاً له. اسأل عن فترة التجربة "
           "أو الإجازات أو الأجور أو ساعات العمل أو إنهاء العقد أو مكافأة نهاية الخدمة.")

MODELS = os.environ.get("GEMINI_MODELS", "gemini-flash-latest,gemini-flash-lite-latest").split(",")

PROMPT = """You are a legal research assistant for the Saudi Labor Law.

Rules:
1. Answer ONLY from the articles below. Never use outside knowledge.
2. Cite every claim with its article number, e.g. [Article 75].
3. Some articles were amended. Amendments are listed in date order after the original text.
   The LATEST amendment is the law in force. Use it, and mention the Royal Decree that made it.
4. If the articles do not contain the answer, reply exactly:
   "I could not find this in the provided articles."
5. Answer in the same language as the question.
6. Be concise. End with a one-line disclaimer that this is general information, not legal advice, in the same language as the question.

ARTICLES:
{context}

QUESTION: {question}
"""

REWRITE_PROMPT = """If the question below is NOT about employment, work, or labor rights
(for example a greeting, or a question about you), return exactly: NONE

Otherwise, rewrite it as a short English search query. Use the formal legal terms a labor
law would use (for example "terminate" instead of "fire", "probation" instead of
"trial period"). Keep every key concept. Do NOT add the name of the law or the country.
Return ONLY the query.

Question: {question}"""


def multi_search(engine: HybridSearch, question: str, rewritten: str,
                 k: int = 5, extra: int = 3) -> list[dict]:
    """Keep the original query's top k; the rewrite can only ADD up to `extra` new articles."""
    primary = [d for _, d in engine.search(question, k=k)]
    seen = {d["article_number"] for d in primary}
    extras = [d for _, d in engine.search(rewritten, k=k + extra)
              if d["article_number"] not in seen][:extra]
    return primary + extras

def generate(client: genai.Client, prompt: str, retries: int = 3, config=None) -> tuple[str, str]:
    """Try each model in order; retry temporary failures with growing waits."""
    last_error = None
    for model in MODELS:
        for attempt in range(retries):
            try:
                response = client.models.generate_content(model=model, contents=prompt, config=config)
                return response.text, model
            except errors.APIError as e:
                last_error = e
                if e.code in (429, 500, 503, 504):  # busy or rate-limited: wait, retry
                    wait = 5 * 2 ** attempt
                    print(f"  [{model}] error {e.code}, retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                break  # other errors (e.g. 404 model not found): try the next model
    raise last_error

def answer(question: str, engine: HybridSearch, client: genai.Client, k: int = 5):
    rewritten, _ = generate(client, REWRITE_PROMPT.format(question=question))
    rewritten = rewritten.strip().strip('"')
    if rewritten.upper() == "NONE":
        is_arabic = re.search(r"[\u0600-\u06FF]", question)
        return (HELP_AR if is_arabic else HELP_EN), [], None, rewritten
    results = multi_search(engine, question, rewritten)
    context = "\n\n---\n\n".join(d["content"] for d in results)
    text, model = generate(client, PROMPT.format(context=context, question=question))
    return text, [d["article_number"] for d in results], model, rewritten


if __name__ == "__main__":
    client = genai.Client()  # reads GEMINI_API_KEY from the environment
    engine = HybridSearch()
    questions = sys.argv[1:] or [
        "What is the maximum probation period?",
        "How much notice must an employer give to end an indefinite contract?",
        "ما هي مدة إجازة الوضع؟",
        "Can I work for another company on the side?",
        "What is the penalty for drunk driving?",
    ]
    for q in questions:
        text, used, model, rewritten = answer(q, engine, client)
        print("=" * 80)
        print("Q:", q)
        print("Search query:", rewritten)
        print(f"Retrieved: {used}   (model: {model})")
        print(text)
        time.sleep(3)
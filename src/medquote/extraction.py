import os
from openai import OpenAI
from dotenv import load_dotenv
from medquote.models import QuoteThrowaway

load_dotenv()

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_SYSTEM_PROMPT = (
    "You extract structured data from medical equipment vendor quotes. "
    "Use only information present in the provided text. "
    "If a field cannot be found, make your best reasonable inference from context, "
    "but do not invent data that contradicts the document."
)


def extract_fields(text: str, model: str = "gpt-4o-2024-08-06") -> QuoteThrowaway:
    """Call the LLM using native structured output (schema-enforced),
    never 'return JSON in your reply' prompting.
    """
    response = _client.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format=QuoteThrowaway,
    )
    return response.choices[0].message.parsed

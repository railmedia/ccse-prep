"""Prompt construction and the explanation contract.

One prompt per role, shared by every provider: comparing models only means
something if the input is identical.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.llm.base import Message
from app.models import Question
from app.rag.search import RetrievedChunk

EXPLAIN_PROMPT_VERSION = "explain-v1"
TUTOR_PROMPT_VERSION = "tutor-v1"

EXPLANATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "why_correct": {"type": "string"},
        "why_others_wrong": {"type": "array", "items": {"type": "string"}},
        "used_chunks": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["summary", "why_correct", "why_others_wrong", "used_chunks", "confidence"],
    "additionalProperties": False,
}

SYSTEM_EXPLAIN = (
    "Eres un profesor que prepara a candidatos para la prueba CCSE del Instituto Cervantes. "
    "Explicas en español, con precisión, usando ÚNICAMENTE los fragmentos del manual que se "
    "te proporcionan. No inventes datos ni cifras que no aparezcan en los fragmentos. "
    "Si los fragmentos no bastan para justificar la respuesta, dilo con claridad y baja la "
    "confianza. Responde siempre en JSON válido."
)

SYSTEM_TUTOR = (
    "Eres un profesor de la prueba CCSE. Respondes en español, en párrafos breves, "
    "citando la página del manual cuando el contexto lo permita. Si la respuesta no está "
    "en el contexto, di que no aparece en el manual en lugar de inventarla."
)


def prompt_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _chunk_block(chunks: list[RetrievedChunk]) -> str:
    parts = []
    for chunk in chunks:
        section = " > ".join(chunk.section_path)
        parts.append(f"[{chunk.id}] (pág. {chunk.page_from}, {section})\n{chunk.body}")
    return "\n\n".join(parts)


def build_query(question: Question) -> str:
    """Retrieval query: stem plus the correct option, never the bare stem."""
    correct = next(
        (option["text"] for option in question.options if option["key"] == question.answer), ""
    )
    # The task is already a hard filter; repeating its label only adds noise.
    return f"{question.stem} {correct}".strip()


def explanation_messages(question: Question, chunks: list[RetrievedChunk]) -> list[Message]:
    options = "\n".join(f"{option['key']}. {option['text']}" for option in question.options)
    schema_hint = json.dumps(EXPLANATION_SCHEMA, ensure_ascii=False)
    user = f"""Pregunta (Tarea {question.task}):
{question.stem}

Opciones:
{options}

Respuesta correcta según la clave oficial: {question.answer}

Fragmentos del manual:
{_chunk_block(chunks)}

Devuelve un objeto JSON con este esquema exacto:
{schema_hint}

Reglas:
- "summary": una frase que indique la respuesta correcta.
- "why_correct": por qué lo es, apoyándote en los fragmentos.
- "why_others_wrong": una entrada por cada opción incorrecta.
- "used_chunks": solo los identificadores entre corchetes que hayas usado.
- "confidence": entre 0 y 1, según cuánto apoyan los fragmentos la explicación."""
    return [Message(role="system", content=SYSTEM_EXPLAIN), Message(role="user", content=user)]


def tutor_messages(question: str, chunks: list[RetrievedChunk]) -> list[Message]:
    user = f"""Pregunta del estudiante: {question}

Fragmentos del manual:
{_chunk_block(chunks)}

Responde de forma directa y breve, citando la página cuando uses un fragmento."""
    return [Message(role="system", content=SYSTEM_TUTOR), Message(role="user", content=user)]

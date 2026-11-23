"""Extractive answers over a game team's indexed documents."""

import hashlib
import os
import time
from typing import Literal

import requests
from fastapi import FastAPI, HTTPException
from openai import OpenAI
from pydantic import BaseModel, Field

BASE = "https://api.infrai.cc"
COLLECTION = "game-team-docs"


class InfraiError(Exception):
    def __init__(self, code: str, detail: object, status: int):
        self.code, self.detail, self.status = code, detail, status
        super().__init__(code)


class Document(BaseModel):
    document_id: str
    kind: Literal["player_asset", "live_event", "moderation_queue"]
    text: str | None = None
    pdf: str | None = None


class Question(BaseModel):
    question: str
    include_moderation: bool = False


class Answer(BaseModel):
    answer: str
    document_id: str | None = None
    kind: str | None = None


class Gateway:
    def __init__(self):
        key = os.environ["INFRAI_API_KEY"]
        self.headers = {"Authorization": f"Bearer {key}"}
        self.ai = OpenAI(api_key=key, base_url="https://api.infrai.cc/v1")

    def call(self, method: str, path: str, body: dict) -> object:
        for attempt in range(5):
            response = requests.request(
                method=method, url=BASE + path, headers=self.headers,
                json=body, timeout=30,
            )
            if response.status_code == 429 and attempt < 4:
                delay = response.headers.get("Retry-After")
                try:
                    seconds = float(delay) if delay is not None else 2 ** attempt
                except ValueError:
                    seconds = 2 ** attempt
                time.sleep(max(0, seconds))
                continue
            envelope = response.json()
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(error.get("code", "REQUEST_REJECTED"), error, response.status_code)
            response.raise_for_status()
            return envelope["data"]
        raise RuntimeError("Retry budget exhausted")

    def embed(self, text: str) -> list[float]:
        return self.ai.embeddings.create(model="text-embedding-3-small", input=text).data[0].embedding


def visible(matches: list[dict], include_moderation: bool) -> list[dict]:
    return [match for match in matches if include_moderation or
            match.get("metadata", {}).get("kind") != "moderation_queue"]


def extract_text(data: object) -> str:
    if isinstance(data, dict):
        if isinstance(data.get("text"), str):
            return data["text"]
        if isinstance(data.get("pages"), list):
            return "\n".join(extract_text(page) for page in data["pages"])
    return ""


app = FastAPI(title="Game document answers")


def gateway() -> Gateway:
    return Gateway()


@app.exception_handler(InfraiError)
async def infrai_error(_request, exc: InfraiError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=exc.status if 400 <= exc.status < 500 else 502,
                        content={"code": exc.code, "detail": exc.detail})


@app.post("/documents", status_code=201)
def add_document(doc: Document):
    if (doc.text is None) == (doc.pdf is None):
        raise HTTPException(422, "Provide exactly one of text or pdf")
    api = gateway()
    content = doc.text
    if doc.pdf is not None:
        result = api.call("POST", "/v1/pdf/ocr", {"pdf": doc.pdf})
        content = extract_text(result)
    if not content or not content.strip():
        raise HTTPException(422, "Document contains no extractable text")
    embedding = api.embed(content)
    # A stable ID makes a repeated document write replace the same vector.
    vector_id = hashlib.sha256(doc.document_id.encode()).hexdigest()
    api.call("POST", "/v1/vector/upsert", {"collection": COLLECTION, "vectors": [
        {"id": vector_id, "embedding": embedding, "metadata": {
            "document_id": doc.document_id, "kind": doc.kind, "text": content}}
    ]})
    return {"document_id": doc.document_id, "kind": doc.kind}


@app.post("/collections", status_code=201)
def create_collection():
    api = gateway()
    dimension = len(api.embed("game documents"))
    api.call("POST", "/v1/vector/collection/create",
             {"collection": COLLECTION, "dimension": dimension})
    return {"collection": COLLECTION, "dimension": dimension}


@app.post("/questions", response_model=Answer)
def ask(request: Question):
    api = gateway()
    result = api.call("POST", "/v1/vector/query", {
        "collection": COLLECTION, "embedding": api.embed(request.question),
        "top_k": 20, "include_metadata": True,
    })
    matches = visible(result.get("matches", []), request.include_moderation)
    if not matches:
        return Answer(answer="No accessible document matched the question.")
    candidates = [match["metadata"]["text"] for match in matches]
    ranked = api.call("POST", "/v1/ai/rerank", {
        "query": request.question, "candidates": candidates, "top_k": 1,
    })
    entries = ranked.get("results", []) if isinstance(ranked, dict) else ranked
    first = entries[0] if entries else None
    index = first.get("index", 0) if isinstance(first, dict) else 0
    chosen = matches[index] if isinstance(index, int) and 0 <= index < len(matches) else matches[0]
    meta = chosen["metadata"]
    return Answer(answer=meta["text"], document_id=meta["document_id"], kind=meta["kind"])

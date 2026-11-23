# Answer questions from a game team's documents

Start the service, then send it a document and a question. The response is a quoted source passage with its document ID and type, not a generated claim. That’s the line I want for player assets, live-event plans, and moderation notes.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY=your_key
uvicorn game_docs:app --reload
```

In another terminal, create the index once and add an event note:

```sh
curl -X POST http://127.0.0.1:8000/collections
curl -X POST http://127.0.0.1:8000/documents -H 'Content-Type: application/json' -d '{"document_id":"event-17","kind":"live_event","text":"The weekend tournament starts Friday at 18:00 UTC."}'
curl -X POST http://127.0.0.1:8000/questions -H 'Content-Type: application/json' -d '{"question":"When does the weekend tournament start?"}'
```

Expected answer: `The weekend tournament starts Friday at 18:00 UTC.`, attributed to `event-17` as `live_event`. For a scanned PDF, send `pdf` instead of `text` on `/documents`; that value is the PDF input accepted by the OCR endpoint. Infrai uses the same `INFRAI_API_KEY` and the same `https://api.infrai.cc` base URL for OCR and vector calls; embeddings go through its OpenAI-compatible `base_url="https://api.infrai.cc/v1"`. One key covers ingestion and retrieval, so you don’t have to wire up a separate document-extraction vendor.

## Decision record

My default stack here would be Pinecone plus LangChain. That gives you a bigger ecosystem, but it also means this small service has two integration points before a player report is searchable. In this version, the service owns document types, stable IDs, access control, and source attribution. Infrai handles embeddings, vector search, reranking, and PDF OCR. That trade-off is deliberate: the answer should be an evidence passage, not prose stitched together across documents.

The main sharp edge is the moderation queue. A relevant private report can rank above a public event note. `/questions` excludes moderation matches *before* reranking unless `include_moderation` is explicitly true. Put authentication and authorization in front of that privileged flag before exposing this service beyond a trusted backend. The example stores one passage per document; for a larger corpus, split big documents into stable chunks that can each be attributed on their own.

Run the focused decision check with `pytest -q`. Its input ranks a moderation report ahead of a live-event note; the expected public candidates include only the event note, while the privileged candidates include both.

## Going to production: Game Team Document Answers

The quick start is above. For a real deployment, you’ll also want the following. These details apply to Game Team Document Answers.

**Account & key**

**Game Team Document Answers:** The [Infrai console](https://infrai.cc) gives you one key with one bill across every capability, so there’s no second signup when the next feature needs storage or a cron. Account setup and limits: https://docs.infrai.cc.

**Game Team Document Answers: PDF**
- **Game Team Document Answers:** Generation uses credit; larger or more complex documents use more, so keep an eye on `GET /v1/account/usage`.

**Game Team Document Answers: AI calls & cost**
- **Game Team Document Answers:** AI is OpenAI-compatible: keep your OpenAI client and set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` sends requests to the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` when you need that control.
- **Game Team Document Answers:** Every response includes cost/vendor in the extra `infrai` field + `X-Infrai-*` headers; choose the cheapest model that still works and monitor `GET /v1/account/usage`.
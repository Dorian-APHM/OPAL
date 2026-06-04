# opal-sapbert

Internal multilingual **SapBERT** encoder service used by OPAL's mapping
suggestions. The OPAL backend calls it to pre-compute top-K semantic matches
between source labels (référentiels CCAM/CIM10, source values with a label) and
the standard OMOP concepts of a domain. Results are stored in the app DB
(`sapbert_mappings`) and surfaced through the existing suggestion engine — so
the suggestion behaviour is unchanged, only the data source becomes in-app.

- Model: `cambridgeltl/SapBERT-UMLS-2020AB-all-lang-from-XLMR` (cross-lingual,
  baked into the image — French labels match English SNOMED/CPT4/… names directly).
- Pure compute: **no DB and no CDM access**. The backend (which owns the
  read-only CDM connections) feeds it concepts and labels over HTTP.
- Opt-in via `SAPBERT_MODE` in `.env` (`off` by default). Started with the
  Compose `sapbert` profile. GPU is used when available, CPU otherwise.

## API (token-gated via `X-Sapbert-Token`)

| Route | Body | Purpose |
|-------|------|---------|
| `GET /health` | — | model + device + indexed keys |
| `POST /index` | `{targets_key, targets[], reset}` | encode & cache target concept embeddings for a `(cdm, domain)` |
| `POST /match` | `{targets_key, sources[], top_k}` | top-K cosine of source labels vs the cached index → rows for `sapbert_mappings` |

`targets_key` is `f"{cdm_name}__{domain}"`. Embeddings are cached on the
`opal_sapbert_cache` volume (one folder per key: `embeddings.npy` + `metadata.jsonl`).

## Local smoke test

```bash
docker compose --profile sapbert up -d opal-sapbert
TOK=$SAPBERT_RUNNER_TOKEN
curl -s localhost:8002/health
curl -s -X POST localhost:8002/index -H "X-Sapbert-Token: $TOK" -H 'Content-Type: application/json' \
  -d '{"targets_key":"demo__Procedure","targets":[
        {"concept_id":4343571,"concept_code":"239348002","concept_name":"Excision of cranial tumor","vocabulary_id":"SNOMED"},
        {"concept_id":4046913,"concept_code":"230810008","concept_name":"Excision of tumor of brain meninges","vocabulary_id":"SNOMED"}]}'
curl -s -X POST localhost:8002/match -H "X-Sapbert-Token: $TOK" -H 'Content-Type: application/json' \
  -d '{"targets_key":"demo__Procedure","top_k":2,"sources":[
        {"code":"AAFA001","name":"Exérèse de tumeur intraparenchymateuse du cervelet, par craniotomie"}]}'
```

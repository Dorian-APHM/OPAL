# Cohort-LLM — Assistant IA de construction de cohortes

Décrit une cohorte en langage naturel (« Patients diabétiques de type 2 sous
metformine, hommes de 25–40 ans ») et obtiens un **brouillon de cohorte** :
démographie + critères, chaque terme résolu en **codes OMOP réels de ton CDM**.

La fonctionnalité est **opt-in** (désactivée par défaut), à la manière d'OHDSI.

---

## 1. Architecture

Le service `opal-llm` (port 8001, interne) fait **deux choses séparées** :

1. **Génération (LLM)** — extrait la requête en JSON structuré (démographie,
   critères, temporalité) et enrichit chaque terme (synonymes/abréviations).
2. **RAG (index + embeddings)** — fait correspondre chaque terme aux **vrais
   `source_value` du CDM**, via un index construit à partir de
   `source_value_cache`. Les embeddings ne sont **pas** calculés ici : `opal-llm`
   appelle le service partagé **`opal-sapbert`** (`POST /encode`), le **même**
   embedder médical multilingue que les suggestions de mapping (un seul modèle en
   VRAM pour les deux features). Module SapBERT **actif par défaut**.

Le backend OPAL est un **relais** : il appelle `opal-llm` en HTTP, ne fait
aucune inférence lui-même. Le navigateur ne joint jamais `opal-llm` directement.

```
Navigateur → Backend (/api/cohort-llm/draft, auth Keycloak)
           → opal-llm (RAG + génération)
                 ├─ génération : LLM embarqué (Ollama) OU LLM externe (on-premise)
                 └─ RAG : index source_value_cache (opal-db)
                          + embeddings via opal-sapbert (/encode)
```

> **Dépendance** : le RAG nécessite le module **SapBERT** (`opal-sapbert`, actif
> par défaut). Si SapBERT est **off**, l'extraction des critères fonctionne mais
> les concept-sets ne sont **pas** pré-remplis (voir §3 et le tableau des modes).

---

## 2. Les trois modes (`COHORT_LLM_MODE`)

| Mode | Onglet « Assistant IA » | LLM de génération | Conteneur |
|---|---|---|---|
| `off` *(défaut)* | masqué, endpoints `503` | — | aucun |
| `embedded` | visible | **modèle local** (Ollama, téléchargé au 1er run) | `opal-llm` (RAG + Ollama) |
| `on-premise` | visible | **ton LLM** (endpoint OpenAI-compatible) | `opal-llm` (RAG seul) |

> Le **RAG tourne dans `opal-llm` dans les deux modes actifs** ; seule la
> génération change. En `on-premise`, aucun modèle n'est téléchargé et Ollama
> n'est pas démarré — la génération part vers ton endpoint. Dans les deux cas, le
> RAG délègue ses embeddings à **`opal-sapbert`** (actif par défaut) ; SapBERT off
> ⇒ critères extraits mais concept-sets non pré-remplis.

---

## 3. Pré-requis

- Le **module SapBERT doit être actif** (`opal-sapbert`, par défaut `on`) : c'est
  lui qui produit les embeddings du RAG. S'il est off, l'assistant extrait les
  critères mais ne pré-remplit plus les concept-sets.
- Le **`source_value_cache` du CDM doit être peuplé** (Réglages → *Source Value
  Cache* → *Build*). C'est la source de l'index RAG ; sans lui, les critères
  n'auront pas de codes.
- Pour le mode `embedded` (LLM local sur GPU) : **runtime conteneur NVIDIA** sur
  l'hôte. Sinon, mets `COHORT_LLM_DEVICE=cpu` (LLM embarqué sur CPU, lent mais
  fonctionnel). Note : les embeddings du RAG tournent désormais dans `opal-sapbert`,
  pas dans `opal-llm`.

---

## 4. Installation / configuration

Variables `.env` (voir `.env.example`) :

```bash
COHORT_LLM_MODE=off            # off | embedded | on-premise
# COHORT_LLM_EMBEDDED_MODEL=qwen2.5:7b-instruct-q4_K_M   # embedded uniquement
# COHORT_LLM_DEVICE=cuda        # cuda (défaut) ou cpu
```

Le service vit derrière le **profil compose `cohort-llm`** : il ne démarre
**que** si tu l'actives explicitement.

### Mode `off` (défaut)
Rien à faire. `docker compose up -d` ne démarre pas `opal-llm`, l'onglet est masqué.

### Mode `embedded` (clé en main, LLM local)
```bash
# .env : COHORT_LLM_MODE=embedded
docker compose --profile cohort-llm up -d --build
```
Au **premier** lancement, Ollama télécharge `COHORT_LLM_EMBEDDED_MODEL` dans le
volume `opal_llm_models` (≈ plusieurs Go selon le modèle). Les suivants sont immédiats.

### Mode `on-premise` (ton propre LLM)
```bash
# .env : COHORT_LLM_MODE=on-premise
docker compose --profile cohort-llm up -d --build
```
Puis configure l'endpoint dans l'**UI → Réglages** (voir §5). Aucun modèle n'est
téléchargé ; `opal-llm` ne fait que le RAG et appelle ton LLM.

---

## 5. Configurer le LLM on-premise (UI Réglages, admin)

Dans **Réglages**, carte **« LLM Cohorte (on-premise) »** (visible uniquement en
mode `on-premise`, réservée aux **admins**) :

| Champ | Exemple | Obligatoire |
|---|---|---|
| **URL (base OpenAI-compatible)** | `https://llm.chu.fr/v1` ou `http://mon-vllm:8000/v1` | ✅ |
| **Modèle** | `llama3.1:70b-instruct`, `mistral-large`… | ✅ |
| **Clé API** | `sk-…` | ❌ **optionnelle** |

> **La clé API n'est requise que si ton endpoint exige une authentification.**
> Un Ollama/vLLM interne sans auth → laisse le champ **vide**, ça fonctionne
> (le backend n'envoie un header `Authorization: Bearer` que si une clé est posée).
>
> La clé est **chiffrée (Fernet)** en base et **jamais réaffichée** (champ
> volontairement vide ; un indicateur signale qu'une clé est enregistrée). Pour
> la changer, retape une nouvelle valeur et enregistre.

**Endpoints compatibles** : tout ce qui parle l'API OpenAI Chat Completions —
vLLM, Ollama (`/v1`), LocalAI, LM Studio, TGI, text-generation-webui, etc.

---

## 6. Usage

1. Sélectionne un CDM, va dans **Cohortes → onglet « Assistant IA »**.
2. Décris la cohorte en français, lance la génération.
3. Le brouillon s'affiche : démographie + critères, chaque terme avec ses
   **concept-sets** (codes OMOP du CDM). Revois, ajuste, applique au builder.

---

## 7. Sécurité

- Clé API LLM **chiffrée Fernet** (`SECRET_KEY`), jamais renvoyée en clair.
- Réglages LLM **réservés aux admins** ; endpoints sous auth Keycloak ;
  `check_cdm_access` appliqué sur `/draft`.
- **Résidence des données** : en `on-premise`, le prompt et les libellés vont
  vers **ton** endpoint LLM (donnée maîtrisée par l'établissement). En `embedded`,
  tout reste dans le conteneur local.

---

## 8. Dépannage

| Symptôme | Cause probable |
|---|---|
| Onglet « Assistant IA » absent | `COHORT_LLM_MODE=off`, ou non-accès à `/api/cohort-llm` (rôle) |
| `503` sur `/draft` | mode `off`, ou (on-premise) endpoint LLM non configuré dans Réglages |
| Critères sans codes (`no_match`) | `source_value_cache` du CDM non peuplé |
| `opal-llm unreachable` | service non démarré (profil `cohort-llm` manquant) |
| 401 de ton LLM externe | endpoint exige une clé API → renseigne-la dans Réglages |
| Génération lente | `COHORT_LLM_DEVICE=cpu` sans GPU, ou modèle externe lent |

---

## 9. Référence des variables / endpoints

**Env** : `COHORT_LLM_MODE` (off/embedded/on-premise), `COHORT_LLM_URL`
(défaut `http://opal-llm:8001`), `COHORT_LLM_EMBEDDED_MODEL`, `COHORT_LLM_DEVICE`.
Le RAG lit aussi `SAPBERT_URL` / `SAPBERT_RUNNER_TOKEN` (embeddings via `opal-sapbert`).

**API backend** (préfixe `/api/cohort-llm`, sous auth) :
- `GET /config` → `{enabled, mode}` (toujours dispo)
- `POST /draft` → `{prompt, cdm_name}` → brouillon de cohorte
- `GET /settings` · `PUT /settings` → config on-premise (**admin**, clé masquée)
- `GET /health` → proxy santé du service

**Service `opal-llm`** (interne :8001) : `POST /draft` (option `llm:{base_url,
model,api_key}` injectée par le backend en on-premise), `GET /health`,
`POST /rebuild/{cdm_name}` (reconstruit l'index RAG).

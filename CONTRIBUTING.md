# Contribuer à OPAL

Merci de l'intérêt que vous portez au projet. OPAL est une plateforme d'analyse
de bases OMOP CDM : qualité des données, construction de cohortes, mapping de
vocabulaires, exploration de concepts et lignage ETL.

Les contributions sont les bienvenues sous toutes leurs formes — signalement de
bug, correction, fonctionnalité, documentation, traduction. **Les issues et les
pull requests sont acceptées en français comme en anglais.**

---

## Sommaire

- [Avant de commencer](#avant-de-commencer)
- [Monter l'environnement de développement](#monter-lenvironnement-de-développement)
- [Lancer les tests](#lancer-les-tests)
- [Organisation du dépôt](#organisation-du-dépôt)
- [Règles d'or](#règles-dor)
- [Conventions de code](#conventions-de-code)
- [Conventions de commit](#conventions-de-commit)
- [Proposer une pull request](#proposer-une-pull-request)
- [Signaler un bug](#signaler-un-bug)
- [Signaler une faille de sécurité](#signaler-une-faille-de-sécurité)
- [Licence](#licence)

---

## Avant de commencer

Pour une correction de bug évidente, ouvrez directement une PR. Pour une
fonctionnalité ou un changement d'architecture, **ouvrez d'abord une issue** :
cela évite de développer plusieurs jours dans une direction qui ne sera pas
retenue.

Lectures utiles selon ce que vous visez :

| Document | Contenu |
|---|---|
| [`README.md`](README.md) | Installation, configuration, tour des 12 modules fonctionnels |
| [`docs/TECHNICAL.md`](docs/TECHNICAL.md) | Architecture interne détaillée |
| [`docs/API.md`](docs/API.md) | Référence des endpoints |
| [`docs/METHODOLOGIE.md`](docs/METHODOLOGIE.md) | Choix méthodologiques (qualité, mapping) |
| [`docs/adr/`](docs/adr/) | Décisions d'architecture (ADR) et leurs justifications |
| [`CLAUDE.md`](CLAUDE.md) | Cartographie condensée du code — le raccourci le plus rapide pour s'orienter |

---

## Monter l'environnement de développement

### Prérequis

| Outil | Version | Remarque |
|---|---|---|
| Python | **3.12** | version de l'image backend |
| Node.js | **20+** | version de l'image frontend ; Vite 8 refuse les versions antérieures |
| Docker + Compose | récent | pour la stack complète |
| PostgreSQL | 16 | fourni par Compose ; inutile de l'installer à la main |

> **Pas de proxy HTTP.** Le projet s'installe et se build en accès direct.
> N'ajoutez pas de `HTTP_PROXY`/`HTTPS_PROXY` ni de `--build-arg` proxy.

### 1. Forker et cloner

```bash
git clone https://github.com/<votre-compte>/OPAL.git
cd OPAL
git remote add upstream https://github.com/DorianGrousset/OPAL.git
```

### 2. Stack complète (recommandé)

C'est le moyen le plus rapide d'avoir une instance qui tourne, Keycloak compris.

```bash
cp .env.example .env
# Renseignez au minimum :
#   SECRET_KEY              -> openssl rand -hex 32
#   POSTGRES_PASSWORD       -> mot de passe de la base applicative
#   KEYCLOAK_ADMIN_PASSWORD -> openssl rand -base64 32
docker compose up -d
```

Frontend sur <http://localhost:3000>, API sur <http://localhost:8000>,
documentation OpenAPI sur <http://localhost:8000/docs>.

### 3. Backend seul (itération rapide)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 4. Frontend seul

```bash
cd frontend
npm install
npm run dev      # :5173, proxifie /api vers :8000
```

### Services optionnels

Plusieurs modules sont **opt-in** et désactivés par défaut. Vous n'avez besoin
de les lancer que si vous travaillez dessus :

| Service | Activation | Rôle |
|---|---|---|
| `opal-ohdsi-runner` | `OHDSI_MODE=on` + profil Compose `ohdsi` | exécute les outils R OHDSI (Achilles, DQD, CdmOnboarding, DashboardExport) |
| `opal-sapbert` | `SAPBERT_MODE` (activé par défaut) | embeddings partagés : suggestions de mapping + RAG cohort-llm |
| `opal-llm` | `COHORT_LLM_MODE` | assistant IA de construction de cohortes |

---

## Lancer les tests

**Toute PR doit laisser les tests au vert.** Aucune base externe n'est
nécessaire : `backend/tests/conftest.py` bascule sur SQLite en mémoire et
surcharge la dépendance FastAPI `get_db`, et les connexions OMOP sont simulées
par `backend/tests/omop_mock.py`.

```bash
# Backend — 59 fichiers de tests
cd backend
pytest tests/ -v
pytest tests/test_api.py -v                      # un seul fichier
pytest tests/test_api.py::test_nom_du_test -v    # un seul test

# Frontend — 129 tests
cd frontend
npx vitest run
npx vitest run src/pages/page-robustness.test.tsx   # un seul fichier

# Runner OHDSI — 8 tests
cd ohdsi-tools/runner
pytest tests/ -v
```

Le build TypeScript fait aussi office de vérification de types :

```bash
cd frontend && npm run build     # tsc && vite build
```

> Si votre Node local est trop ancien, passez par Docker :
> ```bash
> docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp \
>   -v "$PWD/frontend:/app" -w /app node:20-slim npm run build
> ```

Aucun linter ni formateur n'est configuré à ce jour : alignez-vous sur le style
des fichiers voisins.

---

## Organisation du dépôt

```
backend/          API FastAPI
  main.py           point d'entrée, enregistrement des routers
  config.py         configuration par variables d'environnement + DOMAIN_CONFIG
  db/               SQLAlchemy (base applicative) + pool de connexions OMOP
  modules/          21 routers, un par domaine fonctionnel
  utils/            crypto, sûreté SQL/CSV, rate limiting, WebSocket, helpers CDM
  i18n/             traductions backend (en.json / fr.json)
  tests/            pytest — SQLite en mémoire, OMOP simulé
frontend/         React 18 + TypeScript + Vite
  src/pages/        une page par module
  src/components/ui/  design system neumorphique
  src/api/client.ts   client Axios, découpé par module
  src/i18n/         traductions frontend (en.json / fr.json)
ohdsi-tools/      service runner des outils R OHDSI (paquets vendorés)
sapbert-tools/    service d'embeddings SapBERT
cohort-llm/       assistant IA de cohortes (RAG + LLM)
docs/             documentation technique, méthodologique et ADR
keycloak/         configuration du realm importée au démarrage
```

---

## Règles d'or

Ces contraintes ne sont pas négociables : elles touchent à la sécurité des
données de santé ou à l'intégrité des bases. Une PR qui les enfreint ne sera
pas fusionnée.

### 1. Les bases CDM sont en lecture seule

OPAL se connecte aux bases OMOP externes en **lecture seule**, via `psycopg2`
brut (pas SQLAlchemy). La **seule** écriture autorisée est la mise à jour
optionnelle de `source_to_concept_map` lors du push de mapping, et elle est
explicitement opt-in.

Tout cache, tout résultat intermédiaire, tout état applicatif va dans la
**base applicative interne**, jamais dans le CDM.

### 2. Tout identifiant SQL doit être validé

Les noms de schémas, tables et colonnes proviennent de la configuration
utilisateur. Ils passent obligatoirement par `utils/sql_safety.safe_identifier()`
(limite de 63 caractères).

Privilégiez `psycopg2.sql.SQL` + `sql.Identifier`. Les modules qui construisent
du SQL par f-strings (`cohort/sql_builder.py`, `cohort/pathways.py`) appliquent
une défense en profondeur : `safe_identifier()` **et** casts `int()` **et**
regex sur les dates. Respectez ce niveau d'exigence si vous y touchez.

### 3. Passer par `SchemaMap` pour toute référence `schéma.table`

Un CDM peut répartir ses tables entre plusieurs schémas PostgreSQL selon la
catégorie officielle CDM v5.4 (`clinical`, `vocabulary`, `derived`…). N'écrivez
jamais le schéma en dur :

```python
schema = get_cdm_connection(...)          # renvoie un SchemaMap
f"SELECT * FROM {schema.t('concept')}"    # résolution par catégorie
schema.schema_for('concept')              # pour sql.Identifier
```

### 4. Toute chaîne visible est traduite, en anglais **et** en français

Une clé ajoutée dans `en.json` doit l'être aussi dans `fr.json` — côté backend
(`backend/i18n/`) comme côté frontend (`frontend/src/i18n/`). Un test vérifie
la cohérence des deux fichiers.

### 5. Aucun secret dans le dépôt

Pas de mot de passe, de token ni de dump de données de santé, même en exemple,
même dans un test. Les mots de passe des CDM sont chiffrés en Fernet à partir
de `SECRET_KEY` (`utils/crypto.py`). Les fichiers de configuration locale
restent hors dépôt — vérifiez `.gitignore` avant de committer.

### 6. Les exports CSV sont protégés contre l'injection de formules

Passez par `utils/csv_safety.py` pour tout nouvel export.

### 7. Les paquets R OHDSI sont vendorés

Les archives sous `ohdsi-tools/vendor/` sont des sources GitHub figées, pour que
l'image se construise derrière un proxy d'entreprise. Si vous mettez à jour un
outil, remplacez le tarball et documentez la version dans
[`ohdsi-tools/README.md`](ohdsi-tools/README.md).

---

## Conventions de code

### Python

- Style proche de PEP 8, lignes ~100 caractères, comme les fichiers existants.
- Annotations de types sur les signatures publiques.
- Schémas Pydantic pour les entrées/sorties d'API.
- Un router par domaine fonctionnel, préfixé `/api/<domaine>`.
- Les traitements longs passent par le pool borné `utils/thread_pool.py`
  (`MAX_WORKER_THREADS`), jamais par un thread nu.
- Journalisez les exceptions avalées par un flux SSE ou une tâche de fond —
  sans quoi elles disparaissent silencieusement.

### TypeScript / React

- Composants fonctionnels et hooks ; pas de classes.
- Réutilisez le design system de `src/components/ui/` plutôt que de recréer des
  composants. Il couvre déjà les états vides (11 variantes), les erreurs
  (5 variantes), les squelettes de chargement et les toasts.
- Les types partagés vivent dans `src/types/index.ts`.
- Les appels API passent par `src/api/client.ts`, jamais par un `fetch` isolé —
  c'est là qu'est injecté le token Keycloak.
- Le thème sombre (défaut) et le thème clair doivent tous deux rester lisibles.

### SQL

- Requêtes paramétrées systématiquement ; jamais de concaténation de valeurs.
- Attention aux index : les filtres sur concepts et descendants doivent rester
  exploitables par l'optimiseur (voir les commits `perf(cohort)` pour le motif
  attendu).

---

## Conventions de commit

Le dépôt suit les [Conventional Commits](https://www.conventionalcommits.org/) :

```
<type>(<portée>): <résumé à l'impératif, minuscule, sans point final>

<corps optionnel : le POURQUOI, pas le QUOI — le diff dit déjà le quoi>
```

**Types utilisés** : `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `perf`.

**Portées courantes** : `cdm`, `cohort`, `mapping`, `quality`, `concept`,
`ohdsi`, `sapbert`, `cohort-llm`, `lineage`, `ui`, `security`, `deps`,
`keycloak`, `omop`, `compose`.

Exemples tirés de l'historique :

```
fix(omop): ne jamais évincer un pool dont des connexions sont sorties
feat(ohdsi): outil Dashboard Export + gestion des runs terminés
perf(cohort): keep pathways concept+descendants filter index-friendly
```

Le corps du message a de la valeur : expliquez le symptôme observé et la cause
racine. Les messages en français et en anglais coexistent dans l'historique,
les deux conviennent.

---

## Proposer une pull request

1. **Partez de `main` à jour** et créez une branche dédiée :
   ```bash
   git fetch upstream && git checkout -b fix/description-courte upstream/main
   ```
2. **Faites des commits atomiques.** Une PR qui mélange une fonctionnalité, un
   correctif et un renommage massif est beaucoup plus longue à relire.
3. **Ajoutez des tests.** Toute correction de bug devrait venir avec un test qui
   échoue sans le correctif.
4. **Vérifiez que tout est vert** — `pytest tests/`, `npx vitest run`,
   `npm run build`.
5. **Décrivez votre PR** : le problème résolu, l'approche retenue, ce que vous
   avez testé, et les éventuels effets de bord. Si l'UI change, joignez une
   capture.
6. **Une PR = un sujet.** Les changements sans rapport partent dans une autre PR.

Les contributions externes passent par un fork puis une pull request ; l'accès
en écriture au dépôt n'est pas nécessaire.

### Ce qui est relu en priorité

- Respect des règles d'or ci-dessus, en particulier la lecture seule des CDM et
  la validation des identifiants SQL.
- Couverture de tests de la logique ajoutée.
- Impact sur les performances des requêtes sur gros volumes — un CDM de
  production compte facilement des centaines de millions de lignes.
- Complétude des traductions.

---

## Signaler un bug

Ouvrez une [issue](https://github.com/DorianGrousset/OPAL/issues) en précisant :

- ce que vous attendiez et ce qui s'est produit ;
- les étapes de reproduction ;
- la version d'OPAL (voir [`CHANGELOG.md`](CHANGELOG.md)) et le mode de
  déploiement (Compose, développement local) ;
- la version de PostgreSQL et celle du CDM (5.3, 5.4) ;
- les logs pertinents — **expurgés de toute donnée patient et de tout secret**.

N'attachez jamais de données de santé réelles à une issue publique.

---

## Signaler une faille de sécurité

**N'ouvrez pas d'issue publique.** Suivez la procédure décrite dans
[`SECURITY.md`](SECURITY.md), qui précise le canal de signalement, le périmètre
couvert et les délais de réponse.

---

## Licence

En contribuant, vous acceptez que votre contribution soit distribuée sous la
licence [Apache 2.0](LICENSE) du projet.

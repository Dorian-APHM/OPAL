# ADR 0002 — Briques autonomes en Streamlit réutilisant les moteurs du backend

- **Statut** : Accepté
- **Date** : 2026-09-03
- **Décideurs** : équipe OPAL
- **Complète** : l'application complète (Docker Compose) — ne la remplace pas

---

## Contexte

OPAL est une application full-stack : React + FastAPI + PostgreSQL applicatif +
Keycloak, orchestrés par Docker Compose. C'est le bon format pour une plateforme
partagée par une équipe, avec comptes, rôles, partage de cohortes, notifications
et audit.

Ce format est en revanche disproportionné pour un besoin fréquent et légitime :
**analyser un CDM OMOP depuis un poste de travail**. Un data manager qui veut
auditer la qualité d'une base, ou un épidémiologiste qui construit une cohorte,
doit aujourd'hui installer Docker, provisionner une base applicative, configurer
un realm Keycloak et créer des comptes — pour un usage mono-utilisateur, souvent
ponctuel, parfois sur une machine où il n'a pas les droits d'administration.

### Contrainte produit (cadre de la décision)

- Chaque brique fonctionnelle doit pouvoir **se lancer seule**, en Python, sans
  Docker et sans base applicative.
- La configuration doit tenir dans **un seul fichier** : la connexion OMOP.
- **Aucune gestion d'utilisateurs** : ni comptes, ni rôles, ni partage.
- Les analyses doivent rester **identiques** à celles de l'application complète :
  une divergence de résultats entre les deux serait pire que l'absence de mode
  autonome.

---

## Options envisagées

### A. Copier le code d'analyse dans un dossier autonome

Vendorer les moteurs (`quality`, `cohort`, `mapping`, …) dans `standalone/`.

- ✅ Dossier réellement autoportant, aucune contrainte sur le backend.
- ❌ ~5 000 lignes dupliquées : toute correction devrait être appliquée deux
  fois, et la dérive est certaine. C'est précisément le risque que la contrainte
  produit interdit (résultats divergents).

### B. Appeler l'API du backend depuis Streamlit

Faire du standalone un client HTTP de l'application complète.

- ✅ Zéro duplication.
- ❌ Il faut alors faire tourner le backend — donc Docker, la base applicative et
  l'authentification. Cela contredit frontalement l'objectif.

### C. Importer les moteurs d'analyse du dépôt, en neutralisant leurs dépendances serveur

Mettre `backend/` sur le `sys.path` et remplacer, au moment de l'import, les
seuls modules liés au déploiement serveur.

- ✅ Aucune duplication du code d'analyse.
- ✅ Aucune dépendance serveur installée (ni FastAPI, ni SQLAlchemy, ni Keycloak).
- ❌ Le dossier `standalone/` n'est pas autoportant : il exige la présence de
  `backend/` dans le dépôt.
- ❌ Impose une contrainte aux moteurs : rester libres d'imports FastAPI /
  SQLAlchemy au niveau module.

---

## Décision

**Option C.** Les briques autonomes importent les moteurs d'analyse de
`backend/modules/**` et n'en réimplémentent aucun.

### Principes

1. **Un pont explicite, pas une bidouille d'import.**
   `opal_standalone/bootstrap.py` met `backend/` sur le `sys.path` et enregistre
   trois modules de remplacement dans `sys.modules` **avant** tout import de
   moteur. La substitution est déclarée en un seul endroit, documentée, et
   couverte par un test.

2. **Exactement trois modules sont remplacés** — ceux qui sont liés au
   déploiement serveur, pas à l'analyse :

   | Module backend | Pourquoi | Remplacement |
   |---|---|---|
   | `utils.cdm_helper` | cherche le CDM en base applicative, lève des `HTTPException` FastAPI | `SchemaMap` + détection des colonnes optionnelles, sans base ni FastAPI |
   | `utils.reference_labels` | lit les référentiels de la base applicative | no-op |
   | `db.app_db` | fabrique de sessions SQLAlchemy | session inerte |

3. **La glue de niveau routeur est réimplémentée, pas importée.** Les routeurs
   FastAPI mêlent HTTP, autorisation, base applicative et SQL. Le SQL utile
   (cohorte datée, Kaplan-Meier, requêtes vocabulaire, termes non mappés) est
   réécrit dans `opal_standalone/glue.py` — ~500 lignes, à garder alignées sur
   les routeurs.

4. **SQLite remplace la base applicative.** Snapshots versionnés, cohortes,
   concept sets, décisions de mapping, analyses et lignages, sans colonne de
   propriétaire puisqu'il n'y a pas d'utilisateurs.

5. **Une application Streamlit par brique**, plus une application qui les
   regroupe. Chaque point d'entrée fait huit lignes ; toute la logique vit dans
   `opal_standalone/views/`.

6. **Multi-moteurs par héritage.** Les briques passent par la couche de
   dialectes (ADR : voir [CDM_CONNECTORS.md](../CDM_CONNECTORS.md)) : la
   connexion porte `.dialect`, le `SchemaMap` porte `_dialect`, et le SQL propre
   au standalone est routé comme celui du serveur. Le moteur se choisit avec
   `db_type` dans le fichier de configuration.

### Contrat imposé au backend

Un moteur d'analyse (`backend/modules/**`) **ne doit pas importer FastAPI ni
SQLAlchemy au niveau module**. C'était déjà le cas ; c'est désormais une règle
vérifiée par `standalone/tests/test_bootstrap.py`, qui échoue si un import
serveur réapparaît dans un moteur.

---

## Conséquences

### Positives

- Une correction dans un moteur d'analyse bénéficie immédiatement aux deux
  produits ; aucun risque de résultats divergents.
- Installation en deux commandes, sans droits d'administration.
- Surface de dépendances minuscule : `streamlit`, `pandas`, `psycopg2-binary`,
  `plotly` (plus le pilote Oracle ou SQL Server si besoin).
- Le contrat « moteurs sans dépendance serveur » est une bonne propriété
  d'architecture en soi, désormais testée.

### Négatives / coûts

- `standalone/` n'est pas autoportant : il faut le dépôt (ou `OPAL_BACKEND_DIR`).
- `glue.py` est un point de dérive possible : si un routeur change sa logique
  SQL, la glue doit suivre.
- Les shims doivent évoluer avec `utils.cdm_helper` (c'est ce qui s'est produit
  lors de l'arrivée des dialectes : le `SchemaMap` a dû porter `_dialect`).
- Streamlit exécute le script à chaque interaction : les analyses longues
  bloquent la page. Acceptable en mono-utilisateur, avec barre de progression.

### Hors périmètre (explicite)

Comptes et rôles, partage de cohortes, groupes, notifications temps réel,
favoris, journal d'audit, outils OHDSI en R, assistant LLM et suggestions
SapBERT. Ces fonctions supposent un serveur, des utilisateurs ou un service
compagnon : elles restent l'apanage de l'application complète.

---

## Suivi

- Documentation : [docs/STANDALONE.md](../STANDALONE.md)
- Tests : `python -m pytest standalone/tests -q`
- Garde-fous automatisés : absence d'import serveur dans les moteurs, absence de
  SQL PostgreSQL-only dans `opal_standalone/`, rendu de chaque brique sur les
  trois moteurs.

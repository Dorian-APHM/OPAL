# OPAL standalone

Chaque brique d'OPAL, exécutable seule, en Python pur avec **Streamlit** : pas de
Docker, pas de base applicative, pas de Keycloak, pas de gestion d'utilisateurs.
Un seul fichier de configuration décrit la connexion OMOP, ouverte en lecture
seule — **PostgreSQL, Oracle ou SQL Server**.

> 📖 **Documentation complète** : [docs/STANDALONE.md](../docs/STANDALONE.md)
> (configuration détaillée, guide de chaque brique, sécurité, dépannage, FAQ)
> — et [ADR 0002](../docs/adr/0002-standalone-streamlit.md) pour le pourquoi de
> l'architecture.

---

## Démarrage

```bash
pip install -r standalone/requirements.txt
cp standalone/config.example.toml standalone/config.toml   # puis renseignez la connexion OMOP

python standalone/run.py --check                           # vérifie config, pilote, accès CDM
streamlit run standalone/apps/quality.py                   # la brique Qualité, seule
```

Python 3.11+ requis. Le dossier `backend/` du dépôt doit rester présent : les
briques y importent les moteurs d'analyse (déplaçable via `OPAL_BACKEND_DIR`).

## Les briques

| Brique | Lancement | Contenu |
| --- | --- | --- |
| Qualité | `standalone/apps/quality.py` | Analyses Achilles-like par domaine, conformité CDM, snapshots versionnés, comparaison, rapports HTML, exports CSV |
| Cohortes | `standalone/apps/cohort.py` | Critères, SQL généré, effectifs, attrition, échantillon, caractérisation (Table 1), parcours de soins, comparaison, console SQL lecture seule |
| Concepts | `standalone/apps/concepts.py` | Recherche dans le vocabulaire, relations, hiérarchie, valeurs source |
| Concept sets | `standalone/apps/concept_sets.py` | Ensembles de concepts et de codes source, résolution avec descendants, volumétrie, import/export |
| Mapping | `standalone/apps/mapping.py` | Couverture par domaine, termes non mappés, suggestions, décisions locales, export `source_to_concept_map` |
| Incidence | `standalone/apps/incidence.py` | Taux d'incidence, IC de Poisson, stratification |
| Estimation | `standalone/apps/estimation.py` | Kaplan-Meier, survie médiane, test du log-rank |
| Data management | `standalone/apps/datamanagement.py` | Extraction des données d'une cohorte en ZIP de CSV |
| Lineage ETL | `standalone/apps/lineage.py` | Documentation ETL parsée en graphe de lignage |
| Toutes les briques | `standalone/apps/opal.py` | Les neuf dans une seule application |

Le lanceur fait la même chose, avec des raccourcis :

```bash
python standalone/run.py --list                 # lister les briques
python standalone/run.py                        # toutes les briques
python standalone/run.py quality --port 8502    # une brique, sur un autre port
python standalone/run.py cohort --config /chemin/config.toml
```

## Configuration

```toml
[omop]
db_type = "postgresql"   # postgresql (défaut) | oracle | sqlserver
host = "localhost"
port = 5432              # défaut selon le moteur : 5432 / 1521 / 1433
database = "omop"        # Oracle : le service name
user = "opal_readonly"
password = ""            # ou variable d'environnement OPAL_OMOP_PASSWORD
schema = "omop_cdm"
```

Options : schémas par catégorie OMOP (`[omop.schema_categories]`), bases
supplémentaires (`[[cdm]]`, moteurs mélangeables), paramètres d'analyse
(`[analysis]`), emplacement des données locales (`[storage]`), langue des
rapports (`[ui]`). Référence complète :
[docs/STANDALONE.md §3](../docs/STANDALONE.md#3-configuration--référence-complète).

**Pilotes** : PostgreSQL fonctionne avec les dépendances de base ; Oracle demande
`pip install oracledb`, SQL Server `pip install pyodbc` (+ pilote ODBC système).

## Données locales

Snapshots, cohortes, concept sets, décisions de mapping, analyses et lignages
sont conservés dans **un seul fichier SQLite**, partagé par toutes les briques
(`standalone/data/opal-standalone.db` par défaut). C'est ainsi qu'Incidence,
Estimation et Data management retrouvent les cohortes enregistrées par le
constructeur, même lancés dans des processus séparés. Le copier suffit à
déplacer son travail, le supprimer remet à zéro. Détails et tableau des
dépendances entre briques :
[docs/STANDALONE.md §7](../docs/STANDALONE.md#7-données-locales).

## Ce qui n'est pas repris

Comptes et rôles, partage, groupes, notifications, favoris, audit, outils OHDSI
en R, assistant LLM et suggestions SapBERT (la brique Mapping conserve ses trois
stratégies déterministes). Ces fonctions supposent un serveur ou un service
compagnon.

## Tests

```bash
pip install pytest
python -m pytest standalone/tests -q      # 106 tests, aucune base requise
```

Le pont vers les moteurs, la configuration, le stockage, le SQL généré pour les
trois moteurs, les exports, le rendu de chaque application et un aller-retour
complet « analyse → snapshot → affichage » sur une connexion OMOP simulée.

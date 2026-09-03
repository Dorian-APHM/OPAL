# OPAL standalone

Chaque brique d'OPAL, exécutable seule, en Python pur avec **Streamlit** :
pas de Docker, pas de base applicative PostgreSQL, pas de Keycloak, pas de
gestion d'utilisateurs. Un seul fichier de configuration décrit la connexion à
la base OMOP, en lecture seule — **PostgreSQL, Oracle ou SQL Server**.

```bash
pip install -r standalone/requirements.txt
cp standalone/config.example.toml standalone/config.toml   # puis renseignez la connexion OMOP
streamlit run standalone/apps/quality.py                   # la brique Qualité, seule
```

## Les briques

| Brique | Lancement | Contenu |
| --- | --- | --- |
| Qualité | `streamlit run standalone/apps/quality.py` | Analyses Achilles-like par domaine, conformité CDM, snapshots versionnés, comparaison, rapports HTML, exports CSV |
| Cohortes | `standalone/apps/cohort.py` | Constructeur de critères, SQL généré, effectifs, attrition, échantillon, caractérisation (Table 1), parcours de soins, comparaison de cohortes, console SQL lecture seule |
| Concepts | `standalone/apps/concepts.py` | Recherche dans le vocabulaire, relations, hiérarchie (ancêtres/descendants), valeurs source |
| Concept sets | `standalone/apps/concept_sets.py` | Ensembles de concepts et de codes source, résolution avec descendants, volumétrie, import/export JSON |
| Mapping | `standalone/apps/mapping.py` | Couverture de mapping par domaine, termes non mappés, suggestions, décisions locales, export `source_to_concept_map` |
| Incidence | `standalone/apps/incidence.py` | Taux d'incidence et proportion, IC de Poisson, stratification |
| Estimation | `standalone/apps/estimation.py` | Courbes de survie Kaplan-Meier, survie médiane, test du log-rank |
| Data management | `standalone/apps/datamanagement.py` | Extraction des données d'une cohorte, table par table, en ZIP de CSV |
| Lineage ETL | `standalone/apps/lineage.py` | Documentation ETL HTML parsée en graphe de lignage, chaînes OMOP |
| Toutes les briques | `standalone/apps/opal.py` | Les neuf briques dans une seule application |

Un lanceur équivalent est fourni :

```bash
python standalone/run.py --list              # lister les briques
python standalone/run.py quality             # une brique
python standalone/run.py quality --port 8502
python standalone/run.py                     # toutes les briques (apps/opal.py)
python standalone/run.py cohort --config /chemin/vers/config.toml
```

## Configuration

Tout tient dans `standalone/config.toml` (modèle commenté :
`config.example.toml`). L'essentiel :

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

* **Moteur** : `db_type` sélectionne le dialecte partagé avec l'application
  complète (`backend/db/dialects/`). PostgreSQL est le moteur de référence et
  fonctionne avec les dépendances de base ; Oracle demande
  `pip install oracledb`, SQL Server `pip install pyodbc` (+ un pilote ODBC
  système). Le port par défaut suit le moteur choisi.

* **Mot de passe** : laissez le champ vide et exportez `OPAL_OMOP_PASSWORD`.
  `OPAL_OMOP_HOST`, `_PORT`, `_DATABASE`, `_USER`, `_SCHEMA` fonctionnent de la
  même façon et priment sur le fichier.
* **Schémas par catégorie** : `[omop.schema_categories]` permet de placer le
  vocabulaire (ou toute autre catégorie OMOP CDM v5.4) dans un schéma distinct,
  exactement comme l'application complète.
* **Plusieurs bases** : des sections `[[cdm]]` supplémentaires font apparaître un
  sélecteur dans la barre latérale — utile pour comparer deux CDM dans la brique
  Qualité.
* **Chemin de la configuration** : `OPAL_STANDALONE_CONFIG=/chemin/config.toml`.
  `OPAL_OMOP_DB_TYPE` change le moteur sans toucher au fichier.
* **Persistance** : `[storage] path` désigne le dossier du fichier SQLite qui
  conserve snapshots, cohortes, concept sets, décisions de mapping, analyses et
  lignages (par défaut `standalone/data/opal-standalone.db`). Le supprimer
  remet les briques à zéro ; le copier suffit à déplacer son travail.

## Comment ça marche

Les briques **réutilisent les moteurs d'analyse du dépôt** (`backend/modules/**`) :
mêmes requêtes SQL, mêmes calculs, mêmes structures de résultats que
l'application complète — il n'y a pas de fork à maintenir en parallèle. Elles
héritent donc aussi du **support multi-moteurs** : tout le SQL passe par la
couche de dialectes, y compris les requêtes propres au standalone
(`opal_standalone/glue.py`).

Ces moteurs sont volontairement purs (psycopg2 + `db.dialects` + `config` +
`utils.sql_safety`).
Trois modules du backend sont, eux, liés au déploiement serveur ; ils sont
remplacés au démarrage par des versions standalone (`opal_standalone/shims/`) :

| Module backend | Remplacement standalone |
| --- | --- |
| `utils.cdm_helper` | Résolution des schémas et détection des colonnes optionnelles, sans base applicative ni FastAPI |
| `utils.reference_labels` | Enrichissement des libellés désactivé (les référentiels vivent dans la base applicative) |
| `db.app_db` | Session inerte : la persistance passe par SQLite |

Conséquence : `pip install -r standalone/requirements.txt` suffit — ni FastAPI,
ni SQLAlchemy, ni cryptography, ni les services compagnons (seul le pilote du
moteur non-PostgreSQL éventuel est à ajouter). Le dossier
`backend/` du dépôt doit rester présent (les briques l'importent) ; il peut être
déplacé via `OPAL_BACKEND_DIR`.

## Sécurité

* La session est ouverte en **lecture seule** là où le moteur le permet
  (`default_transaction_read_only` sur PostgreSQL, `SET TRANSACTION READ ONLY`
  sur Oracle — SQL Server n'a pas d'équivalent) et bornée par un timeout de
  requête. Aucune brique n'écrit dans le CDM, y compris la brique Mapping —
  ses décisions restent locales et s'exportent en CSV `source_to_concept_map`.
  Utilisez de toute façon un compte de base en lecture seule : c'est la seule
  garantie valable sur les trois moteurs.
* Deux analyses font exception au verrou de session : **caractérisation** et
  **parcours de soins** créent des tables de travail de session (comme dans
  l'application complète) puis les suppriment ; leur connexion est donc ouverte
  sans le verrou. Elles n'écrivent jamais dans les tables du CDM. Si votre
  compte n'a pas le droit de créer de table temporaire, ces deux onglets sont
  les seuls à échouer.
* La console SQL n'accepte que `SELECT` / `WITH` / `EXPLAIN` et refuse les
  mots-clés d'écriture.
* Les identifiants SQL passent par `safe_identifier()` et les exports CSV par la
  protection anti-injection de formules, comme dans l'application complète.
* Il n'y a **aucune authentification** : ces applications sont prévues pour un
  poste de travail ou un serveur d'analyse déjà cloisonné. Ne les exposez pas
  sur un réseau ouvert ; le mot de passe OMOP est en clair dans `config.toml`
  (pensez à `chmod 600`, ou utilisez `OPAL_OMOP_PASSWORD`).

## Ce qui n'est pas repris

Volontairement hors périmètre, parce que ces fonctions n'ont de sens qu'avec le
serveur complet : comptes et rôles (Keycloak), partage de cohortes, groupes,
notifications temps réel, favoris, journal d'audit, outils OHDSI en R,
assistant LLM, et les suggestions **SapBERT** (service GPU séparé — la brique
Mapping conserve ses trois stratégies déterministes : code exact, relation
« Maps to », ingrédient/forme galénique).

## Tests

```bash
pip install pytest
python -m pytest standalone/tests -q
```

La suite tourne sans base de données : elle vérifie le pont vers les moteurs
(aucun import de FastAPI ou SQLAlchemy), la configuration, le stockage SQLite,
le SQL généré pour les trois dialectes (pagination, placeholders, arithmétique
de dates), les exports, et lance chaque application via `AppTest` de Streamlit,
y compris un aller-retour complet « analyse → snapshot → affichage » sur une
connexion OMOP simulée.

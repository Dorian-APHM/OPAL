# ADR 0001 — Exécution des outils OHDSI via un runner dédié (suppression du socket Docker)

- **Statut** : Accepté
- **Date** : 2026-05-28
- **Décideurs** : équipe OPAL
- **Remplace** : l'orchestration OHDSI actuelle basée sur le montage du socket Docker dans le backend

---

## Contexte

OPAL propose une page « Outils OHDSI » (`/ohdsi`) permettant de lancer quatre outils
R de l'écosystème OHDSI sur un CDM enregistré : **Achilles**, **Achilles Export**,
**Data Quality Dashboard (DQD)** et **CDM Onboarding**. L'objectif fonctionnel est
**uniquement de faire tourner ces outils** (déclencher, suivre les logs en temps réel,
exposer les fichiers de sortie). OPAL **n'analyse pas** les résultats produits.

### Architecture actuelle (à remplacer)

- Le conteneur `opal-backend` reçoit le **socket Docker de l'hôte** en montage
  (`/var/run/docker.sock`) et est ajouté au groupe `docker` (`group_add`).
- À chaque lancement, le backend appelle le démon Docker de l'hôte
  (`docker.from_env()` → `containers.run(...)`) pour démarrer une image OHDSI
  construite à part (`ohdsi-tools/docker-compose.yml`), nommée par convention
  (`OHDSI_IMAGE_PREFIX-<service>`).
- L'état des exécutions (statut, logs) est conservé **en mémoire** dans le backend.

### Problèmes identifiés

1. **Sécurité — escalade vers root-hôte (critique).** L'accès au socket Docker
   équivaut à un accès root sur la machine hôte (création de conteneurs privilégiés,
   montage de `/`, etc.). Le service le plus exposé au réseau (l'API FastAPI) détient
   donc, indirectement, un privilège root-hôte. Une compromission du backend (RCE,
   dépendance vulnérable, SSRF…) pivote immédiatement vers la prise de contrôle de
   l'hôte. Le fait que le conteneur tourne en utilisateur non-root (`USER opal`) ne
   protège pas : l'appartenance au groupe `docker` est équivalente à root.
   Il s'agit de **Docker-out-of-Docker (DooD)**, pas de Docker-in-Docker.

2. **Transparence — couplage caché.** Les images OHDSI ne sont pas des services du
   `docker-compose.yml` principal ; elles vivent dans un fichier compose séparé qu'il
   faut builder manuellement. Le lien backend ↔ images repose sur une convention de
   nommage non déclarative. Un `docker compose up` « réussit » mais OHDSI est cassé
   silencieusement jusqu'au premier lancement.

3. **Prod — fonctionnalité morte non assumée.** `docker-compose.prod.yml` retire le
   socket et mentionne un flag `OHDSI_ENABLED` qui **n'existe pas dans le code**. En
   production, l'onglet reste visible mais chaque lancement échoue.

4. **Robustesse (bugs connexes).**
   - L'éviction des tâches terminées (`main.py`) filtre sur des statuts
     (`completed`/`failed`) que le router **n'écrit jamais** (il écrit `done`/`error`)
     → les tâches réussies **fuient en mémoire indéfiniment**.
   - L'état est indexé par **service seul**, pas par `(cdm, service)` → impossible de
     lancer le même outil sur deux CDM en parallèle (HTTP 409), et l'état est **perdu
     au redémarrage** du backend alors que le conteneur continue de tourner (orphelin).
   - Le contrôle d'accès par CDM (`check_cdm_access`) n'est appliqué qu'au lancement,
     **pas** aux endpoints de lecture (`files`, `logs`, `status`) → un utilisateur peut
     lire les sorties/logs d'un CDM auquel il n'a pas accès.
   - Mitigation « creds file » (S08) **inopérante** : le mot de passe est aussi passé
     en clair dans l'environnement du conteneur (visible via `docker inspect`), et
     **aucun script ne lit** le fichier de credentials monté.
   - `run_achilles.R` utilise `smallCellCount = 0` (suppression des petites cellules
     **désactivée**) → risque de confidentialité sur données patients.

5. **Tests — inexistants** sur tout le module (le plus privilégié de l'app).

### Contrainte produit (cadre de la décision)

- L'utilité est **de faire tourner les outils, pas d'en analyser les résultats**.
- Le lancement de ces outils est **universel** : un « code to run » paramétré par
  variables d'environnement (`DB_*`, `*_SCHEMA`, `CDM_VERSION`, `SERVICE`,
  `OUTPUT_DIR`) qui invoque le bon script R, **identique en local ou en conteneur**.
- On veut **un modèle simple** : soit OPAL installe et fait tourner OHDSI, soit rien.
  On n'offre **pas** la possibilité de brancher une installation OHDSI tierce
  préexistante (choix de périmètre assumé).

---

## Décision

**Remplacer l'orchestration par socket par un service runner R dédié, qui exécute les
outils OHDSI en sous-processus, et que le backend pilote via une API HTTP interne.**

### Principes

1. **Le backend ne touche plus jamais Docker.** Suppression du montage
   `/var/run/docker.sock` et du `group_add: docker`.

2. **Un conteneur dédié `opal-ohdsi-runner`** embarque R + les packages OHDSI vendored
   (l'actuel contenu de `ohdsi-tools/`) et **exécute les outils en sous-processus**
   (`Rscript ...`). Aucun socket, aucun lancement de conteneur.

3. **API interne minimale** exposée par le runner et consommée par le backend :
   - `GET  /health` — disponibilité.
   - `POST /jobs` — lance un job (corps : `service`, paramètres CDM + schémas, version).
   - `GET  /jobs/{id}` — statut + métadonnées.
   - `GET  /jobs/{id}/logs?offset=` — logs (incrémental, pour relai SSE par le backend).
   - `POST /jobs/{id}/cancel` — annulation.
   - `GET  /jobs/{id}/artifacts` / `GET /jobs/{id}/artifacts/{path}` — listing /
     téléchargement des sorties.
   - Authentification par **token partagé** (`OHDSI_RUNNER_TOKEN`) sur le réseau interne.

4. **Deux modes seulement, pilotés par `OHDSI_MODE`** :
   - `OHDSI_MODE=off` (**défaut**) : runner non démarré ; les endpoints d'action
     du backend renvoient `503` ; `GET /api/ohdsi/config` reste disponible et
     renvoie `{enabled: false}` pour que le frontend masque l'onglet.
   - `OHDSI_MODE=on` : runner démarré via le **profil Compose `ohdsi`**
     (`docker compose --profile ohdsi up -d`).
   - Le service `opal-ohdsi-runner` est **déclaré dans le `docker-compose.yml` de base**
     (transparence) mais derrière `profiles: ["ohdsi"]` (non démarré par défaut).

5. **Isolation réseau** : le runner est sur un réseau dédié dont le seul egress utile
   est la base OMOP externe ; il **n'a pas** besoin d'accéder à `opal-db` ni à Keycloak.

6. **Suivi de jobs persisté côté runner** (fichier/SQLite local au volume du runner) :
   l'état survit aux redémarrages, supporte la concurrence multi-CDM, et expose les
   orphelins. Le backend ne conserve plus d'état OHDSI en mémoire.

7. **Secrets** : le backend déchiffre le mot de passe CDM et le transmet au runner
   **uniquement** via le corps de la requête `POST /jobs` (canal interne authentifié) ;
   le runner l'injecte dans l'environnement du sous-processus R. Plus d'exposition via
   `docker inspect` (il n'y a plus de conteneur lancé via socket).

### Schéma cible

```
  frontend ──► opal-backend ──HTTP/token──► opal-ohdsi-runner ──JDBC ro──► OMOP CDM
                  (aucun socket Docker)        (R + OHDSI,
                                                sous-processus,
                                                jobs persistés)
```

---

## Conséquences

### Positives

- **Disparition de la classe de risque critique** : un backend compromis ne donne plus
  root-hôte. Le pire cas se réduit à la capacité métier voulue (lancer une analyse
  OHDSI sur un CDM autorisé).
- **Isolation** des secrets de l'app et de la stabilité de l'API vis-à-vis de R/JVM.
- **Transparence** : un seul compose, activation par un flag, plus de build manuel caché.
- **Correction native** des bugs d'état (persistance + clé `(cdm, service)`).
- **Image backend** reste légère (`python:3.12-slim`).

### Négatives / coûts

- Un **service supplémentaire** à construire et maintenir (runner + petite API).
- Le runner reçoit le mot de passe CDM en mémoire (inhérent ; mitigé par réseau interne
  + token + caractère éphémère).
- **Pas de branchement d'une installation OHDSI tierce** (choix assumé) : OHDSI est
  « installé par OPAL ou rien ».

### Hors périmètre (explicite)

- Ingestion / analyse des résultats OHDSI dans OPAL.
- Mode « BYO » (brancher un runner/une install externe a posteriori).
- Orchestration multi-nœuds / file de jobs distribuée (un pool de workers local au
  runner suffit).

---

## Alternatives considérées (et rejetées)

1. **Statu quo (socket Docker).** Rejeté : risque root-hôte inacceptable.

2. **Docker socket proxy** (filtrage des routes de l'API Docker). Rejeté : filtre par
   route, pas par contenu — ne peut pas empêcher la création d'un conteneur montant `/`
   ou privilégié. Atténue sans supprimer le risque.

3. **Exécuter R en sous-processus directement dans le conteneur backend.** Rejeté :
   supprime bien le socket, mais (a) mélange la surface d'attaque R avec les secrets de
   l'app dans la même frontière d'isolation, (b) un run lourd peut faire tomber l'API,
   (c) alourdit fortement l'image backend et couple les cycles de vie.

4. **Modes multiples (managed / external / results-only / off).** Rejeté : complexité
   et dette (contrat public, adaptateurs, auth tierce) sans bénéfice au regard de la
   contrainte produit. Remplacé par un simple ON/OFF.

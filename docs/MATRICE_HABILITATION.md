# Matrice d'habilitation — OPAL

> Source de vérité : [`backend/permissions.yaml`](../backend/permissions.yaml)

## Rôles

| Rôle | Description | Utilisateur type |
|------|-------------|------------------|
| **admin** | Accès total — administration système, utilisateurs, audit | Administrateur IT |
| **data-manager** | Accès complet aux données — qualité, mapping, SQL, gestion CDM | DIM / Ingénieur données |
| **chercheur** | Recherche — cohortes, concepts, cohortes partagées | Chercheur / Biostatisticien |
| **medecin** | Clinique — validation mapping, concepts | Médecin / Expert métier |

## Accès aux pages

| Page | Route | admin | data-manager | chercheur | medecin |
|------|-------|:-----:|:------------:|:---------:|:-------:|
| Accueil | `/` | ✅ | ✅ | ✅ | ✅ |
| Quality | `/quality` | ✅ | ✅ | ❌ | ❌ |
| Cohorts | `/cohorts` | ✅ | ✅ | ✅ | ❌ |
| Data Export | `/data-management` | ✅ | ✅ | ❌ | ❌ |
| Mapping | `/mapping` | ✅ | ✅ | ❌ | ✅ |
| Concept Explorer | `/concepts` | ✅ | ✅ | ✅ | ✅ |
| OHDSI | `/ohdsi` | ✅ | ✅ | ❌ | ❌ |
| Gestion CDM | `/cdm` | ✅ | ✅ | ❌ | ❌ |
| Paramètres | `/settings` | ✅ | ✅ | ❌ | ❌ |
| Gestion utilisateurs | `/users` | ✅ | ❌ | ❌ | ❌ |
| Audit | `/audit` | ✅ | ❌ | ❌ | ❌ |

## Accès aux API

| Module API | admin | data-manager | chercheur | medecin |
|------------|:-----:|:------------:|:---------:|:-------:|
| `/api/quality` | ✅ | ✅ | ❌ | ❌ |
| `/api/cohorts` | ✅ | ✅ | ✅ | ❌ |
| `/api/concepts` | ✅ | ✅ | ✅ | ✅ |
| `/api/mapping` | ✅ | ✅ | ❌ | ✅ |
| `/api/cdm` (écriture) | ✅ | ✅ | ❌ | ❌ |
| `/api/cdm` (lecture) | ✅ | ✅ | ✅ | ✅ |
| `/api/datamanagement` | ✅ | ✅ | ❌ | ❌ |
| `/api/ohdsi` | ✅ | ✅ | ❌ | ❌ |
| `/api/search` | ✅ | ✅ | ✅ | ✅ |
| `/api/favorites` | ✅ | ✅ | ✅ | ✅ |
| `/api/notifications` | ✅ | ✅ | ✅ | ✅ |
| `/api/saved-queries` | ✅ | ✅ | ✅ | ✅ |
| `/api/cohort-templates` | ✅ | ✅ | ✅ | ❌ |
| `/api/cdm-access` (complet) | ✅ | ✅ | ❌ | ❌ |
| `/api/cdm-access/cdms-for-user` | ✅ | ✅ | ✅ | ✅ |
| `/api/groups` | ✅ | ✅ | ✅ | ✅ |
| `/api/incidence` | ✅ | ✅ | ❌ | ❌ |
| `/api/estimation` | ✅ | ✅ | ❌ | ❌ |
| `/api/admin` | ✅ | ❌ | ❌ | ❌ |
| `/api/auth` | ✅ | ✅ | ✅ | ✅ |
| `/api/i18n` | ✅ | ✅ | ✅ | ✅ |
| `/api/health` | ✅ | ✅ | ✅ | ✅ |

## Visibilité CDM

| Capacité | admin | data-manager | chercheur | medecin |
|----------|:-----:|:------------:|:---------:|:-------:|
| Voit tous les CDM | ✅ | ✅ | ❌ | ❌ |
| Voit uniquement les CDM autorisés (ACL) | — | — | ✅ | ✅ |
| Peut gérer les accès CDM (grant/revoke) | ✅ | ✅ | ❌ | ❌ |
| Peut supprimer tous les grants d'un CDM | ✅ | ❌ | ❌ | ❌ |

## Fonctionnalités détaillées par page

### Quality (`/quality`)
| Action | admin | data-manager | chercheur | medecin |
|--------|:-----:|:------------:|:---------:|:-------:|
| Lancer une analyse (single/batch) | ✅ | ✅ | ❌ | ❌ |
| Annuler une analyse | ✅ | ✅ | ❌ | ❌ |
| Consulter les résultats / snapshots | ✅ | ✅ | ❌ | ❌ |
| Comparer des snapshots | ✅ | ✅ | ❌ | ❌ |
| Exporter CSV | ✅ | ✅ | ❌ | ❌ |
| Conformité | ✅ | ✅ | ❌ | ❌ |

### Cohorts (`/cohorts`)
| Action | admin | data-manager | chercheur | medecin |
|--------|:-----:|:------------:|:---------:|:-------:|
| Créer / modifier une cohorte | ✅ | ✅ | ✅ | ❌ |
| Exécuter une cohorte | ✅ | ✅ | ✅ | ❌ |
| Exporter les patients (CSV) | ✅ | ✅ | ✅ | ❌ |
| Partager une cohorte | ✅ | ✅ | ✅ | ❌ |
| Pathways / Caractérisation | ✅ | ✅ | ✅ | ❌ |

### Mapping (`/mapping`)
| Action | admin | data-manager | chercheur | medecin |
|--------|:-----:|:------------:|:---------:|:-------:|
| Consulter les suggestions (per-user) | ✅ | ✅ | ❌ | ✅ |
| Approuver / rejeter un mapping | ✅ | ✅ | ❌ | ✅ |
| Approuver / rejeter depuis l'historique | ✅ | ✅ | ❌ | ✅ |
| Retirer sa propre décision (withdraw) | ✅ | ✅ | ❌ | ✅ |
| Rejeter la décision d'un autre user | ✅ | ❌ | ❌ | ❌ |
| Exporter STCM (consensus uniquement) | ✅ | ✅ | ❌ | ✅ |
| Historique des décisions (partagé) | ✅ | ✅ | ❌ | ✅ |

### Concept Explorer (`/concepts`)
| Action | admin | data-manager | chercheur | medecin |
|--------|:-----:|:------------:|:---------:|:-------:|
| Recherche concepts / hiérarchie | ✅ | ✅ | ✅ | ✅ |
| Recherche source values | ✅ | ✅ | ✅ | ✅ |
| Export CSV | ✅ | ✅ | ✅ | ✅ |

### Administration
| Action | admin | data-manager | chercheur | medecin |
|--------|:-----:|:------------:|:---------:|:-------:|
| Gérer les utilisateurs Keycloak | ✅ | ❌ | ❌ | ❌ |
| Traiter les demandes d'accès | ✅ | ❌ | ❌ | ❌ |
| Consulter l'audit log | ✅ | ❌ | ❌ | ❌ |
| Enregistrer / modifier un CDM | ✅ | ✅ | ❌ | ❌ |
| Lancer les outils OHDSI | ✅ | ✅ | ❌ | ❌ |

## Notes

- Les rôles sont cumulables : un utilisateur peut avoir `chercheur` + `medecin`
- `GET /api/cdm/` est accessible à tous les utilisateurs authentifiés (pour le sélecteur CDM)
- `/api/auth` est accessible sans vérification de rôle (authentification uniquement)
- La visibilité CDM `acl_only` signifie que l'utilisateur ne voit que les CDM pour lesquels un accès explicite a été accordé (par utilisateur ou par groupe)

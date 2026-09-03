# OPAL — Guide Utilisateur

Bienvenue dans OPAL (OMOP Platform for Analytics & Lineage). Ce guide vous accompagne dans l'utilisation de chaque fonctionnalite de la plateforme.

---

## Table des matieres

1. [Premiers pas](#1-premiers-pas)
2. [Navigation et interface](#2-navigation-et-interface)
3. [Gestion des CDM](#3-gestion-des-cdm)
4. [Analyse Qualite](#4-analyse-qualite)
5. [Constructeur de Cohortes](#5-constructeur-de-cohortes)
6. [Workflow de Mapping](#6-workflow-de-mapping)
7. [Explorateur de Concepts](#7-explorateur-de-concepts)
8. [Outils OHDSI](#8-outils-ohdsi)
9. [Parametres](#9-parametres)
10. [Audit et Administration](#10-audit-et-administration)
11. [FAQ et Depannage](#11-faq-et-depannage)

---

## 1. Premiers pas

> **Sans installation serveur ?** Chaque brique d'OPAL existe aussi en
> application Streamlit autonome, sans Docker ni comptes utilisateurs : voir
> [STANDALONE.md](STANDALONE.md). Les analyses y sont les memes ; seule
> l'enveloppe change. Ce guide decrit l'application complete.


### Connexion

#### Avec authentification (Keycloak active)

1. Ouvrir OPAL dans votre navigateur : `http://<adresse>:3000`
2. Cliquer sur **Se connecter via Keycloak**
3. Saisir vos identifiants sur la page Keycloak
4. Vous etes redirige vers OPAL avec votre session active

Si vous n'avez pas de compte :

1. Cliquer sur l'onglet **Inscription**
2. Remplir le formulaire : **identifiant professionnel** et **role souhaite**
3. Soumettre la demande
4. Attendre la validation par un administrateur
5. Vous vous connecterez ensuite avec vos identifiants une fois approuve

#### Sans authentification

Si Keycloak n'est pas active (`AUTH_ENABLED=true` par defaut, a mettre a `false` pour desactiver), vous accedez directement a toutes les fonctionnalites en tant qu'administrateur.

### Roles et permissions

Votre role determine les pages et fonctionnalites auxquelles vous avez acces :

| Role | Description | Pages accessibles |
|------|-------------|-------------------|
| **Admin** | Administrateur systeme | Toutes les pages + Audit + Gestion utilisateurs |
| **OMOP DIM** | Data steward | Toutes les pages fonctionnelles |
| **Chercheur** | Recherche clinique | Qualite, Cohortes, Concepts |
| **Medecin** | Medecin / terminologue | Mapping, Cohortes, Concepts |

Votre role est affiche sous votre nom d'utilisateur dans la barre de navigation supérieure (TopNav).

### Selectionner un CDM

Avant d'utiliser la plupart des fonctionnalites, vous devez selectionner un CDM :

1. Dans la barre de navigation supérieure (TopNav), deployer le selecteur **CDM**
2. Choisir le CDM sur lequel vous souhaitez travailler
3. Le CDM selectionne est retenu entre les sessions

> **Note** : Si aucun CDM n'est enregistre, demandez a un administrateur d'en configurer un (page Gestion des CDM).

---

## 2. Navigation et interface

### Barre de navigation supérieure (TopNav)

La barre de navigation supérieure est votre point d'acces a toutes les fonctionnalites :

- **Logo OPAL** : retour a la page d'accueil
- **Selecteur CDM** : choisir la base OMOP active
- **Qualite** : analyse qualite des donnees
- **Cohortes** : constructeur de cohortes
- **Mapping** : workflow de mapping des vocabulaires
- **Concepts** : explorateur de concepts OMOP
- **Gestion CDM** : enregistrement des connexions (admin)
- **OHDSI** : outils OHDSI (admin)
- **Parametres** : configuration (admin)
- **Audit** : journal d'activite (admin)
- **Utilisateurs** : gestion des comptes (admin)

A droite de la TopNav :
- **Bouton langue** (FR/EN) : basculer entre francais et anglais
- **Mode sombre** : activer/desactiver le theme sombre
- **Cloche notifications** : voir les notifications non lues
- **Deconnexion** : fermer votre session

### Page d'accueil (Dashboard)

La page d'accueil s'affiche apres connexion et offre une vue d'ensemble de votre environnement OPAL :

- **CDM enregistres** : liste des bases OMOP disponibles avec leurs informations principales
- **Activites recentes** : dernieres actions effectuees (analyses, cohortes, mappings)
- **Favoris** : acces rapide aux elements marques comme favoris
- **Acces rapide** : raccourcis vers les fonctionnalites principales (Qualite, Cohortes, Mapping, Concepts)

### Notifications

L'icone cloche dans la TopNav affiche le nombre de notifications non lues :

- Cliquer sur la cloche pour ouvrir le **tiroir de notifications**
- Les notifications sont classees par categorie :
  - **Analyses** : fin d'analyse qualite, nouveaux snapshots
  - **Cohortes** : partage de cohortes, mises a jour
  - **Mapping** : suggestions generees, decisions appliquees
  - **Administration** : demandes d'acces, changements de role
- Actions disponibles : **marquer comme lu**, **supprimer** une notification
- Les notifications arrivent en **temps reel via WebSocket** (pas besoin de rafraichir la page)

### Conventions d'interface

- Les **boutons bleus** declenchent des actions principales
- Les **tags colores** indiquent des statuts (vert = succes, orange = avertissement, rouge = erreur)
- Les **icones d'export** (telechargement) permettent d'exporter en CSV
- Les **indicateurs de chargement** (spinners) indiquent un traitement en cours

---

## 3. Gestion des CDM

**Acces** : Admin, OMOP DIM

Cette page permet d'enregistrer et gerer les connexions aux bases OMOP CDM externes.

### Enregistrer un nouveau CDM

1. Acceder a la page **Gestion des CDM**
2. Remplir le formulaire :
   - **Nom** : identifiant unique (ex: `CHU_OMOP_PROD`)
   - **Hote** : adresse du serveur PostgreSQL
   - **Port** : port PostgreSQL (defaut : 5432)
   - **Base de donnees** : nom de la base
   - **Utilisateur** : compte PostgreSQL
   - **Mot de passe** : sera chiffre avant stockage
   - **Schema OMOP** : schema contenant les tables OMOP (defaut : `omop_cdm`)
3. Cliquer sur **Tester la connexion** pour verifier les parametres
4. Si le test est reussi (nombre de patients affiche), cliquer sur **Enregistrer**

### Gerer les CDM existants

La liste des CDM enregistres affiche :
- Nom, hote, port, base, utilisateur, schema
- Bouton **Tester** : verifier que la connexion fonctionne toujours
- Bouton **Supprimer** : retirer le CDM (avec confirmation)

> **Important** : Le mot de passe n'est jamais affiche. Il est chiffre avec Fernet (AES-128) dans la base.

---

## 4. Analyse Qualite

**Acces** : Admin, OMOP DIM, Chercheur

L'analyse qualite evalue vos donnees OMOP a travers 14 domaines (3 speciaux + 11 cliniques) et stocke les resultats sous forme de snapshots versiones.

### Lancer une analyse

#### Analyse d'un seul domaine

1. Selectionner un **domaine** dans la liste a gauche :
   - **Dashboard** : vue d'ensemble globale
   - **Person** : demographie
   - **ObservationPeriod** : periodes d'observation
   - **Condition, Drug, Measurement, Observation, Procedure, Visit, Device, Death, Specimen, Note, Payer_Plan_Period** : domaines cliniques
2. Cliquer sur **Analyser**
3. Les resultats s'affichent avec graphiques et tableaux

#### Analyse par lot (tous les domaines)

1. Cliquer sur **Analyse complete**
2. Une barre de progression montre l'avancement domaine par domaine
3. Chaque domaine est coche une fois termine
4. Vous pouvez annuler en cours de route

### Comprendre les resultats

#### Dashboard

- **Total personnes** : nombre de patients dans le CDM
- **Tableau par domaine** : pour chaque domaine, le nombre de records, personnes, et taux de mapping
- **Vue globale** : couverture des donnees a travers les domaines

#### Person (demographie)

- **Distribution par genre** : camembert montrant la repartition H/F/Autre
- **Annees de naissance** : histogramme des annees de naissance
- **Distribution par race** : camembert (si disponible)
- **Distribution par ethnicite** : camembert (si disponible)

#### Observation Period

- **Age a la premiere observation** : histogramme de l'age au debut du suivi
- **Age par genre** : quantiles (p10, p25, mediane, p75, p90) par genre
- **Duree d'observation** : histogramme de la duree en mois
- **Observation cumulative** : courbe montrant le % de patients avec au moins X mois de suivi
- **Observation continue par annee** : nombre de patients observes chaque annee

#### Domaines cliniques (Condition, Drug, etc.)

- **Statistiques globales** : total lignes, personnes, moyenne par personne
- **Evolution mensuelle** : courbe du nombre de records par mois
- **Distribution records/personne** : histogramme
- **Top concepts** : tableau des concepts les plus frequents
- **Qualite du mapping** :
  - Taux de mapping au niveau terme (combien de codes source distincts sont mappes)
  - Taux de mapping au niveau ligne (combien de lignes sont mappees)
  - Top termes non mappes avec leur frequence

### Exporter les resultats

Chaque tableau peut etre exporte en CSV :
- Cliquer sur l'icone de telechargement a cote du tableau
- Le fichier CSV est telecharge automatiquement

### Historique des snapshots

Chaque analyse cree une nouvelle version :
- Le selecteur de version (v1, v2, v3...) permet de charger un snapshot anterieur
- La date de creation est affichee

### Comparer deux CDM

1. Cliquer sur le bouton **Comparer** ou activer le mode comparaison
2. Selectionner les deux CDM a comparer
3. Choisir un domaine
4. Les resultats s'affichent cote a cote avec les ecarts en pourcentage
5. Les alertes sont colorees :
   - **Jaune** : ecart > seuil (defaut 5%)
   - **Rouge** : ecart > 2x le seuil (defaut 10%)

### Generer un rapport

1. Cliquer sur **Rapport HTML** ou **Rapport PDF**
2. Choisir la langue (Francais ou Anglais)
3. Le rapport compile tous les domaines analyses
4. Pour un rapport de comparaison, cliquer sur **Rapport comparaison**

---

## 5. Constructeur de Cohortes

**Acces** : Admin, OMOP DIM, Chercheur, Medecin

Le constructeur de cohortes permet de definir visuellement des populations de patients a partir de criteres cliniques.

### Interface

L'ecran est divise en 3 zones :

| Zone | Position | Role |
|------|----------|------|
| **Criteres** | Gauche | Recherche et selection de concepts OMOP |
| **Canvas** | Centre | Construction de la requete (4 onglets) |
| **Resultats** | Droite | Comptage, attrition, echantillon, SQL |

### Creer une cohorte

#### Etape 1 : Rechercher des concepts

1. Dans le panneau de gauche, selectionner un **domaine** (Condition, Drug, etc.)
2. Taper un terme de recherche (ex: "diabete", "metformine")
3. Optionnellement filtrer par **vocabulaire** (SNOMED, ICD10, ATC...)
4. Les concepts correspondants s'affichent dans une liste
5. Cliquer sur un concept pour l'ajouter comme critere d'inclusion

#### Etape 2 : Configurer les criteres

Dans le **Query Builder** (onglet central) :

**Criteres d'inclusion** :
- Chaque critere est affiche comme un bloc avec le nom du concept
- **Inclure descendants** (coche) : inclut automatiquement tous les concepts enfants dans la hierarchie OMOP
- **Operateur** entre criteres : AND (les deux doivent etre vrais) ou OR (l'un ou l'autre)

**Contraintes temporelles** (par critere) :
- **Tout moment** : pas de restriction de date
- **Fenetre absolue** : entre une date de debut et une date de fin
- **Jours relatifs** : dans les N derniers jours

**Contraintes de frequence** (par critere) :
- **Au moins N fois** : le patient doit avoir au moins N occurrences
- **Exactement N fois** : exactement N occurrences
- **Au plus N fois** : pas plus de N occurrences
- **Fenetre glissante** : N occurrences dans les X jours

**Contraintes de valeur** (Measurement uniquement) :
- Operateur : `>`, `<`, `>=`, `<=`, `=`, `entre`
- Valeur numerique et unite

**Criteres d'exclusion** :
- Ajoutez des criteres dans la section exclusion
- Les patients correspondant a ces criteres seront retires du resultat

**Criteres demographiques** :
- **Age** : min et max
- **Genre** : selectionner un ou plusieurs genres
- **Race** et **Ethnicite** : filtres optionnels

#### Etape 3 : Executer

Dans le panneau de droite :

- **Compter** : affiche le nombre de patients correspondants
- **Comptage rapide** : estimation rapide (moins precis mais plus rapide)
- **Attrition** : montre le nombre de patients a chaque etape (critere par critere), pour comprendre l'impact de chaque critere
- **Echantillon** : affiche 10 patients aleatoires avec leur demographie
  - Cliquer sur un `person_id` pour voir le **parcours patient** (timeline de tous les evenements cliniques)

#### Etape 4 : Sauvegarder

1. Donner un **nom** et une **description** a la cohorte
2. Cliquer sur **Sauvegarder**
3. La cohorte apparait dans la liste des cohortes sauvegardees
4. Chaque modification des criteres cree une **nouvelle version**

### Caracterisation (Table 1)

L'onglet **Table 1** genere une caracterisation complete de la cohorte :

1. Definir vos criteres dans le Query Builder
2. Cliquer sur l'onglet **Table 1**
3. Cliquer sur **Generer la caracterisation**
4. Les resultats incluent :
   - **Demographie** : statistiques d'age (moyenne, mediane, ecart-type), repartition par genre, race, ethnicite
   - **Prevalence par domaine** : pourcentage de patients avec des donnees dans chaque domaine + top concepts
   - **Mesures** : statistiques des mesures biologiques (moyenne, mediane, min, max)
   - **Types de visite** : repartition des types de visite (ambulatoire, hospitalisation, urgences...)
   - **Periodes d'observation** : statistiques de duree de suivi

### Comparaison de cohortes

L'onglet **Comparer** permet de comparer deux cohortes sauvegardees :

1. Selectionner la **Cohorte A** et la **Cohorte B**
2. Cliquer sur **Comparer**
3. Les resultats montrent :
   - Comparaison demographique avec **SMD** (Standardized Mean Difference)
   - SMD > 0.1 indique un desequilibre significatif
   - Comparaison de prevalence par domaine
   - Comparaison des mesures biologiques

### Editeur SQL

L'onglet **SQL** permet d'executer des requetes SQL en lecture seule :

1. Saisir votre requete SQL (SELECT, WITH, EXPLAIN uniquement)
2. Appuyer sur **Ctrl+Entree** ou cliquer sur **Executer**
3. Les resultats s'affichent dans un tableau
4. Cliquer sur **Exporter CSV** pour telecharger les resultats

> **Note** : Seules les requetes en lecture sont autorisees. Les INSERT, UPDATE, DELETE sont bloques.

### Exporter

- **Export CSV** : liste des `person_id` avec demographie
- **Export SQL** : requete SQL generee par les criteres
- **Export direct** : export CSV sans sauvegarder la cohorte

---

## 6. Workflow de Mapping

**Acces** : Admin, OMOP DIM, Medecin

Le workflow de mapping guide le processus de correspondance entre les codes source de votre CDM et les concepts standard OMOP.

### Vue d'ensemble

Le processus se deroule en 4 etapes, accessibles via les onglets :

```
Dashboard → Exploration → Suggestions → Historique/Application
```

### Onglet 1 : Dashboard

Vue d'ensemble des taux de mapping :

- **Graphique a barres** : taux de mapping par domaine (termes et lignes)
- **Volume non mappe** : poids en nombre de records des termes non mappes
- **Evolution** : courbe montrant l'amelioration du mapping au fil du temps
- **Performance des strategies** : taux d'approbation/modification/rejet par strategie de suggestion

### Onglet 2 : Exploration des non mappes

1. Selectionner un **domaine** (Condition, Drug, Procedure, etc.)
2. La liste des termes non mappes s'affiche :
   - **Code source** (`source_value`) : le code dans votre systeme
   - **Description** (`source_name`) : le libelle du code (si disponible)
   - **Records** : nombre de lignes concernees
   - **Personnes** : nombre de patients concernes
3. Utiliser la **barre de recherche** pour filtrer
4. **Exporter** la liste complete en CSV

> Les termes sont tries par nombre de records decroissant (les plus impactants en premier).

### Workflow collaboratif

Le mapping dans OPAL est **individuel par utilisateur** : chaque utilisateur travaille independamment sur les suggestions et prend ses propres decisions. Les termes deja approuves par un autre utilisateur restent visibles dans vos suggestions.

Un mapping n'est considere **valide** que lorsqu'il atteint le **consensus** : 2 utilisateurs ou plus ont approuve le meme mapping (meme source_value vers le meme concept cible). Tant qu'un seul utilisateur a approuve, la decision est en statut **pending**.

### Onglet 3 : Suggestions

#### Configurer les strategies

Avant de generer des suggestions, configurez les strategies activees :

- **Fuzzy** : recherche par similarite textuelle (trigrammes)
- **Keyword** : recherche par mots-cles progressifs
- **Contextual** : analyse des patterns existants dans le CDM
- **SapBERT** : suggestions pre-calculees par embeddings semantiques (si chargees)

Definir le **nombre de termes** a traiter par lot (5 a 100).

#### Generer des suggestions

1. Cliquer sur **Generer les suggestions**
2. Seuls les termes que **vous** n'avez pas encore traites apparaissent (les decisions des autres utilisateurs n'impactent pas votre liste)
3. Pour chaque terme non mappe, une carte affiche :
   - Le **code source** et sa description
   - Les **suggestions classees** par confiance decroissante :
     - Confiance en vert (≥80%) : forte probabilite
     - Confiance en orange (50-79%) : a verifier
     - Confiance en rouge (<50%) : faible probabilite
   - La **source** de la suggestion (SapBERT, Exact, Fuzzy, etc.)
   - Le **concept cible** propose (nom, code, vocabulaire)

#### Valider les suggestions

Pour chaque terme, vous pouvez :

- **Approuver** (pouce vert) : accepter la suggestion proposee
- **Modifier** (crayon) : choisir un concept cible different
- **Rejeter** (croix rouge) : marquer comme "pas de mapping applicable" (le terme reapparaitra dans les suggestions)

Vous pouvez aussi ajouter une **raison** pour documenter votre decision.

#### Approbation en lot

Pour accelerer le processus :
- **Approuver tout ≥90%** : approuve automatiquement les suggestions avec une confiance >= 90%
- **Approuver tout ≥80%** : seuil plus bas pour les suggestions ≥ 80%

### Onglet 4 : Historique et Application

#### Vue groupee

L'historique presente les decisions de **tous les utilisateurs**, groupees intelligemment :

- Les lignes sont triees par **source value** (les decisions sur le meme terme se suivent)
- Si 2 utilisateurs approuvent le meme mapping (meme source → meme cible), ils sont **fusionnes sur une seule ligne** avec les deux noms d'utilisateurs et un compteur
- La colonne **Source** affiche le libelle (`source_name`) quand il existe, avec le code en petit

#### Indicateurs de statut

| Icone | Statut | Signification |
|-------|--------|---------------|
| Tick vert | **Consensus** | 2+ utilisateurs ont approuve le meme mapping |
| Triangle jaune | **Conflit** | Des utilisateurs ont mappe le meme terme vers des cibles differentes |
| *(vide)* | **Single** | Un seul utilisateur a pris une decision |

#### Tag d'action

| Tag | Couleur | Signification |
|-----|---------|---------------|
| **pending** | Orange | Approuve par un seul utilisateur, en attente de validation |
| **approved** | Vert | Consensus atteint (2+ utilisateurs) |
| **rejected** | Rouge | Mapping rejete |
| **rolled_back** | Gris | Decision annulee |

#### Actions directes depuis l'historique

Pour chaque ligne, des boutons d'action sont disponibles selon votre relation avec la decision :

- **Tick vert** (Approuver) : approuver ce mapping pour vous — visible si vous n'avez pas encore vote sur cette ligne et qu'un concept cible existe
- **Croix rouge** (Rejeter) : rejeter ce mapping en place (passe la decision en "rejected") — visible si c'est votre decision ou si vous etes admin
- **Fleche retour** (Retirer) : retirer silencieusement votre decision (pas de trace) — visible si c'est votre decision

> **Astuce** : pour resoudre un conflit (triangle jaune), approuvez la bonne ligne et rejetez l'autre directement depuis l'historique.

#### Filtres

- **Domaine** : filtrer par domaine clinique
- **Action** : filtrer par type de decision (approved, rejected, etc.)
- **Utilisateur** : filtrer par utilisateur (liste dynamique)

#### Appliquer les mappings

Seuls les mappings ayant atteint le **consensus** (2+ utilisateurs d'accord) sont inclus dans l'application et l'export :

1. Selectionner un **domaine**
2. Cliquer sur **Preview** pour voir l'impact :
   - Nombre total de decisions consensus
   - Nombre de lignes impactees
   - Nombre de personnes impactees
3. **Exporter STCM CSV** (recommande) : telecharge un fichier CSV au format `source_to_concept_map` contenant uniquement les mappings consensus

> **Note** : Les decisions en statut "pending" (un seul utilisateur) ne sont pas incluses dans l'export. Demandez a un collegue de valider vos mappings pour qu'ils atteignent le consensus.

### Chargement des donnees de reference

#### Codebooks de reference

Les codebooks enrichissent les descriptions des codes source pour ameliorer les suggestions :

- Upload via l'API : `POST /api/mapping/reference/upload`
- Format : CSV avec colonnes code et description
- Exemples : CCAM (actes medicaux), CIM-10 (diagnostics)

#### Mappings SapBERT

Les mappings SapBERT fournissent des suggestions instantanees basees sur des embeddings semantiques :

- Generes par le script `scripts/sapbert_mapping.py`
- Upload via l'API : `POST /api/mapping/sapbert/upload`
- Format : CSV avec source_code, target_concept_id, similarity, etc.

---

## 7. Explorateur de Concepts

**Acces** : Admin, OMOP DIM, Chercheur, Medecin

L'explorateur permet de naviguer dans le vocabulaire OMOP et de comprendre les correspondances entre codes source et concepts standard.

### Recherche par concept

1. Selectionner l'onglet **Par concept**
2. Saisir un terme de recherche (nom, code ou ID numerique)
3. Utiliser les filtres optionnels :
   - **Domaine** : Condition, Drug, Procedure, etc.
   - **Vocabulaire** : SNOMED, ICD10, ATC, etc.
   - **Standard uniquement** : n'afficher que les concepts standard
4. Les resultats s'affichent dans un tableau :
   - ID, Nom, Code, Domaine, Vocabulaire, Classe, Flag standard
   - Nombre de records et de personnes (charge a la demande)

### Recherche par code source

1. Selectionner l'onglet **Par code source**
2. Saisir un code source ou un libelle (ex: `HYDROXYZINE`, `E11.9`)
3. Filtrer par domaine si necessaire
4. Les resultats montrent :
   - Domaine, code source, description
   - Concept mappe (si existant) avec lien
   - Nombre de records et personnes

### Detail d'un concept

Cliquer sur un concept pour afficher le panneau de detail :

#### Onglet Info
- **Metadonnees** : ID, nom, code, domaine, vocabulaire, classe, dates de validite
- **Synonymes** : noms alternatifs du concept

#### Onglet Relations
- **Concepts lies** : tous les concepts en relation (Maps to, Is a, Has finding site, etc.)
- Type de relation, concept lie, vocabulaire

#### Onglet Hierarchie
- **Ancetres** : concepts parents dans la hierarchie (avec niveaux de separation)
- **Descendants** : concepts enfants (avec niveaux de separation)
- Permet de comprendre la position d'un concept dans la taxonomie OMOP

#### Onglet Codes source
- **Codes source mappes** : tous les codes source dans vos tables cliniques qui pointent vers ce concept
- Nombre de records et personnes par code source
- Utile pour comprendre quels codes locaux correspondent a un concept standard

---

## 8. Outils OHDSI

**Acces** : Admin, OMOP DIM

Cette page permet de lancer des outils de l'ecosysteme OHDSI directement depuis OPAL.

### Services disponibles

| Service | Description | Duree typique |
|---------|-------------|---------------|
| **Achilles** | Caracterisation complete du CDM | 10-60 min |
| **Achilles Export** | Export des resultats Achilles | 5-15 min |
| **DQD** | Data Quality Dashboard | 15-45 min |
| **CDM Onboarding** | Rapport d'embarquement | 5-20 min |

### Utilisation

1. Configurer les parametres (panneau gauche) :
   - **Schema resultats** : schema pour stocker les resultats (ex: `omop_cdm`)
   - **Schema vocabulaire** : schema contenant les tables vocabulaire
   - **Version CDM** : version du modele (ex: `5.4`)
   - **Nom source** : nom descriptif du CDM
2. Cliquer sur **Lancer** pour le service souhaite
3. Le statut passe de "Inactif" a "En cours" (tag orange)
4. Les **logs s'affichent en temps reel** dans le terminal en bas de page
5. A la fin, le statut passe a "Termine" (vert) ou "Erreur" (rouge)
6. Consulter les fichiers de sortie dans le **navigateur de fichiers**

### Navigateur de fichiers

- Naviguez dans les dossiers de sortie via les breadcrumbs
- Cliquez sur un fichier pour le telecharger
- La taille du fichier est affichee

---

## 9. Parametres

**Acces** : Admin, OMOP DIM

Configurez les parametres d'analyse pour chaque CDM.

### Parametres disponibles

| Parametre | Defaut | Plage | Description |
|-----------|--------|-------|-------------|
| **Schema OMOP** | `omop_cdm` | texte | Nom du schema PostgreSQL contenant les tables OMOP |
| **Top termes non mappes** | 50 | 1-500 | Nombre de termes non mappes affiches dans les analyses |
| **Top concepts** | 50 | 1-500 | Nombre de top concepts affiches dans les analyses |
| **Max records/personne** | 100 | 10-1000 | Seuil pour la distribution records par personne |
| **Max mois observation** | 120 | 12-600 | Cap pour l'histogramme de duree d'observation |
| **Seuil alerte comparaison** | 5.0% | 0.1-50 | Pourcentage d'ecart declenchant une alerte |

### Modifier les parametres

1. Selectionner le CDM concerne dans le selecteur
2. Modifier les valeurs souhaitees
3. Cliquer sur **Sauvegarder**

---

## 10. Audit et Administration

### Journal d'audit

**Acces** : Admin

Le journal d'audit trace toutes les actions effectuees dans OPAL.

#### Consulter les logs

1. Acceder a la page **Audit**
2. Les statistiques du jour s'affichent en haut :
   - Total des evenements
   - Nombre d'utilisateurs actifs
   - Repartition par type d'action
3. Utiliser les filtres :
   - **Plage de dates** : selectionner une periode
   - **Utilisateur** : filtrer par nom d'utilisateur
   - **Action** : filtrer par type (quality, cohort, mapping, cdm, concept, ohdsi)
4. Le tableau affiche : heure, utilisateur, action, methode HTTP, chemin, statut, duree, IP
5. Les codes de statut sont colores : vert (2xx), bleu (3xx), orange (4xx), rouge (5xx)
6. **Exporter** les logs en CSV

### Gestion des utilisateurs

**Acces** : Admin

#### Onglet Utilisateurs

- Liste de tous les utilisateurs Keycloak
- Pour chaque utilisateur :
  - **Roles** : affiches comme des tags colores
  - **Ajouter un role** : selectionner dans le dropdown et cliquer sur ajouter
  - **Retirer un role** : cliquer sur la croix du tag
  - **Activer/Desactiver** : basculer le switch
- Cliquer sur un nom d'utilisateur pour voir le detail (ID, email, date de creation)

#### Onglet Demandes d'acces

- Badge indiquant le nombre de demandes en attente
- Pour chaque demande :
  - Nom d'utilisateur, nom complet, email, role demande
  - **Approuver** : cree automatiquement le compte Keycloak
    - Un mot de passe temporaire est genere et affiche (a copier et communiquer)
    - L'utilisateur devra le changer a sa premiere connexion
  - **Rejeter** : supprime la demande

---

## 11. FAQ et Depannage

### Questions frequentes

**Q : Pourquoi je ne vois pas certaines pages dans le menu ?**
R : Votre role ne vous donne pas acces a ces fonctionnalites. Contactez un administrateur pour modifier vos permissions.

**Q : Comment changer la langue ?**
R : Cliquez sur le bouton FR/EN dans la barre de navigation supérieure (TopNav). Le choix est retenu entre les sessions.

**Q : Les analyses sont lentes, que faire ?**
R : La duree depend de la taille de votre CDM. Pour les gros CDM (>1M patients), certaines analyses peuvent prendre plusieurs minutes. Utilisez l'analyse par lot pour lancer tous les domaines en une fois.

**Q : Puis-je utiliser OPAL avec un CDM non-PostgreSQL ?**
R : Non, OPAL ne supporte que les CDM PostgreSQL. Le connecteur utilise `psycopg2` qui est specifique a PostgreSQL.

**Q : L'ecriture dans le CDM est-elle risquee ?**
R : L'ecriture est limitee a la table `source_to_concept_map` et utilise un UPSERT transactionnel. En cas d'erreur, un rollback automatique annule toutes les modifications. Il est neanmoins recommande d'utiliser l'export STCM CSV et de l'appliquer via votre propre processus ETL.

**Q : Comment sauvegarder mes donnees ?**
R : Les donnees OPAL sont dans la base PostgreSQL `opal-db`. Utilisez `pg_dump` pour les sauvegardes. N'oubliez pas de sauvegarder aussi le fichier `.secret_key` (necessaire pour dechiffrer les mots de passe CDM).

### Depannage

**Probleme : "CDM connection failed" (502)**
- Verifiez que le serveur PostgreSQL du CDM est accessible
- Verifiez les identifiants de connexion
- Verifiez que le port est ouvert dans le pare-feu
- Utilisez le bouton "Tester" dans la page Gestion des CDM

**Probleme : "Missing or invalid Authorization header" (401)**
- Votre session a expire, rechargez la page
- Si le probleme persiste, deconnectez-vous et reconnectez-vous

**Probleme : "Forbidden: insufficient permissions" (403)**
- Votre role ne permet pas cette action
- Contactez un administrateur pour obtenir les permissions necessaires

**Probleme : L'analyse batch reste bloquee**
- Verifiez la connexion au CDM
- Essayez une analyse sur un seul domaine pour isoler le probleme
- Consultez les logs du backend (`docker compose logs opal-backend`)

**Probleme : Les suggestions de mapping sont vides**
- Verifiez que l'extension `pg_trgm` est installee sur le CDM (requise pour la recherche fuzzy)
- Chargez des codebooks de reference pour enrichir les descriptions
- Chargez des mappings SapBERT pour des suggestions instantanees

**Probleme : Le parcours patient ne s'affiche pas**
- Verifiez que le `person_id` existe dans le CDM
- Le patient doit avoir des evenements cliniques dans au moins un domaine

### Support

Pour obtenir de l'aide :
- Consultez la [documentation API](API.md) pour les details techniques
- Consultez la [documentation technique](TECHNICAL.md) pour l'architecture
- Contactez l'equipe OPAL de l'AP-HM

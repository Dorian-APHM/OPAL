# Politique de sécurité

## Versions supportées

Les versions ci-dessous bénéficient des correctifs de sécurité. Les versions
plus anciennes ne reçoivent plus de mises à jour — merci de migrer.

| Version | Supportée         |
| ------- | ----------------- |
| 3.x     | :white_check_mark:|
| < 3.0   | :x:               |

## Signaler une vulnérabilité

Si vous découvrez une faille de sécurité dans OPAL, **merci de ne pas
l'ouvrir comme issue publique**. Cela exposerait les déploiements existants
le temps qu'un correctif soit disponible.

Utilisez le canal privé GitHub Security Advisories :

👉 **https://github.com/Dorian-APHM/OPAL/security/advisories/new**

Décrivez :

- Le composant concerné (module, endpoint, fichier)
- Les étapes de reproduction
- L'impact estimé (lecture de données, escalade de privilèges, déni de service…)
- Une suggestion de correctif si vous en avez une

## Délais de réponse

| Étape                       | Délai indicatif |
| --------------------------- | --------------- |
| Accusé de réception         | 48 h            |
| Évaluation initiale         | 7 jours         |
| Correctif et publication    | selon sévérité  |

Les vulnérabilités critiques (RCE, fuite massive de données, contournement
d'authentification) sont traitées en priorité.

## Périmètre

### Dans le périmètre

- Authentification et autorisation (Keycloak, JWT, ACL CDM, RBAC)
- Injection SQL, injection de commande, path traversal
- Escalade de privilèges entre rôles (`chercheur`, `medecin`, `data-manager`, `admin`)
- Fuite de données : CDM externe, base applicative, logs, notifications
- XSS, CSRF, désérialisation non sécurisée
- Failles dans le pipeline d'extraction et d'export
- Failles dans les conteneurs OHDSI lancés par OPAL

### Hors périmètre

- DoS / DDoS volumétriques (un rate-limiting applicatif est en place ;
  les attaques réseau relèvent de l'infrastructure d'hébergement)
- Vulnérabilités nécessitant un accès physique au serveur
- Vulnérabilités dans les dépendances déjà signalées par Dependabot
- Configurations utilisateur incorrectes (mot de passe Keycloak faible,
  variables d'environnement laissées à leur valeur d'exemple, etc.)
- Comportements documentés comme intentionnels dans `CLAUDE.md` ou la
  documentation

## Bonnes pratiques pour les déploiements

- Toujours déployer avec `AUTH_ENABLED=true` (valeur par défaut)
- Générer `SECRET_KEY` avec `openssl rand -hex 32` (jamais réutiliser
  une valeur d'exemple)
- Changer le mot de passe Keycloak admin au premier login (la valeur
  importée est `temporary: true`)
- Limiter l'exposition réseau du port Keycloak (par défaut `127.0.0.1:8080`)
- Activer HTTPS via un reverse-proxy devant `opal-frontend` et `opal-keycloak`
- Maintenir Postgres, Keycloak et les images Docker à jour

## Reconnaissance

Les chercheurs en sécurité qui signalent de manière responsable seront
crédités dans le `CHANGELOG.md` au moment de la publication du correctif,
sauf demande contraire.

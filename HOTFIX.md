# OPAL — Guide Hotfix

Procédure pour appliquer des corrections rapides sans reconstruire les images Docker.

## Prérequis

| Outil | Version | Usage |
|-------|---------|-------|
| Docker + Docker Compose | 20+ / v2+ | Containers OPAL en cours d'exécution |
| Node.js | 18+ | Build frontend (`npm run build`) |
| npm | 9+ | Installé avec Node.js |

> **Backend** : aucune dépendance locale (tout est dans le container).
> **Frontend** : Node.js requis pour compiler le TypeScript/React.

### Installer Node.js (si absent)

```bash
# Ubuntu/Debian
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo bash -
sudo apt install -y nodejs

# Vérifier
node --version   # v18.x+
npm --version    # 9.x+
```

### Installer les dépendances frontend (première fois uniquement)

```bash
cd frontend
npm install
```

## Structure du projet

```
opal/
├── backend/          ← Code Python (FastAPI)
│   ├── main.py
│   ├── config.py
│   ├── db/
│   └── modules/      ← Routers par fonctionnalité
├── frontend/         ← Code React/TypeScript
│   ├── src/
│   └── dist/         ← Généré par npm run build
├── docker-compose.yml
└── HOTFIX.md         ← Ce fichier
```

## Hotfix Backend

Le backend est du Python interprété — on copie le fichier modifié dans le container et on redémarre.

```bash
# 1. Copier le(s) fichier(s) modifié(s)
docker cp backend/modules/mon_module/router.py opal-backend:/app/modules/mon_module/router.py

# 2. Redémarrer le backend (uvicorn recharge le code)
docker compose restart opal-backend
```

**Exemples courants :**
```bash
# Un seul fichier
docker cp backend/modules/ohdsi/router.py opal-backend:/app/modules/ohdsi/router.py
docker compose restart opal-backend

# Plusieurs fichiers
docker cp backend/modules/concept/router.py opal-backend:/app/modules/concept/router.py
docker cp backend/main.py opal-backend:/app/main.py
docker compose restart opal-backend
```

**Vérifier :**
```bash
docker logs opal-backend --tail 20    # Pas d'erreur d'import
docker compose ps                      # Status: healthy
```

## Hotfix Frontend

Le frontend est compilé (React → fichiers statiques) puis copié dans le container Nginx.

```bash
# 1. Builder le frontend (~6 secondes)
cd frontend
npm run build

# 2. Copier les fichiers compilés dans le container Nginx
docker cp dist/. opal-frontend:/usr/share/nginx/html/

# 3. Hard refresh dans le navigateur (Ctrl+Shift+R)
```

> Pas besoin de redémarrer le container Nginx.

## Hotfix combiné (Backend + Frontend)

```bash
# Backend
docker cp backend/modules/ohdsi/router.py opal-backend:/app/modules/ohdsi/router.py
docker compose restart opal-backend

# Frontend
cd frontend && npm run build && cd ..
docker cp frontend/dist/. opal-frontend:/usr/share/nginx/html/
```

## Rebuild complet (si hotfix insuffisant)

Si le hotfix ne suffit pas (nouveau package pip/npm, modification du Dockerfile) :

```bash
# Avec proxy (ex: corporate-proxy sur port 3128)
docker compose build \
  --build-arg HTTP_PROXY=http://localhost:3128 \
  --build-arg HTTPS_PROXY=http://localhost:3128 \
  opal-frontend opal-backend

# Sans proxy
docker compose build opal-frontend opal-backend

# Relancer
export POSTGRES_PASSWORD=opal SECRET_KEY=$(openssl rand -hex 32)
docker compose up -d
```

## Troubleshooting

| Problème | Solution |
|----------|----------|
| `ImportError` après hotfix backend | Vérifier le chemin du `docker cp` (doit correspondre à `/app/...`) |
| Frontend inchangé après hotfix | Hard refresh `Ctrl+Shift+R` (cache navigateur) |
| `npm run build` échoue | `cd frontend && npm install` puis réessayer |
| Container unhealthy après restart | `docker logs opal-backend --tail 50` pour voir l'erreur |

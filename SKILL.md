---
name: agentic-microservice-deployer
description: >
  Despliega un flujo agéntico como microservicio FastAPI interno en Coolify, accesible solo desde n8n
  via red interna Docker (sin URL pública). Crea automáticamente el repo privado en GitHub,
  sube el código, crea la aplicación en Coolify y verifica que el healthcheck esté activo.
  Usa este skill siempre que el usuario quiera "desplegar", "subir a producción", "publicar el agente",
  "hacer que n8n llame al microservicio", "crear el repo", o cualquier variación de convertir
  código local en un servicio corriendo. También aplica cuando el usuario dice cosas como
  "ya terminé el agente, ahora qué" o "cómo lo integro con n8n".
---

# Agentic Microservice Deployer

Convierte código local de automatización en un microservicio interno seguro, desplegado en Coolify
y accesible exclusivamente desde n8n vía red Docker interna. Sin URLs públicas. Sin fricción.

---

## Mapa de lo que es manual vs automático

| Paso | Quién | Frecuencia |
|---|---|---|
| Crear GitHub App en Coolify UI | 👤 Usuario | **1 vez por VPS** |
| Todo lo demás | 🤖 Agente | Cada proyecto |

**El único paso manual requiere browser** porque GitHub necesita que el usuario haga click "Install"
(OAuth handshake de seguridad intencional de GitHub). No hay API que lo reemplace.

---

## Prerequisitos — Verificar antes de empezar

### Variables de entorno (en `.env`):

```
GITHUB_TOKEN=         # PAT con scope 'repo' — crear repos privados + vincular GitHub Apps
COOLIFY_URL=          # ej: https://panel-coolify.tudominio.com
COOLIFY_TOKEN=        # API token de Coolify (Settings > API Keys)
COOLIFY_PROJECT_UUID= # UUID del proyecto Coolify donde desplegar
```

Si alguna falta, pídela al usuario antes de continuar.

### GitHub App en Coolify (1 vez por VPS):

Si el usuario nunca configuró esto en su Coolify, explícale:

> **¿Por qué es manual?** GitHub requiere que el usuario haga click "Install" en el navegador
> (OAuth handshake). Solo se hace **una sola vez por VPS/cliente**. Después el agente
> gestiona acceso a todos los repos futuros sin intervención del usuario.

**Instrucciones para el usuario (5 min):**

---
> 1. Panel de Coolify → menú lateral **"Sources"**
> 2. Click **"Add"** → **"GitHub App"**
> 3. **Name**: nombre descriptivo (ej: `coolify-tudominio`)
> 4. **Organization**: dejarlo vacío
> 5. **System Wide**: NO marcar
> 6. **Webhook Endpoint**: seleccionar el dominio HTTPS de Coolify
> 7. Click **"Register Now"** → GitHub abre pantalla de instalación
> 8. En GitHub: seleccionar **"All repositories"** ← crítico para que el agente gestione accesos futuros
> 9. Click **"Install"** → regresa a Coolify automáticamente
>
> ✅ Con esto listo, el agente gestiona todos los repos futuros de forma autónoma.
---

Una vez confirmado, continúa con el Paso 1.

---

## Paso 1: Preparar la estructura del repo

El repo de producción solo incluye lo que necesita el contenedor.

**Estructura mínima requerida:**

```
nombre-del-servicio/
├── main.py               # FastAPI con X-API-Key y GET /health
├── execution/            # scripts usados en runtime
├── directives/
│   └── README.md         # qué hace el servicio, endpoints, variables
├── Dockerfile
├── requirements.txt
├── .env.example
└── .gitignore
```

**`.gitignore` obligatorio:**
```gitignore
.env
.env.*
!.env.example
*.json
!package.json
__pycache__/
*.pyc
.tmp/
credentials.json
token.json
```

**`Dockerfile` estándar:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**`main.py` mínimo con autenticación:**
```python
from fastapi import FastAPI, HTTPException, Security
from fastapi.security import APIKeyHeader
import os

app = FastAPI()
API_KEY = os.getenv("SERVICE_API_KEY", "")
api_key_header = APIKeyHeader(name="X-API-Key")

async def verify_key(key: str = Security(api_key_header)):
    if key != API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")
    return key

@app.get("/health")
def health():
    return {"status": "ok"}

# Endpoints del negocio — siempre con dependencies=[Depends(verify_key)]
```

---

## Paso 2: Crear repo en GitHub y vincular GitHub App

Usa `execution/github_manager.py`:

```python
import sys, os, requests
sys.path.insert(0, 'execution')
from github_manager import create_private_repo, grant_github_app_access, initialize_and_push
from dotenv import load_dotenv
load_dotenv()

REPO_NAME   = "nombre-del-servicio"
DESCRIPTION = "Microservicio: descripción breve"

# 2a. Crear repo privado
result = create_private_repo(REPO_NAME, DESCRIPTION)
if not result:
    raise Exception("Fallo la creacion del repo")
owner, repo_name, repo_id = result

# 2b. Vincular al GitHub App de Coolify (automatiza el paso de "dar acceso al repo")
COOLIFY_URL   = os.getenv("COOLIFY_URL")
COOLIFY_TOKEN = os.getenv("COOLIFY_TOKEN")
coolify_h = {"Authorization": f"Bearer {COOLIFY_TOKEN}", "Accept": "application/json"}
github_apps = requests.get(f"{COOLIFY_URL}/api/v1/github-apps", headers=coolify_h).json()
private_apps = [a for a in github_apps if not a.get("is_public")]
installation_id = private_apps[0]["installation_id"]
grant_github_app_access(repo_id, installation_id)

# 2c. Subir el código
initialize_and_push(repo_name, owner)
```

---

## Paso 3: Crear y configurar app en Coolify

> ⚠️ Son 3 sub-pasos obligatorios. Si omites el 3b, el servicio queda expuesto públicamente
> y n8n no puede alcanzarlo por nombre de red.

### 3a. Crear la app

```python
import sys
sys.path.insert(0, 'execution')
from coolify_manager import CoolifyManager

manager = CoolifyManager()
ALIAS = repo_name   # nombre DNS interno — n8n usará: http://ALIAS:8000

# Endpoint correcto: /api/v1/applications/private-github-app
# (NO /api/v1/applications — ese da 404 para repos privados)
app = manager.create_application(repo_name, f"{owner}/{repo_name}")
APP_UUID = app["uuid"]
print(f"App creada: {APP_UUID}")
```

### 3b. Configurar red interna — CRÍTICO, no omitir

Coolify asigna FQDN público automáticamente. Este paso lo configura como servicio interno:

```python
manager.configure_application(APP_UUID, ALIAS)
# Confirma: alias de red configurado, FQDN eliminado, healthcheck activo
```

> **Importante:** Si `configure_application` no logra eliminar el FQDN via API
> (algunas versiones de Coolify no lo permiten), indica al usuario que lo elimine
> manualmente: panel → app → Settings → FQDN → borrar → Save.
> El servicio **siempre** es accesible internamente aunque tenga FQDN público,
> pero por seguridad debe eliminarse.

### 3c. ¿Quiere el usuario autenticación con API key?

Antes de configurar las variables, **pregunta al usuario**:

> El servicio es interno (solo accesible desde n8n por red Docker).
> La red ya lo protege — la API key es una capa adicional opcional.
>
> **¿Quieres agregar autenticación con X-API-Key?**
> - **Sí** → más seguro ante misconfiguraciones futuras o compromisos laterales
> - **No** → más simple, n8n llama sin headers extra

**Si el usuario dice SÍ — con API key:**

```python
import requests, os, secrets
from dotenv import load_dotenv
load_dotenv()

SERVICE_API_KEY = secrets.token_hex(32)  # NUNCA usar strings hardcodeados
print(f"SERVICE_API_KEY: {SERVICE_API_KEY}")
print("(Guarda este valor — lo usarás en n8n como header X-API-Key)")

COOLIFY_URL = os.getenv("COOLIFY_URL")
headers = {"Authorization": f"Bearer {os.getenv('COOLIFY_TOKEN')}", "Content-Type": "application/json"}

env_vars = [
    {"key": "SERVICE_API_KEY", "value": SERVICE_API_KEY},
    # Otras vars del servicio:
    # {"key": "OPENAI_API_KEY", "value": "sk-..."},
]
for var in env_vars:
    requests.post(f"{COOLIFY_URL}/api/v1/applications/{APP_UUID}/envs",
                  headers=headers, json={**var, "is_preview": False})
print("Variables configuradas")
```

Asegúrate de que `main.py` tiene el middleware de autenticación activo (ver Paso 1).

**Si el usuario dice NO — sin API key:**

```python
# Solo configurar las vars de negocio (sin SERVICE_API_KEY)
env_vars = [
    # {"key": "OPENAI_API_KEY", "value": "sk-..."},
]
for var in env_vars:
    requests.post(f"{COOLIFY_URL}/api/v1/applications/{APP_UUID}/envs",
                  headers=headers, json={**var, "is_preview": False})
```

En `main.py`, simplificar los endpoints eliminando el `Security(api_key_header)`:
```python
@app.post("/mi-endpoint")
def mi_endpoint(data: dict):  # sin dependencies=[Depends(verify_key)]
    ...
```

### 3d. Deploy

```python
result = manager.deploy_application(APP_UUID)
deployment_uuid = result["deployments"][0]["deployment_uuid"]
print(f"Deploy iniciado: {deployment_uuid}")
```

---

## Paso 4: Monitorear el deploy

```python
import time, json, requests, os
from dotenv import load_dotenv
load_dotenv()

headers = {"Authorization": f"Bearer {os.getenv('COOLIFY_TOKEN')}", "Accept": "application/json"}
time.sleep(90)

r = requests.get(f"{os.getenv('COOLIFY_URL')}/api/v1/deployments/{deployment_uuid}", headers=headers)
data = r.json()
status = data.get("status")
logs = json.loads(data.get("logs", "[]"))

print(f"Status: {status}")
for log in logs:
    if not log.get("hidden"):
        output = log.get("output", "")[:200]
        if output.strip():
            print(f"  [{log.get('type','').upper()}] {output}")
```

**Indicadores de éxito:**
- `status: finished`
- Log: `Healthcheck status: "healthy"`
- Log: `Rolling update completed`

---

## Paso 5: Verificar y entregar al usuario

```python
app = requests.get(
    f"{os.getenv('COOLIFY_URL')}/api/v1/applications/{APP_UUID}",
    headers=headers
).json()

print(f"Status:  {app.get('status')}")
print(f"Alias:   {app.get('custom_network_aliases')}")
print(f"FQDN:    {app.get('fqdn') or 'NINGUNO (correcto)'}")

# Entregar al usuario
print(f"""
=== Microservicio listo ===
URL interna (desde n8n): http://{ALIAS}:8000
Header de autenticacion: X-API-Key: {SERVICE_API_KEY}

Para probar desde n8n, crea un nodo HTTP Request:
  Method: POST (o el que corresponda)
  URL: http://{ALIAS}:8000/[tu-endpoint]
  Headers: X-API-Key = {SERVICE_API_KEY}
""")
```

---

## Paso 6: Probar el microservicio desde n8n

Para verificar que n8n puede alcanzar el servicio, crea un workflow de prueba.

> Si tienes el skill de n8n instalado (`npx skills add czlonkowski/n8n-skills`), úsalo
> para crear el workflow de test. Si no, sigue estos pasos manuales:

**Workflow de test mínimo en n8n:**

1. **Nodo Manual Trigger**
2. **Nodo HTTP Request:**
   - Method: `GET`
   - URL: `http://[ALIAS]:8000/health`
   - Headers: `X-API-Key: [SERVICE_API_KEY]`
3. Ejecutar — debe retornar `{"status": "ok"}`

Si el healthcheck responde 200, el microservicio está integrado correctamente con n8n.

> **Si n8n no puede alcanzar el servicio:**
> Verificar que n8n fue instalado como servicio dentro del mismo Coolify
> (comparte la red Docker `coolify`). Si n8n está en otro servidor, la red interna no aplica.

---

## Seguridad: Reglas del estándar

| Regla | Descripción |
|---|---|
| 🔒 **Repo privado SIEMPRE** | Nunca código de cliente en repo público |
| 🚫 **Sin FQDN** | Servicio solo en red interna de Coolify |
| 🔑 **SERVICE_API_KEY con `secrets.token_hex(32)`** | Nunca strings hardcodeados como "secret-key-2024" |
| 📁 **.env solo en local** | Coolify inyecta vars via API |
| 🏷️ **Alias descriptivo** | `cliente-servicio` ej: `acme-yt-optimizer` |

---

## Troubleshooting

**"No hay GitHub Apps privadas conectadas"**
→ El usuario no ha creado la GitHub App todavía. Ver sección de Prerequisitos.

**`grant_github_app_access` da 404**
→ El `installation_id` no tiene permisos "All repositories". El usuario debe ir a
  GitHub → Settings → Applications → [tu GitHub App] → Repository access → All repositories.

**`create_application` da 422 / validation error**
→ `git_repository` debe ser exactamente `owner/repo` (sin `git@`, sin `.git`, sin `https://`).

**`custom_network_aliases` no se aplica / n8n no alcanza el servicio**
→ La API de Coolify rechaza si mandas varios campos juntos en un solo PATCH.
→ La solución es enviar **un PATCH separado por campo**:
```python
base = f"{COOLIFY_URL}/api/v1/applications/{APP_UUID}"
# Cada campo en su propio request
requests.patch(base, headers=headers, json={"custom_network_aliases": ALIAS})
requests.patch(base, headers=headers, json={"domains": ""})
requests.patch(base, headers=headers, json={"dockerfile_location": "/Dockerfile"})
```

**FQDN público no desaparece / `"This field is not allowed"` al usar `fqdn`**
→ El campo correcto para eliminar la URL pública es `domains` (no `fqdn`).
→ Usar: `requests.patch(base, headers=headers, json={"domains": ""})`
→ Después redeploy para que Traefik actualice la configuración.

**`SERVICE_API_KEY` hardcodeada (ej: `algo-secret-key-2024`)**
→ Las variables duplicadas no se pueden actualizar con PATCH individual (da 404).
→ Solución: DELETE del env antiguo + POST del nuevo:
```python
# Eliminar duplicados
envs = requests.get(f"{COOLIFY_URL}/api/v1/applications/{APP_UUID}/envs", headers=headers).json()
for e in [x for x in envs if x["key"] == "SERVICE_API_KEY"]:
    requests.delete(f"{COOLIFY_URL}/api/v1/applications/{APP_UUID}/envs/{e['uuid']}", headers=headers)
# Crear nueva con valor seguro
import secrets
new_key = secrets.token_hex(32)
requests.post(f"{COOLIFY_URL}/api/v1/applications/{APP_UUID}/envs",
              headers=headers, json={"key": "SERVICE_API_KEY", "value": new_key})
print(f"Nueva key: {new_key}")  # Guardar para usar en n8n
```

**Healthcheck falla / `running:unknown`**
→ `main.py` debe tener `GET /health` retornando 200.
→ `dockerfile_location` debe estar configurado (`/Dockerfile`).
→ Usar `configure_application()` que setea estos valores automáticamente.

**n8n no puede alcanzar el servicio**
→ n8n debe estar instalado en el mismo Coolify (misma red Docker `coolify`).
→ Usar `http://alias:8000` — nunca `localhost` ni la IP del servidor.
→ Si n8n está en otro servidor, se necesita exponer el servicio (con FQDN + auth robusta).

import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

class CoolifyManager:
    def __init__(self):
        self.url = os.getenv("COOLIFY_URL").rstrip('/')
        self.token = os.getenv("COOLIFY_TOKEN")
        self.project_uuid = os.getenv("COOLIFY_PROJECT_UUID")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def list_applications(self):
        """Lista las aplicaciones registradas en Coolify."""
        endpoint = f"{self.url}/api/v1/applications"
        try:
            response = requests.get(endpoint, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"❌ Error al listar aplicaciones: {e}")
            return []

    def list_servers(self):
        """Lista los servidores registrados."""
        endpoint = f"{self.url}/api/v1/servers"
        try:
            response = requests.get(endpoint, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"❌ Error al listar servidores: {e}")
            return []

    def list_destinations(self):
        """Lista los destinos (redes Docker) disponibles."""
        endpoint = f"{self.url}/api/v1/destinations"
        try:
            response = requests.get(endpoint, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"❌ Error al listar destinos: {e}")
            return []

    def create_application(self, name, git_repo, project_uuid=None, ports="8000"):
        """
        Crea una nueva aplicacion en Coolify desde un repo privado de GitHub.

        Usa el endpoint correcto: /api/v1/applications/private-github-app
        (NO /api/v1/applications — ese endpoint da 404 para repos privados).

        Auto-detecta el server_uuid y el github_app_uuid (primera GitHub App privada).
        git_repo debe tener formato "owner/repo" (sin git@ ni .git).

        IMPORTANTE: Despues de crear, SIEMPRE llama a configure_application()
        para setear el network alias y quitar el FQDN publico que Coolify asigna automaticamente.
        """
        # Auto-detectar server_uuid
        servers = self.list_servers()
        if not servers:
            print("❌ No se encontraron servidores en Coolify.")
            return None
        server_uuid = servers[0]["uuid"]

        # Auto-detectar github_app_uuid (primera app privada conectada)
        github_apps_resp = requests.get(f"{self.url}/api/v1/github-apps", headers=self.headers)
        github_apps = github_apps_resp.json() if github_apps_resp.ok else []
        private_apps = [a for a in github_apps if not a.get("is_public")]
        if not private_apps:
            print("❌ No hay GitHub Apps privadas conectadas a Coolify.")
            print("   Ve a Coolify → Sources → Add → GitHub App y conecta tu cuenta.")
            return None
        github_app_uuid = private_apps[0]["uuid"]

        endpoint = f"{self.url}/api/v1/applications/private-github-app"
        data = {
            "name": name,
            "project_uuid": project_uuid or self.project_uuid,
            "environment_name": "production",
            "server_uuid": server_uuid,
            "github_app_uuid": github_app_uuid,
            "git_repository": git_repo,
            "git_branch": "main",
            "build_pack": "dockerfile",
            "ports_exposes": ports,
        }
        try:
            response = requests.post(endpoint, headers=self.headers, json=data, timeout=15)
            response.raise_for_status()
            result = response.json()
            app_uuid = result.get("uuid")
            print(f"✅ Aplicacion '{name}' creada. UUID: {app_uuid}")
            print(f"⚠️  Llama a configure_application('{app_uuid}', 'network-alias') antes del deploy")
            return result
        except Exception as e:
            print(f"❌ Error al crear aplicacion: {e}")
            return None

    def configure_application(self, app_uuid, network_alias, healthcheck_path="/health"):
        """
        PASO CRITICO post-creacion.

        Coolify asigna automaticamente una URL publica al crear la app.
        Este metodo:
          1. Elimina la URL publica (campo 'domains', no 'fqdn')
          2. Asigna el network alias DNS interno para que n8n llame por nombre
          3. Configura el dockerfile_location si no esta definido

        NOTA: La API de Coolify es estricta — algunos campos solo se pueden
        actualizar individualmente, no en el mismo PATCH.

        Args:
            app_uuid:         UUID de la app (retornado por create_application)
            network_alias:    Nombre DNS interno, ej: "mi-servicio"
                              n8n llamara a http://mi-servicio:8000/endpoint
            healthcheck_path: Endpoint de salud, por defecto "/health"
        """
        base = f"{self.url}/api/v1/applications/{app_uuid}"
        results = {}

        # 1. Network alias (campo valido en PATCH)
        r1 = requests.patch(base, headers=self.headers,
                            json={"custom_network_aliases": network_alias})
        results["alias"] = r1.status_code

        # 2. Eliminar URL publica — el campo correcto es 'domains' (no 'fqdn')
        r2 = requests.patch(base, headers=self.headers, json={"domains": ""})
        results["domains"] = r2.status_code

        # 3. Asegurar que dockerfile_location esta configurado
        r3 = requests.patch(base, headers=self.headers,
                            json={"dockerfile_location": "/Dockerfile"})
        results["dockerfile"] = r3.status_code

        # Verificar resultado
        try:
            app = requests.get(base, headers=self.headers).json()
            alias_ok = app.get("custom_network_aliases") == network_alias
            fqdn_clear = not app.get("fqdn")

            if alias_ok and fqdn_clear:
                print(f"OK App configurada:")
                print(f"   Alias de red:  {network_alias}")
                print(f"   URL publica:   NINGUNA (interno only)")
                print(f"   URL para n8n:  http://{network_alias}:8000")
            else:
                print(f"Configuracion parcial:")
                print(f"   alias: {app.get('custom_network_aliases')} (esperado: {network_alias})")
                print(f"   fqdn:  {app.get('fqdn') or 'vacio'}")
                print(f"   Status codes: {results}")
            return app
        except Exception as e:
            print(f"Error verificando configuracion: {e}")
            return None


    def deploy_application(self, uuid):
        """Desencadena el despliegue de una aplicacion especifica."""
        endpoint = f"{self.url}/api/v1/deploy?uuid={uuid}&force=true"
        try:
            response = requests.get(endpoint, headers=self.headers)
            response.raise_for_status()
            result = response.json()
            deployment_uuid = result.get("deployments", [{}])[0].get("deployment_uuid")
            print(f"🚀 Despliegue iniciado. Deployment UUID: {deployment_uuid}")
            return result
        except Exception as e:
            print(f"❌ Error al iniciar el despliegue: {e}")
            return None

    def get_deployment_status(self, deployment_uuid):
        """
        Consulta el estado de un deployment especifico.
        Util para monitorear si el deploy termino con exito.
        Retorna dict con 'status' y 'logs' (solo los visibles).
        """
        endpoint = f"{self.url}/api/v1/deployments/{deployment_uuid}"
        try:
            response = requests.get(endpoint, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            status = data.get("status")
            logs = json.loads(data.get("logs", "[]"))
            visible_logs = [
                f"[{e.get('type','').upper()}] {e.get('output','')[:200]}"
                for e in logs if not e.get("hidden")
            ]
            return {"status": status, "logs": visible_logs}
        except Exception as e:
            print(f"❌ Error al consultar deployment: {e}")
            return {"status": "error", "logs": [str(e)]}

    def get_scoped_applications(self):
        """Lista las aplicaciones accesibles con el token actual."""
        return self.list_applications()


if __name__ == "__main__":
    manager = CoolifyManager()
    if not manager.token or not manager.url:
        print("❌ Faltan credenciales de Coolify en .env")
    else:
        apps = manager.list_applications()
        print(f"📦 Encontradas {len(apps)} aplicaciones accesibles.")

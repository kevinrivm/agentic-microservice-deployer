import os
import requests
import subprocess
from dotenv import load_dotenv

load_dotenv()

GITHUB_HEADERS = {
    "Authorization": f"token {os.getenv('GITHUB_TOKEN', '')}",
    "Accept": "application/vnd.github.v3+json",
    "X-GitHub-Api-Version": "2022-11-28"
}

def create_private_repo(repo_name, description="Created by Antigravity Agent"):
    """
    Crea un repositorio privado en GitHub usando el Personal Access Token.
    Retorna (owner, repo_name, repo_id) o None si falla.
    """
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN no encontrado en .env")
        return None

    url = "https://api.github.com/user/repos"
    data = {
        "name": repo_name,
        "description": description,
        "private": True,
        "auto_init": False
    }

    response = requests.post(url, json=data, headers=GITHUB_HEADERS)
    if response.status_code == 201:
        repo = response.json()
        print(f"OK Repositorio '{repo_name}' creado. ID: {repo['id']}")
        return repo["owner"]["login"], repo["name"], repo["id"]
    elif response.status_code == 422:
        # Ya existe — obtener su info
        owner = requests.get("https://api.github.com/user", headers=GITHUB_HEADERS).json()["login"]
        repo = requests.get(f"https://api.github.com/repos/{owner}/{repo_name}", headers=GITHUB_HEADERS).json()
        print(f"Repo '{repo_name}' ya existe. ID: {repo['id']}")
        return repo["owner"]["login"], repo["name"], repo["id"]
    else:
        print(f"Error al crear el repositorio: {response.json().get('message')}")
        return None

def grant_github_app_access(repo_id, installation_id):
    """
    Otorga acceso a un repo especifico a una instalacion de GitHub App.

    Esto automatiza el paso manual de ir a GitHub -> Settings -> 
    GitHub App -> Repository Access y seleccionar el repo.

    El GITHUB_TOKEN (PAT) necesita scope 'repo' para repos privados.
    Status 204 = exito (sin contenido en respuesta).

    Args:
        repo_id:         ID numerico del repo (retornado por create_private_repo)
        installation_id: ID de instalacion de la GitHub App (de Coolify API)
                         Se obtiene via GET /api/v1/github-apps -> installation_id
    """
    url = f"https://api.github.com/user/installations/{installation_id}/repositories/{repo_id}"
    r = requests.put(url, headers=GITHUB_HEADERS)

    if r.status_code == 204:
        print(f"OK Acceso otorgado: repo {repo_id} -> instalacion {installation_id}")
        return True
    elif r.status_code == 304:
        print(f"El repo ya tenia acceso a esta GitHub App.")
        return True
    else:
        print(f"Error al otorgar acceso: {r.status_code} - {r.text[:200]}")
        return False

def initialize_and_push(repo_name, owner, token=None):
    """
    Inicializa el repositorio local y sube el codigo al remoto via HTTPS.
    Usa GITHUB_TOKEN para autenticacion (no SSH).
    """
    token = token or os.getenv("GITHUB_TOKEN")
    remote_url = f"https://{token}@github.com/{owner}/{repo_name}.git"

    try:
        if not os.path.exists(".git"):
            subprocess.run(["git", "init"], check=True)
            print("Git inicializado localmente.")

        subprocess.run(["git", "remote", "remove", "origin"], stderr=subprocess.DEVNULL)
        subprocess.run(["git", "remote", "add", "origin", remote_url], check=True)

        subprocess.run(["git", "add", "."], check=True)
        result = subprocess.run(
            ["git", "commit", "-m", f"initial: autonomous creation of {repo_name}"],
            capture_output=True, text=True
        )
        if "nothing to commit" in result.stdout:
            print("Nada nuevo que commitear.")
        else:
            subprocess.run(["git", "branch", "-M", "main"], check=True)
            subprocess.run(["git", "push", "-u", "origin", "main", "--force"], check=True)
            print(f"Codigo subido a github.com/{owner}/{repo_name}")
        return True
    except Exception as e:
        print(f"Error durante el push: {e}")
        return False

if __name__ == "__main__":
    # Flujo completo: crear repo + dar acceso a GitHub App de Coolify + push
    # Requiere GITHUB_TOKEN, COOLIFY_URL, COOLIFY_TOKEN en .env

    REPO_NAME = "mi-nuevo-microservicio"

    # 1. Crear repo privado
    result = create_private_repo(REPO_NAME)
    if not result:
        exit(1)
    owner, repo_name, repo_id = result

    # 2. Obtener installation_id de la GitHub App de Coolify
    from dotenv import load_dotenv
    COOLIFY_URL = os.getenv("COOLIFY_URL")
    COOLIFY_TOKEN = os.getenv("COOLIFY_TOKEN")
    coolify_headers = {"Authorization": f"Bearer {COOLIFY_TOKEN}", "Accept": "application/json"}
    github_apps = requests.get(f"{COOLIFY_URL}/api/v1/github-apps", headers=coolify_headers).json()
    private_apps = [a for a in github_apps if not a.get("is_public")]
    installation_id = private_apps[0]["installation_id"]

    # 3. Dar acceso a la GitHub App (automatiza el paso manual)
    grant_github_app_access(repo_id, installation_id)

    # 4. Subir codigo
    initialize_and_push(repo_name, owner)

    print(f"\nRepo listo: github.com/{owner}/{repo_name}")
    print(f"Ahora usa coolify_manager.create_application('{repo_name}', '{owner}/{repo_name}')")

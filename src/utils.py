import json
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler
from typing import Dict, Any, Optional, Tuple

# Funcoes auxiliares pra nao precisar de requests nem de bibliotecas externas
# Usa direto o urllib da biblioteca padrao do python pra fazer as chamadas HTTP

# Manda um POST com json no corpo e devolve o status e a resposta ja em dicionario
def http_post_json(url: str, payload: Dict[str, Any], timeout: float = 30.0) -> Tuple[int, Dict[str, Any]]:
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.getcode()
            response_body = response.read().decode("utf-8")
            data = json.loads(response_body) if response_body else {}
            return status_code, data
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        try:
            data = json.loads(error_body)
        except Exception:
            data = {"error": error_body}
        return e.code, data
    except urllib.error.URLError as e:
        return 503, {"error": f"Nao deu pra conectar em {url}: {e.reason}"}
    except Exception as e:
        return 500, {"error": f"Deu erro inesperado: {str(e)}"}

# Manda um GET simples pra consultar status ou health check
def http_get_json(url: str, timeout: float = 10.0) -> Tuple[int, Dict[str, Any]]:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.getcode()
            response_body = response.read().decode("utf-8")
            data = json.loads(response_body) if response_body else {}
            return status_code, data
    except urllib.error.HTTPError as e:
        return e.code, {"error": f"Erro HTTP {e.code}"}
    except urllib.error.URLError as e:
        return 503, {"error": f"Nao conectou em {url}: {e.reason}"}
    except Exception as e:
        return 500, {"error": f"Erro inesperado: {str(e)}"}

# Monta a resposta HTTP com cabecalho application/json e status
def send_json_response(handler: BaseHTTPRequestHandler, status_code: int, data: Dict[str, Any]) -> None:
    body = json.dumps(data, indent=2).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)

# Pega o corpo da requisicao e transforma de json em dicionario python
def parse_json_request(handler: BaseHTTPRequestHandler) -> Optional[Dict[str, Any]]:
    content_length = int(handler.headers.get("Content-Length", 0))
    if content_length == 0:
        return {}
    body_bytes = handler.rfile.read(content_length)
    try:
        return json.loads(body_bytes.decode("utf-8"))
    except Exception:
        return None

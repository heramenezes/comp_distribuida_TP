import sys
import os
import argparse
import time
import threading
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Optional

# adiciona a pasta src no path pra importar os outros modulos
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from clock import LamportClock
from tsp import solve_tsp_branch_and_bound
from utils import send_json_response, parse_json_request

# Representa o no trabalhador: tem um ID, porta e o proprio relogio de lamport
class WorkerNode:
    def __init__(self, node_id: str, host: str, port: int):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.clock = LamportClock(node_id=node_id)
        self.tasks_completed = 0
        self.is_busy = False
        self.server: Optional[HTTPServer] = None
        self._is_running = False

    def get_status(self) -> dict:
        return {
            "node_id": self.node_id,
            "status": "OCUPADO" if self.is_busy else "LIVRE",
            "lamport_clock": self.clock.get_time(),
            "tasks_completed": self.tasks_completed,
            "port": self.port,
        }

# Cria a classe que trata as rotas HTTP do servidor do worker
def make_handler_class(worker: WorkerNode):
    class WorkerHTTPHandler(BaseHTTPRequestHandler):

        def log_message(self, format, *args):
            # print mais limpo no console com o nome do worker
            print(f"[{worker.node_id}] {self.address_string()} - {format % args}")

        # Rotas GET: health check e status
        def do_GET(self):
            if self.path in ("/health", "/status", "/"):
                # conta como um evento local de consulta
                worker.clock.tick(f"STATUS_CHECK vindo de {self.client_address[0]}")
                send_json_response(self, 200, worker.get_status())
            elif self.path == "/history":
                send_json_response(self, 200, {"history": worker.clock.get_history()})
            else:
                send_json_response(self, 404, {"error": "Rota nao encontrada"})

        # Rotas POST: receber fatias de tarefas ou shutdown
        def do_POST(self):
            if self.path == "/task":
                payload = parse_json_request(self)
                if not payload:
                    send_json_response(self, 400, {"error": "Payload JSON invalido"})
                    return

                sender_id = payload.get("sender_id", "coordinator")
                sender_clock = payload.get("sender_clock", 0)
                task_id = payload.get("task_id", "unknown")
                dist_matrix = payload.get("distance_matrix", [])
                prefixes = payload.get("prefixes", [])
                best_known = payload.get("best_known_cost", float("inf"))

                # Regra 3 de Lamport: chegou mensagem do coordenador!
                # Atualiza nosso relogio: max(local, sender_clock) + 1
                new_clock = worker.clock.receive_event(
                    sender_node=sender_id,
                    received_clock=sender_clock,
                    description=f"RECEIVE_TASK_{task_id} ({len(prefixes)} prefixos)",
                )

                print(
                    f"\n>>> [{worker.node_id}] Chegou tarefa (ID: {task_id}) de [{sender_id}]. "
                    f"Relogio Lamport atualizado pra: {new_clock}"
                )

                worker.is_busy = True
                try:
                    # Roda o branch and bound na nossa fatia
                    result = solve_tsp_branch_and_bound(
                        dist_matrix=dist_matrix,
                        prefixes=prefixes,
                        best_known_cost=best_known,
                    )
                finally:
                    worker.is_busy = False
                    worker.tasks_completed += 1

                # Regra 1: evento interno apos terminar o calculo pesado
                worker.clock.tick(description=f"TERMINOU_CALCULO_{task_id}")

                # Regra 2: incrementa relogio antes de responder pela rede
                reply_clock = worker.clock.send_event(
                    target_node=sender_id,
                    description=f"SEND_RESULT_{task_id}",
                )

                response_data = {
                    "worker_id": worker.node_id,
                    "sender_clock": reply_clock,
                    "task_id": task_id,
                    "best_cost": result["best_cost"],
                    "best_route": result["best_route"],
                    "evaluated_paths": result["evaluated_paths"],
                    "pruned_branches": result["pruned_branches"],
                    "execution_time_sec": result["execution_time_sec"],
                }

                print(
                    f"<<< [{worker.node_id}] Terminou tarefa (ID: {task_id}). "
                    f"Melhor custo achado: {result['best_cost']} | Relogio Lamport resposta: {reply_clock}\n"
                )

                send_json_response(self, 200, response_data)

            elif self.path == "/shutdown":
                send_json_response(self, 200, {"message": f"Desligando no {worker.node_id}"})
                threading.Thread(target=self.server.shutdown).start()
            else:
                send_json_response(self, 404, {"error": "Rota nao encontrada"})

    return WorkerHTTPHandler

# Sobe o servidor web do worker
def run_worker_server(node_id: str, host: str = "0.0.0.0", port: int = 8001):
    worker = WorkerNode(node_id=node_id, host=host, port=port)
    handler_class = make_handler_class(worker)
    # ThreadingHTTPServer pra atender requisicoes concorrentes sem travar
    server = ThreadingHTTPServer((host, port), handler_class)
    worker.server = server
    worker._is_running = True

    print("=" * 65)
    print(f"  NO TRABALHADOR ONLINE: {node_id}")
    print(f"  Escutando em: http://{host}:{port}")
    print(f"  Rotas disponiveis:")
    print(f"    - GET  /health   -> checa se o no ta vivo e livre")
    print(f"    - GET  /history  -> historico dos eventos de lamport")
    print(f"    - POST /task     -> processa o pedaco do TSP")
    print("=" * 65)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\nFechando no trabalhador {node_id}...")
    finally:
        server.server_close()
        print(f"No {node_id} finalizado.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inicia um worker do sistema distribuido.")
    parser.add_argument("--id", type=str, default="worker-1", help="Nome/ID do worker")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="IP de escuta")
    parser.add_argument("--port", type=int, default=8001, help="Porta HTTP")
    args = parser.parse_args()

    run_worker_server(node_id=args.id, host=args.host, port=args.port)

import sys
import os
import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import List, Dict, Any, Optional, Tuple

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from clock import LamportClock
from tsp import (
    generate_tsp_instance,
    compute_distance_matrix,
    generate_subproblems,
    partition_tasks,
    solve_tsp_sequential,
)
from utils import http_post_json, http_get_json, send_json_response, parse_json_request

# Classe principal do Coordenador (no mestre)
# Ele cria o problema, quebra em tarefas, manda pros workers em paralelo
# e controla o relogio de lamport a cada envio/recepcao
class Coordinator:
    def __init__(self, node_id: str = "coordinator", worker_urls: Optional[List[str]] = None):
        self.node_id = node_id
        self.worker_urls = worker_urls or ["http://127.0.0.1:8001", "http://127.0.0.1:8002"]
        self.clock = LamportClock(node_id=node_id)
        self.last_solution: Optional[Dict[str, Any]] = None

    # Manda um ping /health em cada worker pra ver se tao vivos antes de mandar trabalho
    def check_workers(self) -> List[Tuple[str, bool, Optional[Dict[str, Any]]]]:
        results = []
        for url in self.worker_urls:
            status_code, data = http_get_json(f"{url}/health", timeout=3.0)
            if status_code == 200:
                results.append((url, True, data))
            else:
                results.append((url, False, data))
        return results

    # Despacha uma tarefa individual pra um worker via POST /task
    def _dispatch_task_to_worker(
        self,
        worker_url: str,
        task_id: str,
        dist_matrix: List[List[float]],
        prefixes: List[List[int]],
        best_known_cost: float,
    ) -> Dict[str, Any]:
        # Regra 2 de Lamport: incrementa antes de mandar a requisicao HTTP
        send_clock = self.clock.send_event(
            target_node=worker_url,
            description=f"DISPATCH_{task_id} ({len(prefixes)} prefixos)",
        )

        payload = {
            "sender_id": self.node_id,
            "sender_clock": send_clock,
            "task_id": task_id,
            "distance_matrix": dist_matrix,
            "prefixes": prefixes,
            "best_known_cost": best_known_cost,
        }

        start_http = time.perf_counter()
        status_code, response_data = http_post_json(f"{worker_url}/task", payload, timeout=120.0)
        http_latency = time.perf_counter() - start_http

        if status_code != 200:
            raise RuntimeError(f"Erro no worker {worker_url}: HTTP {status_code} - {response_data}")

        worker_id = response_data.get("worker_id", worker_url)
        worker_clock = response_data.get("sender_clock", 0)

        # Regra 3 de Lamport: chegou a resposta do worker com o resultado!
        # Atualiza: max(local, worker_clock) + 1
        new_clock = self.clock.receive_event(
            sender_node=worker_id,
            received_clock=worker_clock,
            description=f"RESULT_{task_id} (Custo: {response_data.get('best_cost')})",
        )

        response_data["http_latency_sec"] = round(http_latency, 4)
        response_data["coordinator_clock_after_recv"] = new_clock
        return response_data

    # Funcao principal que orquestra a solucao do TSP
    def solve_distributed(
        self,
        num_cities: int = 11,
        seed: int = 42,
        prefix_depth: int = 2,
        benchmark_sequential: bool = True,
    ) -> Dict[str, Any]:
        # Evento local: comecando a rodar
        self.clock.tick("INICIALIZA_GERACAO_PROBLEMA")

        print("\n" + "=" * 70)
        print(f"  RESOLVENDO TSP DE FORMA DISTRIBUIDA ({num_cities} CIDADES)")
        print("=" * 70)

        # 1. Gera cidades e matriz de distancia
        cities = generate_tsp_instance(num_cities=num_cities, seed=seed)
        dist_matrix = compute_distance_matrix(cities)

        # 2. Roda sequencial primeiro pra gente ter a referencia do speedup
        seq_result = None
        if benchmark_sequential:
            print(f"[*] Rodando teste sequencial de referencia em 1 no so...")
            self.clock.tick("INICIO_BENCHMARK_SEQUENCIAL")
            seq_result = solve_tsp_sequential(dist_matrix)
            self.clock.tick("FIM_BENCHMARK_SEQUENCIAL")
            print(f"    -> Custo sequencial: {seq_result['best_cost']}")
            print(f"    -> Tempo sequencial: {seq_result['execution_time_sec']}s")

        # 3. Gera os prefixos e reparte entre os workers
        prefixes = generate_subproblems(num_cities=num_cities, prefix_depth=prefix_depth)
        num_workers = len(self.worker_urls)
        partitions = partition_tasks(prefixes, num_partitions=num_workers)

        print(f"[*] Dividiu a busca em {len(prefixes)} prefixos (profundidade {prefix_depth}).")
        print(f"[*] Repartindo entre {num_workers} workers cadastrados:")
        for i, url in enumerate(self.worker_urls):
            print(f"    - Worker {i+1} ({url}): {len(partitions[i])} prefixos de rota")

        # 4. Dispara as requisicoes HTTP pros workers ao mesmo tempo usando threads
        dist_start_time = time.perf_counter()
        worker_results = []
        global_best_cost = float("inf")
        global_best_route = None
        total_eval_paths = 0
        total_pruned = 0

        self.clock.tick("DISPARO_TAREFAS_INICIO")

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            future_to_task = {}
            for idx, worker_url in enumerate(self.worker_urls):
                task_id = f"batch_{idx + 1}"
                task_prefixes = partitions[idx]
                future = executor.submit(
                    self._dispatch_task_to_worker,
                    worker_url=worker_url,
                    task_id=task_id,
                    dist_matrix=dist_matrix,
                    prefixes=task_prefixes,
                    best_known_cost=global_best_cost,
                )
                future_to_task[future] = task_id

            # Conforme os workers vao respondendo, a gente pega o resultado
            for future in as_completed(future_to_task):
                task_id = future_to_task[future]
                try:
                    res = future.result()
                    worker_results.append(res)
                    total_eval_paths += res.get("evaluated_paths", 0)
                    total_pruned += res.get("pruned_branches", 0)

                    cost = res.get("best_cost")
                    if cost is not None and cost < global_best_cost:
                        global_best_cost = cost
                        global_best_route = res.get("best_route")
                except Exception as e:
                    print(f"[!] Erro ao processar {task_id}: {e}")

        dist_elapsed = time.perf_counter() - dist_start_time
        self.clock.tick("AGREGACAO_RESULTADOS_FIM")

        # 5. Calcula as metricas de speedup e eficiencia
        speedup = None
        efficiency = None
        if seq_result and dist_elapsed > 0:
            speedup = round(seq_result["execution_time_sec"] / dist_elapsed, 2)
            efficiency = round(speedup / num_workers, 2)

        summary = {
            "num_cities": num_cities,
            "seed": seed,
            "prefix_depth": prefix_depth,
            "num_workers": num_workers,
            "global_best_cost": round(global_best_cost, 4),
            "global_best_route": global_best_route,
            "distributed_time_sec": round(dist_elapsed, 4),
            "sequential_time_sec": seq_result["execution_time_sec"] if seq_result else None,
            "speedup": speedup,
            "efficiency": efficiency,
            "total_evaluated_paths": total_eval_paths,
            "total_pruned_branches": total_pruned,
            "final_lamport_clock": self.clock.get_time(),
            "worker_details": worker_results,
            "lamport_history": self.clock.get_history(),
        }

        self.last_solution = summary
        self._print_summary(summary)
        return summary

    # Mostra o relatorio final no console
    def _print_summary(self, s: Dict[str, Any]):
        print("\n" + "=" * 70)
        print("                 RELATORIO FINAL DE EXECUCAO")
        print("=" * 70)
        print(f" Instancia TSP: {s['num_cities']} cidades | Seed: {s['seed']}")
        print(f" Melhor Custo Achado: {s['global_best_cost']}")
        print(f" Melhor Rota: {s['global_best_route']}")
        print(f" Caminhos Avaliados: {s['total_evaluated_paths']:,} | Podas Feitas: {s['total_pruned_branches']:,}")
        print("-" * 70)
        print(f" Tempo Distribuido: {s['distributed_time_sec']}s ({s['num_workers']} workers)")
        if s["sequential_time_sec"]:
            print(f" Tempo Sequencial:  {s['sequential_time_sec']}s (1 no local)")
            print(f" Speedup (T_seq / T_dist): {s['speedup']}x")
            print(f" Eficiencia (Speedup / Workers): {s['efficiency'] * 100:.1f}%")
        print("-" * 70)
        print(f" Relogio Lamport Final: {s['final_lamport_clock']}")
        print("=" * 70 + "\n")


# Handler se a gente quiser deixar o proprio coordenador rodando como servidor HTTP
def make_coordinator_handler(coordinator: Coordinator):
    class CoordinatorHTTPHandler(BaseHTTPRequestHandler):

        def log_message(self, format, *args):
            print(f"[coordinator-web] {self.address_string()} - {format % args}")

        def do_GET(self):
            if self.path in ("/status", "/health", "/"):
                coordinator.clock.tick("WEB_STATUS_CHECK")
                worker_statuses = coordinator.check_workers()
                data = {
                    "node_id": coordinator.node_id,
                    "lamport_clock": coordinator.clock.get_time(),
                    "configured_workers": coordinator.worker_urls,
                    "workers_alive": [url for url, ok, _ in worker_statuses if ok],
                    "last_solution": coordinator.last_solution,
                }
                send_json_response(self, 200, data)
            elif self.path == "/history":
                send_json_response(self, 200, {"history": coordinator.clock.get_history()})
            else:
                send_json_response(self, 404, {"error": "Rota nao encontrada"})

        def do_POST(self):
            if self.path == "/solve":
                payload = parse_json_request(self) or {}
                num_cities = int(payload.get("num_cities", 11))
                seed = int(payload.get("seed", 42))
                prefix_depth = int(payload.get("prefix_depth", 2))
                benchmark_seq = bool(payload.get("benchmark_sequential", True))

                res = coordinator.solve_distributed(
                    num_cities=num_cities,
                    seed=seed,
                    prefix_depth=prefix_depth,
                    benchmark_sequential=benchmark_seq,
                )
                send_json_response(self, 200, res)
            else:
                send_json_response(self, 404, {"error": "Rota nao encontrada"})

    return CoordinatorHTTPHandler


def run_coordinator_service(coordinator: Coordinator, host: str = "0.0.0.0", port: int = 8000):
    handler_class = make_coordinator_handler(coordinator)
    server = ThreadingHTTPServer((host, port), handler_class)
    print(f"[*] Coordenador Web iniciado em http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nFechando coordenador...")
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Coordenador do TSP distribuido.")
    parser.add_argument("--workers", nargs="+", default=["http://127.0.0.1:8001", "http://127.0.0.1:8002"], help="URLs dos workers")
    parser.add_argument("--cities", type=int, default=11, help="Quantidade de cidades do TSP")
    parser.add_argument("--seed", type=int, default=42, help="Seed deterministica")
    parser.add_argument("--depth", type=int, default=2, help="Profundidade do particionamento")
    parser.add_argument("--no-seq", action="store_true", help="Nao rodar o benchmark sequencial")
    parser.add_argument("--serve", action="store_true", help="Iniciar como servidor web")
    parser.add_argument("--port", type=int, default=8000, help="Porta web")
    args = parser.parse_args()

    coord = Coordinator(worker_urls=args.workers)

    if args.serve:
        run_coordinator_service(coord, port=args.port)
    else:
        coord.solve_distributed(
            num_cities=args.cities,
            seed=args.seed,
            prefix_depth=args.depth,
            benchmark_sequential=not args.no_seq,
        )

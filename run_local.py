import sys
import os
import time
import threading
from typing import Tuple
from http.server import ThreadingHTTPServer

# Adiciona o diretorio src pro python achar nossos arquivos
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from worker import WorkerNode, make_handler_class
from coordinator import Coordinator
from utils import http_post_json

# Sobe um worker numa thread separada pra gente conseguir rodar tudo num comando so
def start_worker_in_thread(node_id: str, port: int) -> Tuple[WorkerNode, ThreadingHTTPServer, threading.Thread]:
    worker = WorkerNode(node_id=node_id, host="127.0.0.1", port=port)
    handler_class = make_handler_class(worker)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_class)
    worker.server = server

    thread = threading.Thread(target=server.serve_forever, daemon=True, name=f"thread-{node_id}")
    thread.start()
    return worker, server, thread

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Executa demonstracao local do sistema distribuido.")
    parser.add_argument("--cities", type=int, default=12, help="Quantidade de cidades do TSP (sugestao: 11 a 14)")
    parser.add_argument("--seed", type=int, default=42, help="Seed deterministica")
    args = parser.parse_args()

    num_cities = args.cities
    seed = args.seed

    print("=" * 75)
    print("      DEMONSTRACAO DO SISTEMA DISTRIBUIDO DE OTIMIZACAO (TSP)")
    print("  Requisitos: Web Services (HTTP/REST) & Relogios Logicos de Lamport")
    print("=" * 75)

    # 1. Inicia os 2 workers locais
    print("\n[Passo 1/4] Subindo os workers locais...")
    w1, s1, t1 = start_worker_in_thread(node_id="worker-1", port=8001)
    w2, s2, t2 = start_worker_in_thread(node_id="worker-2", port=8002)
    time.sleep(0.5)

    # 2. Inicia o coordenador e faz o ping nos workers
    print("\n[Passo 2/4] Coordenador checando se os workers estao online via HTTP GET...")
    coord = Coordinator(
        node_id="coordinator",
        worker_urls=["http://127.0.0.1:8001", "http://127.0.0.1:8002"]
    )
    worker_status = coord.check_workers()
    for url, ok, data in worker_status:
        if ok:
            print(f"  [OK] Conectou em {url} -> No: {data.get('node_id')} | Relogio: {data.get('lamport_clock')}")
        else:
            print(f"  [FALHA] Nao conseguiu conectar em {url}")
            sys.exit(1)

    # 3. Roda a resolucao distribuida do TSP
    print(f"\n[Passo 3/4] Resolvendo TSP para {num_cities} cidades (seed={seed})...")
    result = coord.solve_distributed(
        num_cities=num_cities,
        seed=seed,
        prefix_depth=2,
        benchmark_sequential=True,
    )

    # 4. Mostra o historico de eventos de Lamport ordenado
    print("\n[Passo 4/4] Linha do tempo dos Relogios Logicos de Lamport (ordem causal)...")
    print("-" * 75)
    print(f"{'No':<14} | {'Tipo':<8} | {'Descricao':<32} | {'Relogio':<12}")
    print("-" * 75)

    all_events = []
    for ev in coord.clock.get_history():
        all_events.append(ev)
    for ev in w1.clock.get_history():
        all_events.append(ev)
    for ev in w2.clock.get_history():
        all_events.append(ev)

    # Ordena pelo relogio de lamport
    all_events.sort(key=lambda e: (e["clock_after"], e["node_id"]))

    for ev in all_events:
        node = ev["node_id"]
        etype = ev["type"]
        desc = ev["description"][:30]
        clock_trans = f"{ev['clock_before']} -> {ev['clock_after']}"
        print(f"{node:<14} | {etype:<8} | {desc:<32} | {clock_trans:<12}")

    print("-" * 75)

    # 5. Finaliza os servidores
    print("\n[*] Fechando os workers...")
    s1.shutdown()
    s2.shutdown()
    s1.server_close()
    s2.server_close()
    print("[*] Tudo finalizado com sucesso!\n")

if __name__ == "__main__":
    main()

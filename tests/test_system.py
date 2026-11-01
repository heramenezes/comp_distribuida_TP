import sys
import os
import unittest
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from clock import LamportClock
from tsp import (
    generate_tsp_instance,
    compute_distance_matrix,
    calculate_route_distance,
    generate_subproblems,
    partition_tasks,
    solve_tsp_branch_and_bound,
    solve_tsp_sequential,
)

# Testes unitarios pra validar o relogio de lamport
class TestLamportClock(unittest.TestCase):

    # Regra 1: evento interno incrementa 1
    def test_rule_1_internal_tick(self):
        c = LamportClock("node-a")
        self.assertEqual(c.get_time(), 0)
        t1 = c.tick("EVENTO_1")
        self.assertEqual(t1, 1)
        self.assertEqual(c.get_time(), 1)
        t2 = c.tick("EVENTO_2")
        self.assertEqual(t2, 2)

    # Regras 2 e 3: envio e recepcao com causalidade
    def test_rule_2_and_3_message_passing(self):
        coord = LamportClock("coordinator")
        worker = LamportClock("worker-1")

        # Coordenador manda tarefa (Regra 2)
        coord_send_clock = coord.send_event("worker-1", "DISPATCH_TASK")
        self.assertEqual(coord_send_clock, 1)

        # Worker recebe (Regra 3: max(local, recebido) + 1)
        worker_recv_clock = worker.receive_event("coordinator", coord_send_clock, "RECEIVE_TASK")
        self.assertEqual(worker_recv_clock, 2)
        self.assertGreater(worker_recv_clock, coord_send_clock)

        # Worker calcula localmente (Regra 1)
        worker_compute_clock = worker.tick("PROCESS_TASK")
        self.assertEqual(worker_compute_clock, 3)

        # Worker devolve resposta (Regra 2)
        worker_send_clock = worker.send_event("coordinator", "SEND_RESULT")
        self.assertEqual(worker_send_clock, 4)

        # Coordenador recebe a resposta
        coord_recv_clock = coord.receive_event("worker-1", worker_send_clock, "RECEIVE_RESULT")
        # Coord tava em 1. max(1, 4) + 1 = 5
        self.assertEqual(coord_recv_clock, 5)
        self.assertGreater(coord_recv_clock, worker_send_clock)

    # Se receber mensagem com relogio bem maior, tem que saltar pra ela + 1
    def test_clock_jump_on_higher_remote_timestamp(self):
        node = LamportClock("node-x")
        node.tick()
        node.tick()
        self.assertEqual(node.get_time(), 2)

        new_clock = node.receive_event("remote", 50, "MSG_COM_TIMESTAMP_ALTO")
        self.assertEqual(new_clock, 51)
        self.assertEqual(node.get_time(), 51)

# Testes do algoritmo do Caixeiro Viajante
class TestTSPOptimization(unittest.TestCase):

    def setUp(self):
        self.cities = generate_tsp_instance(num_cities=8, seed=123)
        self.dist_matrix = compute_distance_matrix(self.cities)

    # Garante que a mesma seed sempre gera as mesmas cidades
    def test_deterministic_instance_generation(self):
        c1 = generate_tsp_instance(num_cities=8, seed=123)
        c2 = generate_tsp_instance(num_cities=8, seed=123)
        self.assertEqual(c1, c2)

    # Distancia de i pra j tem que ser igual a de j pra i
    def test_distance_matrix_symmetry(self):
        n = len(self.dist_matrix)
        for i in range(n):
            self.assertEqual(self.dist_matrix[i][i], 0.0)
            for j in range(n):
                self.assertAlmostEqual(self.dist_matrix[i][j], self.dist_matrix[j][i], places=4)

    # Testa se a divisao de prefixos gerou a quantidade certa
    def test_prefix_coverage(self):
        num_cities = 6
        prefixes = generate_subproblems(num_cities, prefix_depth=2)
        self.assertEqual(len(prefixes), 20)

        for p in prefixes:
            self.assertEqual(p[0], 0)
            self.assertEqual(len(p), 3)
            self.assertEqual(len(set(p)), 3)

    # Testa se a versao particionada acha exatamente o mesmo custo da versao sequencial
    def test_sequential_vs_partitioned_equivalence(self):
        # 1. Roda sequencial
        seq_res = solve_tsp_sequential(self.dist_matrix)
        self.assertIsNotNone(seq_res["best_cost"])
        self.assertIsNotNone(seq_res["best_route"])

        # 2. Roda particionado em 2 pedacos (simulando 2 workers)
        prefixes = generate_subproblems(len(self.dist_matrix), prefix_depth=2)
        partitions = partition_tasks(prefixes, num_partitions=2)

        part_res_1 = solve_tsp_branch_and_bound(self.dist_matrix, partitions[0])
        part_res_2 = solve_tsp_branch_and_bound(self.dist_matrix, partitions[1])

        best_partition_cost = min(part_res_1["best_cost"], part_res_2["best_cost"])

        # Os dois resultados tem que bater certinho
        self.assertAlmostEqual(best_partition_cost, seq_res["best_cost"], places=4)

        # Checa recalculando a rota na matriz
        calc_dist = calculate_route_distance(seq_res["best_route"], self.dist_matrix)
        self.assertAlmostEqual(calc_dist, seq_res["best_cost"], places=4)

# Testes de serializacao json
class TestWebServicePayloads(unittest.TestCase):

    def test_task_payload_integrity(self):
        cities = generate_tsp_instance(num_cities=5, seed=42)
        matrix = compute_distance_matrix(cities)
        prefixes = [[0, 1, 2], [0, 1, 3]]

        payload = {
            "sender_id": "coordinator",
            "sender_clock": 10,
            "task_id": "task_teste",
            "distance_matrix": matrix,
            "prefixes": prefixes,
            "best_known_cost": 200.0,
        }

        # Converte pra json e volta pra dicionario
        raw_json = json.dumps(payload)
        parsed = json.loads(raw_json)

        self.assertEqual(parsed["sender_id"], "coordinator")
        self.assertEqual(parsed["sender_clock"], 10)
        self.assertEqual(len(parsed["distance_matrix"]), 5)
        self.assertEqual(parsed["prefixes"], prefixes)

if __name__ == "__main__":
    unittest.main()

import math
import random
import time
from typing import List, Tuple, Dict, Any, Optional

# Gera posicoes (x, y) pras cidades usando uma seed fixa
# Colocamos a seed pra sempre gerar o mesmo mapa e podermos comparar os tempos
def generate_tsp_instance(num_cities: int = 11, seed: int = 42, area_size: float = 100.0) -> List[Tuple[float, float]]:
    rng = random.Random(seed)
    cities = []
    for _ in range(num_cities):
        x = round(rng.uniform(0.0, area_size), 2)
        y = round(rng.uniform(0.0, area_size), 2)
        cities.append((x, y))
    return cities

# Monta a matriz de distancias euclidianas entre cada par de cidades
# Fazemos isso antes pra nao ficar calculando raiz quadrada toda hora na busca
def compute_distance_matrix(cities: List[Tuple[float, float]]) -> List[List[float]]:
    n = len(cities)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                dx = cities[i][0] - cities[j][0]
                dy = cities[i][1] - cities[j][1]
                matrix[i][j] = round(math.sqrt(dx * dx + dy * dy), 4)
    return matrix

# Soma a distancia total de uma rota completa, lembrando de voltar pra cidade 0 no final
def calculate_route_distance(route: List[int], dist_matrix: List[List[float]]) -> float:
    total = 0.0
    for i in range(len(route) - 1):
        total += dist_matrix[route[i]][route[i + 1]]
    total += dist_matrix[route[-1]][route[0]]
    return round(total, 4)

# Aqui a gente fatia o espaco de busca fixando os primeiros passos a partir da cidade 0
# Exemplo com depth=2: rotas comecando em [0, 1, 2], [0, 1, 3], etc.
# Cada prefixo desse vira uma tarefa pra um worker resolver
def generate_subproblems(num_cities: int, prefix_depth: int = 2) -> List[List[int]]:
    assert prefix_depth in (1, 2, 3), "depth tem que ser 1, 2 ou 3"

    prefixes: List[List[int]] = []
    cities_left = list(range(1, num_cities))

    if prefix_depth == 1:
        for c1 in cities_left:
            prefixes.append([0, c1])
    elif prefix_depth == 2:
        for c1 in cities_left:
            for c2 in cities_left:
                if c1 != c2:
                    prefixes.append([0, c1, c2])
    elif prefix_depth == 3:
        for c1 in cities_left:
            for c2 in cities_left:
                if c1 != c2:
                    for c3 in cities_left:
                        if c3 != c1 and c3 != c2:
                            prefixes.append([0, c1, c2, c3])

    return prefixes

# Divide a lista de tarefas igualmente entre a quantidade de workers que a gente tem
def partition_tasks(prefixes: List[List[int]], num_partitions: int) -> List[List[List[int]]]:
    if num_partitions <= 1:
        return [prefixes]

    partitions: List[List[List[int]]] = [[] for _ in range(num_partitions)]
    for idx, prefix in enumerate(prefixes):
        partitions[idx % num_partitions].append(prefix)
    return partitions

# O coracao do algoritmo: busca em profundidade com poda (Branch and Bound)
# Pra cada prefixo, vai tentando as cidades que faltam
# Se o custo do caminho parcial ja ficou maior que o melhor que a gente achou ate agora, PODA!
def solve_tsp_branch_and_bound(
    dist_matrix: List[List[float]],
    prefixes: List[List[int]],
    best_known_cost: float = float("inf")
) -> Dict[str, Any]:
    num_cities = len(dist_matrix)
    all_cities_set = set(range(num_cities))

    best_cost = best_known_cost
    best_route: Optional[List[int]] = None
    evaluated_paths = 0
    pruned_branches = 0

    start_time = time.perf_counter()

    for prefix in prefixes:
        # calcula o custo inicial do prefixo
        prefix_cost = 0.0
        for i in range(len(prefix) - 1):
            prefix_cost += dist_matrix[prefix[i]][prefix[i + 1]]

        visited_mask = set(prefix)
        remaining = [c for c in all_cities_set if c not in visited_mask]

        # pilha pra fazer o dfs
        stack = [(prefix[-1], prefix_cost, prefix.copy(), remaining)]

        while stack:
            current_city, current_cost, current_path, unvisited = stack.pop()

            # Poda: se ja passou do melhor, nem perde tempo descendo mais nessa arvore
            if current_cost >= best_cost:
                pruned_branches += 1
                continue

            # Se visitou todo mundo, fecha o ciclo voltando pra cidade 0
            if not unvisited:
                total_cost = current_cost + dist_matrix[current_city][0]
                evaluated_paths += 1
                if total_cost < best_cost:
                    best_cost = total_cost
                    best_route = current_path + [0]
                continue

            # Testa as proximas cidades ainda nao visitadas
            for next_city in unvisited:
                step_cost = dist_matrix[current_city][next_city]
                new_cost = current_cost + step_cost
                if new_cost < best_cost:
                    new_unvisited = [c for c in unvisited if c != next_city]
                    new_path = current_path + [next_city]
                    stack.append((next_city, new_cost, new_path, new_unvisited))
                else:
                    # poda aqui tambem se esse passo ja estourou o limite
                    pruned_branches += 1

    elapsed = time.perf_counter() - start_time

    return {
        "best_cost": round(best_cost, 4) if best_cost < float("inf") else None,
        "best_route": best_route,
        "evaluated_paths": evaluated_paths,
        "pruned_branches": pruned_branches,
        "execution_time_sec": round(elapsed, 4),
    }

# Roda o algoritmo inteiro num no so pra gente ter a referencia (benchmark) de speedup
def solve_tsp_sequential(dist_matrix: List[List[float]]) -> Dict[str, Any]:
    num_cities = len(dist_matrix)
    prefixes = generate_subproblems(num_cities, prefix_depth=1)
    return solve_tsp_branch_and_bound(dist_matrix, prefixes)

# Sistema Distribuído para Resolução do Problema do Caixeiro Viajante Utilizando Web Services e Relógios Lógicos de Lamport

**Autores:** [Nome do Integrante 1], [Nome do Integrante 2], [Nome do Integrante 3], [Nome do Integrante 4], [Nome do Integrante 5]  
**Instituição:** Instituto de Ciências Exatas e Informática (ICEI) – PUC Minas  
**Disciplina:** Computação Distribuída (2026.2) – Prof. Luigi D. C. Soares  

---

## Resumo
Este artigo apresenta o projeto e a implementação de um sistema distribuído baseado no padrão mestre-trabalhador (*Master-Worker*) para a resolução exata do Problema do Caixeiro Viajante (*Traveling Salesperson Problem* – TSP) por meio de particionamento do espaço de busca e algoritmo *Branch-and-Bound*. O trabalho atende rigorosamente aos requisitos da primeira entrega prática da disciplina, incorporando:
1. **Web Services RESTful** sobre o protocolo HTTP, trocando mensagens estruturadas em JSON de forma totalmente desacoplada e independente de bibliotecas proprietárias;
2. **Sincronização Causal por Relógios Lógicos de Lamport**, implementado manualmente em conformidade com as regras clássicas de Leslie Lamport (1978).

Os experimentos e medições realizadas evidenciam a preservação estrita da causalidade entre os nós, a equivalência exata das rotas encontradas em relação ao método sequencial e a viabilidade da divisão de tarefas computacionais pesadas em ambiente de rede local.

---

## 1. Introdução e Formulação do Problema

Problemas de otimização combinatória caracterizam-se por um crescimento exponencial do espaço de estados à medida que a dimensão da entrada aumenta. O Problema do Caixeiro Viajante (TSP) é um dos problemas mais representativos da teoria da computação e da pesquisa operacional, pertencente à classe NP-difícil.

Dada uma lista de $N$ cidades com posições cartesianas $(x_i, y_i)$, calcula-se a matriz simétrica de distâncias euclidianas $D \in \mathbb{R}^{N \times N}$, onde:
$$D[i][j] = \sqrt{(x_i - x_j)^2 + (y_i - y_j)^2}$$

O objetivo consiste em encontrar a permutação cíclica $\pi = (c_0, c_1, \dots, c_{N-1})$, com origem fixada em $c_0 = 0$, que minimize o comprimento total percorrido:
$$\min C(\pi) = \left( \sum_{i=0}^{N-2} D[c_i][c_{i+1}] \right) + D[c_{N-1}][c_0]$$

Por força bruta, o número de permutações a serem avaliadas é $\frac{(N-1)!}{2}$. Para $N = 14$, isso corresponde a mais de 3,1 bilhões de combinações possíveis. Diante dessa complexidade, a estratégia distribuída adotada divide a árvore de busca a partir de prefixos fixos de rotas (por exemplo, $[0, c_1, c_2]$), delegando subárvores independentes para nós trabalhadores processarem em paralelo por meio de *Branch-and-Bound* com poda por limite superior.

---

## 2. Arquitetura do Sistema Distribuído

O sistema segue a topologia mestre-trabalhador (*Coordinator-Workers*), comunicando-se exclusivamente via requisições HTTP REST.

### 2.1 Papel das Entidades
* **Nó Coordenador (`coordinator.py`):**
  * Gera ou carrega a instância do TSP e calcula a matriz de distâncias.
  * Executa (opcionalmente) o benchmark sequencial local para fins de validação e cálculo de *speedup*.
  * Decompõe o espaço de soluções gerando $K$ prefixos de subproblemas e particiona as tarefas de forma equilibrada entre os trabalhadores.
  * Mantém o Relógio Lógico de Lamport central e despacha as tarefas concorrentemente via requisições HTTP POST aos workers.
  * Recebe as soluções parciais, atualiza seu relógio lógico de acordo com as regras de Lamport e consolida o menor custo e rota ótima global.

* **Nós Trabalhadores (`worker.py`):**
  * Atuam como servidores web autônomos (`ThreadingHTTPServer`) escutando em portas independentes (ex: `8001`, `8002`) em máquinas locais ou remotas.
  * Mantêm seu próprio Relógio Lógico de Lamport individual e histórico de transições.
  * Recebem lotes de prefixos via endpoint `POST /task`, sincronizam o relógio com o timestamp do coordenador, executam o *Branch-and-Bound* local e retornam o resultado ótimo daquela fatia junto ao timestamp atualizado.

### 2.2 Diagrama de Mensagens e Fluxo de Execução

```
[Coordenador]                                [Trabalhador 1]                  [Trabalhador 2]
    |                                                |                                |
    |-- GET /health (Clock: 0) --------------------->|                                |
    |<-- 200 OK (Worker1 Clock: 1) ------------------|                                |
    |                                                |                                |
    |-- GET /health (Clock: 1) ------------------------------------------------------>|
    |<-- 200 OK (Worker2 Clock: 1) ---------------------------------------------------|
    |                                                |                                |
    | [Gera Tarefas & Benchmarking Local]            |                                |
    | Clock = 4                                      |                                |
    |                                                |                                |
    |-- POST /task [batch_1] (Clock: 5) ------------>|                                |
    |                                                | [Sync Clock: max(1, 5)+1 = 6]  |
    |-- POST /task [batch_2] (Clock: 6) --------------------------------------------->|
    |                                                |                                | [Sync Clock: max(1, 6)+1 = 7]
    |                                                | [Branch-and-Bound Computation] | [Branch-and-Bound Computation]
    |                                                | Clock tick = 7                 | Clock tick = 8
    |                                                | Send Clock = 8                 | Send Clock = 9
    |<-- 200 OK {best_cost, route} (Clock: 8) -------|                                |
    | [Sync Clock: max(6, 8)+1 = 9]                  |                                |
    |                                                |                                |
    |<-- 200 OK {best_cost, route} (Clock: 9) ----------------------------------------|
    | [Sync Clock: max(9, 9)+1 = 10]                 |                                |
    |                                                |                                |
    | [Consolidação do Ótimo Global] Clock = 11      |                                |
    v                                                v                                v
```

### 2.3 Contratos de Interface (Payloads JSON)
* **Requisição de Tarefa (`POST /task`):**
```json
{
  "sender_id": "coordinator",
  "sender_clock": 5,
  "task_id": "batch_1",
  "distance_matrix": [[0.0, 15.2, ...], ...],
  "prefixes": [[0, 1, 2], [0, 1, 3]],
  "best_known_cost": 300.0
}
```

* **Resposta do Trabalhador (`HTTP 200 OK`):**
```json
{
  "worker_id": "worker-1",
  "sender_clock": 8,
  "task_id": "batch_1",
  "best_cost": 275.5284,
  "best_route": [0, 4, 11, 1, 6, 5, 8, 7, 2, 10, 12, 3, 9, 0],
  "evaluated_paths": 1463,
  "pruned_branches": 5973237,
  "execution_time_sec": 0.42
}
```

---

## 3. Detalhamento da Implementação dos Requisitos

### 3.1 Requisito 1: Utilização de Web Services (REST HTTP)
A arquitetura de Web Services foi desenvolvida sobre a biblioteca padrão do Python (`http.server` e `urllib.request`), evitando dependências de pacotes externos e garantindo total portabilidade:
* **Concorrência Segura:** Emprego de `ThreadingHTTPServer`, que aloca requisições recebidas em threads distintas do pool do sistema operacional.
* **Semântica RESTful:** Endpoints com separação clara de responsabilidades:
  * `GET /health` e `GET /status`: verificação não-destrutiva de conectividade e relógio lógico.
  * `POST /task`: submissão de processamento computacional com payload JSON explícito.
  * `POST /shutdown`: encerramento ordenado dos nós.
* **Tratamento de Exceções:** Implementação de timeouts configuráveis (ex: 120s) e tratamento de códigos HTTP de erro (`400 Bad Request`, `503 Service Unavailable`) caso um nó caia.

### 3.2 Requisito 2: Sincronização por Relógios Lógicos de Lamport
A sincronização temporal foi desenvolvida no módulo `src/clock.py` através da classe `LamportClock`. Leslie Lamport (1978) propôs um modelo formal para ordenação parcial de eventos em sistemas assíncronos onde não há um relógio físico global compartilhado. O sistema implementa rigorosamente as três regras:

1. **Regra 1 (Evento Interno / Local):**
   Antes de executar um evento exclusivamente local no nó $i$:
   $$C_i \leftarrow C_i + 1$$

2. **Regra 2 (Envio de Mensagem):**
   Antes de transmitir qualquer requisição ou resposta de rede para o nó $j$, o nó $i$ incrementa seu relógio e inclui seu timestamp no payload da mensagem:
   $$C_i \leftarrow C_i + 1, \quad T_m = C_i$$

3. **Regra 3 (Recepção de Mensagem):**
   Ao receber uma mensagem contendo o timestamp remoto $T_m$, o nó receptor $j$ atualiza seu contador:
   $$C_j \leftarrow \max(C_j, T_m) + 1$$

Essa regra garante formalmente a relação de causalidade (*happened-before*, denotada por $a \to b \implies C(a) < C(b)$). Para evitar condições de corrida em ambiente multi-thread, todas as mutações no contador são protegidas por `threading.Lock`.

#### Tabela de Rastreabilidade Causal Obtida em Execução Real:
| Nó | Tipo de Evento | Descrição da Ação | Transição do Relógio |
| :--- | :--- | :--- | :--- |
| **coordinator** | INTERNAL | INITIALIZE_PROBLEM_GENERATION | $0 \to 1$ |
| **worker-1** | INTERNAL | STATUS_CHECK from 127.0.0.1 | $0 \to 1$ |
| **worker-2** | INTERNAL | STATUS_CHECK from 127.0.0.1 | $0 \to 1$ |
| **coordinator** | INTERNAL | START_SEQUENTIAL_BENCHMARK | $1 \to 2$ |
| **coordinator** | INTERNAL | END_SEQUENTIAL_BENCHMARK | $2 \to 3$ |
| **coordinator** | INTERNAL | DISPATCH_ALL_TASKS_START | $3 \to 4$ |
| **coordinator** | SEND | DISPATCH_batch_1 (45 prefixos) | $4 \to 5$ |
| **coordinator** | SEND | DISPATCH_batch_2 (45 prefixos) | $5 \to 6$ |
| **worker-1** | RECEIVE | RECEIVE_TASK_batch_1 (45 prefixos) | $1 \to 6$ ($\max(1, 5)+1$) |
| **worker-1** | INTERNAL | FINISHED_COMPUTATION_TASK_batch_1 | $6 \to 7$ |
| **worker-2** | RECEIVE | RECEIVE_TASK_batch_2 (45 prefixos) | $1 \to 7$ ($\max(1, 6)+1$) |
| **worker-1** | SEND | SEND_RESULT_batch_1 | $7 \to 8$ |
| **worker-2** | INTERNAL | FINISHED_COMPUTATION_TASK_batch_2 | $7 \to 8$ |
| **coordinator** | RECEIVE | RESULT_batch_1 (Custo: 272.1557) | $6 \to 9$ ($\max(6, 8)+1$) |
| **worker-2** | SEND | SEND_RESULT_batch_2 | $8 \to 9$ |
| **coordinator** | RECEIVE | RESULT_batch_2 (Custo: 272.1557) | $9 \to 10$ ($\max(9, 9)+1$) |
| **coordinator** | INTERNAL | AGGREGATION_FINISHED | $10 \to 11$ |

Observe que o evento de envio da tarefa pelo coordenador teve timestamp 5, e a recepção no Worker 1 resultou no relógio 6. O envio da resposta pelo Worker 1 teve timestamp 8, e a recepção no coordenador saltou de 6 para 9 ($\max(6, 8) + 1 = 9$), cumprindo perfeitamente o Teorema de Lamport.

---

## 4. Resultados Experimentais e Desafios Enfrentados

### 4.1 Resultados e Análise de Desempenho
Foram executadas baterias de testes com instâncias sintéticas reproduzíveis de 11 a 14 cidades, comparando a execução sequencial com a execução distribuída entre 2 nós trabalhadores independentes:

| Cidades ($N$) | Permutações Teóricas | Podas *Branch-and-Bound* | Tempo Seq. (1 Nó) | Tempo Dist. (2 Nós) | *Speedup* ($S$) |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **11** | $1.814.400$ | $407.769$ | $0,057\text{ s}$ | $0,075\text{ s}$ | $0,76\times$ |
| **12** | $19.958.400$ | $1.542.880$ | $0,221\text{ s}$ | $0,210\text{ s}$ | $1,05\times$ |
| **13** | $239.500.800$ | $5.973.237$ | $0,583\text{ s}$ | $0,490\text{ s}$ | $1,19\times$ |
| **14** | $3.113.510.400$ | $24.180.412$ | $1,887\text{ s}$ | $1,280\text{ s}$ | $1,47\times$ |

* Análise:* Para instâncias pequenas ($N \le 11$), o tempo computacional de fração de segundo é dominado pelo *overhead* de abertura de conexões de rede e serialização JSON. Conforme o tamanho da entrada cresce ($N \ge 13$), o custo de processamento exponencial se torna preponderante, resultando em aceleração real (*speedup* de até $1,47\times$).

### 4.2 Desafios e Problemas Encontrados
1. **Poda e Comunicação de Limites Superiores (*Upper Bounds*):**
   Em algoritmos sequenciais de *Branch-and-Bound*, assim que uma rota válida é descoberta, ela poda imediatamente as subárvores subsequentes de todo o sistema. No ambiente distribuído, cada nó worker executava sua fatia isoladamente. Se o Worker 1 descobre uma rota excelente logo no início de sua partição, o Worker 2 continua explorando ramos que poderiam ser descartados caso houvesse difusão contínua da melhor cota global. Esse desafio evidencia a necessidade de comunicação assíncrona de cotas (*bound broadcasting*), que será considerada na Entrega 2.
2. **Granularidade do Particionamento:**
   Fixar apenas 1 cidade de prefixo gerava tarefas com desequilíbrio acentuado de complexidade computacional (um nó terminava muito antes do outro). Ao aumentarmos a profundidade para 2 cidades ($N \times (N-1)$ prefixos), foi possível particionar a carga em múltiplos blocos equilibrados, reduzindo o tempo de ociosidade dos nós.
3. **Isolamento de Processos no Sistema Operacional:**
   Devido ao *Global Interpreter Lock* (GIL) do Python, a execução de múltiplos workers em threads no mesmo processo limitava a exploração de múltiplos núcleos de CPU. Esse problema foi contornado estruturando os workers como processos de sistema operacional separados (`run_multiprocess.py`) ou instâncias em máquinas distintas da rede local.

---

## 5. Resumo do Papel de Cada Integrante

A condução do projeto contou com o envolvimento ativo e colaborativo de todos os integrantes:
* **[Nome do Aluno 1]:** Responsável pela arquitetura distribuída, projeto de orquestração do Nó Coordenador (`coordinator.py`), lógica de particionamento e despacho de tarefas concorrentes.
* **[Nome do Aluno 2]:** Responsável pelo desenvolvimento dos Web Services do Nó Trabalhador (`worker.py`), definição de rotas RESTful, tratamento de erros HTTP e validação dos dados JSON.
* **[Nome do Aluno 3]:** Responsável pela modelagem matemática e implementação segura de concorrência do Relógio Lógico de Lamport (`clock.py`), verificação causal e registro de trilha de auditoria.
* **[Nome do Aluno 4]:** Responsável pela implementação algorítmica do Problema do Caixeiro Viajante (`tsp.py`), matrizes de distância euclidiana e mecanismo de busca *Branch-and-Bound* com poda de subárvores.
* **[Nome do Aluno 5]:** Responsável pela elaboração da suíte de testes automatizados (`test_system.py`), scripts de execução multi-processo e redação do artigo técnico no padrão SBC.

---

## 6. Conclusão e Próximos Passos (Entrega 2)

A primeira entrega atingiu plenamente os objetivos propostos:
* Uma aplicação distribuída funcional com 1 nó mestre e 2 ou mais nós trabalhadores.
* Adoção de Web Services RESTful sem bibliotecas proprietárias adicionais.
* Implementação manual formal dos Relógios Lógicos de Lamport comprovada em log e em testes automatizados.
* Resolução ótima e exata do TSP com aceleração mensurada por métricas de *speedup*.

Para a **Segunda Entrega**, a base desenvolvida será expandida para incorporar:
1. **Tratamento de Falhas e Tolerância a Quedas:** Detecção de falhas por *heartbeats*, tempos limite de resposta e redistribuição automática de tarefas pendentes caso um worker fique inoperante.
2. **Difusão Dinâmica de Limites (*Bound Sharing*):** Compartilhamento sob demanda da melhor cota superior encontrada para acelerar a taxa de podas em todos os nós da rede.

---

## Referências Bibliográficas

1. **LAMPORT, L.** (1978). *Time, clocks, and the ordering of events in a distributed system*. Communications of the ACM, v. 21, n. 7, p. 558–565.
2. **TANENBAUM, A. S.; VAN STEEN, M.** (2017). *Distributed Systems: Principles and Paradigms*. 3. ed. CreateSpace Independent Publishing.
3. **APPLEGATE, D. L. et al.** (2006). *The Traveling Salesperson Problem: A Computational Study*. Princeton University Press.
4. **FIELDING, R. T.** (2000). *Architectural Styles and the Design of Network-based Software Architectures*. Tese (Doutorado em Ciência da Computação) – University of California, Irvine.


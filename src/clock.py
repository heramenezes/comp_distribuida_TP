import threading
import time
from typing import List, Dict, Any, Optional

# Classe que controla o Relogio Logico de Lamport em cada no
# Segue as 3 regras basicas que o professor pediu:
# 1. Evento local: incrementa 1
# 2. Envio: incrementa 1 e manda junto na mensagem
# 3. Recepcao: pega o maximo entre o local e o recebido + 1
class LamportClock:
    def __init__(self, node_id: str):
        self.node_id = node_id
        self._value = 0
        # lock pra evitar que duas threads mexam no contador ao mesmo tempo
        self._lock = threading.Lock()
        # guarda o historico de tudo pra gente mostrar no relatorio e no console
        self._history: List[Dict[str, Any]] = []

    def get_time(self) -> int:
        with self._lock:
            return self._value

    # Regra 1: quando acontece alguma coisa interna no no (ex: terminou de calcular)
    def tick(self, description: str = "INTERNAL_EVENT") -> int:
        with self._lock:
            old_val = self._value
            self._value += 1
            new_val = self._value
            self._record_event(
                event_type="INTERNAL",
                description=description,
                clock_before=old_val,
                clock_after=new_val,
                remote_clock=None,
                remote_node=None,
            )
            return new_val

    # Regra 2: antes de enviar qualquer mensagem pela rede
    def send_event(self, target_node: str, description: str = "SEND_MESSAGE") -> int:
        with self._lock:
            old_val = self._value
            self._value += 1
            new_val = self._value
            self._record_event(
                event_type="SEND",
                description=description,
                clock_before=old_val,
                clock_after=new_val,
                remote_clock=None,
                remote_node=target_node,
            )
            return new_val

    # Regra 3: quando chega mensagem de outro no
    def receive_event(self, sender_node: str, received_clock: int, description: str = "RECEIVE_MESSAGE") -> int:
        with self._lock:
            old_val = self._value
            # a magica de lamport: max(local, recebido) + 1
            self._value = max(self._value, received_clock) + 1
            new_val = self._value
            self._record_event(
                event_type="RECEIVE",
                description=description,
                clock_before=old_val,
                clock_after=new_val,
                remote_clock=received_clock,
                remote_node=sender_node,
            )
            return new_val

    # salva o evento numa listinha pra gente auditar depois
    def _record_event(
        self,
        event_type: str,
        description: str,
        clock_before: int,
        clock_after: int,
        remote_clock: Optional[int],
        remote_node: Optional[str],
    ) -> None:
        entry = {
            "node_id": self.node_id,
            "type": event_type,
            "description": description,
            "clock_before": clock_before,
            "clock_after": clock_after,
            "remote_clock": remote_clock,
            "remote_node": remote_node,
            "wall_time": time.strftime("%H:%M:%S", time.localtime()),
        }
        self._history.append(entry)

    def get_history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._history)

    # funcao simples pra printar bonitinho no terminal
    def format_log(self, limit: int = 10) -> str:
        with self._lock:
            lines = [f"=== HISTORICO LAMPORT - NO: {self.node_id} (Atual: {self._value}) ==="]
            for ev in self._history[-limit:]:
                if ev["type"] == "INTERNAL":
                    lines.append(f"[{ev['wall_time']}] LOCAL: {ev['description']} | Relogio: {ev['clock_before']} -> {ev['clock_after']}")
                elif ev["type"] == "SEND":
                    lines.append(f"[{ev['wall_time']}] ENVIO p/ [{ev['remote_node']}]: {ev['description']} | Relogio: {ev['clock_before']} -> {ev['clock_after']}")
                elif ev["type"] == "RECEIVE":
                    lines.append(
                        f"[{ev['wall_time']}] RECEBEU de [{ev['remote_node']}]: {ev['description']} "
                        f"| Local: {ev['clock_before']}, Msg: {ev['remote_clock']} -> Foi pra: {ev['clock_after']}"
                    )
            return "\n".join(lines)

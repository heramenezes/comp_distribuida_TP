import sys
import os
import time
import subprocess

# Script alternativo que sobe os workers como processos separados no Windows/Linux
# Bom pra testar sem o GIL do python atrapalhar as threads
def main():
    python_exe = sys.executable
    worker_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "src", "worker.py"))
    coord_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "src", "coordinator.py"))

    print("=" * 75)
    print(" INICIANDO OS WORKERS COMO PROCESSOS SEPARADOS DO SO")
    print("=" * 75)

    # Inicia Worker 1
    p_w1 = subprocess.Popen([python_exe, worker_script, "--id", "worker-1", "--port", "8001"])
    # Inicia Worker 2
    p_w2 = subprocess.Popen([python_exe, worker_script, "--id", "worker-2", "--port", "8002"])

    time.sleep(1.0) # Espera 1s pros sockets abrirem

    try:
        # Roda o coordenador
        p_coord = subprocess.run([
            python_exe, coord_script,
            "--workers", "http://127.0.0.1:8001", "http://127.0.0.1:8002",
            "--cities", "13",
            "--seed", "42",
            "--depth", "2"
        ])
    finally:
        print("\n[*] Encerrando processos dos workers...")
        p_w1.terminate()
        p_w2.terminate()
        p_w1.wait()
        p_w2.wait()
        print("[*] Processos fechados.")

if __name__ == "__main__":
    main()

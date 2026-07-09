"""
start_server.py

Script auxiliar que monta e executa o comando de inicialização do
llama-server (llama.cpp) a partir de config/models.json e
config/system_params.json, evitando digitar manualmente os parâmetros de
hardware toda vez.

Uso:
    python scripts/start_server.py --model exemplo_llama3_8b

Requer que o binário 'llama-server' esteja disponível no PATH (compilado a
partir de https://github.com/ggml-org/llama.cpp) ou informado via
--server-bin.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import ConfigError, get_model, load_system_params, fail  # noqa: E402


def build_command(server_bin: str, model_alias: str, config_dir: Path,
                   extra_log_flags: bool = True) -> list[str]:
    model_cfg = get_model(config_dir, model_alias)
    sys_params = load_system_params(config_dir, model_alias)

    cmd = [
        server_bin,
        "--model", model_cfg.gguf_path,
        "--host", model_cfg.server_host,
        "--port", str(model_cfg.server_port),
        "--ctx-size", str(sys_params.get("n_ctx", model_cfg.context_length)),
        "--threads", str(sys_params.get("n_threads", 8)),
        "--threads-batch", str(sys_params.get("n_threads_batch", 8)),
        "--n-gpu-layers", str(sys_params.get("n_gpu_layers", 0)),
        "--batch-size", str(sys_params.get("n_batch", 512)),
        "--ubatch-size", str(sys_params.get("n_ubatch", 512)),
    ]

    if sys_params.get("use_mmap", True) is False:
        cmd.append("--no-mmap")
    if sys_params.get("use_mlock", False):
        cmd.append("--mlock")
    if sys_params.get("flash_attn", True):
        cmd.extend(["--flash-attn", "on"])
    else:
        cmd.extend(["--flash-attn", "off"])

    if extra_log_flags:
        # Evita que prompts/conteúdo sensível de eventos de segurança sejam
        # ecoados no log de console do llama-server. Veja README para detalhes.
        cmd.append("--log-disable")

    return cmd


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sobe o llama-server com os parâmetros definidos em config/."
    )
    parser.add_argument("--model", required=True, help="Alias do modelo (ver config/models.json)")
    parser.add_argument("--server-bin", default="llama-server", help="Caminho do binário llama-server")
    parser.add_argument("--config-dir", type=Path, default=PROJECT_ROOT / "config")
    parser.add_argument(
        "--allow-server-logs", action="store_true",
        help="NÃO desabilita o log de conteúdo do llama-server (use com cautela; "
             "prompts com dados de eventos de segurança serão ecoados no console).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Apenas imprime o comando montado, sem executá-lo.",
    )
    args = parser.parse_args()

    try:
        cmd = build_command(
            args.server_bin, args.model, args.config_dir,
            extra_log_flags=not args.allow_server_logs,
        )
    except ConfigError as e:
        fail(str(e))
        return

    print("Comando montado:")
    print(" ".join(cmd))

    if args.dry_run:
        return

    print("\nIniciando llama-server...\n")
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()

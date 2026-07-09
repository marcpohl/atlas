"""
main.py

Ponto de entrada do classificador de eventos de segurança do Wazuh via LLM
local (llama-server) com Grammar Constrained Decoding (GBNF).

Uso básico:
    python -m src.main --data-dir data --model exemplo_llama3_8b

Veja --help para todas as opções, e o README.md para exemplos completos.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.config_loader import (
    ConfigError,
    get_model,
    load_inference_params,
    load_system_params,
    fail,
)
from src.exec_logger import ExecutionLogger
from src.llama_client import LlamaServerError, health_check, request_completion
from src.output_writer import ClassificationRecord, OutputWriter
from src.prompt_builder import build_prompt
from src.wazuh_reader import iter_events

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_GRAMMAR_PATH = PROJECT_ROOT / "grammar" / "classification.gbnf"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Classifica eventos de segurança do Wazuh (alerts.json) usando "
            "um LLM local via llama-server, com saída restrita por gramática "
            "GBNF (classificação + tática/técnica MITRE ATT&CK)."
        )
    )
    parser.add_argument(
        "--data-dir", required=True, type=Path,
        help="Pasta contendo os arquivos alerts.json a serem classificados.",
    )
    parser.add_argument(
        "--model", required=True,
        help="Alias do modelo a usar, conforme definido em config/models.json.",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=PROJECT_ROOT / "output",
        help="Pasta onde os resultados de classificação serão gravados (default: ./output).",
    )
    parser.add_argument(
        "--logs-dir", type=Path, default=PROJECT_ROOT / "logs",
        help="Pasta onde o log de execução será gravado (default: ./logs).",
    )
    parser.add_argument(
        "--output-format", choices=["jsonl", "csv"], default="jsonl",
        help="Formato do arquivo de resultados de classificação (default: jsonl).",
    )
    parser.add_argument(
        "--config-dir", type=Path, default=DEFAULT_CONFIG_DIR,
        help="Pasta com models.json, system_params.json e inference_params.json.",
    )
    parser.add_argument(
        "--grammar", type=Path, default=DEFAULT_GRAMMAR_PATH,
        help="Caminho do arquivo de gramática GBNF (default: grammar/classification.gbnf).",
    )
    parser.add_argument(
        "--file-pattern", default="*.json",
        help="Padrão glob dos arquivos de alerta na pasta de dados (default: *.json).",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limita o número de eventos processados (útil para testes rápidos).",
    )
    return parser.parse_args()


def parse_llm_output(raw_content: str) -> dict:
    """Parseia o JSON retornado pelo LLM. Graças à gramática GBNF, a saída
    é garantidamente um JSON válido conforme o schema -- mas ainda assim
    tratamos erros de forma defensiva."""
    return json.loads(raw_content)


def main() -> None:
    args = parse_args()

    # --- carregamento de configuração --------------------------------------
    try:
        model_cfg = get_model(args.config_dir, args.model)
        inference_params = load_inference_params(args.config_dir)
        # system_params carregado apenas para referência/log; quem efetivamente
        # aplica esses parâmetros é o servidor llama-server já em execução.
        _ = load_system_params(args.config_dir, args.model)
    except ConfigError as e:
        fail(str(e))
        return

    if not args.grammar.exists():
        fail(f"Arquivo de gramática não encontrado: {args.grammar}")
        return
    grammar_text = args.grammar.read_text(encoding="utf-8")

    # --- checagem do servidor -----------------------------------------------
    print(f"Verificando disponibilidade do llama-server em {model_cfg.server_url} ...")
    if not health_check(model_cfg.server_url):
        fail(
            f"llama-server não respondeu em {model_cfg.server_url}/health. "
            f"Verifique se o servidor está rodando (veja scripts/start_server.py "
            f"ou docker-compose.yml) e se o modelo '{args.model}' está "
            f"configurado na porta correta em config/models.json."
        )
        return
    print("llama-server disponível. Iniciando classificação...\n")

    # --- processamento --------------------------------------------------------
    processed = 0
    failed = 0

    try:
        events = iter_events(args.data_dir, args.file_pattern)
    except FileNotFoundError as e:
        fail(str(e))
        return

    with OutputWriter(args.output_dir, args.output_format) as writer, \
         ExecutionLogger(args.logs_dir) as exec_logger:

        for event in events:
            if args.limit is not None and processed + failed >= args.limit:
                break

            prompt = build_prompt(event, model_cfg.chat_format)

            try:
                result = request_completion(
                    server_url=model_cfg.server_url,
                    prompt=prompt,
                    grammar=grammar_text,
                    inference_params=inference_params,
                )
            except LlamaServerError as e:
                print(f"[ERRO] Falha ao classificar evento {event.event_id}: {e}")
                exec_logger.log(
                    model_name=args.model,
                    prompt=prompt,
                    input_tokens=0,
                    output_tokens=0,
                    event_id=event.event_id,
                    error=str(e),
                )
                failed += 1
                continue

            exec_logger.log(
                model_name=args.model,
                prompt=prompt,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                event_id=event.event_id,
            )

            try:
                parsed = parse_llm_output(result.content)
            except (json.JSONDecodeError, TypeError) as e:
                print(
                    f"[ERRO] Resposta do modelo não pôde ser interpretada como "
                    f"JSON para o evento {event.event_id}: {e}\n"
                    f"Conteúdo bruto: {result.content!r}"
                )
                failed += 1
                continue

            record = ClassificationRecord(
                event_id=event.event_id,
                rule_id=event.rule_id,
                source_file=event.source_file,
                event_timestamp=event.timestamp,
                classification=parsed.get("classification", "Needs_Investigation"),
                mitre_tactic=parsed.get("mitre_tactic", "Not_Applicable"),
                mitre_technique=parsed.get("mitre_technique", "N/A"),
                confidence=float(parsed.get("confidence", 0.0)),
                reasoning=parsed.get("reasoning", ""),
                model_name=args.model,
                classified_at=datetime.now(timezone.utc).isoformat(),
            )
            writer.write(record)
            processed += 1

    print(f"\nConcluído. {processed} evento(s) classificado(s), {failed} falha(s).")
    print(f"Resultados: {args.output_dir}")
    print(f"Log de execução: {args.logs_dir / 'execution_log.jsonl'}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.")
        sys.exit(130)

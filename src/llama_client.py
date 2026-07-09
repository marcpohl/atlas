"""
llama_client.py

Cliente HTTP para o llama-server (llama.cpp), responsável por:
  - checar se o servidor está no ar (/health)
  - enviar requisições ao endpoint /completion com a gramática GBNF anexada
  - aplicar timeout e retry configuráveis
  - devolver o texto gerado junto com a contagem de tokens de entrada/saída
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests


class LlamaServerError(Exception):
    """Erro de comunicação com o llama-server (timeout, conexão, HTTP, etc.)."""


@dataclass
class CompletionResult:
    content: str
    input_tokens: int
    output_tokens: int
    total_tokens: int


def health_check(server_url: str, connect_timeout: float = 5.0) -> bool:
    """Verifica se o llama-server está respondendo no endpoint /health."""
    try:
        resp = requests.get(f"{server_url}/health", timeout=connect_timeout)
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False


def request_completion(
    server_url: str,
    prompt: str,
    grammar: str,
    inference_params: dict,
) -> CompletionResult:
    """Envia o prompt ao endpoint /completion do llama-server, com a
    gramática GBNF aplicada, respeitando timeout e retry configurados em
    inference_params. Lança LlamaServerError se todas as tentativas falharem.
    """
    payload = {
        "prompt": prompt,
        "grammar": grammar,
        "temperature": inference_params.get("temperature", 0.2),
        "top_p": inference_params.get("top_p", 0.9),
        "top_k": inference_params.get("top_k", 40),
        "min_p": inference_params.get("min_p", 0.05),
        "repeat_penalty": inference_params.get("repeat_penalty", 1.1),
        "n_predict": inference_params.get("max_tokens", 400),
        "seed": inference_params.get("seed", -1),
        "cache_prompt": True,
    }

    request_timeout = inference_params.get("request_timeout_seconds", 120)
    connect_timeout = inference_params.get("connect_timeout_seconds", 10)
    max_retries = inference_params.get("max_retries", 2)
    backoff = inference_params.get("retry_backoff_seconds", 3)

    last_error: Exception | None = None

    for attempt in range(1, max_retries + 2):  # tentativa inicial + retries
        try:
            resp = requests.post(
                f"{server_url}/completion",
                json=payload,
                timeout=(connect_timeout, request_timeout),
            )
            resp.raise_for_status()
            data = resp.json()

            content = data.get("content", "")
            input_tokens = data.get("tokens_evaluated", 0)
            output_tokens = data.get("tokens_predicted", 0)

            return CompletionResult(
                content=content,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            )

        except requests.exceptions.Timeout as e:
            last_error = e
            print(
                f"[AVISO] Timeout na tentativa {attempt}/{max_retries + 1} "
                f"ao chamar {server_url}/completion"
            )
        except requests.exceptions.RequestException as e:
            last_error = e
            print(
                f"[AVISO] Erro de requisição na tentativa "
                f"{attempt}/{max_retries + 1}: {e}"
            )
        except ValueError as e:  # JSON de resposta inválido
            last_error = e
            print(
                f"[AVISO] Resposta inválida (não-JSON) do llama-server na "
                f"tentativa {attempt}/{max_retries + 1}: {e}"
            )

        if attempt <= max_retries:
            time.sleep(backoff * attempt)

    raise LlamaServerError(
        f"Falha ao obter resposta de {server_url}/completion após "
        f"{max_retries + 1} tentativa(s). Último erro: {last_error}"
    )

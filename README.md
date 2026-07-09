# Classificador de Eventos de Segurança do Wazuh via LLM Local (llama.cpp + GBNF)

Ferramenta em Python que classifica eventos de segurança extraídos do
`alerts.json` do Wazuh usando um modelo de linguagem local, servido via
**llama-server** (llama.cpp), com a saída restrita por uma **gramática GBNF**
(Grammar Constrained Decoding) que força o modelo a responder sempre em um
JSON válido contendo classificação, tática/técnica MITRE ATT&CK e nível de
confiança.

---

## Índice

1. [Arquitetura](#arquitetura)
2. [Requisitos](#requisitos)
3. [Instalação dos modelos (GGUF)](#instalação-dos-modelos-gguf)
4. [Subindo o llama-server](#subindo-o-llama-server)
5. [Instalação do classificador Python](#instalação-do-classificador-python)
6. [Configuração](#configuração)
7. [Exemplos de uso](#exemplos-de-uso)
8. [Formato dos arquivos de saída](#formato-dos-arquivos-de-saída)
9. [A gramática GBNF](#a-gramática-gbnf)
10. [Segurança e privacidade dos logs](#segurança-e-privacidade-dos-logs)
11. [Estrutura do projeto](#estrutura-do-projeto)
12. [Solução de problemas](#solução-de-problemas)

---

## Arquitetura

```
┌──────────────────┐        HTTP        ┌───────────────────────┐
│  Classificador    │ ─────────────────▶ │   llama-server         │
│  Python (main.py) │  /completion +     │   (llama.cpp)          │
│                    │  grammar (GBNF)    │   modelo .gguf carregado│
└──────────────────┘ ◀───────────────── └───────────────────────┘
         │
         ├── lê:   data/alerts.json  (eventos do Wazuh, evento a evento)
         ├── grava: output/classifications.jsonl (ou .csv)
         └── grava: logs/execution_log.jsonl (prompt completo + tokens)
```

O classificador **não pré-processa** os logs em disco: cada evento do
`alerts.json` é lido, um prompt é montado a partir dos campos relevantes, e
enviado diretamente ao `llama-server` evento a evento. Essa decisão foi
tomada para manter a solução simples; veja [Solução de problemas](#solução-de-problemas)
para orientações caso o volume de eventos cresça e um pré-processamento
(deduplicação, agrupamento) passe a ser necessário no futuro.

O `llama-server` roda **um modelo por instância** (uma porta = um modelo
carregado). Isso é refletido em `config/models.json`, onde cada modelo
registrado aponta para um host:porta específico.

---

## Requisitos

- Linux
- Python 3.12+
- `llama-server` (binário do [llama.cpp](https://github.com/ggml-org/llama.cpp)) **ou** Docker, para rodá-lo em container
- Um ou mais modelos no formato `.gguf`
- GPU NVIDIA (opcional, mas recomendada para desempenho)

---

## Instalação dos modelos (GGUF)

O `llama-server` só executa modelos no formato **GGUF**. Se você tem um
modelo em outro formato (ex.: safetensors do Hugging Face), ele precisa ser
convertido antes.

### Opção 1: baixar um GGUF já pronto (mais simples)

A comunidade [TheBloke](https://huggingface.co/TheBloke) e o próprio
[Hugging Face](https://huggingface.co/models?library=gguf) hospedam milhares
de modelos já convertidos e quantizados. Passos:

1. Acesse o Hugging Face e busque pelo modelo desejado + `GGUF`
   (ex.: `Meta-Llama-3-8B-Instruct-GGUF`).
2. Escolha o nível de quantização conforme sua VRAM/RAM disponível:

   | Quantização | Qualidade | Tamanho aproximado (modelo 8B) | Uso recomendado |
   |---|---|---|---|
   | Q8_0 | Muito próxima do original | ~8.5 GB | GPUs com bastante VRAM |
   | Q5_K_M | Boa, recomendada para produção | ~5.7 GB | Equilíbrio qualidade/tamanho |
   | Q4_K_M | Aceitável, mais leve | ~4.9 GB | VRAM/RAM limitada |
   | Q3_K_M | Degradação perceptível | ~3.8 GB | Apenas se necessário |

3. Baixe o arquivo `.gguf` (ex. via `wget` ou `huggingface-cli download`) para
   uma pasta local, por exemplo `/models/`.

```bash
pip install -U "huggingface_hub[cli]"
huggingface-cli download bartowski/Meta-Llama-3-8B-Instruct-GGUF \
    meta-llama-3-8b-instruct-Q4_K_M.gguf \
    --local-dir /models
```

### Opção 2: converter e quantizar você mesmo

Necessário se você tem um modelo fine-tunado próprio ou quer uma
quantização específica não disponível pronta.

```bash
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp
pip install -r requirements.txt

# Converte de safetensors/HF para GGUF (fp16, sem quantizar ainda)
python convert_hf_to_gguf.py /caminho/do/modelo/hf --outfile /models/modelo-fp16.gguf

# Compila o llama.cpp (necessário para o binário 'quantize')
cmake -B build
cmake --build build --config Release -j

# Quantiza (exemplo: Q4_K_M)
./build/bin/llama-quantize /models/modelo-fp16.gguf /models/modelo-Q4_K_M.gguf Q4_K_M
```

### Registrando o modelo no projeto

Depois de ter o `.gguf` em disco, edite `config/models.json` e adicione uma
entrada (veja [Configuração](#configuração) para detalhes de cada campo).

---

## Subindo o llama-server

Você tem duas opções: **nativo** (binário compilado) ou **container**.

### Opção A — Nativo

```bash
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp

# Com suporte a GPU NVIDIA (CUDA):
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release -j

# Ou apenas CPU:
# cmake -B build
# cmake --build build --config Release -j

# Adicione build/bin ao PATH, ou copie o binário llama-server para /usr/local/bin
export PATH=$PATH:$(pwd)/build/bin
```

Depois, use o script auxiliar do projeto para subir o servidor já com os
parâmetros de `config/system_params.json` aplicados:

```bash
python scripts/start_server.py --model exemplo_llama3_8b
```

Isso monta e executa o comando `llama-server` com `--ctx-size`, `--threads`,
`--n-gpu-layers`, `--batch-size` etc. já preenchidos a partir do arquivo de
configuração, e aplica `--log-disable` por padrão (ver
[Segurança e privacidade dos logs](#segurança-e-privacidade-dos-logs)).

Para ver o comando sem executá-lo:

```bash
python scripts/start_server.py --model exemplo_llama3_8b --dry-run
```

### Opção B — Container (Docker Compose)

Recomendado se você quer isolar as dependências pesadas do llama.cpp
(drivers CUDA, toolchain de build) do restante do sistema, ou for subir o
servidor em uma máquina diferente da que roda o classificador.

```bash
cp .env.example .env
# edite .env com o caminho dos seus modelos e parâmetros de hardware

# Com GPU NVIDIA (requer NVIDIA Container Toolkit):
docker compose --profile gpu up -d llama-server-gpu

# Ou CPU-only:
docker compose --profile cpu up -d llama-server-cpu
```

Verifique se subiu corretamente:

```bash
curl http://localhost:8080/health
```

---

## Instalação do classificador Python

```bash
cd wazuh_llm_classifier
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

A única dependência externa é `requests`.

---

## Configuração

Três arquivos em `config/`:

### `models.json` — modelos instalados

```json
{
  "models": {
    "meu_llama3": {
      "gguf_path": "/models/llama-3-8b-instruct.Q4_K_M.gguf",
      "server_host": "127.0.0.1",
      "server_port": 8080,
      "chat_format": "llama-3",
      "context_length": 8192,
      "description": "Llama 3 8B Instruct, Q4_K_M"
    }
  }
}
```

- `chat_format`: como o prompt system/user é formatado para esse modelo.
  Suportados: `llama-3`, `mistral`, `chatml`, `gemma`, `raw` (concatenação
  simples, sem tags — use para modelos sem template conhecido).
- Cada modelo = uma instância do `llama-server` rodando em `server_host:server_port`.
  Para usar dois modelos, suba dois servidores em portas diferentes e
  registre ambos aqui.

### `system_params.json` — parâmetros de hardware (usados para subir o servidor)

Controla `n_ctx`, `n_threads`, `n_gpu_layers`, `n_batch`, `n_ubatch`,
`use_mmap`, `use_mlock`, `flash_attn`. Tem uma seção `defaults` (aplicada a
todos os modelos) e `overrides` (por alias de modelo, caso um modelo
específico precise de parâmetros diferentes, ex.: rodar em CPU enquanto os
demais usam GPU).

### `inference_params.json` — parâmetros de inferência (enviados por requisição)

Controla `temperature`, `top_p`, `top_k`, `min_p`, `repeat_penalty`,
`max_tokens`, `seed`, além dos parâmetros do **cliente HTTP**:
`request_timeout_seconds`, `connect_timeout_seconds`, `max_retries`,
`retry_backoff_seconds`.

> `temperature` está configurada em `0.2` por padrão — valor baixo é
> recomendado para classificação, priorizando consistência sobre
> criatividade.

---

## Exemplos de uso

### 1. Fluxo básico

```bash
# 1. Suba o servidor (nativo ou container — ver seções acima)
python scripts/start_server.py --model meu_llama3

# 2. Coloque seus arquivos alerts.json na pasta data/
cp /var/ossec/logs/alerts/alerts.json data/

# 3. Rode o classificador
python -m src.main --data-dir data --model meu_llama3
```

Saída esperada no console:
```
Verificando disponibilidade do llama-server em http://127.0.0.1:8080 ...
llama-server disponível. Iniciando classificação...

[True_Positive] evento=1719999999.123457 rule=5712 tactic=Credential_Access technique=T1110 confidence=0.95 modelo=meu_llama3
[Benign] evento=1719999999.123458 rule=100002 tactic=Not_Applicable technique=N/A confidence=0.88 modelo=meu_llama3

Concluído. 2 evento(s) classificado(s), 0 falha(s).
Resultados: output
Log de execução: logs/execution_log.jsonl
```

### 2. Testar rapidamente com poucos eventos

```bash
python -m src.main --data-dir data --model meu_llama3 --limit 5
```

### 3. Gerar saída em CSV em vez de JSONL

```bash
python -m src.main --data-dir data --model meu_llama3 --output-format csv
```

### 4. Usar pastas de saída customizadas (ex.: separar por execução/data)

```bash
python -m src.main \
  --data-dir data \
  --model meu_llama3 \
  --output-dir output/2026-06-15 \
  --logs-dir logs/2026-06-15
```

### 5. Comparar dois modelos no mesmo lote de eventos

```bash
# Suba os dois servidores em portas diferentes (registrados em models.json)
python scripts/start_server.py --model meu_llama3 &
python scripts/start_server.py --model meu_mistral &

# Rode o classificador duas vezes, uma para cada modelo, com saídas separadas
python -m src.main --data-dir data --model meu_llama3  --output-dir output/llama3
python -m src.main --data-dir data --model meu_mistral --output-dir output/mistral
```

### 6. Filtrar arquivos de alerta por padrão de nome

Se sua pasta `data/` tiver múltiplos arquivos e você quiser processar
apenas alguns:

```bash
python -m src.main --data-dir data --model meu_llama3 --file-pattern "alerts-2026-06*.json"
```

### 7. Ver todas as opções disponíveis

```bash
python -m src.main --help
```

---

## Formato dos arquivos de saída

### `output/classifications.jsonl` (ou `.csv`)

Um registro por evento classificado:

```json
{
  "event_id": "1719999999.123457",
  "rule_id": "5712",
  "source_file": "alerts.json",
  "event_timestamp": "2026-06-15T14:23:05.000-0300",
  "classification": "True_Positive",
  "mitre_tactic": "Credential_Access",
  "mitre_technique": "T1110",
  "confidence": 0.95,
  "reasoning": "Múltiplas tentativas de login SSH falhas para usuário inexistente, padrão de força bruta.",
  "model_name": "meu_llama3",
  "classified_at": "2026-06-15T17:23:07.769860+00:00"
}
```

### `logs/execution_log.jsonl`

Um registro por chamada ao LLM (inclui o **prompt completo** enviado —
veja a seção de [segurança](#segurança-e-privacidade-dos-logs)):

```json
{
  "timestamp": "2026-06-15T17:23:07.770529+00:00",
  "model_name": "meu_llama3",
  "event_id": "1719999999.123457",
  "input_tokens": 767,
  "output_tokens": 51,
  "total_tokens": 818,
  "prompt": "<|begin_of_text|><|start_header_id|>system<|end_header_id|>..."
}
```

Em caso de falha (timeout, erro de conexão), o registro inclui um campo
adicional `"error"` com a mensagem, e `input_tokens`/`output_tokens` ficam
zerados.

---

## A gramática GBNF

Arquivo: `grammar/classification.gbnf`. Restringe a saída do modelo a:

```json
{
  "classification": "True_Positive | False_Positive | Benign | Needs_Investigation",
  "mitre_tactic": "<uma das 14 táticas MITRE ATT&CK Enterprise, ou Not_Applicable>",
  "mitre_technique": "T#### ou T####.### (validado por padrão, não por lista fechada) ou N/A",
  "confidence": "0.00 a 1.00",
  "reasoning": "<texto livre, até 500 caracteres>"
}
```

**Por que a técnica não é um enum fechado:** o MITRE ATT&CK Enterprise tem
mais de 200 técnicas (400+ contando sub-técnicas). Um enum fechado seria
grande, difícil de manter atualizado, e exigiria alterar a gramática toda
vez que o framework fosse revisado. Em vez disso, a gramática valida apenas
o **formato** do ID (`T` + 4 dígitos + sub-técnica opcional), e a
responsabilidade de escolher a técnica correta fica com o modelo, guiado
pelo prompt. Isso é uma escolha de simplicidade/manutenibilidade — se no
futuro você quiser restringir a um subconjunto específico de técnicas
relevantes ao seu ambiente, edite a regra `technique` em
`grammar/classification.gbnf` para um enum fechado.

**Compatibilidade:** a gramática usa o operador de repetição `{0,500}`
(disponível em builds recentes do llama.cpp). Se seu build for mais antigo
e o carregamento da gramática falhar, há uma alternativa comentada ao final
do próprio arquivo `.gbnf`.

---

## Segurança e privacidade dos logs

Dois pontos de atenção, já tratados por padrão no projeto:

1. **Log de console do `llama-server`**: por padrão, o `llama-server` pode
   ecoar o conteúdo dos prompts recebidos em stdout. Como os prompts aqui
   contêm trechos de logs de segurança (potencialmente sensíveis — IPs,
   usuários, comandos executados), o `scripts/start_server.py` já inclui a
   flag `--log-disable` por padrão. Se você subir o servidor manualmente
   (sem o script auxiliar) ou via `docker-compose.yml`, confirme que essa
   flag está presente no comando.

2. **`logs/execution_log.jsonl`**: por decisão de projeto, este arquivo
   grava o **prompt completo** de cada chamada (incluindo os dados do
   evento do Wazuh), para fins de auditoria e rastreamento de custo de
   tokens. Isso significa que esse arquivo tem, na prática, o mesmo nível
   de sensibilidade dos logs originais do Wazuh. Recomendações:
   - Restrinja as permissões da pasta `logs/` (ex.: `chmod 700 logs/`).
   - Trate `logs/` e `output/` como diretórios sensíveis em qualquer
     política de backup/retenção que você já aplique aos logs do Wazuh.
   - Ambos os diretórios já estão no `.gitignore` do projeto — não serão
     versionados por engano.

---

## Estrutura do projeto

```
wazuh_llm_classifier/
├── config/
│   ├── models.json           # modelos GGUF instalados
│   ├── system_params.json    # parâmetros de hardware (para subir o servidor)
│   └── inference_params.json # parâmetros de inferência + timeout/retry
├── grammar/
│   └── classification.gbnf   # gramática GBNF (Grammar Constrained Decoding)
├── src/
│   ├── config_loader.py      # carrega e valida as configurações
│   ├── wazuh_reader.py       # lê alerts.json evento a evento
│   ├── prompt_builder.py     # monta o prompt (system+user) por chat_format
│   ├── llama_client.py       # cliente HTTP do llama-server (timeout/retry)
│   ├── output_writer.py      # grava classifications.jsonl/csv
│   ├── exec_logger.py        # grava execution_log.jsonl
│   └── main.py                # orquestração / CLI
├── scripts/
│   └── start_server.py       # monta e sobe o llama-server a partir das configs
├── data/                      # pasta de entrada (informada via --data-dir)
├── output/                    # resultados de classificação (gerado em runtime)
├── logs/                      # log de execução (gerado em runtime)
├── docker-compose.yml         # llama-server em container (GPU ou CPU)
├── .env.example
├── requirements.txt
└── README.md
```

---

## Solução de problemas

**`llama-server não respondeu em .../health`**
Confirme que o servidor está de fato rodando (`curl http://host:porta/health`)
e que `server_host`/`server_port` em `config/models.json` batem com onde o
servidor foi iniciado.

**Erro ao carregar a gramática (`--grammar`) no llama-server**
Provavelmente seu build do llama.cpp é anterior ao suporte de repetição
`{m,n}` no GBNF. Veja a alternativa comentada ao final de
`grammar/classification.gbnf`.

**Resposta do modelo não é JSON válido, mesmo com a gramática**
Isso não deveria acontecer (a gramática força a estrutura), mas se ocorrer,
confira se o `--grammar` foi realmente aplicado na chamada — o cliente
Python envia a gramática a cada requisição via campo `"grammar"` no payload
de `/completion`; confirme na sua versão do llama-server que esse campo é
suportado (é padrão em versões recentes).

**Processamento muito lento / volume de eventos muito grande**
A solução atual classifica evento a evento, sem pré-processamento, por
decisão de simplicidade. Se o volume crescer a ponto de isso se tornar um
gargalo, os pontos de extensão mais naturais são: (a) deduplicar eventos
idênticos antes de enviar ao modelo, (b) agrupar eventos correlacionados
num único prompt (respeitando `n_ctx`), ou (c) paralelizar chamadas ao
`llama-server` (com cautela: aumenta uso de VRAM/RAM e pode exigir
`--parallel` no `llama-server`).

**Quero limitar o tamanho do campo `reasoning`**
Já é limitado a 500 caracteres pela própria gramática (rule `reasoning`).
Para reduzir mais, ajuste o `{0,500}` em `grammar/classification.gbnf` e/ou
o `max_tokens` em `config/inference_params.json`.

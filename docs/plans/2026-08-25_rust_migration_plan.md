# Plano de Migração para Rust

## Forza Motorsport Results Extractor

## 1. Objetivo

Reimplementar o projeto em Rust, produzindo uma versão funcionalmente equivalente à versão Python atual.

O projeto é também um experimento de aprendizado. A migração deve permitir avaliar Rust em um aplicativo desktop real, com processamento de imagens, chamadas HTTP para um LLM local, SQLite, exportação de relatórios e GUI.

A equivalência será avaliada principalmente no nível observável pelo usuário:

- a GUI deve abrir e apresentar as mesmas áreas funcionais;
- o banco deve representar os mesmos conceitos e relações;
- o pipeline deve processar as mesmas entradas;
- as regras de domínio devem manter o mesmo significado;
- revisão, rebuild, melhores voltas e exportação devem continuar disponíveis;
- com a mesma entrada, os PDFs devem apresentar uma lista equivalente de resultados.

Não é objetivo preservar a implementação interna Python. A versão Rust pode reorganizar algoritmos, tipos, concorrência e acesso ao banco quando isso produzir uma solução mais adequada à linguagem.

## 2. Princípios da migração

### 2.1 Preservar contratos, não código

Os contratos criados durante o desenvolvimento Python devem ser tratados como conhecimento do domínio e da aplicação, independentemente da linguagem:

- nomes e significado dos campos persistidos;
- valores e semântica dos enums;
- regras de validação;
- estados de execução;
- motivos de revisão;
- formato das configurações;
- argumentos e comportamento dos comandos CLI;
- formato dos exports;
- relações e constraints do SQLite;
- eventos e estados utilizados pela GUI.

As classes Python, heranças de SQLModel, `QObject`, `QThread` e `QAbstractTableModel` não precisam ser copiadas literalmente.

### 2.2 Preservar a modularização

A separação atual é uma decisão arquitetural acumulada e deve continuar existindo. Arquivos grandes e módulos com responsabilidades misturadas devem ser evitados também em Rust.

Cada módulo deve ter:

- uma responsabilidade principal;
- uma API pública pequena;
- tipos explícitos para entrada e saída;
- testes próximos da regra que implementa;
- dependências direcionadas para dentro, evitando ciclos.

### 2.3 GUI e SQLite são partes centrais

O primeiro fluxo completo não será apenas uma CLI. A GUI e o acesso ao banco devem ser validados cedo, porque o desempenho observado no projeto é principalmente o tempo para abrir a interface e carregar a lista de imagens.

### 2.4 Migração incremental com executáveis funcionais

Cada fase deve produzir uma parte executável e testável. A versão Python continuará servindo como referência durante a implementação, mas não será necessário manter compatibilidade operacional permanente com a DB antiga.

Decisão registrada: o banco da versão Rust será sempre criado do zero pela própria aplicação. Bancos criados pelo Python não serão abertos pela versão Rust em operação; eles permanecem apenas como material de validação comparativa, usado em somente leitura para fixtures, testes do doctor e comparações entre os dois sistemas.

### 2.5 Validação proporcional ao objetivo

Não será feita uma validação byte a byte de PDFs. Para uma entrada equivalente, serão gerados os PDFs Python e Rust e será verificado se a lista de resultados é equivalente.

### 2.6 Decisões de dependências e artefatos

As seguintes decisões ficam explícitas:

- `configparser` será a biblioteca INI escolhida, por ser próxima do modelo mental do `configparser` Python;
- a biblioteca de PDF será escolhida por um spike entre `genpdf` e `printpdf`; `genpdf` será a primeira candidata por oferecer layout de parágrafos, tabelas e quebra de página, enquanto `printpdf` permanecerá disponível para controle de baixo nível; observar que `genpdf` 0.2 depende internamente de `printpdf` 0.5, cuja API difere do `printpdf` 0.12 listado nas dependências — as duas opções são avaliadas como bibliotecas independentes;
- `r2d2` + `r2d2_sqlite` serão usados para o acesso concorrente ao SQLite, com escritas coordenadas pelo application layer;
- o cliente LM Studio usará `async fn` nativo em traits enquanto os backends puderem ser passados como tipos genéricos; `async-trait` só será adicionado se dispatch dinâmico com `Box<dyn LlmBackend>` se tornar necessário;
- arquivos `.slint` externos serão compilados por `slint-build` em `build.rs`;
- o reparo de JSON será escolhido por fixtures reais entre uma crate compatível, como `llm_json`/`jsonrepair`, e um porte/complemento da lógica Python `json-repair`;
- a GUI usará Slint sob a licença royalty-free para aplicações desktop, decisão compatível com a distribuição pretendida; essa escolha deve ser registrada nas notas de licença do empacotamento;
- referências estáveis como `cars.txt`, `tracks.txt` e `track_aliases.json` ficarão em `assets/` e serão embutidas no binário;
- fixtures pequenas e não sensíveis ficarão no repositório Rust, em `fixtures/`; screenshots grandes ou dados pessoais ficarão fora do Git e serão documentados em `fixtures/README.md`.

## 3. Escopo funcional

### 3.1 Funcionalidades que devem permanecer

- descoberta de screenshots;
- identificação de arquivos novos, processados e duplicados;
- inspeção de metadados e hash de arquivos;
- preparação e codificação de imagens;
- comunicação com LM Studio;
- reparo e validação de respostas JSON;
- normalização de nomes de carros e pistas;
- conversão e formatação de tempos;
- identificação de classe, clima, temperatura e volta suja;
- execução e acompanhamento de runs;
- persistência de resultados, tentativas e artefatos;
- revisão manual;
- correções e rebuild sem nova chamada desnecessária ao modelo;
- referências de carros e pistas;
- cálculo de melhores voltas;
- importação de registros externos;
- diagnóstico do banco;
- exportação CSV;
- geração do relatório PDF;
- dashboard e análise de Performance, incluindo a lógica de detecção de recarga do modelo;
- configurações `.ini`;
- CLI e GUI;
- logs, progresso, cancelamento e tratamento de erros.

### 3.2 Funcionalidades que podem mudar internamente

- SQLModel pode ser substituído por SQL direto ou outro acesso tipado ao SQLite;
- PySide6 pode ser substituído por Slint;
- `requests` pode ser substituído por `reqwest`;
- workers Qt podem ser substituídos por threads, canais e tarefas Tokio;
- serviços podem ser agrupados de forma diferente, desde que suas responsabilidades permaneçam claras;
- o sistema de migrations pode deixar de usar Alembic, desde que a versão do schema seja controlada de forma explícita;
- o algoritmo de carregamento da lista pode ser otimizado com consultas específicas, paginação ou carregamento incremental.

## 4. Arquitetura Rust proposta

O projeto será um workspace Cargo. A divisão abaixo preserva os limites arquiteturais do Python sem obrigar uma tradução arquivo a arquivo.

```text
forza-rust/
├── Cargo.toml
├── crates/
│   ├── forza-domain/
│   ├── forza-config/
│   ├── forza-db/
│   ├── forza-pipeline/
│   ├── forza-lmstudio/
│   ├── forza-output/
│   ├── forza-app/
│   ├── forza-cli/
│   └── forza-gui/
├── assets/
│   ├── cars.txt
│   ├── tracks.txt
│   └── track_aliases.json
├── fixtures/
│   ├── images/
│   ├── model_responses/
│   ├── python_outputs/
│   └── expected/
└── docs/
    ├── contracts.md
    ├── database.md
    └── benchmark.md
```

Os arquivos em `assets/` são fontes versionadas. No build, serão incorporados com `include_str!()` ou por uma etapa equivalente, de modo que a aplicação não dependa do diretório de execução para encontrar as referências. Caso no futuro seja necessário permitir edição pelo usuário, essa será uma configuração explícita de runtime, separada dos assets embutidos.

A separação por crate deve ser mantida quando houver fronteira arquitetural real. Se um crate se tornar apenas um agrupamento artificial, ele poderá ser consolidado sem perder a separação dos módulos internos.

### 4.1 `forza-domain`

Crate sem acesso a filesystem, rede, GUI ou SQLite. Deve concentrar regras puras e tipos de negócio.

Módulos sugeridos:

```text
src/
├── enums.rs
├── lap.rs
├── race_class.rs
├── normalizer.rs
├── ordering.rs
├── review_rules.rs
├── text_utils.rs
├── reference_data.rs
├── schemas.rs
├── events.rs
├── errors.rs
└── lib.rs
```

Tipos principais:

- `LapRecord`;
- `RaceSession`;
- `ImageMetadata`;
- `ExtractionResult`;
- `ReviewCase`;
- `ImageFile`;
- `ExtractionRun`;
- `ExportLap`;
- `ExternalLapRecord`;
- `ModelExtractionAttempt`;
- `ModelRequestMetadata`;
- `ModelResponseStats`.

Regras a portar e testar:

- `parse_lap_time_ms`;
- `format_lap_time_ms`;
- `is_dirty_lap`;
- `strip_dirty_symbol`;
- `sanitize_driver_name`;
- normalização de clima;
- conversão Fahrenheit/Celsius;
- extração e detecção de classe;
- normalização de carros e pistas;
- ordenação de classes, pistas e voltas;
- sugestões e motivos de revisão;
- comparação Unicode e normalização ASCII.

Enums que são persistidos ou enviados para a GUI devem ter representação explícita. Não se deve depender da ordem automática dos variantes Rust.

### 4.2 `forza-config`

Responsável pelo `.ini`, defaults e validação.

Tipos:

- `AppConfig`;
- `LLMConfig`;
- `ImageConfig`;
- `ValidationConfig`;
- `PDFConfig`;
- `PromptConfig`.

Requisitos:

- manter as chaves atuais;
- manter defaults existentes;
- produzir erros com arquivo, seção e chave quando possível;
- permitir validação independente da GUI;
- oferecer `config-check` pela CLI;
- documentar diferenças inevitáveis entre `configparser` e a biblioteca INI escolhida.

### 4.3 `forza-db`

Responsável pelo schema, migrations, conexões, transações e queries.

Módulos:

```text
src/
├── connection.rs
├── schema.rs
├── migration.rs
├── entities.rs
├── repositories/
│   ├── images.rs
│   ├── laps.rs
│   ├── runs.rs
│   ├── reviews.rs
│   ├── review_corrections.rs
│   ├── model_results.rs
│   ├── image_flags.rs
│   ├── external_records.rs
│   ├── references.rs
│   ├── artifacts.rs
│   ├── frontier.rs
│   └── run_inputs.rs
├── gui_queries.rs
├── doctor.rs
└── lib.rs
```

Tabelas e relações devem ser conferidas diretamente contra as entidades e migrations Python. O schema Rust deve manter inicialmente:

- nomes de tabelas e colunas;
- tipos SQLite efetivos;
- índices;
- unicidade;
- foreign keys;
- `ON DELETE`;
- check constraints;
- defaults relevantes;
- representação de JSON, enums, UUIDs e timestamps.

Além da estrutura física, a auditoria deve registrar os invariantes persistidos:

- índices únicos parciais e suas cláusulas `WHERE`;
- triggers e check constraints que representam regras de negócio;
- cada ação `ON DELETE` (`CASCADE`, `RESTRICT` ou `SET NULL`) por foreign key;
- defaults e combinações válidas de estados.

Os índices `idx_attempts_one_accepted_per_result` e `idx_runtime_one_preflight_per_run`, por exemplo, devem ser tratados como regras de integridade, não como simples otimizações.

O Rust usará uma tabela `schema_version` própria ou `PRAGMA user_version`, escolhendo uma única estratégia antes da primeira execução. Essa versão controla o schema Rust e não precisa reproduzir a tabela `alembic_version` internamente. A decisão deve ser testada em banco vazio e documentada.

Como a aplicação Rust cria sempre seu banco do zero, não existe caminho suportado para abrir um banco legado criado pelo Python. A manutenção dos mesmos nomes de tabelas e colunas existe para viabilizar a validação comparativa, os testes de contrato e eventuais ferramentas de diff entre os dois sistemas — não a coexistência operacional.

Na primeira versão Rust, “schema compatível” significa manter os contratos persistidos externamente: tabelas, colunas, tipos SQLite efetivos, relações, constraints e representação dos valores relevantes. A implementação interna pode usar entidades Rust diferentes, repositories diferentes e migrations sem Alembic. Melhorias incompatíveis no schema ficam fora do primeiro marco de equivalência.

O acesso concorrente usará um pool `r2d2_sqlite` para leituras e operações curtas. Escritas e transações que alteram múltiplas entidades serão coordenadas por uma camada de persistência, respeitando o modelo de escritor único do SQLite.

Toda conexão do pool será inicializada com `PRAGMA journal_mode=WAL`, `busy_timeout` configurado e `foreign_keys=ON`. O WAL permite que a GUI leia durante escritas do pipeline sem bloquear; o timeout cobre contenção transitória de escrita; `foreign_keys=ON` preserva a integridade referencial que as entities Python já dependem implicitamente via SQLite. Essas configurações fazem parte do contrato de conexão e devem ter teste próprio.

Mesmo que o banco atual possa ser descartado, devem existir bancos de teste reproduzíveis para as funcionalidades de revisão, rebuild e diagnóstico.

#### Carregamento da lista de imagens

O caminho usado pela GUI deve ter queries próprias, em vez de reutilizar uma consulta genérica que traga dados desnecessários. Deve ser possível:

- listar arquivos com status;
- filtrar por run, processamento e revisão;
- ordenar de forma estável;
- obter a quantidade total;
- carregar detalhes somente quando uma imagem for selecionada.

Se necessário, usar paginação ou carregamento incremental. O objetivo é reduzir o tempo até a primeira lista útil sem sacrificar a consistência do inventário.

### 4.4 `forza-pipeline`

Responsável por filesystem, imagens e processamento de uma entrada.

Módulos:

```text
src/
├── discovery.rs
├── image_encoding.rs
├── metadata.rs
├── hashing.rs
├── duplicates.rs
├── planning.rs
├── processing.rs
├── normalization.rs
└── lib.rs
```

Responsabilidades:

- descobrir extensões válidas;
- localizar inputs e outputs;
- calcular SHA-256 e tamanho;
- detectar duplicatas;
- gerar nome semântico;
- redimensionar e codificar imagens;
- preservar as decisões de grayscale/desaturação relevantes;
- produzir payloads base64 com MIME correto;
- devolver erros por arquivo sem abortar o lote inteiro quando o comportamento Python permitir.

### 4.5 `forza-lmstudio`

Responsável exclusivamente pelo protocolo HTTP e pelo ciclo de vida do runtime LM Studio.

Componentes:

- cliente de health check;
- listagem de modelos;
- diagnóstico de runtime;
- carregamento e comparação de configuração;
- backend de extração;
- retry e registro de tentativas;
- parsing/reparo de JSON;
- validação de resposta.

O backend também deve preservar o controle de desempenho do runtime:

- medir TPS e tempo de resposta;
- detectar streak de respostas lentas;
- decidir quando recarregar o modelo;
- persistir os metadados de performance do run;
- emitir eventos para a GUI e para o diagnóstico.

Essa lógica não deve ser confundida com o `PerformanceService` do dashboard. O backend LM Studio controla observações e decisões de runtime; o serviço de aplicação agrega e apresenta os resultados.

O contrato assíncrono deve ser coerente. A opção inicial é usar `async fn` nativo em trait, sem `async-trait`, quando o application layer puder receber o backend como tipo genérico:

```rust
pub trait LlmBackend: Send + Sync {
    async fn extract(
        &self,
        request: ModelRequest,
    ) -> Result<ModelExtractionResult, LlmError>;
}
```

Se a GUI, os testes ou a aplicação precisarem armazenar diferentes implementações como `Box<dyn LlmBackend>`, o trait deverá ser adaptado para dispatch dinâmico e `async-trait` poderá ser adicionado. Essa escolha deve ser feita por necessidade de arquitetura, não por padrão. O pequeno custo de boxing é aceitável para chamadas ao LM Studio, que são muito mais lentas que uma alocação local.

Se o future precisar ser enviado para tarefas multithread, o contrato também deverá declarar ou gerar a variante `Send` apropriada. Isso pode ser feito com bounds explícitos ou com `trait-variant`; não se deve assumir que `async fn` nativo resolve automaticamente todos os requisitos de `Send`.

O processamento CPU-intensivo não deve ficar misturado à implementação HTTP. `Tokio` será usado para I/O e `rayon` somente quando houver trabalho CPU paralelo claramente identificado.

### 4.6 `forza-app`

Coordena os casos de uso e mantém a GUI/CLI desacopladas das implementações de infraestrutura.

Serviços previstos:

- `RunService`;
- `RunLifecycleService`;
- `ExtractionService`;
- `ExtractionPersistenceService`;
- `RebuildService`;
- `ReviewService`;
- `DatabaseService`;
- `ExportService`;
- `ReferenceDataService`;
- `BestLapRecomputeService`;
- `ImageService`;
- `ExternalRecordService`;
- `PerformanceService`;
- `DbDoctorService`;
- `RuntimeSnapshotService`;
- serviços de leitura e escrita da GUI.

Os serviços não devem conhecer widgets. Devem emitir eventos de aplicação, estados e resultados tipados que possam ser consumidos pela CLI ou pela GUI.

Eventos importantes:

- início e fim de run;
- arquivo descoberto;
- arquivo ignorado;
- arquivo em processamento;
- tentativa do modelo;
- resultado persistido;
- erro recuperável;
- progresso;
- cancelamento;
- conclusão.

`PerformanceService` deve concentrar o dashboard de desempenho e os cálculos de:

- gaps relativos;
- melhores voltas por combinação;
- uso e vitórias por carro;
- progresso temporal;
- comparação com registros externos;
- cards e linhas consumidos pela GUI.

Ele também deve preservar a lógica operacional associada ao desempenho do LM Studio, incluindo `performance_tps_floor`, `performance_reload_elapsed_s` e `performance_reload_streak`.

### 4.7 `forza-output`

#### CSV

- manter headers e ordem de colunas;
- definir serialização de `NULL`, tempos e símbolos;
- criar um teste com dados conhecidos;
- permitir comparação normalizada com a saída Python.

#### PDF

O PDF Rust deve reproduzir o conteúdo e a organização funcional:

- agrupamento por pista;
- melhores voltas;
- classe e cores;
- símbolos de volta suja;
- metadados;
- rodapé;
- ordenação;
- número e conteúdo das linhas.

Antes da implementação completa, fazer um spike com um relatório representativo:

1. implementar uma página com título, metadados, uma tabela e uma quebra de página em `genpdf`;
2. implementar a mesma página em `printpdf`;
3. comparar esforço, controle de estilo, fontes, símbolos e tabelas;
4. escolher a biblioteca que melhor equilibre layout automático e controle necessário.

`genpdf` é a candidata inicial para reduzir a necessidade de criar um motor de layout próprio. `printpdf` será preferível se os requisitos de estilo ou posicionamento não puderem ser expressos adequadamente no layout de alto nível.

A validação principal será manual: gerar Python e Rust para a mesma entrada e comparar a lista apresentada. Diferenças de layout podem ser aceitas desde que os dados exibidos sejam equivalentes.

### 4.8 `forza-cli`

Comandos a preservar:

```text
forza run [--dry-run] [--force] [--retry-errors] [--limit N]
forza gui
forza rebuild
forza export [--out FILE]
forza config-check
forza maintenance db-status
forza maintenance db-doctor [--json]
forza maintenance db-upgrade
forza maintenance db-reset
```

O CLI deve ser implementado cedo para fornecer uma forma rápida de testar o backend enquanto a GUI ainda está incompleta. A construção é distribuída pelas fases, de modo que cada comando entra junto da funcionalidade que ele expõe:

- Fase 1: crate `forza-cli` com `clap` e esqueleto de subcomandos;
- Fase 2: `config-check`;
- Fase 3: `maintenance db-status`, `db-doctor`, `db-upgrade` e `db-reset`;
- Fase 4: `gui`;
- Fase 6: `run --dry-run`;
- Fase 8: `run` completo e `rebuild`;
- Fase 9: `export`.

### 4.9 `forza-gui`

A GUI Rust deve manter a estrutura funcional da aplicação, mas não precisa reproduzir a implementação Qt.

Componentes:

- janela principal;
- navegação entre seções;
- image browser;
- process view;
- review queue;
- best laps;
- performance;
- records;
- diagnostics;
- developer overview;
- image debug;
- DB doctor;
- logs;
- settings;
- image detail.

O subsistema Performance deve incluir controller, worker, modelo de tabela/dashboard e uma superfície visual própria ou uma seção claramente identificada dentro de Diagnostics/Developer Overview. A escolha visual pode variar, mas as operações e dados do Performance Python devem continuar disponíveis.

O padrão MVCW continua válido conceitualmente:

- views/componentes Slint;
- controllers Rust;
- modelos de dados para tabelas;
- workers ou tarefas para operações demoradas;
- application services para regras e persistência.

Regras de concorrência:

- nunca bloquear a thread da UI com chamadas LM Studio, varreduras grandes ou exportação;
- toda tarefa de longa duração deve ter estado de progresso;
- cancelamento deve ser cooperativo;
- resultados devem retornar à UI por mensagens tipadas;
- atualizações de modelo devem ocorrer na thread exigida pelo framework.

Integração Tokio/Slint:

- o runtime Tokio será criado uma única vez no startup do processo, em threads dedicadas, e permanecerá invisível para os callbacks da UI;
- callbacks do Slint são síncronos: eles despacham trabalho por canais para workers ou tarefas e retornam imediatamente;
- resultados assíncronos retornam à thread da UI por `slint::invoke_from_event_loop` ou mecanismo equivalente do framework, nunca por acesso direto de outra thread;
- nenhuma thread de UI pode chamar `blocking_wait` ou equivalente sobre futures do Tokio.

Para arquivos `.slint` externos, `forza-gui` terá um `build.rs` semelhante a:

```rust
fn main() {
    slint_build::compile("ui/main.slint").unwrap();
}
```

O crate `slint-build` ficará em `[build-dependencies]`, enquanto `slint` ficará em `[dependencies]`.

## 5. Fases de implementação

### Fase 0 — Baseline e contratos

Objetivo: criar uma referência pequena e reproduzível antes de escrever Rust.

Entregas:

- selecionar um conjunto de screenshots representativo;
- registrar uma execução Python de referência;
- salvar respostas do LM Studio quando possível;
- salvar CSV, PDF e resultados normalizados;
- registrar o tempo atual para abrir a GUI e carregar a lista;
- revisar `docs/contracts/*.md` como fonte primária dos contratos existentes, incluindo `database.md`, `configuration.md`, `gui.md`, `gui_signal_payloads.md`, `review.md`, `rebuild.md`, `best_laps.md`, `images_and_files.md`, `raw_artifacts.md` e `versioning.md`;
- classificar os testes Python `*_static.py` como contratos executáveis de referência;
- traduzir os contratos estáticos relevantes para testes Rust em `forza-domain`, `forza-db`, `forza-app` e `forza-gui`;
- documentar tabelas, estados e contratos que ainda não estejam cobertos;
- identificar quais campos são derivados e quais são dados de revisão;
- auditar índices únicos parciais, triggers, check constraints, defaults e ações `ON DELETE` por tabela;
- criar `fixtures/` no projeto Rust, com `fixtures/README.md` explicando o que é versionado e o que permanece fora do Git.

Critério de conclusão: os contratos existentes foram catalogados, os invariantes do banco têm uma checklist explícita e existe uma entrada pequena que pode ser processada repetidamente e comparada entre Python e Rust.

### Fase 1 — Workspace e ferramentas Rust

Entregas:

- workspace Cargo;
- crates iniciais;
- esqueleto do `forza-cli` com `clap` e subcomandos placeholder;
- `cargo fmt`, `cargo clippy` e `cargo test` funcionando;
- configuração de build Windows;
- política de erros;
- política de logging;
- convenções de módulos e tamanho de arquivos;
- CI inicial.

Critério de conclusão: o workspace compila vazio com a estrutura definitiva.

### Fase 2 — Domínio e configuração

Entregas:

- enums e structs de domínio;
- serialização explícita;
- parsing de tempos;
- normalizadores;
- regras de revisão;
- ordenação;
- carregamento de referências;
- parser `.ini`;
- validações de configuração;
- comando `config-check` no CLI;
- testes unitários para regras puras.

Critério de conclusão: fixtures de domínio produzem os mesmos valores semanticamente que Python.

### Fase 3 — SQLite e queries da GUI

Entregas:

- schema Rust;
- controle de versão do schema;
- conexão e transações, com inicialização padrão WAL, `busy_timeout` e `foreign_keys=ON` e teste próprio desse contrato;
- repositories;
- queries de leitura da GUI;
- inserção de banco de teste;
- DB doctor básico;
- comandos `maintenance db-status`, `db-doctor`, `db-upgrade` e `db-reset` no CLI;
- testes de constraints e relacionamentos.

Critério de conclusão: um banco de teste pode ser criado, populado, consultado e inspecionado pelo Rust.

### Fase 4 — Primeiro vertical slice da GUI

Implementar primeiro:

1. abertura da janela;
2. carregamento de configuração;
3. abertura do SQLite;
4. consulta da lista de imagens;
5. filtros básicos;
6. seleção de uma imagem;
7. exibição de detalhes;
8. logs e mensagens de erro.

O slice é acessível pelo subcomando `gui`, já com o runtime Tokio em threads dedicadas e o retorno de resultados à UI por mensagens tipadas, mesmo que ainda sem tarefas longas.

Critério de conclusão: a GUI Rust permite abrir o projeto e navegar pela lista de imagens de forma utilizável.

### Fase 5 — Benchmark da lista de imagens

Medir Python e Rust usando:

- o mesmo computador;
- o mesmo banco ou bancos semanticamente equivalentes;
- o mesmo volume de imagens;
- a mesma configuração;
- a mesma condição de cache, registrando se o cache está quente ou frio.

Métricas:

- tempo até a janela aparecer;
- tempo até a consulta terminar;
- tempo até a primeira lista ser exibida;
- tempo até todos os itens serem exibidos;
- memória inicial e após o carregamento, se for simples de medir.

O resultado principal será o tempo de carregamento visual da lista. A meta experimental é que o Rust torne essa etapa praticamente instantânea, mas o resultado deve ser acompanhado do tamanho da entrada e da estratégia de consulta usada.

Se o ganho não aparecer, medir separadamente:

- abertura SQLite;
- query;
- filesystem;
- hashing;
- leitura de metadados;
- construção do modelo da tabela;
- renderização da GUI.

### Fase 6 — Imagens e planejamento de execução

Entregas:

- descoberta;
- inspeção de metadados;
- hash;
- duplicatas;
- planejamento de arquivos;
- resize/desaturação;
- base64 e MIME;
- `dry-run`;
- comando `forza run --dry-run` no CLI;
- registro de erros por imagem.

Critério de conclusão: o Rust consegue planejar o mesmo conjunto de imagens do Python para a fixture escolhida.

### Fase 7 — Cliente LM Studio e pipeline

Entregas:

- health check;
- listagem de modelos;
- diagnóstico;
- request OpenAI-compatible;
- payload de imagem;
- retry;
- tracking de tentativas;
- spike de reparo com as respostas malformadas reais do projeto;
- escolha e integração de `llm_json`, `jsonrepair` ou implementação complementar própria;
- parser/reparo de JSON;
- validação;
- persistência do resultado.

Critério de conclusão: uma fixture com resposta gravada percorre o pipeline inteiro sem depender da disponibilidade do modelo.

### Fase 8 — Runs, revisão e rebuild

Entregas:

- lifecycle de run;
- progresso e cancelamento;
- persistência de resultados;
- geração de review cases;
- correções manuais;
- referências de carros e pistas;
- rebuild sem nova chamada ao modelo;
- recomputação de melhores voltas;
- `PerformanceService` com dashboard, gaps relativos e comparação com registros externos;
- `PerformanceController`, worker e modelo de dados da GUI;
- métricas de TPS, tempo de reload e streak persistidas no run;
- decisão de reload do modelo preservada e testada;
- telas correspondentes na GUI;
- comandos `forza run` completo e `forza rebuild` no CLI.

Critério de conclusão: o fluxo `processar → revisar → corrigir → rebuild` funciona sobre um banco de teste.

### Fase 9 — CSV, PDF e telas de resultado

Entregas:

- exportação CSV;
- geração PDF;
- best laps;
- records;
- agrupamento e ordenação;
- símbolos e cores;
- artifacts e metadados;
- comando `forza export` no CLI;
- abertura do arquivo gerado pela GUI.

Critério de conclusão: para a mesma fixture, a lista do PDF Rust é equivalente à lista do PDF Python.

### Fase 10 — GUI completa

Implementar as seções restantes:

- process;
- review queue;
- best laps;
- records;
- diagnostics;
- developer overview;
- performance ou seção equivalente dentro de Diagnostics/Developer Overview;
- image debug;
- DB doctor;
- logs;
- settings;
- image detail;
- rebuild.

Cada tela deve consumir application services, não executar SQL ou regras de domínio diretamente.

Critério de conclusão: o fluxo normal do usuário pode ser executado na GUI sem recorrer à CLI.

### Fase 11 — Empacotamento e acabamento

Entregas:

- build release Windows;
- assets embutidos ou instalados corretamente;
- configuração inicial;
- logs de erro;
- documentação de uso;
- versão do aplicativo;
- registro de licenças de terceiros, incluindo a licença royalty-free do Slint;
- testes de máquina limpa;
- comparação final Python/Rust;
- benchmark final.

A remoção do Python do pacote Rust é opcional. O código Python pode continuar no repositório como referência até a conclusão do experimento.

## 6. Dependências iniciais

As versões devem ser confirmadas no momento da implementação, mas o conjunto conceitual é:

```toml
[workspace]
members = [
    "crates/forza-domain",
    "crates/forza-config",
    "crates/forza-db",
    "crates/forza-pipeline",
    "crates/forza-lmstudio",
    "crates/forza-output",
    "crates/forza-app",
    "crates/forza-cli",
    "crates/forza-gui",
]

# Domínio e dados
serde = { version = "1", features = ["derive"] }
serde_json = "1"
thiserror = "2"
uuid = { version = "1", features = ["v4", "serde"] }
chrono = { version = "0.4", features = ["serde"] }

# Configuração e texto
configparser = "3"
regex = "1"
unicode-normalization = "0.1"

# Banco
# Manter rusqlite e r2d2_sqlite em versões compatíveis entre si.
rusqlite = { version = "0.40", features = ["bundled"] }
r2d2 = "0.8"
r2d2_sqlite = "0.35"

# Pipeline
image = "0.25"
base64 = "0.22"
sha2 = "0.10"
rayon = "1"

# HTTP e concorrência
reqwest = { version = "0.12", features = ["json", "stream"] }
tokio = { version = "1", features = ["rt-multi-thread", "macros", "sync", "time"] }

# JSON repair: escolher após validar fixtures reais.
# Candidatas: llm_json, jsonrepair ou implementação complementar própria.

# CLI e logging
clap = { version = "4", features = ["derive"] }
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter"] }

# Output
csv = "1"
genpdf = "0.2"  # spike de layout; remover se printpdf for escolhido; usa printpdf 0.5 internamente
printpdf = "0.12"

# GUI — licença royalty-free para aplicações desktop (ver 2.6)
slint = "1"

[build-dependencies]
slint-build = "1"
```

O crate `slint-build` é uma build dependency do crate que contém os arquivos `.slint`; ele não é uma dependência runtime do aplicativo. `async-trait` permanece fora do conjunto inicial e só entra se for necessário usar `dyn LlmBackend`.

As dependências devem ser adicionadas somente quando uma fase precisar delas. Não é necessário escolher todo o stack antes do primeiro vertical slice.

## 7. Estratégia de testes

### 7.1 Testes unitários

Concentrar em:

- tempos;
- normalização;
- Unicode;
- classe;
- clima;
- volta suja;
- ordenação;
- validação de configuração;
- parsing de respostas;
- regras de revisão.

### 7.2 Testes de banco

- criação de schema;
- versionamento;
- foreign keys;
- constraints;
- inserts e updates;
- transações;
- queries da GUI;
- diagnóstico de banco inválido;
- recomputação de melhores voltas.

Também devem existir testes específicos para:

- índices únicos parciais;
- tentativa aceita única por resultado;
- snapshot preflight único por run;
- cada ação `ON DELETE` relevante;
- triggers e check constraints de regras de negócio;
- defaults e combinações inválidas de estados.

### 7.3 Testes de pipeline

- imagens pequenas de fixture;
- hashes conhecidos;
- payloads conhecidos;
- respostas LM Studio gravadas;
- JSON válido e inválido;
- retry;
- erro isolado por arquivo;
- cancelamento.

As fixtures de JSON malformado devem cobrir as respostas que o Python corrige atualmente. A crate escolhida só será aceita se produzir resultados compatíveis nessas fixtures; caso contrário, a lógica deverá ser complementada ou portada.

### 7.4 Testes de Performance

- dashboard com dados vazios e completos;
- gaps relativos;
- melhores resultados por combinação;
- registros externos;
- limiares de TPS;
- streak de respostas lentas;
- decisão de reload;
- persistência dos campos de performance no run;
- payloads do worker e atualizações da GUI.

### 7.5 Testes de contrato da GUI

Sem exigir automação visual completa, testar:

- nomes dos callbacks;
- estados iniciais;
- filtros;
- transição de páginas;
- atualização do modelo;
- resposta a erros;
- início e conclusão de workers;
- salvar e carregar configurações.

Os testes `*_static.py` existentes devem ser usados como catálogo de contratos a traduzir. A conversão não precisa copiar a técnica de inspeção textual, mas deve preservar o contrato que cada teste protege.

### 7.6 Comparação Python/Rust

Para uma fixture selecionada:

1. processar ou carregar a mesma entrada;
2. normalizar os resultados;
3. comparar campos de domínio;
4. gerar CSV/PDF nos dois sistemas;
5. confirmar manualmente que a lista do PDF é equivalente.

Diferenças de layout, fonte ou paginação podem ser aceitas quando os dados exibidos forem equivalentes.

## 8. Critérios de conclusão

O projeto Rust será considerado funcionalmente equivalente quando:

- a GUI abrir e carregar a lista de imagens;
- filtros e seleção funcionarem;
- o pipeline processar screenshots;
- respostas LM Studio forem persistidas;
- revisão e rebuild funcionarem;
- melhores voltas forem calculadas;
- CSV e PDF forem gerados;
- a lista do PDF Rust for equivalente à do Python para a mesma entrada;
- diagnóstico e logs permitirem investigar falhas;
- o benchmark da GUI estiver documentado;
- `cargo test`, `cargo fmt --check` e `cargo clippy` passarem no estado final.

## 9. Resultado esperado do experimento

O experimento deve responder, com dados reais, às seguintes perguntas:

1. Rust reduz o tempo de carregamento da lista de imagens?
2. Qual parte desse carregamento é realmente o gargalo?
3. A modularização atual continua adequada em Rust?
4. Quais contratos Python eram de domínio e quais eram apenas detalhes de framework?
5. A GUI Slint atende às necessidades do projeto?
6. O acesso direto ao SQLite simplifica ou complica a manutenção?
7. O binário Rust melhora distribuição, inicialização e consumo de memória?
8. Quais partes do pipeline se beneficiam de concorrência Rust?

O sucesso da migração não será apenas “compilar em Rust”. Será obter uma aplicação utilizável, modular e funcionalmente equivalente, com uma medição clara do desempenho da GUI e conclusões úteis sobre as escolhas feitas.

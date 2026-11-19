# Plano — Automação de Renovações Lotéricas no SGCOR

> Documento vivo. Status: **rascunho v0.4 (18/11/2026)** — `grill-me` concluído (rodadas 1–4, ver §13); aguardando confirmação para iniciar a F0.
> Nada de código ainda. Decisões marcadas como ❓ estão em aberto (ver §12).

---

## 1. Objetivo

Um aplicativo Windows que, a partir das pastas de seguros **fechados** (Porto e Tokio),
cadastra a **renovação** de cada lotérica no SGCOR (grupoprotege.sgcor.com.br):
proposta → itens/coberturas → repasse (bônus do consultor) → parcelas → anexos (ACORDO + PROPOSTA).

O consultor só intervém quando a automação **não tem certeza** (parcelas não encontradas,
mais de um arquivo, cobertura divergente, etc.). Tudo o mais roda sozinho, sem tomar o
navegador que ele está usando para vender.

**Sucesso =** o consultor seleciona as pastas, marca as lotéricas, aperta "Executar" e,
no fim, tem uma lista de *cadastradas* + uma fila curta de *pendências com motivo*.

---

## 2. Fatos levantados nos arquivos reais (`Documentos\FECHADOS PORTO|TOKIO`)

| Fato | Evidência | Impacto |
|---|---|---|
| PDFs têm **texto extraível** (não precisam de OCR) | `pdftotext` funcionou em Porto e Tokio | Parser simples e rápido |
| 35 subpastas, **todas com exatamente 2 PDFs** | varredura | Regra "2 arquivos = ok" é viável |
| Há 1 PDF **solto** na raiz de `FECHADOS TOKIO` (`ACORDO LOTERICA A MILIONARIA LEME...`) | varredura | Precisa virar pendência, não ser ignorado |
| Nomes de arquivos **não são padronizados** (`De acordo - HR ...`, `Proposta - ...`, `... - 21c desconto.pdf`, `... 40k sub.pdf`) | varredura | Classificar ACORDO × PROPOSTA pelo **conteúdo**, não pelo nome |
| Nome da pasta ≠ nome no PDF (`CENTRALINA LTDA ME` × `CENTRALINA LTDA`; `GRANEMANN E CELEVI` × `GRANEMANN & CELIVI`) | varredura | **Não** usar nome como chave |
| **Tokio**: `Renova Apólice nº 180 000000002694000` → bate com a apólice `2694000` no SGCOR | proposta CASA LOTERICA OK × tela SGCOR | **Chave de busca confiável** |
| **Porto**: bloco "Informações da apólice a ser renovada" → `Número da apólice 4069823` | proposta BONI SORTE AZUL | Mesma ideia: chave = apólice anterior |
| **Tokio**: comissão em `Comercialização` → `2100CCD...` = 21% | pág. 17/17 | Regex `^(\d{2})\d{2}` |
| **Porto**: comissão no cabeçalho de página → `... - CO20 - PORTO PRINT WEB EMPRESA` | todas as páginas | Regex `- CO(\d{2}) -` |
| **O acordo pode contradizer a proposta**: CASA LOTERICA OK tem `(X) 1 + 5` na proposta, mas o cliente escreveu **"Na forma de 0+10"** e "No boleto" | acordo × proposta | **Acordo vence a proposta** |
| Acordos frequentemente citam **várias opções** (o consultor oferece "6x ou 10x") | varredura dos 36 acordos | É preciso separar fala do **cliente** (coluna esquerda) da fala do **consultor** (coluna direita) e pegar a **última escolha do cliente** |
| 2 acordos sem nenhuma menção reconhecível de pagamento (LOTERIA DO POVO, LOTERICA SAO LUIS) | varredura | Viram pendência "informar parcelas" |
| Formatos vistos: `6x`, `6 x`, `6 vezes`, `6 parcelas`, `05 parcelas`, `1+5`, `1 + 5`, `1+ 9`, `0+10`, `à vista`, `a vista`, `10 X`, `cartao` | varredura | Base para o parser de parcelas + testes |
| Porto: IOF/prêmio total **mudam conforme a forma de pagamento** (12x Cartão Porto → IOF 107,30; boleto → 112,94) | pág. 10 | Escolher a linha da tabela de acordo com a forma do acordo |
| Na máquina de desenvolvimento há Python 3.15.2 (ver Q1), `pdftotext` (via Git) e Firefox; nas máquinas dos consultores não se assume nada | checagem | O app precisa ser um `.exe` autocontido |

---

## 3. Arquitetura proposta (com críticas às ideias iniciais)

```
┌─────────────── App Windows (.exe) ───────────────┐
│ UI (lista de lotéricas c/ checkbox, status, fila) │
│        │                                          │
│  Scanner de pastas ──► Parser PDF ──► Regras      │
│  (watcher, sem refresh manual)   (parcelas,       │
│        │                          comissão→bônus) │
│        ▼                                          │
│  Estado local (SQLite)  ◄──►  Robô SGCOR          │
│  chave = apólice anterior     (Playwright, em     │
│                               navegador PRÓPRIO)  │
└───────────────────────────────────────────────────┘
```

### 3.1 Navegador dedicado ao SGCOR + execução em lote ✅
- O robô **não** usa o Firefox do consultor. Abre um **navegador dedicado ao SGCOR** (Playwright, perfil persistente próprio).
- **Sem usuário de robô**: cada consultor usa o próprio login (o repasse/produtor é dele).
- Como o mesmo usuário pode não aguentar duas sessões, o SGCOR passa a "morar" nesse navegador dedicado.
- **Quando roda:** duas camadas, para não pesar a máquina nem disputar a sessão:
  1. **Leitura das pastas — contínua e leve**: o watcher lê PDFs novos assim que aparecem e já monta
     a fila e as pendências. O consultor resolve pendências ao longo da manhã, em segundos.
  2. **Cadastro no SGCOR — em lote, só com clique (Q33)**: o consultor marca as lotéricas e clica "Executar";
     o app mostra um resumo do que vai cadastrar e pede confirmação. **Sem agendamento automático.**

### 3.2 Sem "refresh das páginas"
Em vez de ficar recarregando páginas/pastas, o app:
- observa as pastas com um *file watcher* (nova lotérica aparece sozinha na lista);
- guarda o estado de cada renovação num SQLite local, **chaveado pelo nº da apólice anterior**;
- antes de cadastrar, **confere no SGCOR** se a renovação já existe (idempotência: rodar duas vezes não duplica).

### 3.3 Login
O app **não guarda senha em texto**. Na primeira vez, abre a janela do navegador do robô para o
consultor logar manualmente; a sessão fica no perfil persistente. Botão "Verificar conexão ao SGCOR"
apenas testa se a sessão ainda é válida.

### 3.4 Stack ✅
- **Python 3.15.2 (instalado) + Playwright** (automação), **pdfplumber** (texto com coordenadas → separa colunas do acordo),
  **PySide6** (UI), **SQLite** (estado), **PyInstaller** (gera `.exe`).
- Alternativa: C#/.NET + Microsoft.Playwright (exe nativo, mais verboso). Python ganha em velocidade de entrega e em parsing de PDF.

---

## 4. Estrutura de pastas esperada

```
Documentos\
├── FECHADOS PORTO\
│   └── <NOME DA LOTÉRICA>\
│       ├── ACORDO <...>.pdf      ← "Histórico de Atendimento"
│       └── <...>.pdf             ← Orçamento Porto
└── FECHADOS TOKIO\
    └── <NOME DA LOTÉRICA>\
        ├── ACORDO <...>.pdf
        └── <...>.pdf             ← Cotação Tokio Marine
```
A seguradora é deduzida pela pasta raiz **e** confirmada pelo conteúdo (cabeçalho "PORTO SEGURO" / "TOKIO MARINE").
Divergência → pendência.

---

## 5. Extração de dados

| Campo | Porto | Tokio |
|---|---|---|
| **CNPJ (chave de busca no SGCOR)** | Dados do proponente | Cabeçalho "A(o)" (`... - 00.000.000/0000-00`) |
| Apólice anterior (escolher a linha certa do CNPJ) | "Informações da apólice a ser renovada" → Nº da apólice | "Renova Apólice nº" (remover zeros à esquerda) |
| Nº a lançar como "Proposta" no SGCOR ✅ | Número do orçamento | Cotação nº |
| CNPJ / Razão social | Dados do proponente | Cabeçalho "A(o)" |
| Vigência | 31/12/2026 a 31/12/2027 (confirmar) | Idem (confirmar contra o SGCOR) |
| Coberturas + LMI + franquia | Tabela "COBERTURAS" | Tabelas "Cobertura Contratada" (várias páginas) |
| Prêmio líquido / IOF / Prêmio total | "Demonstrativo de prêmio geral" + linha da forma de pagamento | "Resumo do Prêmio" |
| Comissão | `CO20` no cabeçalho | `Comercialização` 2 primeiros dígitos |
| Forma + nº de parcelas | **Acordo** (fallback: proposta) | **Acordo** (fallback: `(X)` na proposta) |

Classificação dos arquivos pelo conteúdo:
- contém "Histórico de Atendimento" → ACORDO;
- contém "ORÇAMENTO … PORTO SEGURO" ou "COTAÇÃO DE SEGURO TOKIO MARINE" → PROPOSTA.

---

## 6. Regras de negócio

### 6.1 Parcelas (a parte mais delicada)
**Regra de ouro ✅: vale o que o CLIENTE disse no acordo. A marcação `(X)` da proposta é ignorada.**
1. Ler o acordo com coordenadas; mensagens da **coluna esquerda** = cliente, coluna do cabeçalho "Atendente" = consultor.
2. Procurar padrões: `N x|vezes|parcelas`, `A + B`, `A e mais B`, `à vista`, `N ou M` (ambíguo), `boleto|cartão|cartão porto|pix|débito`.
3. Usar a **última** condição combinada (Q31): fala explícita do cliente, ou oferta do consultor com parcelas + forma aceita pelo cliente. Quantidade de parcelas = soma: `1+5` → 6; `1+9` → 10; `0+10` → 10; `à vista` → 1.
4. Com ou sem entrada não importa no cadastro: `1+9`, `0+10` e `10x` viram todos **10** (Q13).
5. Validar: a opção existe na tabela de pagamento da proposta? Se não → pendência.
6. Nada encontrado / ambíguo → **pendência "informar parcelas"** (o consultor digita no app e a lotérica volta para a fila).

### 6.2 Datas
- Emissão = data atual. 1ª parcela = **10/01/2027** (Porto e Tokio). Deixar configurável (vai mudar no próximo ciclo).

### 6.3 Comissão → bônus (Valor Fixo do repasse)
Tabela da campanha (imagem 15):

| Comissão | Bônus |
|---|---|
| ≤ 16% | R$ 18,00 |
| 17% a 19% | R$ 20,00 |
| 20% a 23% | R$ 30,00 |
| ≥ 24% | R$ 40,00 |

✅ Os R$ 26,00 da tela de exemplo eram de uma campanha antiga; vale esta tabela.
A tabela vai para um arquivo de configuração, não para o código (troca a cada campanha).

### 6.4 Coberturas
- Comparar coberturas da proposta × itens do SGCOR (guarda-chuva) por **LMI**.
- Os nomes diferem entre seguradora e SGCOR (ex.: "Valores no Interior do Estabelecimento - Lotérica" × "GERPA - SUB. DE VALORES NO INTERIOR DO ESTABELECIMENTO"),
  então precisamos de um **dicionário de equivalência** editável (config).
- Política de divergência ✅: ajustar só o LMI das coberturas casadas com segurança; cobertura nova na proposta → ignorada; removida da proposta → fica como está (Q57); sem equivalente no dicionário → pendência.

---

## 7. Fluxo no SGCOR por lotérica

1. Propostas/Apólices → pesquisar pelo **CNPJ** → filtrar por **seguradora + ramo** (Q24) → escolher a de **vigência mais recente** (sem conferir o número contra o PDF — Q11/Q11b; empate → pendência) → conferir se já existe renovação.
2. Ícone **renovar** (duas setas) → tela da proposta (imagem 10):
   nº da proposta, conferir vigência, **digitar** prêmio total, IOF, prêmio líquido do PDF (Q19), forma de pagamento,
   **quantidade de parcelas**, emissão = hoje, 1ª parcela = 10/01/2027 → **Avançar**.
3. **Itens e coberturas** (guarda-chuva): conferir/ajustar LMI → **Avançar**.
4. **Repasses**: lápis → confirmar "Sim" → produtor = consultor → Valor Fixo = bônus da campanha →
   **Salvar e Gerar Parcelamento**.
5. **Avançar** → **Concluir**.
6. Na lista, **clipe** da lotérica → anexar (só Descrição + arquivo; Tipo Documento e "Válido até" não são preenchidos — Q16):
   - Descrição `ACORDO` + arquivo do acordo → Salvar;
   - Descrição `PROPOSTA` + arquivo da proposta **escolhida** (Q14) → Salvar.
7. Marcar como concluída no estado local; registrar ID SGCOR, valores lançados e prints de cada etapa (auditoria).

Qualquer falha no meio → print + mensagem → pendência, e o robô segue para a próxima lotérica.
Renovação que ficou **pela metade** (Q12) → status "Pela metade — conferir no SGCOR" com print e ID; o robô **não retoma sozinho** na v1.

---

## 8. Intervenção humana (fila de pendências)

Motivos previstos:
- mais (ou menos) de 2 PDFs na pasta / PDF solto na raiz;
- não foi possível classificar ACORDO × PROPOSTA;
- parcelas não encontradas ou ambíguas;
- apólice anterior não encontrada no SGCOR, ou renovação já existente;
- seguradora da pasta ≠ seguradora do PDF;
- cobertura sem equivalência no dicionário / LMI divergente (conforme ❓Q8);
- comissão não encontrada;
- erro de tela/tempo esgotado no SGCOR.

O consultor resolve **dentro do app** (ex.: digita "6") e a lotérica volta para a fila.

---

## 9. UI (evolução do rascunho da imagem 1)

- **Pasta TOKIO** [selecionar] · **Pasta PORTO** [selecionar] (lembradas entre execuções)
- **Consultor/Produtor**: campo com autocomplete dos produtores do SGCOR
- **Verificar conexão ao SGCOR** (status verde/vermelho)
- **Tabela de lotéricas**: ☐ | Seguradora | Lotérica | CNPJ | Apólice anterior | Prêmio total | Parcelas | Comissão → Bônus | Status
  - "Selecionar todos", filtros por status (Novo / Pronto / Pendente / Concluído / Erro)
- **Modo**: `Conferência` (preenche a 1ª tela e espera o Continuar — Q34/Q41) × `Automático` (liberado só na F3)
- **Executar selecionadas** → janela de **resumo + confirmação** (padrão = Cancelar) → robô (F2). Pausar / log ao vivo na F2.
- Painel de detalhe: dados lidos, trecho do acordo, pendências/avisos, **Resolver** (parcelas, forma, proposta final),
  abrir pasta/acordo/proposta. Ajustes ficam em `%LOCALAPPDATA%\SGCOR-Renovacoes\estado.sqlite` (fora do git).
- Pastas observadas: PDF/pasta nova ou alterada é relida sozinha (só o que mudou). Abrir: `abrir-app.bat`.

---

## 10. Fases de entrega

| Fase | Entrega | Toca no SGCOR? |
|---|---|---|
| **F0 — Descoberta** | Mapear seletores das telas do SGCOR **a partir de prints/HTML enviados pelo consultor** (Q18), catálogo de coberturas do SGCOR, confirmar ❓ | Não (o consultor captura) |
| **F1 — Leitor de pastas** | Scanner + parser + regras + UI mostrando a tabela e as pendências, rodando nos **36 casos reais**. Testes automatizados com esses PDFs | Não |
| **F2 — Robô em modo conferência** | Preenche proposta, coberturas e repasse e **para antes de salvar**; consultor confere | Escrita sem salvar |
| **F3 — Robô completo** | Salvar, gerar parcelamento, concluir, anexar, idempotência | Sim |
| **F4 — Empacotamento** | `.exe`, watcher de pastas, logs, configuração editável | — |

F1 sozinha já entrega valor: um relatório "o que está pronto para cadastrar e o que falta".

---

## 11. Riscos

- **Mudança de layout** do SGCOR ou dos PDFs das seguradoras → seletores e parsers isolados + testes com PDFs reais.
- **Dados de clientes** (CNPJ, telefone): PDFs nunca entram no git (`.gitignore`); logs locais.
- **Ações irreversíveis** no SGCOR → modo conferência até ganhar confiança.
- **Sessão do SGCOR** expirando no meio do lote → detectar e pausar, pedindo novo login.
- Pasta com mais de uma proposta (ex.: `21c desconto`, `40k sub`) → o app pergunta ao consultor qual é a final.

---

## 12. Decisões em aberto

Nenhuma. F0 mapeada (`docs/f0-mapa-sgcor.md`); F1 concluída (leitura, regras, tela, coberturas + dicionário validado).
F2 construída (robô Playwright + Chrome instalado (Q53), perfil em `%LOCALAPPDATA%\SGCOR-Renovacoes\perfil-sgcor`): verificar conexão
e carregar produtores, buscar e escolher a apólice, preencher a 1ª tela (Q52) e esperar; Pular/Parar/Pausar; prints e
log locais com limpeza de 90 dias. 1ª tela testada no SGCOR real (DDA, 19/11/2026): campos corretos.
F3 construída (Avançar + aviso de datas, coberturas pelo dicionário, repasse, conferência das parcelas, anexos,
mover pasta); leitores testados nas páginas salvas; **falta o 1º cadastro completo real**.

## 13. Registro de decisões

| # | Decisão | Data |
|---|---|---|
| Q1 | Python (3.15.2 instalado) + Playwright + pdfplumber + PySide6 → `.exe` por máquina | 18/11/2026 |
| Q2 | Sem usuário de robô; cada consultor usa o próprio login num **navegador dedicado ao SGCOR** | 18/11/2026 |
| Q2b | Leitura das pastas contínua; cadastro no SGCOR **em lote** (substituída em parte pela Q33: sem agendamento) | 18/11/2026 |
| Q33 | Nada no SGCOR sem clique: cadastro só quando o consultor clica "Executar", com resumo e confirmação antes; **sem horário agendado** | 18/11/2026 |
| Q34 | Modo Conferência = robô preenche **só a 1ª tela** (renovação) e espera; depois do OK faz coberturas, repasse, parcelas e anexos sozinho | 18/11/2026 |
| Q35 | Navegador do robô = **Chromium embutido** no .exe, com perfil próprio | 18/11/2026 |
| Q36 | Produtor escolhido numa **lista lida do SGCOR** ao "Verificar conexão"; fica salvo | 18/11/2026 |
| Q37 | Vigência = **data fixa da configuração** (31/12/2026 a 31/12/2027), para Porto e Tokio | 18/11/2026 |
| Q38 | Dicionário de coberturas: eu proponho a partir dos 36 PDFs + 105 coberturas do SGCOR, o consultor valida uma vez | 18/11/2026 |
| Q39 | Primeiro cadastro real com **1 lotérica**, acompanhada, em modo Conferência | 18/11/2026 |
| Q40 | Commits **direto na main** (sem PR) | 18/11/2026 |
| Q41 | OK da 1ª tela pelo botão **Continuar** no app (ou "Pular lotérica"); o robô clica Avançar | 18/11/2026 |
| Q42 | Correção manual na 1ª tela antes do OK é **mantida e registrada** no histórico | 18/11/2026 |
| Q43 | No Automático a janela do robô fica **visível** | 18/11/2026 |
| Q44 | Vigência de início da proposta Porto ≠ configuração → **pendência** | 18/11/2026 |
| Q45 | A 1ª lotérica do teste real: eu sugiro uma sem avisos, o consultor confirma | 18/11/2026 |
| Q46 | `planejamento-f0` vai para a main e **a branch é mantida** no GitHub como histórico | 18/11/2026 |
| Q47 | **Pausar** = termina a lotérica em andamento e para; Continuar retoma a fila | 18/11/2026 |
| F1 | Dicionário de coberturas por **tipo** (`config/coberturas.toml`): o robô casa cada cobertura do PDF com a cobertura do **mesmo tipo já existente no item** e só ajusta o LMI (o catálogo do SGCOR tem códigos duplicados, então não se escolhe código) | 18/11/2026 |
| Q48 | Porto "Subtração de valores" = valores no interior (GERPA interior) | 18/11/2026 |
| Q49 | Porto "Responsabilidade civil" = SGCOR "RESPONSABILIDADE CIVIL" genérica (≠ RC operações) | 18/11/2026 |
| Q50 | Porto "Despesas fixas" / "Lucros cessantes" = mesmo tipo de lucros cessantes/despesas fixas do SGCOR | 18/11/2026 |
| Q51 | Cobertura do item sem par na proposta: LMI 0 → ignora; LMI > 0 → pendência | 18/11/2026 |
| Q53 | Navegador do robô = **Google Chrome instalado**, com perfil próprio (substitui a Q35: o Chromium do Playwright não é assinado e o Controle Inteligente de Aplicativos do Windows 11 o bloqueia). Cada máquina precisa ter o Chrome; alternativa configurável: Edge | 18/11/2026 |
| F2 | "Verificar conexão" espera o consultor logar na janela do robô e conecta sozinho (até 5 min); o robô roda numa thread Python própria (o laço do Qt quebrava o Playwright no 2º comando) | 18/11/2026 |
| Q54 | Na busca, vale só o registro em **Nível Produção** (bolinha verde); Nível Revisão (bolinha amarela) é desconsiderado, mesmo com a mesma vigência (caso real: DDA). Só Revisão → pendência | 18/11/2026 |
| Q55 | Escolha da apólice continua **só pela vigência** (muitas têm 123456; nº não é comparado), com a trava: a apólice a renovar tem de **terminar no início da nova vigência** (31/12/2026); senão → pendência (caso real: DDA abriu a de 2024–2025) | 19/11/2026 |
| Q56 | **Modo Automático é o padrão** (substitui Q34/Q41): o robô faz 1ª tela → Avançar → coberturas → repasse → parcelas → anexos → move a pasta, sem o consultor. O consultor só intervém nas pendências (antes no app, ou "Pela metade" se algo falhar depois do Avançar). Modo Conferência continua como opção (para na 1ª tela; Continuar grava) | 19/11/2026 |
| Q58 | O app se chama **AutoCOR** (identidade do Grupo Protege: faixa azul-marinho com a logo, ícone do "P"). Ao abrir, mostra um **tutorial** (organização das pastas: uma pasta por lotérica com o nome dela, `ACORDO <lotérica>.pdf` + `<lotérica>.pdf`; conferir, conectar, executar) **antes de ler as pastas**; pode ser desligado ("Não mostrar ao abrir") e reaberto em "Como usar". Identificadores internos (registro, %LOCALAPPDATA%\SGCOR-Renovacoes) não mudaram | 19/11/2026 |
| Q57 | Coberturas que não casam (substitui a Q51 e parte da Q8): cobertura **nova na proposta** que não existe no item do SGCOR → **ignorada**; cobertura do item que **sumiu da proposta** → **fica como está** (LMI antigo). As duas só vão para o log; o robô segue. Continua pendência: cobertura da proposta sem tipo no dicionário e tipo repetido no item (caso real: BONI SORTE, Porto, com Salvamento/Custos de Defesa novos e GERPA fora sumida) | 19/11/2026 |
| F3 | Fechar o app com lote em andamento: o robô termina a lotérica atual e o app fecha (nunca interrompe no meio de uma gravação) | 19/11/2026 |
| Q52 | 1ª tela: o robô preenche **só os campos marcados pelo consultor** (Proposta, Apólice, Apólice Baixa comissão, Vigência, "Confirma as datas de vigência?" marcada, Comissão, Prêmio Total, IOF, Prêmio Líquido, Forma de Cobrança, Parcelas, 1ª Parcela–Vencimento, Emitida); o resto fica como veio. O aviso de datas que o SGCOR abre no Avançar é confirmado só se as datas forem as da config | 18/11/2026 |
| Q3 | Chave de busca = **CNPJ** da proposta; apólice anterior escolhe a linha | 18/11/2026 |
| Q4 | Cotação nº (Tokio) / Nº do orçamento (Porto) → campo "Proposta" | 18/11/2026 |
| Q5 | Tabela de bônus da imagem 15 (R$ 26,00 era campanha antiga) | 18/11/2026 |
| Q6 | Parcelas = soma (`1+5`=6, `1+9`=10, `0+10`=10); acordo do cliente sempre vence a proposta | 18/11/2026 |
| Q8 | v1 ajusta só LMI de coberturas casadas com segurança; resto → pendência | 18/11/2026 |
| Q9 | Mais de uma proposta na pasta → **perguntar ao consultor qual é a final** | 18/11/2026 |
| Q10 | Concluída → mover pasta para `_CADASTRADOS` | 18/11/2026 |
| — | ACORDO × PROPOSTA identificados **pelo conteúdo**; acordo sem forma de pagamento → pendência | 18/11/2026 |
| Q11 | CNPJ com várias apólices → escolher a de **vigência mais recente** | 18/11/2026 |
| Q11b | **Não** conferir o nº da apólice escolhida contra a apólice anterior do PDF | 18/11/2026 |
| Q12 | Falha no meio → parar naquela lotérica, marcar "Pela metade — conferir no SGCOR", seguir; sem retomada automática na v1 | 18/11/2026 |
| Q13 | **Confirmado**: `A+B` é unificado no cadastro → Parcelas = A+B (`1+9` = `0+10` = 10; `1+5` = `0+6` = 6); 1ª parcela 10/01/2027 em todos | 18/11/2026 |
| Q14 | 2+ propostas → anexar **só a escolhida** como `PROPOSTA` | 18/11/2026 |
| Q15 | Pendências no app; notificação do Windows só no fim do lote, na sessão expirada e no máx. 1 aviso agrupado/hora | 18/11/2026 |
| Q16 | Anexos: preencher **só** Descrição + arquivo; Tipo Documento e "Válido até" não são tocados | 18/11/2026 |
| Q17 | Produtor do repasse = dono do login (um consultor por instalação, campo travado) | 18/11/2026 |
| Q18 | F0 feita **a partir de prints/HTML** enviados pelo consultor | 18/11/2026 |
| Q19 | Prêmio total, IOF e prêmio líquido **digitados do PDF**; líquido + IOF ≠ total → pendência | 18/11/2026 |
| Q20 | Pastas FECHADOS **locais por consultor**; sem trava na v1 | 18/11/2026 |
| Q21 | Mover para `_CADASTRADOS` só depois de Concluir **e** dos 2 anexos salvos | 18/11/2026 |
| Q22 | F0: para cada tela, consultor manda **print + HTML** (Ctrl+S "Página completa") | 18/11/2026 |
| Q23 | Sem critério fixo F2→F3; o lote = **lotéricas marcadas no checkbox** (o robô cadastra no máx. as N marcadas); modo Conferência/Automático escolhido pelo consultor | 18/11/2026 |
| Q24 | Antes da "vigência mais recente", filtrar por **seguradora + ramo**; empate → pendência | 18/11/2026 |
| Q25 | Prints/logs só locais, apagados após **90 dias**; registro texto (ID SGCOR, valores) permanente | 18/11/2026 |
| Q26 | `.exe` instalado/atualizado **manualmente pela TI**; config separada do `.exe` | 18/11/2026 |
| Q27 | Apólice e Apólice (Baixa comissão) recebem nº **provisório** (`123456`, configurável); o consultor troca quando a apólice for emitida | 18/11/2026 |
| Q28 | Forma de Cobrança: boleto→BOLETO(1), cartão de crédito→CARTÃO DE CRÉDITO(4), cartão Porto→CARTÃO DE CRÉDITO PORTO SEGURO(25 — no SGCOR o texto está "SEGURTO"; confirmado), débito→DÉBITO EM CONTA - PJ(12), pix→PIX(36); não mapeada → pendência | 18/11/2026 |
| Q29 | Fracionamento e valor da 1ª parcela **não são preenchidos** pelo robô (o SGCOR preenche) | 18/11/2026 |
| Q30 | Renovação aparentemente já cadastrada (mais recente começa em 31/12/2026 ou anterior "Renovada") → **pendência para conferir**, sem pular sozinho | 18/11/2026 |
| F0 | Busca por URL direta (`p`=base64 do form) com CNPJ + companhia (Porto 12 / Tokio 13) + ramo 9 (Empresarial Lotérico). Mapa em `docs/f0-mapa-sgcor.md` | 18/11/2026 |
| F0 | "Concluir" não grava nada; a renovação passa a existir no **Avançar** da tela de informações. "Pela metade" (Q12) = existe `<N>` mas falta cobertura/repasse/anexo | 18/11/2026 |
| F0 | Anexo enviado direto pelo campo de arquivo (sem janela do Windows); limite 10 MB; Descrição já anexada não é reenviada | 18/11/2026 |
| F0 | Tela de Parcelas só é **conferida** (nº, 1º vencimento, soma, comissão, repasse); robô nunca clica Apagar/Cancelar/Recadastrar/Excluir | 18/11/2026 |
| Q31 | Vale a última condição combinada: fala explícita do cliente **ou** oferta explícita do consultor com parcelas **e** forma ("Podemos fechar em 1+5x no boleto?") aceita pelo cliente depois; sem isso → pendência "perguntar ao consultor" | 18/11/2026 |
| Q32 | Forma de pagamento não citada por ninguém → **boleto**, com aviso | 18/11/2026 |
| F1 | Porto: à vista e cartão Porto têm desconto e IOF próprio → prêmio total/IOF/líquido saem da **linha da forma escolhida**, não do demonstrativo geral | 18/11/2026 |
| F1 | Acordo pode ser **e-mail impresso** (Gmail) em vez de Histórico de Atendimento; numa pasta com 1 proposta, o outro PDF é tratado como acordo | 18/11/2026 |
| F1 | Acordo com CNPJ diferente da proposta → pendência (caso real: acordo de outra lotérica na pasta errada) | 18/11/2026 |

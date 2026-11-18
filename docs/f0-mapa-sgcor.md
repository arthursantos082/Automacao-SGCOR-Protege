# F0 — Mapa das telas do SGCOR

> Fonte: prints + páginas salvas em `html-sgcor/` (fora do git — contêm dados reais).
> Base: `https://grupoprotege.sgcor.com.br/`. Todas as telas são PHP clássico com jQuery; não há SPA.
> `<P>` = propostaId da apólice **anterior**; `<N>` = propostaId da **renovação** criada.

## Padrões gerais

| O quê | Como | Observação |
|---|---|---|
| Botões da barra (Avançar, Salvar…) | `ul.botoesToolbar li` cujo `span` tem o texto exato | Sem `id` estável (exceto `#btnSalvar`, que se repete). Usar texto: `li:has(> span:text-is("Avançar"))` |
| Popups | `abrirJanela2('popup.php?...')` abre camada jQuery (`jmpopups`) com iframe | Mais simples: o robô abre a URL do `popup.php` direto numa aba |
| Confirmações | `confirmaSwal(...)` / `swal` (SweetAlert) | Clicar no botão de confirmar do SweetAlert |
| Pesquisa | `?op=propostas&form=listar&p=<base64 do form serializado>` | Ex.: `p=YXBvbGljZT0yNjk0MDAw` = `apolice=2694000`. O robô pode **navegar direto** para a busca montando o `p` |
| Mensagens | faixa verde no topo ("Arquivo inserido com sucesso!", "Atualização realizada com sucesso!") | Usar como confirmação de cada etapa |

## 1. Busca (Propostas/Apólices → Pesquisar)

Campos do `form[name=form-pesquisa]` relevantes:

| Campo | name | Valor do robô |
|---|---|---|
| CPF/CNPJ | `cpf_cnpj` + `tipoCpfCnpj=segurado` | CNPJ do PDF |
| Companhia | `companhiaId` | Porto = `12` (PORTO SEGURO CIA. DE SEGUROS GERAIS), Tokio = `13` |
| Ramo | `ramoId` | `9` = EMPRESARIAL LOTÉRICO (resolve o fato pendente da Q24) |

URL direta: `?op=propostas&form=listar&p=` + base64(`cpf_cnpj=<cnpj>&tipoCpfCnpj=segurado&companhiaId=<12|13>&ramoId=9`).
⚠️ Confirmar na F2 se o servidor aceita o `p` só com esses campos (o form serializa todos).

Colunas da lista: ID, Proposta, Apólice, Clientes, Ramo (ícone), Cia (ícone), Início/Final Vigência, Tipo (ícone ↻ = Renovação, 📄 = Nova), Status.

Ações por linha (ícones da coluna Opções):

| Ícone | title | Ação |
|---|---|---|
| ↻ `fa-sync-alt` | Renovar | `?op=propostas&form=alterar&propostaId=<P>&renovar=true` |
| 📎 `fa-paperclip` | Anexos | `popup.php?op=anexos&form=listar&propostaId=<N>` |
| 💲 | Parcelas | `popup.php?op=parcelasCompletas&form=listar&propostaId=<N>&editar=true` |

## 2. Informações do Seguro (renovação)

URL: `?op=propostas&form=alterar&propostaId=<P>&renovar=true` · form `#form-formulario` → `?op=propostas&acao=renovar&propostaId=<P>&original=<P>`.

**O robô preenche só os campos marcados em amarelo pelo consultor** (print de 18/11/2026): Proposta, Apólice, Apólice (Baixa
comissão), Vigência início e fim, **Confirma as datas de vigência?** (marcar), Comissão, Prêmio Total, IOF, Prêmio
Líquido, Forma de Cobrança, Parcelas, 1ª Parcela – Vencimento e Emitida. Todo o resto fica como o SGCOR trouxe.

| Campo na tela | Seletor | Valor do robô |
|---|---|---|
| Tipo | `select[name=tipo]` (4 = Renovação) | já vem 4 — só conferir |
| Companhia | `#companhiaId` | já vem — conferir 12/13 |
| Ramo | `#ramoId` | já vem 9 — conferir |
| Proposta | `input[name=proposta]` | Cotação nº (Tokio) / Nº do orçamento (Porto) |
| Apólice | `#numeroApolice` (name `apolice`) | nº provisório `123456` (config); consultor troca na emissão (Q27) |
| Apólice (Baixa comissão) | `#apolice` (name `apoliceBaixaComissao`) ⚠️ id enganoso | **igual ao campo Apólice** (informado pelo consultor) |
| Vigência início/fim | `#data_texto_dataVigenciaInicial`, `#data_texto_dataVigenciaFinal` | vêm **vazios** na renovação → data fixa da config (Q37) |
| Confirma as datas de vigência? | `#verificaConfirmacaoVigencia` | **marcar** (indicado pelo consultor). Com ela marcada, o Avançar (`confirmaVigencia()`) abre o aviso “As datas de vigência … estão corretas?”: o cálculo do SGCOR soma 1 mês à data inicial, então o aviso aparece **sempre** para 31/12→31/12. O robô confirma o aviso só se as datas na tela forem as da config; senão, pendência |
| Comissão | `#comissao` (name `comissao[]`) | vem a do ano anterior → sobrescrever com a do PDF |
| Prêmio Total | `#premioTotal` | PDF |
| Fracionamento | `#fracionamento` | não mexer — SGCOR preenche (Q29) |
| IOF | `#imposto` | PDF |
| Prêmio Líquido | `#premioLiquido` | PDF |
| Forma de Cobrança | `#cobrancaId` | boleto=1, cartão de crédito=4, cartão Porto=25 (texto no SGCOR: "CARTÃO DE CRÉDITO PORTO SEGURTO"; selecionar pelo **value** 25, não pelo texto), débito PJ=12, pix=36 (Q28, em config) |
| Parcelas | `#parcelas` | regra §6.1 |
| 1ª Parcela vencimento | `#data_texto_dataEntrada` | 10/01/2027 (config) |
| 1ª Parcela valor | `#valorEntrada` | não mexer — SGCOR preenche (Q29) |
| Emitida | `#data_texto_dataEmitida` | hoje |
| Corretor, Funcionário/Subscritor, Funcionário Emissor, Fracionamento, 1ª Parcela – Valor, Status, Segurado, Grupos | — | já vêm — **não mexer** |

Barra: **Avançar** (`confirmaVigencia()`), Voltar, Importar PDF (`?op=importacaoPropostasNova&form=importarLote`).

## 3. Itens e Coberturas

URL: `?op=propostasItens&form=listar&avancar=true&propostaId=<N>&cadastro=true`.
Item "guarda-chuva" (ícone `fa-umbrella`, title "Coberturas") → `popup.php?op=propostasItensCoberturas&form=listar&propostaId=<N>&propostaItemId=<I>`.

Lista de coberturas: Cobertura, Valor/LMI (R$), Franquia, Prêmio Líquido. Lápis de cada linha →
`popup.php?op=propostasItensCoberturas&form=alterar&propostaItemCoberturaId=<C>&propostaId=<N>&...`.

Formulário de edição da cobertura (`#form-formulario` → `?op=propostasItensCoberturas&acao=atualizar&propostaItemCoberturaId=<C>&propostaItemId=<I>&ramoId=9&propostaId=<N>`):

| Campo | Seletor | Valor do robô |
|---|---|---|
| Cobertura | `select[name=coberturaId]` (105 opções, "456 - GERPA - SUB. DE VALORES NO INTERIOR…") | **não mexer** — só ler para casar com o dicionário |
| LMI R$ | `input[name=importancia]` (formato `30.000,00`) | LMI do PDF quando casado com segurança (Q8) |
| LMI US$, Franquia, Bônus, %, Prêmio Líquido, Observações | `importanciaDolar`, `franquia[valor]`, `franquia[franquiaDolar]`, `franquia[descricao]`, `bonus`, `porcentagem`, `premioPadraoCobertura`, `observacoes` | não mexer |

Barra do popup: **Salvar** (`li#btnSalvar` → `$('#form-formulario').submit()`), Voltar → volta à lista de coberturas.

Barra: **Avançar** → `?op=propostas&form=getRepassesPropostaOriginal&cadastro=true&propostaId=<N>`.

## 4. Repasses

Lista: `?op=repasses&form=listar&propostaId=<N>&cadastro=true`. Lápis → `confirmaSwal("…iremos excluir as parcelas…")` → confirmar →
`?op=repasses&form=alterar&propostaRepasseId=<R>&propostaId=<N>&cadastro=true&parcelas=true`.

| Campo | Seletor | Valor do robô |
|---|---|---|
| Produtor | `#produtorId` | consultor do login (Q17) |
| Forma de Repasse | `#repasseForma` | já vem `NP` — conferir |
| Repasse Sobre | `#repasseSobre` | `VF` |
| Valor Fixo | `#valorFixo` | bônus da tabela da campanha |
| Parcela Única / Definir Parcelas | `#radio_definirParcelasVF_0` / `_1` | Parcela Única (padrão) |

Barra: **Salvar e Gerar Parcelamento** (`li#btnSalvar` com `salvar(event, true)` — há dois `#btnSalvar`, usar o texto).
Depois volta à lista de repasses ("Atualização realizada com sucesso!") → conferir Valor Fixo na linha → **Avançar** →
`?op=parcelasCompletas&form=listar&propostaId=<N>&cadastro=true`.

## 5. Parcelas

URL: `?op=parcelasCompletas&form=listar&propostaId=<N>&cadastro=true`. Tabela por parcela: Parc., Valor Parc., Vencimento, P.L., Com. (%), Com. Prev.; rodapé com totais e "Repasse para <produtor>" = Valor Fixo.

| Conferência do robô (só leitura) | Esperado |
|---|---|
| Nº de linhas | = parcelas do acordo |
| Vencimento da parcela 1 | 10/01/2027 (config) |
| Soma Valor Parc. | ≈ Prêmio Total do PDF (tolerância de centavos) |
| Com. (%) | = comissão do PDF |
| Repasse para o produtor | = bônus da campanha |

Divergência → pendência "Parcelas divergentes" (nada é apagado).

**Concluir** só navega para `?op=propostas&form=listar` — **não grava nada**. Os pontos que gravam são: Avançar da tela 2 (cria a renovação `<N>`), Salvar de cada cobertura, e Salvar e Gerar Parcelamento.
Botões perigosos que o robô **nunca** clica: Apagar, Cancelar, Recadastrar, Excluir.

## 6. Anexos

Lista: `popup.php?op=anexos&form=listar&propostaId=<N>` (colunas Tipo Documento, Descrição, Arquivo, Status).
Novo: `popup.php?op=anexos&form=cadastrar&propostaId=<N>` · form `#form-formulario` → `?op=anexos&acao=inserir&propostaId=<N>`.

| Campo | Seletor | Valor do robô |
|---|---|---|
| Descrição | `input[name=descricao]` | `ACORDO` / `PROPOSTA` |
| Arquivo | `input[type=file][name=arquivo]` | caminho do PDF — `set_input_files` direto, **sem abrir a janela do Windows** |
| Tipo Documento, Válido até, Observações | `tipoDocumentoId`, `validade`, `observacoes` | não mexer (Q16) |

Salvar: `li#btnSalvar` → mensagem "Arquivo inserido com sucesso!". Limite do SGCOR: **10 MB** por arquivo → PDF maior vira pendência antes de tentar.
Idempotência: antes de inserir, ler a lista e pular a Descrição que já existir.

## Faltam

Nada para o caminho principal. Na F2 confirmar: URL de busca com `p` reduzido, e o comportamento do SweetAlert ao editar o repasse.

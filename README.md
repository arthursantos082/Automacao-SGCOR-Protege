# AutoCOR

Robô do **Grupo Protege** que cadastra no **SGCOR** as renovações das lotéricas fechadas da **Porto** e da **Tokio**.

O consultor organiza as pastas, confere a lista no AutoCOR e clica em Executar. O robô então faz a renovação inteira no SGCOR:

1. busca a apólice anterior;
2. preenche a 1ª tela;
3. ajusta o LMI de Incêndio e de Valores (no interior e em trânsito); as outras coberturas ficam como estão no SGCOR;
4. faz o repasse;
5. confere as parcelas;
6. anexa o acordo e a proposta;
7. move a pasta para `_CADASTRADOS`.

O consultor só precisa agir quando aparece uma **pendência**, por exemplo quando o AutoCOR não consegue identificar no acordo as parcelas que o segurado pediu.

## Como organizar as pastas

Cada lotérica tem a sua própria pasta, com o nome da lotérica, dentro de `FECHADOS PORTO` ou `FECHADOS TOKIO`. Dentro dela ficam só dois PDFs: o acordo e a proposta da seguradora.

```
FECHADOS TOKIO
└── COSTA & CANDIDA LTDA
    ├── ACORDO COSTA & CANDIDA LTDA.pdf     ← conversa/e-mail com o que foi combinado
    └── COSTA & CANDIDA LTDA.pdf            ← proposta da seguradora
```

- O nome da pasta pode ser o nome da lotérica, o nome + CNPJ, ou só o CNPJ.
- Outros PDFs na pasta (por exemplo, a apólice anterior) são ignorados: o robô só usa o acordo e a proposta.
- Não deixe PDF solto direto em `FECHADOS PORTO` ou `FECHADOS TOKIO`.
- A pasta `_CADASTRADOS` é do robô: ele move para lá cada lotérica que termina. Se uma lotérica que já está lá aparecer de novo em `FECHADOS` (mesmo CNPJ ou mesmo nome), ela fica como pendência "Já cadastrada", para não ser cadastrada duas vezes.

O AutoCOR identifica cada PDF pelo conteúdo, então nomes um pouco diferentes também funcionam. Mesmo assim, siga esse padrão para todo mundo achar tudo.

## Como usar

O AutoCOR abre com um tutorial, que também pode ser aberto no botão **Como usar**. O uso é este:

1. Na lista, cada lotérica aparece como **Pronto** (verde), **Pendente** (vermelho) ou **Pela metade** (laranja); os botões acima da lista filtram por cada um. Para ver o motivo de uma pendência, clique na lotérica: os botões **Abrir acordo** / **Abrir proposta** ficam amarelos no PDF onde está o problema. Para resolver, corrija a pasta ou informe as parcelas e a forma em **Resolver**. Se a vigência da proposta for diferente da padrão, o botão **Seguir com a vigência padrão…** pede a sua confirmação.
2. Clique em **Verificar conexão ao SGCOR** (fica amarelo até a conexão dar certo). Se o SGCOR pedir login, entre com o seu usuário na janela do Chrome que o robô abre. O robô nunca digita nem guarda senha.
3. Escolha o seu nome em **Consultor / Produtor**. É esse nome que vai no repasse.
4. Marque as lotéricas prontas, clique em **Executar selecionadas** e confirme o resumo.
5. Acompanhe pelo log. Se algo falhar depois de criada a renovação, ela fica **Pela metade**. Nesse caso, execute de novo, que o robô continua de onde parou.
6. Em **Ver cadastradas** aparecem as lotéricas já cadastradas, com o ID do SGCOR.

O ícone ao lado do CNPJ copia o número. O botão **Tema**, no cabeçalho, troca entre claro, escuro e automático (igual ao Windows).

## Instalação nas máquinas (TI)

**Download:** baixe o `AutoCOR.zip` da [última Release](https://github.com/arthursantos082/Automacao-SGCOR-Protege/releases/latest). Ele fica fora do git porque passa do limite de 100 MB por arquivo do GitHub.

O pacote `AutoCOR.zip` já traz tudo o que é preciso. **Não é preciso instalar Python** nem nenhuma outra dependência. A única exigência é o **Google Chrome**, que o robô usa para operar o SGCOR.

1. Descompacte o `AutoCOR.zip` em qualquer lugar e abra o `AutoCOR.exe`.
2. Ele avisa que ainda não está instalado. Clique em **Instalar** e aceite a permissão de administrador que o Windows pede.
3. O AutoCOR se copia para `C:\Program Files\AutoCOR`, cria o atalho no Menu Iniciar e **pergunta se você quer um atalho na área de trabalho**. Depois disso, a pasta descompactada pode ser apagada.
4. Para remover, use **Configurações > Aplicativos > Aplicativos instalados > AutoCOR > Desinstalar**. Os dados do consultor ficam guardados.

**Atualizações.** A partir da 1.1.0, o AutoCOR instalado procura versão nova sempre que abre (ou pelo botão **Verificar atualização**). Se houver, ele baixa, fecha e se atualiza; o Windows pede permissão de administrador. As máquinas que ainda estão na **1.0.0** não têm esse recurso e precisam atualizar uma vez à mão: baixe o `AutoCOR.zip` da última Release, abra o `AutoCOR.exe` e clique em **Atualizar**.

Atualizar à mão funciona do mesmo jeito: abra o `AutoCOR.exe` novo e clique em Atualizar. A pasta `config\` que a TI já ajustou é mantida, e a da versão nova fica em `config.novo\` para comparar.

O botão **Só abrir desta vez** roda o AutoCOR da própria pasta, sem instalar.

O .exe não tem assinatura digital. Se o Windows mostrar "aplicativo não reconhecido", libere-o uma vez. Com o Controle Inteligente de Aplicativos ligado, um .exe sem assinatura pode ser bloqueado; isso aconteceu com um instalador separado que tentamos, e por isso o próprio `AutoCOR.exe` se instala. A solução definitiva é assinar o .exe com um certificado de assinatura de código da empresa.

### Configuração (`config\`, ao lado do .exe)

| Arquivo | O que tem |
|---|---|
| `padrao.toml` | datas da campanha (vigência e 1ª parcela), tabela de bônus por comissão, códigos das formas de cobrança, coberturas que o robô ajusta, repositório das atualizações, endereço do SGCOR e IDs de companhia e ramo |
| `coberturas.toml` | dicionário de coberturas Porto/Tokio ↔ SGCOR (por tipo) |

Depois de editar algum desses arquivos, feche e abra o AutoCOR.

### Dados locais

Os dados locais ficam em `%LOCALAPPDATA%\SGCOR-Renovacoes`:
- o estado: ajustes do consultor, renovações pela metade e cadastradas;
- os logs e os prints do robô, apagados automaticamente depois de 90 dias;
- o perfil do Chrome do robô.

Esses arquivos têm dados de clientes e **nunca** vão para o repositório.

## Desenvolvimento

É preciso ter o Python 3.15 e o Google Chrome.

```powershell
py -3.15 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest -q
```

Para abrir sem empacotar, use `abrir-app.pyw` (o `criar-atalho.ps1` cria o atalho com ícone) ou `abrir-app.bat`.

### Gerar o .exe

```powershell
.venv\Scripts\python.exe empacotar\montar.py
```

O comando gera `dist\AutoCOR\` (`AutoCOR.exe` + `config\` + `LEIA-ME.txt`) e `dist\AutoCOR.zip` para a TI. A instalação fica em `src/sgcor_renov/instalacao.py`. As pastas `dist/` e `build/` não vão para o git.

Para publicar uma versão nova, suba o número em `VERSAO` (`instalacao.py`), gere o .exe e crie a Release:

```powershell
gh release create v1.0.1 dist\AutoCOR.zip --title "AutoCOR 1.0.1" --notes "O que mudou"
```

### Estrutura

| Caminho | O que é |
|---|---|
| `src/sgcor_renov/` | leitura dos PDFs (`propostas`, `acordo`, `coberturas`), regras (`regras`), estado local (`estado`) |
| `src/sgcor_renov/robo/` | robô do SGCOR: `paginas` (leitura de telas, testável sem navegador) e `navegador` (Playwright + Chrome) |
| `src/sgcor_renov/ui/` | janela (PySide6), tutorial, cadastradas, leitor em paralelo e a thread do robô |
| `config/` | configuração editável |
| `docs/f0-mapa-sgcor.md` | mapa das telas e seletores do SGCOR |
| `plan.md` | plano e registro de decisões (Q1…Q78) |
| `empacotar/` | ponto de entrada e script do PyInstaller |

### Regras de segurança

- Dados de clientes nunca vão para o git. Isso inclui PDFs, HTML salvo do SGCOR, relatórios, SQLite, logs e prints.
- Nada é gravado no SGCOR sem o consultor clicar em Executar e confirmar o resumo.
- O robô nunca clica em Apagar, Cancelar, Recadastrar ou Excluir.

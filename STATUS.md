# STATUS — ERP IN-360 (MVP) · MVP_ERP_GIRAFFAS

**Última atualização:** 02/10/2026 — 🟡 **Passo 5c-3 (motor de match banco × GCOM) construído na sessão NUVEM, ainda NÃO
instalado no PC** (seção abaixo). Antes: 30/09 ~23h55, abril do Santander completado.

## 🟡 Passo 5c-3: MOTOR DE MATCH BANCO × GCOM (02/10, código pronto, falta rodar no PC)
- Feito numa sessão **na nuvem** (sem acesso a `C:\giraffas-erp-data`, ao Postgres do PC nem ao Drive). Testado em
  Postgres 16 local da nuvem só com dados fictícios: **56/56**. Ramo git `claude/amazing-fermat-a3ee0o`.
- `modules/conciliacao/motor.py` (função pura) + `servico.py` + CLI `python -m modules.conciliacao.rodar --tenant
  rodiza [--simular]` + API `POST /tenants/{id}/conciliacao/rodar` (conciliacao:operar), `GET …/conciliacao/resumo` e
  `GET …/conciliacao?status=&mes=` (conciliacao:ler **e** banco:ler: gestor de loja recebe 403).
- Migração `d1e2f3a4b5c6`: `conciliacoes` + `conciliacao_itens` (RLS nas duas; 1 débito só em 1 conciliação ativa;
  `acrescimo` = multa/juros por atraso separado da diferença).
- Regras: um_para_um (RFG) · agrupado_vencimento (Ribeiro: soma por vencimento) · nota_mais_ajuste (JM: agrupa pelo
  NÚMERO, complemento "1"/"/1"/"D"; pago após o vencimento aceita acréscimo até `parametros.atraso_max_pct`, padrão 5%)
  · consolidado_mensal (Kelminas: soma do mês × débito do mês seguinte perto de `parametros.dia_debito`, padrão 5;
  sem soma exata e 1 débito só na janela → "investigar" com a diferença) · livre/sem padrão/sem fornecedor: só valor
  exato + janela e par único → "sugerido" (nunca "batido"). Empate → "investigar", nunca escolha automática.
- Cada rodada refaz só o que o motor criou e ninguém confirmou. Resumo por mês mostra também **débitos sem documento**
  (banco) e **documentos sem pagamento** (GCOM). Transferência entre contas e PREVISTO ficam fora.
- **Para instalar no PC:** `git pull` deste ramo → backup manual → `alembic upgrade head` → `python -m
  modules.conciliacao.rodar --tenant rodiza --simular` → conferir os números → rodar sem `--simular`.
- ⚠️ **Conferir no PC:** os nomes das chaves gravadas em 30/09 no `parametros` do padrão da JM. O motor lê
  `atraso_max_pct`; se a chave gravada tiver outro nome, vale o padrão de 5% (o mesmo aprovado).
- **Falta:** tela no painel; confirmar/descartar pela API (hoje só o motor grava); descarte não impede o motor de
  propor o mesmo par de novo (resolver junto com o botão de descartar).
- **3 camadas de recebíveis (pedido do usuário, 02/10):** 1 = sistema × digitado (coluna do fechamento de caixa, a
  mesma da quebra de caixa) · 2 = sistema × adquirentes e parceiros (Cielo, Getnet, iFood, Alelo, Ticket, VR,
  Pluxee) + **taxa cobrada × contrato** (sem gabarito → em branco, com divergências) · 3 = adquirentes/parceiros ×
  banco. Ordem aprovada: **3 → 2 → 1**. Só existem no Datalake (Drive); os repositórios `giraffas-datalake` e
  `giraffas_conciliacao_financeiro` no GitHub estão **vazios**. Portar exige sessão LOCAL no PC (paridade só lá).
- 🔴 **O repositório `MVP_ERP_GIRAFFAS` no GitHub está PÚBLICO** (visto em 02/10). Tornar privado e, depois, trocar
  as senhas repetidas dos 5 serviços.

## 🔎 Getnet × extrato Santander (30/09 ~19h45, só análise; nada importado ainda)
- Usuário achou os relatórios da Getnet (EC 16081414, 01/02–29/09/26), copiados (não movidos) do Datalake para
  `C:\giraffas-erp-data\entrada\getnet\`: `Vendas_Detalhado_…xlsx` (abas CARTÕES 266 vendas · PIX 2.925: 2.679 pagas,
  245 QR expirado, 1 negada · VOUCHER 3) e `Recebivel_Completos_…xlsx` (Resumo, Sintético, Detalhado: 304 linhas com
  venda → vencimento → líquido, NSU, autorização; recebido total R$ 13.868,62; 1 "Aluguel/Tarifa" −R$ 71,07 em set).
  Pix Getnet: taxa zero, 100% liquidado no Santander, cai no mesmo dia (54%) ou em até 3 dias (fim de semana).
- **Cartões Getnet × Santander: centavo a centavo** em fev, mar, abr, jul e ago; só mai (−R$ 727,81) e jun (−R$ 107,64)
  divergem = buracos do extrato.
- **Pix, venda a venda (valor + até 3 dias): 2.475 de 2.679 achados no Santander.** Os 204 que faltam (R$ 9.926,50)
  estão quase todos em 28/02–01/03, 01–02/04, 01–07/05 e 02–05/06 → **prova que os arquivos do Santander de abr, mai e
  jun foram cortados no limite de 440 linhas** (começam em 02/04, 07/05 e 05/06). Rebaixar esses trechos resolve.
  Sobram 8 créditos Pix sem venda Getnet (R$ 254,36: 3 centavos de teste em 06/02 + 5 Pix diretos).
- **Provedor do Pix de venda (confirmado pelo usuário, 30/09):** Cielo no Bradesco até fev/26 → Getnet no Santander
  (27/02 a jul, 33 vendas em ago) → de volta à Cielo no Bradesco. No extrato: "PIX RECEBIDO REM: RODIZA ALIMENTOS"
  (Bradesco) = favorecido **CIELO PIX**; "PIX RECEBIDO <nº>" (Santander) = **GETNET PIX** (dicionário atualizado e
  reaplicado). Exceções ainda como CIELO PIX: R$ 8.000 (04/05) e R$ 5.200 (05/06), prováveis transferências nos buracos
  do Santander.
- **Buracos do Santander verificados (30/09, saldo + Getnet):**
  - 28/02–01/03 = fim de semana (usuário). Saldo: +R$ 260,10 entre 27/02 e 02/03 → Pix do fim de sexta/início de
    segunda fora dos arquivos (≈ R$ 236,60 de vendas Getnet sem crédito). Baixa prioridade.
  - **01/04 (quarta): falta o dia inteiro** (arquivo de abr começa 02/04). +R$ 951,22 = R$ 962,70 de Pix Getnet −
    ~R$ 11 de tarifa.
  - 01/05 feriado, 02–03/05 fim de semana. **04–06/05 (seg–qua): faltam.** −R$ 3.647,32 ≈ R$ 4.433,20 de Pix Getnet
    − **R$ 8.000 de transferência ao Bradesco (o crédito de 04/05 lá)** − ~R$ 80 de tarifa.
  - **02–04/06 (ter–qui) + início de 05/06: faltam.** −R$ 1.463,37, compatível com Pix Getnet (R$ 2,8–3,4 mil) −
    **R$ 5.200 de transferência ao Bradesco (crédito de 05/06 lá)** − tarifas.
  - **Rebaixar do Santander:** 01/04, 04/05–06/05 e 02/06–05/06 (períodos curtos, por causa do limite de 440 linhas).
  - Arquivo novo `extrato-pj-30_09_2026_16h34m57s.xlsx` (Downloads → copiado para entrada\extratos): 15/07–10/09, 520
    linhas, saldo fecha, **0 lançamentos novos** (período já carregado). Não cobre os buracos.
  - ✅ **Novo formato: extrato do internet banking do Santander** ("EXTRATO DE CONTA CORRENTE", data por extenso,
    Crédito/Débito, SEM saldo, sem documento, Pix sem CPF, mês inteiro). Lido por `extratos.py` (formato `santander_ib`)
    e importado por `servico._completar_buracos`: reconhece por DATA + VALOR dia a dia; recusa o arquivo se o banco
    tiver algo que ele não tem; só insere dentro de buraco provado pelo saldo e só se a soma fechar EXATAMENTE; recalcula
    o saldo dos novos (no último dia do buraco entram antes dos existentes). Testes 44/44.
  - ✅ **Abril completado (30/09 ~23h55):** `santander_ib_2026-04_excel_export1790822771547.xlsx` (de Downloads, copiado):
    06–30/04 idênticos ao banco lançamento a lançamento; entraram 01/04 inteiro (13) + manhã de 02/04 (11) = 24, soma
    R$ 951,22 = buraco. Regra do Pix agora `^PIX RECEBIDO( \d+)?$` (a antiga, id 263, desligada com audit_log) + regra
    "JUROS SALDO UTILIZ" (cheque especial) = SANTANDER/ENCARGO.
  - **Falta exportar neste mesmo modelo: MAIO e JUNHO** (buracos 30/04→07/05 −R$ 3.647,32 e 01/06→05/06 −R$ 1.463,37);
    opcional fev/mar (27/02→02/03, +R$ 260,10). Salvar com "santander" no nome na pasta de sempre, ou mandar o caminho.
  - Pergunta do usuário: o nº depois de "PIX RECEBIDO" serve de documento? **Não: é o CPF (11 díg.) ou CNPJ (14) de quem
    pagou** (2.316 lançamentos com só 1.674 CPFs distintos). Nem precisa: a chave anti-duplicidade é data + valor + saldo,
    e o leitor do Santander já aceita arquivo sem a coluna Documento. O relatório Pix da Getnet não traz o CPF do pagador,
    então o cruzamento Getnet × banco continua por valor + data (2.475/2.679). É dado pessoal (LGPD): só aparece para
    quem tem `banco:ler`.

## ✅ Calendário da franqueadora (30/09 ~16h10, em produção)
- **Regra do usuário (30/09):** não existem 2 royalties no mesmo mês. **Royalties vence dia 20**, **fundo de marketing
  no último dia do mês**; em fim de semana paga no 1º dia útil seguinte. Os boletos chegam no e-mail da Rodiza
  (rodizaalimentos@gmail.com, acessível pelo conector Gmail) — boletos do shopping também. As 2 linhas "cegas" de 25/05
  (DESPESA/DIVERSOS) **estão corretas** (confirmado pelo usuário).
- E-mail confirma: "BOLETO ROYALTIES - VENCIMENTO 20/03/2026 (Ref. FEVEREIRO/2026)" → royalties do dia 20 = vendas do
  mês ANTERIOR (idem fundo de marketing: "venc. 31/03, Ref. Fat. FEVEREIRO").
- Migração `c9d0e1f2a3b4`: `extrato_regras.parametros` (jsonb). Regra manual "PAGTO ELETRON COBRANCA GIRAFFAS" com
  `calendario`: REFIN = valores fixos R$ 2.419,16 e R$ 1.747,35 (~dia 15); ROYALTIES dia 20; FUNDO MKT último dia.
  Janela: vencimento −3 dias até 1º dia útil +4 (cobre feriado: 30/04 pago 04/05); empate → humano. Vale ACIMA da
  planilha (origem `sistema`); `manual` intocável. Também regra "COBRANCA REFIN GIRAFFAS" (texto novo, set/26).
- **4 correções na planilha:** 20/03 R$ 8.990,89 FUNDO MKT→ROYALTIES; 20/07 R$ 9.679,90 REFIN→ROYALTIES; 31/07
  R$ 5.807,94 REFIN→FUNDO MKT; 20/08 R$ 13.903,92 REFIN→ROYALTIES. Agora todo mês: 1 royalties + REFIN R$ 4.166,51.
- 🔴 **Erros no GCOM (NÃO corrigidos: escrita no GCOM é do usuário):**
  - jul/26: 1 doc de R$ 15.487,84 como ROYALTIES = royalties R$ 9.679,90 (20/07) + fundo mkt R$ 5.807,94 (31/07);
    a observação do doc ainda diz "REFIN".
  - abr/26: **royalties em dobro** (R$ 10.561,96 doc 20042026 + R$ 10.562,00 doc 20260619124147); o banco pagou 1.
  - fev/26: **fundo de marketing em dobro** (R$ 8.240,06 doc 02032026 + doc 20260615021035 venc. 03/06); o banco pagou 1.
  - mar/26: R$ 8.990,89 (venc. 20/03) lançado como FUNDO DE MARKETING; é ROYALTIES (e-mail).
- **Lacunas:** fundo mkt de ago (venc. 31/08) não está no extrato → provável no buraco do Bradesco 31/08→01/09
  (−R$ 21.097,24); REFIN de set/26 só 1 dos 2 boletos (falta o de R$ 2.419,16).
- Testes: 43/43. Backup antes: `backups\manual\antes_calendario_20260930.dump`.

## ✅ Passo 5c-2: VISÃO CAIXA (30/09 ~15h20, em produção)
- Respostas do usuário (30/09): **MB = RFG**; **Getnet sem acesso ao portal → usar o extrato do banco**; conversão
  para as categorias do GCOM aprovada ("pode seguir assim"); vai passar a pasta com todos os extratos do Santander.
- Migração `b8c9d0e1f2a3`: `extrato_categorias` (classe do extrato → Tipo de Desembolso do GCOM, com exceção por
  favorecido; grupos despesa/receita/fora_dre/outra_entrada; RLS) + `extrato_regras.classificacoes` (classes já vistas
  para o texto: se todas caem na mesma categoria, o painel usa ela — ex.: Pix de funcionário → PESSOAL).
- Sementes: `database/seeds/categorias_caixa_rodiza.json` (55 itens) e 7 `regras_manuais` em
  `extrato_favorecidos_rodiza.json` (MB→RFG; Getnet crédito/débito; "PIX RECEBIDO <nº>" = cliente Pix; tarifa QR e IOF
  do Santander; Pix ao sócio no Santander = RETIRADA, como no Bradesco). Carga: `python -m modules.banco.classificar
  --tenant rodiza --planilha … --banco Bradesco --dicionario … --categorias …` (idempotente).
- **Correção da proposta aprovada, pelos dados:** REFIN vai para DESPESAS FINANCEIRAS OPERACIONAIS (não "fora do DRE"),
  porque o GCOM lança lá (Outros Custos Financeiros: R$ 58.340,00 × R$ 58.557,33 pagos). Fora do DRE: transferência
  entre contas, aportes, retiradas, empréstimo, consórcio.
- `modules/paineis/caixa.py` + rota `?visao=caixa` (exige **`banco:ler`**; gestor de loja recebe 403) + `meses?visao=caixa`.
  Tela: botão Caixa, receita = vendas recebidas no banco, bloco "Fora do DRE", aviso "extrato até" e "R$ X a classificar".
- **Regra só aprende com linha cujo texto na planilha = texto do banco.** Achado: em 25/05 a exportação antiga trazia
  só "PAGTO ELETRON COBRANCA" e 2 boletos foram classificados às cegas como DESPESA/DIVERSOS; o banco mostra que eram
  **Ribeiro (R$ 552)** e **associação de lojistas (R$ 173)**. Continuam como a planilha disse (revisar).
- Cobertura agora: Santander entradas **2.530/2.530**; Santander saídas 91/101 (falta: fatura cartão Master 7×, 1 boleto,
  prefeitura BH, 1 Pix); Bradesco saídas 653/688 (pendente R$ 39,8 mil, maior: Pix de R$ 13.430 a uma pessoa).
- Números (fev–ago): receita recebida no banco ≈ faturamento (ex.: ago R$ 220 mil × R$ 233 mil); despesas caixa
  R$ 1,397 mi × competência R$ 1,469 mi; retiradas do sócio R$ 177 mil × aportes R$ 173,5 mil.
- 🔎 **Achado (RESOLVIDO pelo calendário da franqueadora, ver seção acima):** em jul/ago a planilha marcou como REFIN boletos da franqueadora que batem centavo a
  centavo com os ROYALTIES do GCOM: 20/07 R$ 9.679,90 + 31/07 R$ 5.807,94 = R$ 15.487,84 (royalties jul) e 20/08
  R$ 13.903,92 (royalties ago). O REFIN de verdade é fixo: 2 boletos/mês, R$ 2.419,16 + R$ 1.747,35 = R$ 4.166,51.
  Por isso a visão caixa mostra royalties zerados e despesas financeiras altas em jul/ago.
- Testes: 42/42. Backup manual antes: `C:\giraffas-erp-data\backups\manual\antes_5c2_20260930.dump`.
- **Próximo:** importar os extratos do Santander da pasta que o usuário vai indicar (fecha os buracos de mai/jun e
  confirma as 2 transferências prováveis), depois 5c-3 (motor de match banco × GCOM, que resolve os "a classificar").

**(29/09) ✅ ETAPA 1 CONCLUÍDA E EM USO NO PC.**
- ✅ Cópia offline da chave-mestra (usuário).
- ✅ Admin criado: rod.santana.particular@gmail.com (id=1, `plataforma_admin`).
- ✅ Passo 4: cliente `rodiza` (id 1), loja Shopping BH/GSHBH (id 1), 7 conexões, **7 senhas levadas do
  keyring ao cofre** (versão 1 cada). O keyring do Windows segue intacto (scripts atuais continuam).
- Acesso: http://127.0.0.1:8100/docs → Authorize (e-mail + senha).
- ⚠️ **Achado de segurança:** a mesma impressão digital (`75e59dac…`) aparece em GCOM, iFood, Pluxee, VR
  e Alelo, ou seja, **a mesma senha em 5 serviços**. Recomendado trocar por senhas distintas em cada
  portal e depois atualizar keyring + cofre (`configurar_etapa1_rodiza.py --substituir`).
- Dica: o `getpass` do Python no terminal do VS Code não mostra nada e não aceita Ctrl+V. Para digitar a
  senha, usar wrapper PowerShell com `Read-Host -AsSecureString` e a variável `ERP_SENHA`.

## 🧭 Pedido novo (29/09): painel "peso de cada fornecedor" + decisões
- **Painel pedido:** % e valor absoluto de cada fornecedor sobre (a) despesa total, (b) a categoria dele
  (ex.: MB % de INSUMOS) e (c) a receita. Seletor de período, vários meses lado a lado, visão
  **competência** e visão **caixa**. Mais o **relatório CRM em Excel** gerado do banco.
- **Decisão:** despesas vêm por **cópia diária SÓ LEITURA do banco do Raio-X** (contêiner
  `in-360-giraffas-db-1`, sessão `default_transaction_read_only`, sem mexer em nada lá) até o Raio-X ser
  portado. **Receita:** o usuário quer ver as duas fontes (vendas da Gestão × receita do DRE do GCOM) para
  um mês antes de escolher.
- **Achados no Raio-X (lidos 29/09):** 685 despesas, fev–ago/2026, todas PAGO. O `mes` = mês da **data de
  entrada** (100%), ou seja, competência. **`data_pagamento` está vazia em todas**, então a visão caixa real
  depende do **extrato** (e do caixa em espécie). Categoria = `desembolso` do GCOM (INSUMOS, OCUPAÇÃO...);
  12 docs têm várias categorias e são rateados por `sub_itens`. **"O PRÓPRIO ESCRITÓRIO" = 231 docs,
  R$ 503 mil (~30%)**: não é fornecedor, precisa ser aberto por categoria no painel.
- **Caixa em espécie:** hoje é uma planilha manual; **a partir de outubro/2026 será lançado no GCOM**.
- **Conciliação com conta corrente / entradas e saídas reais** (pedido de 28/09 19h05): desenhada (plano §6 +
  modelo 002), **ainda não construída**. É o próximo bloco depois do painel (importar extrato Bradesco).
- **JM (analisado 29/09):** não existe diferença entre nota e pagamento. Cada compra gera a nota principal
  + um 2º documento com o MESMO número + sufixo "1" (ou "/1", ou prefixo "D"), de ~15–40% do valor, com o
  mesmo vencimento. A soma dos dois = o que se paga. Proposta: trocar o padrão para `agrupado_vencimento`
  com tolerância R$ 0,00 (aguarda OK). Erros de digitação no GCOM achados: doc 231350 com vencimento
  **11/09/2027** (o par 2313501 é 11/09/2026); doc "20260824041737" (R$ 276,39, venc. 25/06); nº 208528
  usado nas duas notas de 19/03.
- **Integrações reais hoje:** GCOM pelo sistema; Cielo por e-mail diário (vendas + financeiro); parceiros
  (vouchers, iFood) manuais por causa de captcha.

## ✅ Passo 5c-1: QUEM RECEBEU CADA SAÍDA (30/09 ~14h20, em produção)
- PC reiniciado às 13h07 (o `.wslconfig` de 6 GB já vale). Docker subiu sozinho com a API.
- Migração `a6b7c8d9e0f1`: tabela `extrato_regras` (RLS) + `extrato_lancamentos.favorecido/regra_id`; origem
  `sistema` para transferência entre contas. Backup manual antes: `C:\giraffas-erp-data\backups\manual\antes_5c_20260930.dump`.
- `modules/banco/classificacao.py` + CLI `python -m modules.banco.classificar`. Origens, da mais forte para a mais
  fraca: **manual** (nunca tocada) > **sistema** (transferência provada pelo PAR: saída numa conta = entrada na
  outra, mesmo valor, ≤ 2 dias, nome da empresa na entrada; só se o par for único) > **planilha** (linha a linha da
  `15_Bradesco_tratado_2026_08_Atualizado.xlsx`) > **aprendida** (regra por LEFT 33 do histórico, com "TRANSFERENCIA
  PIX DES/REM" padronizado para "PIX ENVIADO DES/PIX RECEBIDO REM" e sem a data do fim do Pix).
- **A regra dá o FAVORECIDO; a classificação só quando o texto decide.** 16 das 126 regras ficam só com favorecido
  (ex.: boleto "COBRANCA GIRAFFAS" = royalties OU fundo mkt OU REFIN; Multiplan = aluguel OU transf. de ponto; Pix
  de funcionário = folha OU adiantamento OU dobra). Quem decide é o match com o GCOM (5c-3) ou um humano.
- Grafias e ligação favorecido → fornecedor do CRM: `database/seeds/extrato_favorecidos_rodiza.json`
  (MG Comercial Bebidas = BOITIQUE, pela razão social do GCOM).
- O importador diário (`IN360_Pontes_Diarias` → `modules.banco.importar`) agora classifica sozinho o que entra.
- **Resultado:** 3.039/3.041 linhas da planilha ligadas ao extrato; 126 regras; 2.379 lançamentos classificados por
  regra (inclui out/25–jan/26 e set/26); 30 transferências. Cobertura: Bradesco saídas 652/688 (pendente R$ 51,4 mil),
  entradas 4.764/4.789; Santander saídas 30/101 (tarifas Pix, fatura cartão, 2 Pix ao sócio, IPTU…), **entradas 0/2.530**
  (a planilha é só do Bradesco; vendas Getnet cartão + Pix).
- **Paridade com a planilha (fev–ago, por mês × natureza × classificação): 120/134 grupos idênticos**; os 14 com
  diferença estão explicados abaixo. Testes: 41/41.
- **Achados:**
  - **R$ 115.138,78 de "PIX" na planilha (créditos) são transferências do Santander** (30 pares exatos). Quem somar
    as entradas das duas contas conta esse dinheiro duas vezes. Jul/26: R$ 28,1 mil dos R$ 28,3 mil de "PIX" eram isso.
  - **Linha duplicada na planilha:** Pix de R$ 400,00 de 02/03 (doc. 2113419) aparece 2× (DOBRA e INSUMO/DIVERSOS);
    o banco tem 1 (saldo confere). O IN-360 ficou com DOBRA.
  - "PIX RECEBIDO REM: RODIZA ALIMENTOS" sem par = venda Pix repassada (média ~R$ 50), EXCETO **R$ 8.000 em 04/05 e
    R$ 5.200 em 05/06**, que caem nos buracos do Santander (01–06/05 e 02–04/06): prováveis transferências cuja saída
    está no trecho que falta. Baixar esses trechos resolve.
  - Maiores saídas sem favorecido: Pix de R$ 13.430 a uma pessoa (não aparece na planilha), boleto "COBRANCA MB
    PAGAMEN" R$ 11,6 mil (provável RFG com texto novo), 5 boletos "COBRANCA MG COMERCI" R$ 6,7 mil (BOITIQUE por boleto).
- **Decisão pendente para o 5c-2 (visão CAIXA):** as classes da planilha (INSUMO, ALUGUEL, FOLHA, RETIRADA, REFIN…) não
  são as do GCOM (INSUMOS, OCUPAÇÃO, PESSOAL, DISTRIBUICAO LUCRO, DESPESAS FINANCEIRAS…). Proposta: mapear para as do
  GCOM, e o que não é DRE (transferência entre contas, aporte, retirada, REFIN) aparece à parte.

## 🔎 JM — padrão confirmado com o extrato (30/09)
- Cada compra = **nota principal + nota complementar com o MESMO número + "1"** (ou "/1", ou "D" na frente),
  e a JM cobra **um boleto só com a soma das duas**.
- 37 débitos da JM no Bradesco (dez/25–set/26): **15 batem exato** com a soma das notas do mesmo número;
  **8 batem com acréscimo por pagamento em atraso** (+R$ 15,59 a +R$ 57,11; total **R$ 284,77** de multa/juros;
  histórico às vezes diz "VENCIDO"); 7 são de dez/25–04/02/26 (antes do GCOM, sem nota); **7 sem par**, dos quais
  3 já explicados por erro de digitação no GCOM (12/08: notas 2275530 + 2275301; 09/07: nota "20260824041737";
  25/06: nota 2213781 de R$ 1.636,57 lançada como complemento de outra compra).
- **Correção da proposta anterior:** agrupar por VENCIMENTO falha (o complemento às vezes está no GCOM com outro
  vencimento, ex.: 03/07 pagou 222451 + 2224511 que consta com venc. 19/06). A regra certa é agrupar pelo
  NÚMERO da nota. O tipo `nota_mais_ajuste` já existente serve ("ajuste" = nota complementar); proposta:
  diferença aceita R$ 0,00 + acréscimo de atraso separado como juros/multa.
- ✅ **Aplicado em 30/09 com OK do usuário** (correção do padrão vigente desde 01/01/2026, registrada no
  `audit_log`): `tolerancia_valor` 0,00 · `ajuste_max_pct` 0 · `parametros` = agrupar por número do documento
  (complemento: sufixo "1"/"/1" ou prefixo "D"), atraso → separar multa/juros (até 5%, só se pago após o
  vencimento), sem par → pendente para humano. **Quem usa:** o motor de match (passo 5c, ainda não construído).

## ✅ Passo 5/5: BANCO E CAIXA NO AR (30/09 ~09h30) → http://127.0.0.1:8100/painel/banco
- Feito sem reiniciar o PC: o trabalho pesado roda DENTRO do contêiner (a VM tem memória; o Windows não).
  `%UserProfile%\.wslconfig` criado (memory=6GB, autoMemoryReclaim=gradual) com OK do usuário: vale no próximo
  reinício do WSL/PC.
- Migração `f5a6b7c8d9e0`: `contas_bancarias`, `extrato_importacoes`, `extrato_lancamentos` (RLS) + permissão
  **`banco:ler`** (admin, franqueado, eng. dados; gestor de loja NÃO vê o banco).
- `modules/banco/extratos.py`: lê Bradesco (.xlsx, .xls antigo via `xlrd`, .csv com quebras CR CR LF) e Santander
  (.xlsx, vem do mais novo pro mais antigo → invertido), para no "Total", ignora "Últimos Lançamentos", confere
  saldo linha a linha e RECUSA arquivo que não fecha. Planilha "tratado" é ignorada (sem saldo).
- **Anti-duplicidade = data + valor + saldo depois do lançamento** (o Bradesco muda o texto entre exportações:
  "TRANSFERENCIA PIX REM" → "PIX RECEBIDO REM"); sem saldo, data + histórico + valor + ocorrência.
- Carga: 19 arquivos, **Bradesco out/25 → 22/09/26 e Santander fev/26 → 10/09/26**; 2ª rodada = 19 "já importado".
  Arquivos copiados (não movidos) para `C:\giraffas-erp-data\entrada\extratos\`.
- **Buracos provados pelo saldo** (mostrados em destaque na tela): Bradesco 31/12/25→02/01/26 (+R$ 721,50) e
  **31/08→01/09/26 (−R$ 21.097,24)**; Santander 28/02→01/03 (+260,10), 01/04 (+951,22), 01–06/05 (−3.647,32),
  02–04/06 (−1.463,37) = cortes do limite de 440 linhas. Baixar de novo esses trechos em partes menores.
- **Nov/25 quase vazio** no extrato (1 lançamento de R$ 9,56 no fechamento; o usuário disse que houve movimento):
  conferir se falta o extrato de nov/25 ou se o movimento foi em outra conta.
- Saldo do Bradesco NEGATIVO no fim de mai/26 (−R$ 17,7 mil) e jun/26 (−R$ 39,4 mil) e set/26 (−R$ 12,6 mil).
- Tela `/painel/banco`: período (de/até), conta, KPIs, tabela mensal (saldo inicial, entradas, saídas, resultado,
  saldo final, selos "antes do GCOM" / "⚠ extrato incompleto"), clique no mês → entradas e saídas por tipo +
  lançamentos com busca. Navegação entre as telas Fornecedores ⇄ Banco e caixa.
- `automations/tools/ponte_extratos.py` na tarefa **IN360_Pontes_Diarias** (agora 3 cópias: Raio-X, Gestão,
  extratos): copia extratos novos das pastas onde o usuário já os salva e importa. Testada: resultado 0.
- Testes: 38/38.
- **Próximo (5c) — 5c-1 FEITO em 30/09, ver seção acima:** ligar as SAÍDAS aos fornecedores (regras de texto semeadas das planilhas "tratado" do usuário,
  que já classificam cada débito) → visão CAIXA no painel de fornecedores + conciliação de 3 vias.

## (histórico) Passo 5: levantamento e pausa por falta de memória (29/09 ~00h)
- **PC sem RAM:** 0,2–0,3 GB livres de 15,7 GB. Os contêineres somam ~1,3 GB, mas a VM do Docker/WSL reserva
  ~7,8 GB (cache dos vários builds do dia) e não devolve ao Windows sem reiniciar a VM. `drop_caches` liberou
  5,4 GB DENTRO da VM, sem efeito no Windows. Um Python caiu com "OpenBLAS: memory allocation failed" e a
  criação de tarefa agendada falhou com "Memória insuficiente". **Pedido ao usuário: reiniciar o PC.**
  Sugestão para evitar recorrência: `%UserProfile%\.wslconfig` com `memory=6GB` e `autoMemoryReclaim=gradual`
  (aguarda OK do usuário: afeta todos os contêineres do PC).
- **Extratos (só leitura, `Giraffas-Datalake/01_entrada/processados/`):**
  - Bradesco **nov/25 → jun/26**: fechamentos mensais `.xlsx`, **saldo fecha linha a linha (0 quebras)**.
    Dez/25: ent. R$ 296 mil, saí. R$ 249 mil. O `Bradesco_25092026_154326.CSV` cobre out–dez/25 (sobreposto).
  - Bradesco **jul → set/26**: só em `Bradesco_25092026_005938.XLS` (Excel 97 binário: precisa de `xlrd`) e nas
    planilhas "tratado" do usuário (jul–ago, com CREDITO/DEBITO).
  - Santander: fev → jun/26 + ago/26 + jul (só 01–20) + 1 lanç. de set. **Suspeito:** o saldo "quebra" em quase
    toda linha (ordem invertida?) e abr, mai, jun e ago têm **exatamente 440 lançamentos** (limite de exportação
    cortando o mês?). Conferir antes de importar. A Gestão registra que essa conta recebe o Pix via Getnet.
- Desenho da importação: tabelas do modelo 002 (`contas_bancarias`, `extrato_importacoes`,
  `extrato_lancamentos`), leitura com a mesma lógica dos parsers da Gestão (para na linha "Total", ignora
  "Últimos Lançamentos"), MAS com créditos E débitos, checagem de saldo corrido (recusa arquivo que não fecha)
  e deduplicação por conta+data+histórico+valor+ocorrência.

## ✅ Painel, passo 4/5: PAINEL DE FORNECEDORES NO AR (29/09 ~23h50) → http://127.0.0.1:8100/painel
- 1ª tela própria do IN-360 (`modules/paineis/static/painel_fornecedores.html`, sem dependências externas,
  login do IN-360). Meses (chips + atalhos), % sobre total / categoria / receita, filtro por categoria,
  busca, categorias recolhíveis, KPIs (receita, despesas, despesas÷receita, nº fornecedores), CSV.
  Visão CAIXA desabilitada até o passo 5 (data de pagamento vazia no Raio-X).
- Dados: `GET /tenants/{id}/paineis/fornecedores?meses=...` (`dashboards:ler`, gestor vê só a própria loja).
  Categoria = Tipo de Desembolso do GCOM; documento rateado entra por linha (`sub_itens`). Nome do GCOM →
  CRM pelos apelidos. "O PRÓPRIO ESCRITÓRIO" aberto por sub-tipo. Meses oferecidos = meses com despesas.
- Receita: migração `e3f4a5b6c7d8` (`vendas_realizado_dia`, RLS) + `automations/tools/ponte_gestao.py` →
  `modules/vendas/ponte.py`. 237 dias (03-02 a 27-09-2026), idempotente. A mesma migração trocou o JSON null
  do `sub_itens` por NULL de SQL (671 linhas; a ponte agora grava NULL).
- Conferência ago/26: receita R$ 233.172,31; despesas R$ 182.856,26 (78,4%). **RFG ("MB") R$ 67.516,10 =
  36,9% do total, 77,8% dos INSUMOS, 29,0% da receita.**
- Tarefa diária agora é **IN360_Pontes_Diarias** (07:30; Raio-X + Gestão), criada por
  `infra/agendamentos/registrar_pontes_diarias.ps1` via `schtasks` + XML. A `IN360_Ponte_RaioX` foi removida.
  ⚠️ Os cmdlets `*-ScheduledTask` falharam por **falta de memória** (RAM livre 0,2 GB de 15,7 GB): a 1ª versão
  do script removeu a tarefa antiga mesmo com o erro. Corrigido (para no 1º erro). Testada: resultado 0.
- **02/02 resolvido (29/09):** os R$ 11.778,73 digitados no caixa de 02/02 são **2 dias faturados em outro
  sistema antes do GCOM** (informado pelo usuário). Lançados em `vendas_realizado_dia` com `fonte =
  'ajuste_manual'` (data 02/02/2026, com a explicação em `origem` e registro no `audit_log`). A ponte da Gestão
  só mexe na `fonte = 'gestao_realizado_dia'` e não apaga o ajuste. **Receita fev/26 = R$ 168.914,12**
  (157.135,39 da Gestão + 11.778,73). Se um dia a Gestão passar a trazer 02/02, remover o ajuste.
- Testes: 31/31.

## 📅 Recorte de datas (definido pelo usuário, 29/09)
- **Faturamento começa em 02/02/2026.** Painéis de receita/despesa: **foco de fev/2026 em diante**.
- **Caixa (entradas e saídas da conta bancária): desde nov/2025**, mas o foco também é fev/26 em diante.
- Fontes para o passo 5 (só leitura, pasta `Giraffas-Datalake/01_entrada/processados/`):
  `15/16_Bradesco_Bruto_2025-11 … 2026-06-Fechamento.xlsx`, `17_Santander_Bruto_2026-02 … 06-Fechamento.xlsx`,
  `Bradesco_25092026_*.XLS/CSV` e `santander_extrato-pj-25_09_2026_*.xlsx` (período recente).
  O `database_banco.csv` da Gestão tem **só créditos** (a Gestão usa o extrato só para conferir recebimentos):
  as SAÍDAS precisam vir dos extratos originais.
- Respondido pelo usuário (29/09): de nov/25 a jan/26 a conta **já tinha recebimentos e pagamentos**
  (dez/25: R$ 561 mil em créditos; jan/26: R$ 228 mil), mas o GCOM só começou a faturar em 02/02/2026. Então
  **não há como analisar faturamento/receita/despesas de out/25 a jan/26**. Nesse período o IN-360 mostra
  **só o movimento bancário** (entradas e saídas), sem cruzar com DRE. Análises cruzadas: fev/26 em diante.

## ✅ Painel, passo 3/5: as 2 receitas são IGUAIS (29/09 22h40)
- Lido no GCOM pelo próprio IN-360 (pedido do usuário): `automations/gcom/dre_interativo.py` (login/navegação
  copiados do Raio-X, senha do keyring nunca exibida, navegador visível por causa do WAF, SÓ LEITURA: recusa
  qualquer clique de escrita). DRE Interativo → passo **1 Vendas**: Faturamento Líquido = Faturamento Total =
  **R$ 233.172,31** em ago/26, com cortesias, estornos, gorjeta e taxa de entrega zerados.
- **Os 31 dias batem centavo a centavo com `database_realizado_dia.csv` da Gestão.** Não há escolha a fazer:
  o painel usa a série diária da Gestão (já automatizada, fev–set).
- Arquivos: `C:\giraffas-erp-data\entrada\DRE_GCOM_2026-08_Vendas.xlsx` + prints/texto em `entrada\_diagnostico_dre\`.
  A tela não tem botão Excel: a planilha é montada a partir da tabela lida.
- O DRE Interativo tem os passos 1 Vendas · 2 Entrada de Mercadorias · 3 Despesas · 4 Gestão de Estoque ·
  5 Resultados (este último pode alimentar o DRE completo no futuro).

## (histórico) passo 3: levantamento inicial
- **Vendas da Gestão:** `Giraffas-Datalake/02_database/database_realizado_dia.csv` (coluna `faturamento`,
  origem "analitico", vem do `database_vendas.csv` do GCOM). **Ago/26 = R$ 233.172,31 (31 dias)**, igual ao
  `faturamento_st_fev_ago.csv` entregue ao contador. Série fev–set disponível.
- **Receita do DRE do GCOM:** não é extraída por ninguém hoje (o Raio-X só traz despesas). **Aguardando o
  usuário exportar o DRE Interativo de ago/26 com as linhas de receita** em `C:\giraffas-erp-data\entrada\`.
- Referência: despesas ago/26 (competência, Raio-X) = R$ 182.856,26.
- Achado útil para o passo 5: o Datalake já tem `database_banco.csv` (extrato consolidado desde out/2025,
  Bradesco, com `fonte_provavel`) e `database_caixa_dia.csv` (sistema × digitado × depositado, sangria).

## ✅ Painel, passo 2/5: cópia diária Raio-X → IN-360 (29/09 18h45, em produção)
- `automations/tools/ponte_raiox.py` (Windows) lê o Raio-X por `docker exec in-360-giraffas-db-1 psql`
  numa sessão `default_transaction_read_only` (nenhuma escrita, nenhuma senha do Raio-X) e entrega o JSON a
  `modules/raiox_dre/ponte.py` (na API): espelho por mês (insere/atualiza/remove o que sumiu; meses fora da
  exportação ficam intocados), chave loja+mês+id_original.
- 1ª carga: **685 despesas, fev–ago/2026, totais por mês idênticos ao Raio-X** (conferido centavo a centavo).
  2ª rodada: 685 iguais.
- Liga nome do GCOM → CRM pela razão social (guarda em `fornecedores.apelidos`): **7 ligados** (RFG, Multiplan
  Arrecadadora, JM, Kelminas, Ribeiro, Carrefour, Termotec). **16 sem par** (SPAL, Planeta/Coca-Cola, MG
  Comercial, OESA ×2, Sendas/Assaí, Damax, Oximil, SMBH, Multiplan Estacionamento, Suiminas, Ki Pão, Drogaria
  Araujo, Leitura, Getnet e "O PRÓPRIO ESCRITÓRIO"). O painel mostra esses pelo nome do GCOM.
- Tarefa **IN360_Ponte_RaioX** (diária 07:30, roda ao ligar se perdeu), registrada por
  `infra/agendamentos/registrar_ponte_raiox.ps1`. Testada pelo agendador (resultado 0). Log:
  `C:\giraffas-erp-data\logs\ponte_raiox.log`. Desligar quando o Raio-X for portado.
- Testes: 26/26 (4 novos da ponte).

## ✅ Painel, passo 1/5: relatório Excel do CRM (29/09 18h32, em produção)
- `modules/pagamentos/relatorio_crm.py`: gera `CRM_Fornecedores_Rodiza.xlsx` do banco (formato de 28/09 +
  colunas "Também aparece como", "Padrão de pagamento" e "Situação"; datas DD-MM-AAAA).
- Download: `GET /tenants/{id}/fornecedores/relatorio.xlsx` (quem lê a conciliação). Arquivo gerado em
  `C:\giraffas-erp-data\dashboards\` com `python -m modules.pagamentos.relatorio_crm --tenant rodiza`.
- `openpyxl==3.1.5` no requirements. Testes: 22/22.
- Ordem aprovada pelo usuário (29/09): 1 Excel ✅ → 2 cópia diária Raio-X + ligação nomes GCOM↔CRM → 3 comparar as 2
  receitas de 1 mês → 4 painel (competência; caixa depois) → 5 extrato Bradesco (entradas/saídas, conciliação, caixa).
- JM: padrão continua `nota_mais_ajuste` sem % (nada alterado); troca para `agrupado_vencimento` tol. 0 aguarda OK.

## ✅ Fase 1B, passo 1: CRM de fornecedores (EM PRODUÇÃO desde 29/09 16h50, dados carregados 17h10)
- Publicado com autorização do usuário: backup 16h46 → build → migração `d7e8f9a0b1c2` aplicada no boot →
  API healthy. Carga simulada, mostrada ao usuário e gravada: 14 fornecedores, 14 padrões vigentes,
  9 recorrentes (8 ativas). 2ª rodada criou 0 (idempotente).
- ⚠️ O backup automático de 29/09 02h30 saiu com **0 bytes** (as senhas estavam dessincronizadas nessa
  hora). Os backups manuais de 11h17 e 16h46 estão OK. Conferir amanhã se o das 02h30 veio com tamanho normal.
- Módulo novo `modules/pagamentos/` (Conciliação de **Pagamentos**; `modules/conciliacao/` fica reservado
  à conciliação de **vendas** do Datalake, que é outra coisa).
- Migração `d7e8f9a0b1c2`: `fornecedores` (campos do CRM, CNPJ só dígitos), `padroes_pagamento` (um
  vigente por fornecedor, histórico preservado), `despesas_recorrentes` (as "despesas fixas": dia e faixa
  de valor). RLS igual ao cofre.
- API: 8 rotas em `/tenants/{id}/fornecedores...` e `/despesas-recorrentes`. Ler = `conciliacao:ler`
  (inclusive gestor de QUALQUER loja do cliente); alterar = `parametros:gerir`.
- Carga: `python -m modules.pagamentos.carga --tenant rodiza --arquivo database/seeds/fornecedores_rodiza.json`
  (`--simular` primeiro). Idempotente: 14 fornecedores, 14 padrões (desde 01-01-2026), 9 recorrentes (a
  Taxa de Transferência da Multiplan entra encerrada em 20-06-2026).
- Testes: **21/21** (14 Etapa 1 + 7 novos) na stack descartável `bash infra/testes/rodar_testes.sh`
  (projeto `erp-teste`, imagem `:teste`, portas 55499/8199, segredos temporários, apaga tudo no fim).
- `.dockerignore` agora exclui `.venv` (98 MB a menos por build).
- **Para publicar (precisa de OK do usuário):** `docker compose build api` → `docker compose up -d api`
  (roda a migração no boot) → carga com `--simular` → carga real.
- Pendências de negócio: % de ajuste aceito da JM (`ajuste_max_pct`, hoje vazio); CNPJs faltando (13 de 14);
  janelas/tolerâncias são os padrões do desenho (3 dias antes/5 depois, R$ 0,00).
- Próximo passo da 1B: relatório `CRM_Fornecedores_Rodiza.xlsx` gerado do banco; depois o extrato bancário.

## ✅ Cloudflare (29/09 17h01): dashboards FECHADOS atrás de login
- Conta Cloudflare: rodizaalimentos@gmail.com (a mesma da publicação da Gestão). Zero Trust Free, team
  `empty-grass-92da`, login por código no e-mail (One-time PIN).
- 2 aplicações Access: "giraffas-dash - Cloudflare Pages" (`*.giraffas-dash.pages.dev`, previews; o `*` é
  travado pelo Pages) + a nova para `giraffas-dash.pages.dev` (principal), política Allow/Emails (3 e-mails).
- Validado de fora: principal, previews e caminhos internos → HTTP 302 para o login do Access.
- Testado pelo usuário no celular em 29/09: OK.
- A publicação diária da Gestão (wrangler) não é afetada pelo Access.

## 🔧 Incidente corrigido (29/09, ~01h30)
- Das 00h58 às 01h28 de 29/09, o `autoheal` reiniciou o Postgres **a cada 2 min**. Causa: o contêiner foi
  recriado por volta de 00h40 com `POSTGRES_DB` vazio, e o `.env` foi alterado às 00h57. Com isso o
  healthcheck virou `pg_isready -U erp -d ` (sem argumento) e falhava sempre. Não houve perda de dados
  (volume nomeado, banco `erp` intacto, migração `c0f3e1a2b4d5`, 0 usuários).
- Correção: `docker compose up -d --no-deps postgres` (recriado, healthy na hora). Blindagem no
  `docker-compose.yml`: `POSTGRES_USER`/`POSTGRES_DB` do serviço postgres e do healthcheck usam
  `${VAR:?...}`, então o compose **se recusa a subir** se faltarem no `.env`.
- Lição: depois de mexer no `.env`, rodar `docker compose config --quiet` e depois `docker compose up -d`.
- **2º achado (mesma madrugada):** às 00h24 de 29/09, `postgres_password`, `app_db_password`,
  `jwt_secret` e `erp_master_key` foram regravados à mão (valores curtos + quebra de linha). O banco
  continuava com as senhas originais, então `erp_app` não autenticava (o `criar-admin` falhou). A
  `erp_master_key` também foi movida para fora da pasta e depois devolvida pelo usuário (válida, 32
  bytes; o `.strip()` ignora a quebra de linha). O cofre estava vazio, então nada se perdeu.
- **Correção (29/09, 11h15):** o usuário rodou `py infra\secrets\rotacionar_segredos_tecnicos.py`
  (script novo: guarda `*.antigo-20260929`, gera valores fortes, `ALTER ROLE` lendo de `/run/secrets`,
  reinicia api+backup). Conferido: conexão `erp_app` OK, migrações OK, 0 falhas de autenticação, backup
  manual de 29/09 OK. Os `*.antigo-20260929` ficam na pasta protegida e podem ser apagados depois.
- O modo automático do Claude Code bloqueia gravação na pasta de segredos: operações ali são feitas
  pelo usuário (script pronto + comando).

## 🟢 Etapa 1 no ar (28/09, 18h15)
- `DATA_DIR = C:\giraffas-erp-data` (fora do OneDrive). `secrets/` com acesso restrito ao usuário
  (icacls: só rodsa, SYSTEM e Administrators).
- Serviços: `postgres` (127.0.0.1:55433), `api` (http://127.0.0.1:8100, docs em /docs), `backup`
  (diário 02:30; 1º backup forçado OK em `backups/`), `autoheal`. n8n/console/worker ainda não sobem.
- Banco: 7 migrações aplicadas (`c0f3e1a2b4d5`), papel `erp_app` sem superusuário/BYPASSRLS, 13
  integrações no catálogo, 0 usuários.
- Console Streamlit: porta trocada para **8502** no `.env` (8501 ocupada por outro processo local).
- Operar: `docker compose ps` · `docker compose logs -f api` · backup manual (Git Bash):
  `MSYS_NO_PATHCONV=1 docker compose exec backup /backup.sh`.
- O Raio-X segue rodando em paralelo (8000/55432), sem alteração.
- **Backup na nuvem (pedido do usuário, 28/09):** cópia diária para o Google Drive
  `G:\Meu Drive\1-RSIN(holding)\3-Rodiza - Giraffas\backup in-360` (conta
  **rod.santana.particular**, confirmada pelo usuário). Script `infra/backup/copiar_backup_drive.ps1`
  (robocopy, **só acrescenta**, nunca apaga, ignora os links `*-latest`) + tarefa agendada
  **`IN360_Backup_Drive`** (diária 03:00, roda ao ligar se perdeu o horário). Testada manualmente e pelo
  agendador (resultado 0). Log: `C:\giraffas-erp-data\logs\backup_drive.log`.
  ⚠️ A `erp_master_key` NÃO vai para o Drive, e não deve ficar junto do backup.
- **Passo 4 pronto:** `automations/tools/configurar_etapa1_rodiza.py` (cliente Rodiza + loja GSHBH + 7
  conexões + senhas do keyring → cofre). Testado em stack descartável (modo `--sem-senhas`, 2 rodadas,
  sem duplicar). Pergunta CPF (Alelo) e CNPJ (Ticket) na hora.
- **Aguardando o usuário:** (A) cópia offline da chave-mestra; (B) `criar-admin`; depois rodar o passo 4.
- PC com pouca memória: Docker e Git Bash falharam 1x cada por falta de recurso durante os testes.

## Como vamos trabalhar (decisão do usuário, 28/09)
- **Por etapas, módulo a módulo.** Hoje em produção: Gestão (Performance + Quebra, automáticos) e
  Raio-X (em teste e já em uso). A Conciliação é manual, porque ainda não há APIs de adquirentes,
  fornecedores e bandeiras (sem solução por enquanto).
- **Primeiro requisito:** perfil de segurança e banco de senhas desde o início → Etapa 1.
- Processos serão descobertos juntos. Alguns já existem e serão reaproveitados, outros serão construídos.

## ✅ Etapa 1 — Perfis de acesso + cofre de senhas (construída 28/09)
O que existe:
- `core/`: configuração (segredos só por arquivo), banco com isolamento por cliente (RLS), login
  JWT/bcrypt com **bloqueio após 10 falhas em 15 min**, perfis (RBAC) e **cofre** (AES-256-GCM,
  chave-mestra fora do banco → chave por cliente → cada senha).
- 7 perfis: `plataforma_admin`, `ti_ops`, `eng_dados`, `franqueado_admin`, `gestor_loja`, `auditor`,
  `colaborador`, com 20 permissões (`modulo:acao`). Anti-escalada: ninguém concede o que não tem.
- Cofre: gravar/trocar (histórico de versões)/revogar. **Nenhuma rota devolve senha**, exceto
  `revelar`, que exige permissão própria (hoje só `plataforma_admin`) e motivo, e fica registrada.
  Recusa senha colocada por engano em "parâmetros".
- Catálogo com 13 integrações (GCOM, e-mail IMAP, Cielo portal/API, Getnet, Alelo, Pluxee, Ticket, VR,
  iFood, extratos Bradesco/Santander, certificado A1).
- Trilha: `audit_log` (login ok/falha, perfis, senhas: sem o valor) + `credencial_acessos`.
- Migrações: as 6 do Raio-X (copiadas, sem mudança) + `c0f3e1a2b4d5` (Etapa 1).
- Ferramentas: `infra/secrets/gerar_segredos.py` (nunca sobrescreve), `python -m core.cli criar-admin`,
  `automations/tools/importar_keyring.py` (leva senha do keyring do Windows → cofre, sem exibir).

Testes (stack descartável, já removida):
- **14/14 testes passando** (`tests/test_etapa1_seguranca_cofre.py`): login/bloqueio, senha não volta
  na API e está cifrada no banco, rotação, revelar com motivo, isolamento entre clientes (API e banco),
  Eng. Dados grava mas não vê senha, TI só metadados, gestor de loja sem acesso a integrações,
  anti-escalada, e senha copiada para outra linha não decifra.
- API subiu como serviço (healthy), acessível do Windows em `127.0.0.1`, `/docs` OK.
- **Backup real do Raio-X (22/09) restaurado + migrado:** 698 despesas preservadas, loja Shopping BH
  → cliente `rodiza`, perfil antigo `gestor` → `franqueado_admin` + `ti_ops` + `eng_dados`.
- Bug achado e corrigido: o comando do `api` no compose perdia `-b 0.0.0.0 -w 2` (quebra de linha no YAML).

Ainda não feito na Etapa 1: tela própria (por ora usa `/docs`), subir no PC para uso real, cadastrar
as conexões e importar as senhas do keyring.

## Conciliação de Pagamentos 3 vias (desenhada, não construída)
- Nasce no IN-360 (seção 6 do plano; modelo `database/sql/002_conciliacao_pagamentos.sql`, testado).
- 3 vias: **previsão lançada no GCOM** (substitui a planilha de pedidos) ↔ despesa real/paga (DRE) ↔
  **saída de dinheiro**.
- **Respostas do usuário (28/09):**
  - Previsões no GCOM começam em **setembro/2026**. O DRE Interativo mostra só pago porque até agora só
    havia lançamentos passados.
  - A planilha `15_Bradesco_tratado` era uma redundância sem sentido e **será eliminada**. O
    descritivo vai no campo **Observações do GCOM** (inclusive se foi lançado pelo escritório ou não).
  - **A saída de dinheiro pode ser do BANCO ou do CAIXA (dinheiro em espécie)**. O modelo precisa de uma
    fonte "caixa" além do extrato (a ajustar quando o módulo for construído).
  - Se a previsão efetivada vira o mesmo doc ou um novo no GCOM: o usuário não sabe e autorizou um
    lançamento de teste → **feito e limpo em 28/09: é o MESMO documento** (ver seção do teste assistido).
- Padrões por fornecedor: RFG 1:1, Kelminas consolidado mensal, Ribeiro por vencimento, JM nota + ajuste.
- **NA FILA — CRM de fornecedores (pedido 28/09):** 14 fornecedores + 9 despesas fixas guardados em
  `database/seeds/fornecedores_rodiza.json`. Decisão do usuário: vira **dado do IN-360** (carga de
  `fornecedores`/`padroes_pagamento`), e a planilha `CRM_Fornecedores_Rodiza.xlsx` passa a ser um relatório
  gerado a partir do banco. Entra junto com a construção do módulo de conciliação (Fase 1B), logo após
  a Etapa 1 estar completa (admin + conexões + senhas).

## ✅ Teste assistido no GCOM — CONCLUÍDO e LIMPO (28/09)
Autorizado pelo usuário. Previsão de teste criada, efetivada, voltada a previsão e **excluída**. Conferido
no relatório que não sobrou nada (Chrome do teste fechado, perfil temporário apagado).

**Como o GCOM trata previsão (respostas definitivas):**
- **Onde lançar:** Contas A Pagar → Movimento → Manutenção de Documentos a Pagar → ADIC. DOCTO → chave
  **"Previsão"**. Campos: unidade, fornecedor, tipo doc (existe **"PEDIDO"** = PED), cobrança, entrada,
  vencimento, nº, valor, observação, periodicidade (semanal/mensal/anual) e rateio Tipo/Subtipo de
  Desembolso + **Mês Competência** (botão "ADICIONAR RATEIO" obrigatório antes de confirmar).
- **Efetivar = MESMO documento.** Desligar a chave muda o status de "Previsto" para "Real" na mesma linha
  (mesmo Nº). O inverso também funciona. Ao editar pode vir a pergunta SIM/NÃO sobre o valor das parcelas.
- **Excluir:** só **previsão** pode ser excluída (menu ⋮ → "EXCLUIR PREVISÕES"). Documento **real** só
  pode ser **cancelado** (⋮ → "CANCELAR DOCUMENTOS"). Também há: Autorizar Pagamentos, Baixa Múltipla,
  Estornar em Lote.
- **Onde ler o status:** a lista da Manutenção mostra a coluna **Status (Previsto/Real)** e tem botão
  **EXCEL**. O relatório antigo "Documentos em aberto por data" **NÃO distingue** previsão de real.

**Impacto no IN-360 (já aplicado no modelo 002, retestado):** sem vínculo previsão→real (é o mesmo
registro). O ciclo de vida é o histórico de status, e previsão excluída no GCOM vira `sumiu_da_origem_em`
(pedido abandonado) em vez de sumir do IN-360.

**Achados de passagem (documentos reais em aberto, vencimento 2026):** Ribeiro DUP 161/164/167 venc.
07/09 (R$ 856,94 = exemplo real do padrão "agrupado por vencimento"), RFG DUP 798514 venc. 18/09
(R$ 13.859,08) e Carrefour NF 2664105 (R$ 46,35, doc de teste antigo do Raio-X, que pode ser
rebaixado ou cancelado). Todos vencidos: pagos no banco e não baixados no GCOM, ou ainda a pagar?

## 🔴 Achado urgente (28/09)
`https://giraffas-dash.pages.dev` está **PÚBLICO** (menu + 6 dashboards, HTTP 200 sem login).
Correção sem mexer no Datalake: Cloudflare Zero Trust → Access → Self-hosted em
`giraffas-dash.pages.dev` e `*.giraffas-dash.pages.dev`. Pendente com o usuário.

## Próximos passos sugeridos
1. ~~Fechar a exposição do Cloudflare Pages~~ ✅ feito 29/09 17h01, testado no celular pelo usuário.
2. Trocar a senha repetida nos 5 serviços (ver achado acima).
3. **Fase 1B:** módulo de Conciliação 3 vias + carga do CRM de fornecedores (`fornecedores_rodiza.json`).
4. Tela simples do cofre/perfis (hoje é pelo `/docs`).
5. `git init` + repositório privado.
6. Estender a extração do GCOM para a lista da Manutenção (coluna Status Previsto/Real, export EXCEL).

## Notas / decisões pendentes
- Quem além do administrador pode **revelar** senha? (hoje só `plataforma_admin`)
- Dados reais do Raio-X: migrar para o IN-360 só quando o módulo Raio-X for portado (o teste provou que funciona).
- RPA com navegador visível: executor padrão = agente no Windows. O contêiner (perfil `rpa`) é experimento.
- Postgres em volume nomeado. A durabilidade vem de backup diário + cópia fora da máquina + teste de restauração.
- Hospedagem: local agora, nuvem 24x7 depois (Fase 5B do plano).
- Pendências de escrita no GCOM: o usuário fecha no projeto do Raio-X. Este projeto não escreve no GCOM.
- Docker no PC teve 1 falha de memória do cliente durante os testes: acompanhar a RAM disponível.

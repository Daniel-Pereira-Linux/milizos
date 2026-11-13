# Notas de versão do MilizOS

O que entrou, mudou e saiu em cada versão. A mesma lista, com capturas, está no
[site](https://milizos.com.br/#novidades).

## 2.1.0 "Heloisa" (13 nov 2026)

A 2.0 deu história à máquina. A 2.1.0 dá a essa história o resto das ferramentas de um
repositório: mensagem, blame, bisect, ramos, push, clone e assinatura. Quem instalou a 2.0
recebe tudo sozinho pela atualização diária; a ISO 2.1.0 substitui a 2.0.

[Baixar a 2.1.0](https://github.com/Daniel-Pereira-Linux/milizos/releases/tag/v2.1.0)

| No git | No MilizOS 2.1.0 |
|---|---|
| mensagem de commit | **Resumo automático**: cada ponto registra o que mudou desde o anterior. |
| `git blame` | **Quando mudou?**: entre quais pontos um arquivo mudou, quantas linhas e a causa provável. |
| `git bisect` | **Procurar o que quebrou**: busca binária entre os pontos, reiniciando e perguntando "funciona?". |
| `git branch` | **Ramos da máquina**: sistemas paralelos no mesmo disco, também no menu de boot. |
| `git worktree` | **Experimentar um ponto**: terminal dentro de uma cópia descartável, sem voltar nada. |
| `git push` | **Enviar os pontos** para outro disco btrfs ou servidor por SSH, de forma incremental. |
| `git clone` | **Clonar a máquina** pela mídia, a partir de um ponto enviado. |
| `git tag -s` | **Selar um ponto**: SHA-256 de todo o conteúdo, assinado com a chave da máquina. |

### Entrou

- **Resumo automático** em cada ponto: arquivos de configuração editados, criados e
  apagados, e a contagem de arquivos pessoais criados, alterados, apagados e renomeados.
- **Quando mudou?** na aba *Qualquer coisa*: o histórico de um arquivo, ponto a ponto.
- **Procurar o que quebrou**: diga em que ponto funcionava; a Heloisa reinicia nos pontos
  do meio até achar o ponto em que o problema entrou e mostra o que mudou nele. No fim, a
  máquina volta ao sistema em que você estava.
- **Ramos da máquina** (até 6): um segundo sistema completo, criado do estado atual ou de
  um ponto. Troca pelo aplicativo ou pelo submenu *Heloisa: iniciar outro ramo* do GRUB.
- **Experimentar um ponto**: um terminal (`systemd-nspawn`) dentro de uma cópia gravável e
  descartável do sistema e dos arquivos pessoais daquele ponto.
- **Selar um ponto**: hash de todos os arquivos, assinado (ed25519). A verificação aponta
  o que difere. Ponto selado ou protegido nunca é apagado sozinho.
- **Enviar os pontos para outro disco ou servidor** (`btrfs send`/`receive`): só vai o que
  mudou desde o último envio. É isso que transforma os pontos em backup.
- **Clonar a máquina**: pela mídia de instalação, um disco novo recebe o sistema e os
  arquivos pessoais de um ponto enviado, com outro nome de máquina e novas chaves SSH.
- **Alarme de ransomware**: se cem ou mais arquivos pessoais são reescritos entre dois
  pontos e viram dados sem padrão, a Heloisa avisa na sessão, protege o último ponto bom e
  mostra por onde recuperar.
- **Pontos nas caixas da Pandora**: a caixa inteira (programas e pasta pessoal) é
  congelada e volta em segundos. Voltar cria um ponto antes, como na Heloisa.

### Mudou

- **Voltar um arquivo em uso**: voltar um arquivo ou pasta nunca precisou reiniciar; agora
  a Heloisa avisa quando um serviço está escrevendo no caminho (um banco de dados, por
  exemplo) e oferece **parar, voltar e religar**. Também avisa em caminhos de dados vivos.
- **Menu de cada ponto**: atalho *Voltar só um arquivo ou pasta deste ponto*.
- **Aviso ao entrar na sessão**: a Heloisa abre sozinha se houver alarme ou busca em
  andamento.
- **Instalador**: tentar de novo depois de uma falha não esbarra mais em disco ocupado.
- **Numeração**: três números (2.1.0). A release 2.0 foi substituída por esta.

### Saiu

- O link `miliz`, que apontava para o comando `nos` removido na 2.0.

## 2.0 "Heloisa" (11 nov 2026)

A 1.0 era um conjunto de comandos de terminal em volta do `nos`. A 2.0 troca isso por uma
ideia só: **a máquina inteira tem histórico, como um repositório git**, e tudo se faz por
dois aplicativos gráficos e pelas ferramentas originais.

A ISO da 2.0 foi substituída pela 2.1.0.

### Da 1.0 para a 2.0

| | 1.0 "Sentinel" | 2.0 "Heloisa" |
|---|---|---|
| O que entra em um ponto | Só o sistema. `/home` tinha snapshots separados; logs não voltavam. | A máquina inteira no mesmo instante: sistema, `/home` e logs. |
| Pontos automáticos | Antes de cada `dnf` (10 mantidos); `/home` de hora em hora. | Antes de cada `dnf` (12), de hora em hora, a cada primeira inicialização do dia e antes de toda volta. |
| Voltar um arquivo ou pasta | Só de `/home`, por comando. | De qualquer lugar do sistema, com lista de versões, diff e cópia ao lado. |
| Como se usa | Comandos `nos checkpoint` e `nos data`. | Aplicativo gráfico Heloisa. Nenhum comando próprio. |
| Menu de boot | Submenu de checkpoints. | Submenu Heloisa com os 15 pontos mais recentes. |
| Outras distribuições | `nos box`: 5 distribuições, sempre na rede e na pasta do host. | Aplicativo Pandora: 10 distribuições, modo isolado ou em ponte, atalhos automáticos no menu. |
| Atualização do MilizOS | Não havia. | Automática e diária, pelo repositório `dnf` do projeto, com ponto antes. |
| Memória | 4 GB no mínimo, 8 GB recomendados. | 4 GB bastam: swap comprimido em RAM (zram). |
| Desktop | Fundo animado, que chegava a quase 400% de CPU sem aceleração 3D. | Papel de parede estático. A animação 3D ficou só na tela de boot. |
| Tamanho da ISO | 2,9 GB | 3,3 GB |

### Entrou

- **Heloisa**, a máquina do tempo: linha do tempo, versões de qualquer caminho, diff e
  volta pelo aplicativo, pelo GRUB ou pela mídia de resgate. Toda volta cria um ponto
  antes, então a história só cresce.
- **Pandora**, as caixas Linux descartáveis (Debian, Kali, AlmaLinux, Ubuntu, Fedora, Arch,
  Rocky, openSUSE, Alpine e Parrot), com rede isolada ou em ponte e atalhos automáticos.
- **Atualização automática** diária dos pacotes do MilizOS (`milizos-update.timer`).
- **Trava de espaço**: com menos de 15% do disco livre, os pontos automáticos mais antigos
  saem sozinhos.
- **Pontos legíveis em `/.heloisa`**, somente leitura, com `ls`, `diff` e `cp`.
- **Documentação nova**: [arquitetura](docs/ARQUITETURA.md) e
  [guia do administrador](docs/ADMINISTRADOR.md), com capturas e diagramas.

### Mudou

- Voltar o sistema agora pode levar junto os arquivos pessoais e os logs, ou só parte.
- Retenção por tipo de ponto, em vez de um limite único.
- O submenu do GRUB passa a se chamar Heloisa e lista os 15 pontos mais recentes.
- Ajuste de memória do kernel para swap comprimido (`vm.swappiness=180`, `vm.page-cluster=0`).
- Download em um comando, que junta as partes e confere o SHA-256.
- A montagem da ISO saiu deste repositório; aqui ficam os pacotes, a identidade visual e a
  documentação.

### Saiu

- O comando `nos` e todos os subcomandos.
- Modo incidente (`nos incident`), captura em anel (`nos capture`) e triagem (`nos triage`).
- Treino de detecção (`nos drill`).
- Atestação de integridade (`nos attest`).
- Forja de ISOs (`nos forge`). A instalação desassistida por `autoinstall.json` continua.
- Catálogo `nos tools`: as ferramentas seguem no menu do GNOME, por categoria.
- Fundo animado do desktop.

### Vindo da 1.0

A 1.0 não tem o repositório de atualização, então ela não vira 2.0 sozinha: a troca é por
instalação nova, a partir da ISO. Da 2.0 em diante as correções chegam sozinhas.

### Testes

Testada em máquina virtual (QEMU/KVM, UEFI, 4 GB de RAM). O que passou, o que ainda não foi
testado e os limites conhecidos estão em
[docs/PROBLEMAS-CONHECIDOS.md](docs/PROBLEMAS-CONHECIDOS.md).

## 1.0 "Sentinel" (10 nov 2026)

Primeira versão pública.

- Base Fedora 44, GNOME, SELinux em *Enforcing*; ISO híbrida (BIOS e UEFI, Secure Boot).
- Instalador próprio, gráfico e desassistido; btrfs, xfs ou ext4; LUKS2 opcional.
- Perfis SOC, Engenharia de Redes e Sensor (IDS sem interface gráfica).
- Comando `nos`: checkpoints do sistema com rollback (inclusive pelo menu de boot), linha
  do tempo de `/home`, modo incidente, treino de detecção, atestação, forja de ISOs e
  caixas de outras distribuições.
- 362 ferramentas catalogadas em 11 categorias.

[Baixar a 1.0](https://github.com/Daniel-Pereira-Linux/milizos/releases/tag/v1.0)

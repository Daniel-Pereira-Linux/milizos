# Notas de versão do MilizOS

O que entrou, mudou e saiu em cada versão. A mesma lista, com capturas, está no
[site](https://daniel-pereira-linux.github.io/milizos/#novidades).

## 2.0 "Heloisa" (11 nov 2026)

A 1.0 era um conjunto de comandos de terminal em volta do `nos`. A 2.0 troca isso por uma
ideia só: **a máquina inteira tem histórico, como um repositório git**, e tudo se faz por
dois aplicativos gráficos e pelas ferramentas originais.

[Baixar a 2.0](https://github.com/Daniel-Pereira-Linux/milizos/releases/tag/v2.0)

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

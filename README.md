<p align="center"><img src="docs/assets/logo.svg" width="150" alt="Logo do MilizOS"></p>
<h1 align="center">MilizOS</h1>
<p align="center"><b>A distribuição Linux para quem defende: SOC, Blue Team e Engenharia de Redes.</b></p>
<p align="center">
<a href="https://github.com/Daniel-Pereira-Linux/milizos/releases/latest">Baixar a ISO</a> ·
<a href="https://daniel-pereira-linux.github.io/milizos/">Site</a> ·
<a href="docs/MANUAL.md">Manual</a> ·
<a href="docs/BUILD.md">Como construir</a> ·
<a href="CONTRIBUTING.md">Como colaborar</a>
</p>

---

O Kali é feito para quem ataca. O **MilizOS** é feito para quem defende: uma distribuição
baseada em Fedora, com instalador próprio, pensada para o analista de SOC, o time de
resposta a incidentes e o engenheiro de redes.

Além de reunir as ferramentas, ele traz recursos que são do próprio sistema: voltar no
tempo sem abrir mão do acesso de escrita, isolar a máquina e preservar evidências com um
comando, e medir o que o seu sensor de fato detecta.

| | |
|---|---|
| Base | Fedora 44 (x86-64), GNOME, SELinux em *Enforcing* |
| ISO | 2,8 GB, híbrida: BIOS e UEFI, com Secure Boot |
| Pacotes | 2.312 na imagem, 362 ferramentas catalogadas em 11 categorias |
| Instalador | próprio, gráfico e desassistido; btrfs, xfs ou ext4; LUKS2 opcional |
| Perfis | SOC, Engenharia de Redes, Sensor (IDS sem interface gráfica) |

## O que só o MilizOS faz

Tudo passa pelo comando `nos`.

### Rollback do sistema, com acesso total

Um checkpoint é criado antes de cada `dnf`. Se algo quebrar, volte pelo terminal ou pelo
menu de boot. Diferente de uma distribuição imutável, o sistema continua gravável.

```console
$ sudo nos checkpoint list
▍Checkpoints do sistema   (⏻ = disponível no menu de boot)
  ⏻ #1   2026-11-10 14:02  instalação   instalação limpa
  ⏻ #2   2026-11-10 15:40  automático   antes de: dnf install zeek
$ sudo nos checkpoint rollback 1
```

Se até o `/boot` for destruído, `nos checkpoint rescue`, rodando pela ISO, restaura o
sistema e reinstala o boot.

### Linha do tempo dos dados

Snapshots somente-leitura de `/home` de hora em hora. Um arquivo apagado, ou criptografado
por ransomware, volta com um comando:

```console
$ sudo nos data restore ~/relatorios --at ontem --in-place
```

### Modo incidente

```console
$ sudo nos incident start
▍MODO INCIDENTE  INC-20261110-153012
  15:30:12  captura de tráfego iniciada (anel 20 × 50 MB, todas as interfaces)
  15:30:13  coletado 02-processos  sha256=…
  15:30:19  HOST ISOLADO da rede
  15:30:21  checkpoint #3 do sistema criado (estado em disco preservado)
  15:30:40  manifesto de integridade gravado
```

Captura, coleta na ordem de volatilidade, contenção por nftables, checkpoint, triagem e um
pacote de evidências com linha do tempo e SHA-256.

### Treino de detecção

Gera tráfego de ataque sintético e passa pelo Suricata com as suas regras, offline. O
relatório mostra, por técnica MITRE ATT&CK, o que o sensor viu e o que deixou passar.

```console
$ sudo nos drill run
  ✔ DETECTADO  T1046      Varredura de portas TCP (SYN)
  ✔ DETECTADO  T1190      Injeção de SQL automatizada contra aplicação web
  ✘ PASSOU     T1071.004  Túnel/exfiltração por consultas DNS
  Cobertura: 7/8 técnicas (87%)
```

### E mais

| Comando | O que faz |
|---|---|
| `nos attest` | Atesta que o sistema ainda é o que foi instalado: confere todos os arquivos de pacotes, executáveis sem dono, Secure Boot e SELinux |
| `nos forge` | Gera uma ISO que instala sozinha com a sua configuração (sensor pronto ao ligar) |
| `nos box kali` | Kali, Debian, Arch, Ubuntu ou Parrot integrados ao sistema, sem tocar na base |
| `nos sensor` | Configura e atualiza o sensor IDS (Suricata) |
| `nos status` | Postura de segurança da máquina |
| `nos capture` / `nos triage` | Captura em anel e coleta de triagem do host |
| `nos tools` | Catálogo de ferramentas, com busca |

O [manual](docs/MANUAL.md) descreve cada um em detalhe, incluindo os limites.

## Ferramentas

| Categoria | Exemplos |
|---|---|
| Tráfego e captura | Wireshark, tcpdump, tshark, ngrep, tcpflow, tcpreplay, mitmproxy, argus, nfdump |
| Detecção e monitoramento | Suricata, fail2ban, auditd, osquery, sysdig, glances |
| Descoberta e varredura | nmap, masscan, zmap, arp-scan, fping, dnsrecon, gobuster, ffuf |
| Diagnóstico de rede | mtr, iperf3, trippy, bandwhich, gping, ethtool, bpftrace |
| Engenharia de redes | FRR, BIRD, ExaBGP, Ansible, Netmiko, Scapy, WireGuard, strongSwan |
| Forense e análise de malware | Sleuth Kit, YARA, ClamAV, binwalk, rizin, bulk_extractor, ddrescue |
| Senhas e criptografia | hashcat, John the Ripper, hydra, medusa, crunch |
| Redes sem fio e rádio | aircrack-ng, Kismet, hcxtools, GNU Radio, rtl-sdr, HackRF |
| Auditoria e hardening | OpenSCAP, Lynis, AIDE, trivy, rkhunter, testssl |

A lista completa sai de `nos tools --all`. Só entra na ISO o que existe nos repositórios
do Fedora; o que falta (Metasploit e Burp Suite, por exemplo) roda por `nos box kali`.

## Baixar e instalar

1. Baixe a ISO em [Releases](https://github.com/Daniel-Pereira-Linux/milizos/releases/latest).
   A ISO passa do limite de 2 GB por arquivo do GitHub, entao vai em duas partes. Junte e confira:
   ```bash
   cat MilizOS-1.0-x86_64.iso.part-* > MilizOS-1.0-x86_64.iso
   sha256sum -c MilizOS-1.0-x86_64.iso.sha256
   ```
2. Grave em um pendrive:
   ```bash
   sudo dd if=MilizOS-1.0-x86_64.iso of=/dev/sdX bs=4M status=progress oflag=sync
   ```
3. Inicie pelo pendrive. O instalador abre sozinho no modo live.

Requisitos: x86-64, 4 GB de RAM (8 GB recomendado), 30 GB de disco.
Para checkpoints e linha do tempo, mantenha o btrfs sugerido pelo instalador.

## Construir a partir do código

Tudo roda em podman sem root:

```bash
git clone https://github.com/Daniel-Pereira-Linux/milizos
cd milizos
./build.sh all        # → out/MilizOS-1.0-x86_64.iso
tests/vm.py start live && tests/vm.py shot tela.png
```

Detalhes, estágios e armadilhas em [docs/BUILD.md](docs/BUILD.md).

## Colaborar

Adicionar uma ferramenta é editar uma linha; criar um subcomando do `nos` é um arquivo
Python; um novo cenário de ataque para o treino de detecção é uma função.
O [guia de contribuição](CONTRIBUTING.md) tem a receita de cada um.

## O que foi testado

Testado em QEMU/KVM nesta versao: boot UEFI da ISO, animacao 3D do boot, desktop live com
fundo animado, instalador, `nos about`, `nos tools` e `nos drill` (7 de 8 cenarios).
Varios recursos estao escritos mas ainda nao foram testados, e ha problemas conhecidos
(o fundo animado pesa em VM sem aceleracao 3D). A lista honesta esta em
[docs/PROBLEMAS-CONHECIDOS.md](docs/PROBLEMAS-CONHECIDOS.md). Nao foi testado em hardware real.

## Licença e avisos

Código sob GPL-3.0-or-later; arte e identidade visual sob CC-BY-SA-4.0. Os pacotes
incluídos na ISO mantêm as próprias licenças.

O MilizOS é baseado no Fedora Linux, mas é um projeto independente, sem vínculo com o
Projeto Fedora ou a Red Hat. Use as ferramentas de segurança apenas em sistemas e redes
que você tem autorização para testar.

## Autor

Criado por **Daniel Pereira da Silva** ·
[linkedin.com/in/danielpereira-linux](https://www.linkedin.com/in/danielpereira-linux/)

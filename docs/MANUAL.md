# Manual do MilizOS

Tudo o que a distribuição faz, e como usar. O ponto de entrada é o comando **`nos`**
(também disponível como `miliz`); `nos help` mostra o resumo no terminal.

- [Instalação](#instalação)
- [Perfis](#perfis)
- [Ferramentas](#ferramentas)
- [Checkpoints e rollback do sistema](#checkpoints-e-rollback-do-sistema)
- [Linha do tempo dos dados](#linha-do-tempo-dos-dados)
- [Modo incidente](#modo-incidente)
- [Treino de detecção](#treino-de-detecção)
- [Atestação de integridade](#atestação-de-integridade)
- [Sensor IDS](#sensor-ids)
- [Forja de imagens](#forja-de-imagens)
- [Caixas de outras distribuições](#caixas-de-outras-distribuições)
- [Utilitários do dia a dia](#utilitários-do-dia-a-dia)

## Instalação

1. Grave a ISO em um pendrive (`dd`, Fedora Media Writer, Ventoy, balenaEtcher).
2. Inicie por ele. O menu oferece: iniciar (live / instalar), modo gráfico seguro,
   modo texto e instalação desassistida.
3. No modo live o instalador abre sozinho. Escolha idioma, disco, usuário e perfil.

O instalador cria uma tabela GPT que inicia tanto em BIOS quanto em UEFI (com Secure
Boot), e oferece:

| Opção | Escolhas |
|---|---|
| Sistema de arquivos | **btrfs** (padrão; habilita checkpoints e linha do tempo), xfs, ext4 |
| Criptografia | LUKS2 no disco inteiro, opcional |
| Perfil | SOC, Redes ou Sensor |

> Checkpoints, rollback e linha do tempo **exigem btrfs**. Em xfs ou ext4 o sistema
> funciona normalmente, sem esses recursos.

### Instalação desassistida

Grave um `autoinstall.json` na pasta `milizos/` da mídia e escolha "instalação
desassistida" no menu de boot:

```json
{"disk": "auto", "filesystem": "btrfs", "encrypt": false, "passphrase": "",
 "hostname": "sensor01", "locale": "pt_BR.UTF-8", "keymap": "br",
 "timezone": "America/Sao_Paulo", "profile": "sensor",
 "user": {"name": "soc", "fullname": "SOC", "password_hash": "$6$...", "admin": true}}
```

- `"disk": "auto"` usa o maior disco interno; ou informe um caminho como `/dev/nvme0n1`.
- Em `user`, use `password_hash` (gere com `openssl passwd -6`) em vez de `password`
  para não deixar a senha em claro na mídia.
- O jeito mais simples de produzir essa mídia é o [`nos forge`](#forja-de-imagens).

## Perfis

O perfil define quais serviços sobem. Dá para trocar depois com `sudo nos profile NOME`.

| Perfil | Para quem | O que liga |
|---|---|---|
| `soc` | analista de SOC / Blue Team | desktop completo, firewall e auditoria; SSH desligado |
| `neteng` | engenharia de redes | desktop, firewall, SSH e descoberta de vizinhos (LLDP) |
| `sensor` | appliance IDS | sem interface gráfica; Suricata, SSH, auditoria e painel web Cockpit (porta 9090) |

## Ferramentas

```bash
nos tools              # categorias e quantidade de ferramentas
nos tools dfir         # lista uma categoria (● instalada, ○ ausente)
nos tools dns          # busca por nome ou descrição
nos tools --all        # tudo
```

As mesmas categorias aparecem como pastas no menu de aplicativos.

## Checkpoints e rollback do sistema

Um checkpoint é uma fotografia somente-leitura do sistema (`/usr`, `/etc`, pacotes),
com o kernel correspondente guardado em `/boot`. Diferente de uma distribuição imutável,
o sistema continua com acesso total de escrita.

```bash
sudo nos checkpoint list
sudo nos checkpoint create "antes de mexer no firewall"
sudo nos checkpoint diff 7              # pacotes e arquivos de /etc que mudaram desde o #7
sudo nos checkpoint diff 7 /etc/ssh/sshd_config
sudo nos checkpoint rollback 7          # vale no próximo boot
sudo nos checkpoint delete 3
```

- **Automático**: toda transação do `dnf` cria um checkpoint antes de alterar o sistema.
  Ficam os 10 automáticos mais recentes; os manuais não expiram.
- **Pelo menu de boot**: se o sistema não sobe, escolha *MilizOS: checkpoints* no GRUB.
  O rollback é feito no initramfs, antes de montar a raiz.
- **O estado atual nunca é perdido**: antes de reverter, ele vira um checkpoint.
- **`/home` e `/var/log` não voltam no tempo** no rollback do sistema.

### Resgate pela mídia

Se o `/boot` ou o GRUB foram destruídos, o menu de checkpoints deixa de existir, mas os
snapshots continuam no disco. Inicie pela ISO do MilizOS e rode:

```bash
sudo nos checkpoint rescue        # lista os checkpoints do disco e pergunta qual restaurar
```

O resgate restaura o sistema, reconstrói kernels e initramfs em `/boot` e reinstala o GRUB.

### Limites

Checkpoints protegem contra erro, atualização ruim e alteração indevida do sistema. Não
substituem backup: falha do disco, ou alguém com root apagando os snapshots, não tem volta.

## Linha do tempo dos dados

Snapshots somente-leitura de `/home`, tirados sozinhos de hora em hora. Ficam os das
últimas 24 horas e um por dia durante 14 dias.

```bash
sudo nos data list
sudo nos data snap                                   # snapshot agora
sudo nos data restore ~/relatorio.odt --at ontem     # cria relatorio.odt.restaurado-<id>
sudo nos data restore ~/projeto --at 3h --in-place   # sobrescreve com a versão de 3 h atrás
sudo nos data restore ~ --at 2026-11-09 --in-place   # o home inteiro
```

`--at` aceita `ontem`, `3h`, `2d`, `AAAA-MM-DD`, `"AAAA-MM-DD HH:MM"` ou o id do snapshot.
Sem `--at`, usa o mais recente.

Isso recupera arquivos apagados ou criptografados por ransomware que rodou como usuário
comum, porque os snapshots são somente-leitura e ficam fora de `/home`. Um atacante com
root pode apagá-los: mantenha também um backup fora da máquina.

## Modo incidente

Para o momento em que você suspeita que a máquina foi comprometida. Um comando, na ordem
de volatilidade:

```bash
sudo nos incident start                    # isola a máquina
sudo nos incident start --allow 10.0.0.5   # isola, mas mantém acesso ao IP do analista
sudo nos incident start --no-isolate       # só coleta
sudo nos incident status
sudo nos incident release                  # encerra, remove o isolamento e empacota
```

O que acontece no `start`:

1. **Captura de tráfego** em anel (20 × 50 MB) em todas as interfaces.
2. **Estado volátil**: processos, conexões, rotas, vizinhos, usuários, módulos, executáveis
   apagados em execução, firewall, timers, journal e auditoria — cada item com SHA-256.
3. **Contenção**: regras nftables bloqueiam toda entrada e saída, exceto os IPs de
   `--allow`. Se você estiver conectado por SSH, seu IP é liberado automaticamente.
4. **Checkpoint** do sistema, preservando o estado em disco.
5. **Triagem** do host e **manifesto** de integridade.

O `release` gera `/var/lib/milizos/incidents/INC-<data>.tar.gz` com `timeline.log`
(quem fez o quê e quando), `caso.json`, `MANIFEST.sha256` e o SHA-256 do pacote.

A memória RAM não é adquirida por padrão: o kernel em *lockdown* bloqueia o acesso e a
ISO não traz módulo de aquisição. Se o `avml` estiver instalado, ele é usado.

## Treino de detecção

Mede o que o seu sensor de fato detecta. O `nos drill` gera tráfego de ataque sintético
em pcap e passa pelo Suricata **offline**; nenhum pacote vai para a rede.

```bash
nos drill list                         # cenários e técnicas MITRE ATT&CK
sudo nos drill run                     # todos, com as regras em uso no sensor
sudo nos drill run sqlmap dnstunnel    # só alguns
sudo nos drill run --baseline          # com as regras de referência do MilizOS
sudo nos drill run --export ~/pcaps    # salva os pcaps para usar com tcpreplay
```

| Cenário | Técnica | O que simula |
|---|---|---|
| `portscan` | T1046 | varredura de portas TCP (SYN) |
| `sqlmap` | T1190 | injeção de SQL automatizada |
| `traversal` | T1083 | leitura de `/etc/passwd` por path traversal |
| `shell` | T1059 | shell reversa devolvendo `uid=0(root)` |
| `dnstunnel` | T1071.004 | túnel por consultas DNS |
| `sshbrute` | T1110 | força bruta de SSH |
| `eicar` | T1105 | download de arquivo malicioso de teste |
| `icmptunnel` | T1095 | túnel por ICMP |

O resultado mostra cada técnica como DETECTADO ou PASSOU, a cobertura em porcentagem e
as lacunas. O relatório em JSON fica em `/var/lib/milizos/drill/`. O código de saída é
3 quando há lacunas, o que permite usar o treino em automação.

## Atestação de integridade

Responde "este sistema ainda é o que foi instalado?".

```bash
sudo nos attest seal     # grava o estado de referência (faça logo após instalar e configurar)
sudo nos attest          # verifica
```

A verificação cobre: Secure Boot, lockdown do kernel, SELinux, módulos externos, o
conteúdo de **todos os arquivos de pacotes** contra o banco RPM, e executáveis ou units
do systemd que não pertencem a pacote nenhum. Com o selo gravado, mostra também pacotes
adicionados e removidos e executáveis novos. Veredito: ÍNTEGRO ou ALTERADO.

Limite: a verificação roda no próprio sistema. Um rootkit de kernel pode enganá-la; para
esse nível de suspeita, verifique a partir da mídia live. Guarde uma cópia do selo fora
da máquina.

## Sensor IDS

```bash
nos sensor status               # interface, estado do Suricata, regras, alertas recentes
sudo nos sensor setup enp3s0    # define a interface de captura
sudo nos sensor update          # atualiza as regras
```

No perfil `sensor` isso é configurado sozinho na instalação: o Suricata sobe na interface
detectada, com um conjunto inicial de regras.

## Forja de imagens

Gera uma ISO que instala sozinha com a sua configuração.

```bash
nos forge --iso MilizOS-1.0-x86_64.iso                 # assistente interativo
nos forge --iso MilizOS-1.0-x86_64.iso --config meu.json -o sensor-filial.iso
```

A mídia resultante inicia direto na instalação automática após 8 segundos. A senha do
usuário vai como hash, nunca em claro.

> **A mídia forjada apaga o disco da máquina em que iniciar, sem perguntar.**
> Identifique bem o pendrive.

## Caixas de outras distribuições

Para a ferramenta que só existe em outra distribuição. A caixa compartilha a sua pasta
pessoal, a rede e a tela, sem alterar a base do MilizOS. Roda sem root.

```bash
nos box                  # lista
nos box kali             # cria (na primeira vez) e entra
nos box kali nmap -sV alvo
nos box rm kali
```

Disponíveis: `kali`, `debian`, `ubuntu`, `arch`, `parrot`, `alpine`, `fedora`.
Dentro da caixa Kali, `sudo apt install kali-linux-headless` traz o conjunto completo de
ferramentas do Kali. É preciso internet para baixar a imagem na primeira vez.

## Utilitários do dia a dia

```bash
nos status                       # postura de segurança: SELinux, firewall, Secure Boot, serviços
nos ifaces                       # interfaces, endereços, enlace, vizinhos
sudo nos capture enp3s0 port 53  # captura em anel (pcap rotativo) com filtro BPF
sudo nos triage                  # coleta de triagem do host em um .tar.gz com SHA-256
nos about                        # sobre o MilizOS
```

---

MilizOS foi criado por **Daniel Pereira da Silva** ·
https://www.linkedin.com/in/danielpereira-linux/

# Guia do administrador

Para quem instala, mantém e responde pelo MilizOS em uma ou em muitas máquinas.
Uso do dia a dia: [MANUAL.md](MANUAL.md). Funcionamento interno: [ARQUITETURA.md](ARQUITETURA.md).

- [Antes de instalar](#antes-de-instalar)
- [Instalar](#instalar)
- [Primeiros minutos](#primeiros-minutos)
- [Atualizações](#atualizações)
- [Heloisa na operação](#heloisa-na-operação)
- [Pandora na operação](#pandora-na-operação)
- [Sensores](#sensores)
- [Quando algo dá errado](#quando-algo-dá-errado)
- [Referência rápida](#referência-rápida)

## Antes de instalar

| Item | Mínimo | Observação |
|---|---|---|
| CPU | x86-64 | |
| RAM | 4 GB | o desktop completo cabe graças ao zram |
| Disco | 30 GB | mais espaço = mais história guardada pela Heloisa |
| Boot | BIOS ou UEFI | Secure Boot pode ficar ligado |

Confira a ISO antes de gravar:

```bash
curl -fL --remote-name-all "https://github.com/Daniel-Pereira-Linux/milizos/releases/download/v2.0/MilizOS-2.0-x86_64.iso.part-0[0-1]" "https://github.com/Daniel-Pereira-Linux/milizos/releases/download/v2.0/MilizOS-2.0-x86_64.iso.sha256" \
  && cat MilizOS-2.0-x86_64.iso.part-* > MilizOS-2.0-x86_64.iso \
  && sha256sum -c MilizOS-2.0-x86_64.iso.sha256 && rm MilizOS-2.0-x86_64.iso.part-*
sudo dd if=MilizOS-2.0-x86_64.iso of=/dev/sdX bs=4M status=progress oflag=sync
```

## Instalar

**Uma máquina:** inicie pelo pendrive; o instalador abre sozinho. Mantenha **btrfs**: é o
que dá a linha do tempo. Marque a criptografia (LUKS2) em notebooks.

**Muitas máquinas:** grave um `autoinstall.json` na pasta `milizos/` do pendrive e escolha
"instalação desassistida" no menu de boot.

```json
{"disk": "auto", "filesystem": "btrfs", "encrypt": false, "passphrase": "",
 "hostname": "soc-01", "locale": "pt_BR.UTF-8", "keymap": "br",
 "timezone": "America/Sao_Paulo", "profile": "soc",
 "kernel_args": "",
 "user": {"name": "analista", "fullname": "Analista", "password_hash": "$6$...", "admin": true}}
```

| Campo | Valores |
|---|---|
| `disk` | `auto` (maior disco interno) ou um caminho, como `/dev/nvme0n1` |
| `filesystem` | `btrfs`, `xfs`, `ext4` |
| `profile` | `soc`, `neteng`, `sensor` |
| `kernel_args` | argumentos extras do kernel, por exemplo `console=ttyS0` em sensores de rack |
| `user.password_hash` | gere com `openssl passwd -6`; evita senha em claro na mídia |

O registro fica em `/var/log/milizos-install.log` no sistema instalado.

## Primeiros minutos

```bash
getenforce                         # Enforcing
zramctl                            # swap comprimido ativo
systemctl list-timers 'heloisa*' 'milizos*'
ls /.heloisa                       # o ponto 1 é a instalação limpa
```

Abra a **Heloisa** e confira o ponto "instalação limpa": enquanto ele existir, sempre dá
para voltar ao sistema de fábrica.

## Atualizações

Há dois fluxos, de propósito separados.

### Pacotes do MilizOS: automático

Heloisa, Pandora, instalador e identidade vêm do repositório do projeto e são atualizados
**sozinhos, uma vez por dia**, pelo `milizos-update.timer`. Quando o projeto publica uma
correção, ela chega às máquinas em até 24 horas, sem ninguém fazer nada.

```bash
systemctl list-timers milizos-update.timer     # quando roda de novo
journalctl -u milizos-update -n 30             # o que a última execução fez
sudo systemctl start milizos-update.service    # forçar agora
```

Antes de instalar qualquer coisa, a Heloisa cria um ponto. Se uma atualização causar
problema, volte ao ponto "antes de: dnf upgrade".

Para **desligar** (ambiente sem internet ou com janela de mudança):

```bash
sudo systemctl disable --now milizos-update.timer
```

Para usar um **espelho interno**, edite `baseurl` em `/etc/yum.repos.d/milizos.repo`.

### Pacotes do Fedora: quando você decidir

```bash
sudo dnf upgrade
```

Também cria um ponto antes. Depois de atualizar o kernel, reinicie; se o novo kernel não
subir, o GRUB tem o submenu **Heloisa** com o sistema de antes.

## Heloisa na operação

| Situação | O que fazer |
|---|---|
| Vou mexer em algo arriscado | **Criar ponto agora**, com um nome que explique |
| Um arquivo de configuração quebrou | aba **Qualquer coisa** → o arquivo → **Voltar** |
| Apagaram uma pasta | **Ver:** um ponto anterior → a pasta → **Voltar** |
| Atualização quebrou o sistema | **Linha do tempo** → ponto de antes → **Voltar para cá** |
| O sistema não inicia | no GRUB, submenu **Heloisa** |
| Nem o GRUB aparece | pendrive do MilizOS → Heloisa → **Procurar sistemas instalados** |
| Ransomware no `/home` | **Voltar para cá** marcando só *Arquivos pessoais* |

**Retenção** (em `/usr/lib/milizos/heloisa/engine.py`, constantes `KEEP*` e `MIN_FREE`):
automáticos de hora em hora por 24 h e um por dia por 14 dias; 12 de pacotes; 5 de
inicialização; manuais e o da instalação para sempre. Com menos de 15% de disco livre, os
automáticos mais antigos saem sozinhos.

**Espaço:** um ponto não copia nada; só segura o que mudar depois. Veja o uso real com:

```bash
sudo btrfs filesystem usage /
```

**Por script**, sem a interface:

```bash
ls /.heloisa/                                        # pontos, somente leitura
sudo cp -a /.heloisa/12/root/etc/ssh/sshd_config /etc/ssh/
sudo /usr/libexec/milizos/heloisa-engine create '{"desc": "antes da janela de mudança"}'
sudo /usr/libexec/milizos/heloisa-engine status
```

**Backup externo** continua necessário. Para mandar um ponto para outro disco:

```bash
sudo btrfs send /.heloisa/12/home | sudo btrfs receive /mnt/backup/
```

## Pandora na operação

- Caixas são por usuário e não precisam de root.
- **Isolada** para o que não é confiável; **Ponte** para ferramentas que precisam da rede.
- Listar e limpar pela linha de comando:

```bash
podman ps -a --filter label=pandora=1
podman system df                    # espaço usado por imagens e caixas
```

- As imagens vêm da internet na criação. Em rede fechada, pré-carregue com
  `podman load -i imagem.tar`.
- As caixas moram em `~/.local/share/containers`, dentro de `/home`: entram nos pontos da
  Heloisa junto com os arquivos pessoais.

## Sensores

O perfil `sensor` não sobe interface gráfica: Suricata, SSH e Cockpit na porta 9090.

```bash
sudo systemctl status suricata milizos-sensor-setup
sudo suricata-update && sudo systemctl restart suricata
sudo tail -f /var/log/suricata/fast.log
```

Os logs ficam no subvolume `log`: voltar o sistema não apaga o que o sensor registrou.

## Quando algo dá errado

| Sintoma | Causa provável | Saída |
|---|---|---|
| Heloisa diz "sem linha do tempo" | instalação em xfs/ext4 | reinstalar em btrfs |
| Heloisa mostra "reinicie para concluir" | há uma volta aplicada | reiniciar |
| Disco enchendo | arquivos grandes apagados ainda presos em pontos | excluir pontos antigos na Heloisa |
| Atalho de caixa não aparece | caixa desligada | abrir a Pandora → **Sincronizar menu** |
| Caixa isolada sem internet | DNS fora da porta 53 ou rede do host caída | testar no host primeiro |
| `milizos-update` falhou | sem rede no momento | roda de novo no próximo ciclo; ver `journalctl` |
| Tela preta no boot | driver de vídeo | no GRUB da mídia, "modo gráfico seguro" |

## Referência rápida

| Coisa | Onde |
|---|---|
| Pontos | `/.heloisa/N/{root,home,log}` |
| Motor da Heloisa | `/usr/libexec/milizos/heloisa-engine` |
| Entrar em uma caixa | `/usr/libexec/milizos/pandora-enter NOME` ou `distrobox enter NOME` |
| Repositório de atualização | `/etc/yum.repos.d/milizos.repo` |
| Serviços | `heloisa-boot`, `heloisa-timeline.timer`, `milizos-update.timer`, `pandora-watch` (usuário) |
| Memória | `/usr/lib/systemd/zram-generator.conf`, `/usr/lib/sysctl.d/60-milizos-memory.conf` |

# Como construir o MilizOS

O MilizOS inteiro sai de `./build.sh`. Tudo roda dentro de um contêiner **podman sem root**:
você não precisa de `sudo`, e nada é instalado na sua máquina além do podman.

## Requisitos

| Item | Mínimo |
|---|---|
| Sistema | Linux x86-64 com `podman` (rootless) |
| Disco livre | 40 GB (cache de pacotes, base expandida e ISO) |
| RAM | 8 GB |
| Rede | necessária no primeiro build (baixa ~2.300 pacotes do Fedora) |
| Para testar | `qemu-system-x86_64` com KVM e `python3` |

## Build completo

```bash
git clone https://github.com/Daniel-Pereira-Linux/milizos
cd milizos
./build.sh all          # resultado: out/MilizOS-1.0-x86_64.iso (+ .sha256)
```

Na primeira execução o `build.sh` constrói a imagem do contêiner (`builder/Containerfile`,
Fedora 44 com rpm-build, erofs-utils, xorriso, grub2 e afins).

## Os quatro estágios

O build é dividido para que você só refaça o que mudou.

| Estágio | Comando | O que faz | Saída |
|---|---|---|---|
| 1. Pacotes | `./build.sh rpms` | Gera a identidade visual e empacota os quatro RPMs próprios | `out/repo/` |
| 2. Base | `./build.sh rootfs` | Resolve e baixa todos os pacotes e instala em uma única transação `rpm` | `cache/rootfs/` |
| 3. Configuração | `./build.sh configure` | Presets do systemd, localidade, dconf, Plymouth, catálogo de ferramentas, dieta e initramfs live | `cache/iso/boot/` |
| 4. Imagem | `./build.sh image` | Sistema em EROFS com rótulos SELinux, GRUB para BIOS e UEFI, ISO híbrida | `out/*.iso` |

`./build.sh shell` abre um terminal dentro do contêiner de build, útil para depurar.

### O ciclo do dia a dia

Mudou algo em `packages/` (o comando `nos`, o instalador, a identidade visual)?
Não é preciso baixar nada de novo:

```bash
# 1. suba o Release: no .spec do pacote que você alterou
./build.sh rpms
./build.sh configure --refresh    # reinstala os RPMs próprios na base existente
./build.sh image
```

Mudou a lista de pacotes (`build/packages.list` ou `build/tools-extra.list`)?
A base precisa ser refeita:

```bash
podman unshare rm -rf cache/rootfs
./build.sh rootfs && ./build.sh configure && ./build.sh image
```

Os pacotes já baixados ficam em `cache/dnf/` e são reaproveitados.

## Mapa do repositório

```
build.sh                    orquestrador (escolhe o estágio e chama o contêiner)
builder/Containerfile       ambiente de build
build/
  stage-rpms.sh             estágio 1
  stage-rootfs.sh           estágio 2
  stage-configure.sh        estágio 3
  stage-image.sh            estágio 4
  packages.list             pacotes da base e do desktop
  tools-extra.list          catálogo estendido: "categoria: pacotes" (candidatos)
  packages-extra.list       o subconjunto de tools-extra que entra na imagem
  gen-branding.sh           wallpapers, ícones, fontes do GRUB, tema do Plymouth
  gen-bootanim.py           quadros da animação 3D do boot
  gen-menu.py               lançadores e pastas do menu a partir do catálogo
  gen-catalog.py            catalog.d/extra.json a partir do que foi instalado
branding/src/               logo, wordmark e gerador de wallpaper (SVG)
packages/
  milizos-release/          os-release, presets do systemd, /etc/issue
  milizos-branding/         tema GRUB e Plymouth, dconf, extensão do GNOME Shell
  milizos-installer/        instalador (engine.py + gui.py) e modo live
  milizos-tools/            comando nos, checkpoints, incidente, drill, attest, forge, box
tests/vm.py                 bancada de testes em QEMU/KVM
docs/                       site (index.html) e documentação
```

Cada pacote em `packages/NOME/` tem um `.spec` genérico e uma árvore `root/` que é copiada
como está para o sistema. Para adicionar um arquivo ao sistema, basta criá-lo no caminho
certo dentro de `root/`.

## Detalhes que economizam horas

Estes pontos custaram tempo para descobrir; estão resolvidos nos scripts, mas explicam
por que eles são como são.

- **SELinux do hospedeiro vaza para o contêiner privilegiado.** O plugin SELinux do `rpm`
  tenta aplicar rótulos e os scriptlets falham com "Permission denied". Os estágios
  montam um `tmpfs` sobre `/sys/fs/selinux` antes de instalar.
- **Os rótulos SELinux são gravados na criação da imagem**, com
  `mkfs.erofs --file-contexts`, e não no sistema de arquivos do build.
- **Dependências fracas estão desligadas** para a imagem não inchar. Se um pacote
  recomendado for de fato necessário (foi o caso do `systemd-pam`, sem o qual a sessão
  gráfica não sobe), ele precisa estar explícito em `packages.list`.
- **A base é instalada por `rpm` direto**, a partir da lista resolvida pelo `dnf`
  (`--downloadonly`). Assim a transação é única e reproduzível.
- **O modo live roda com `enforcing=0`**; o sistema instalado roda em *Enforcing*
  (o instalador faz o `setfiles` no destino).
- **Contêiner sem `--privileged` lendo o diretório do projeto** precisa de
  `--security-opt label=disable`.
- **Nomes de pacotes variam**: `--skip-unavailable` deixa passar o que não existe no
  Fedora. Confira no log do estágio 2 o que ficou de fora.

## Compressão da imagem

O estágio 4 aceita `EROFS_OPTS` para trocar o método de compressão sem editar o script.
Veja a tabela de medições no README antes de escolher: métodos mais fortes deixam a ISO
menor, mas o build demora mais e a leitura em modo live fica um pouco mais lenta.

## Testando

```bash
tests/vm.py start live            # sobe a ISO em QEMU/KVM (BIOS)
tests/vm.py start live --uefi     # idem, em UEFI
tests/vm.py shot tela.png         # captura de tela
tests/vm.py sh "nos status"       # roda um comando pelo console serial
tests/vm.py key ret               # envia uma tecla
tests/vm.py stop
```

Instalação desassistida de ponta a ponta:

```bash
tests/vm.py start autoinstall --cfg tests/autoinstall-btrfs.json
tests/vm.py wait "MILIZOS-AUTOINSTALL: OK"
tests/vm.py stop
tests/vm.py start disk            # inicia pelo disco recém-instalado
```

Antes de abrir um pull request, rode no mínimo: boot live, uma instalação desassistida em
btrfs, boot do sistema instalado e `nos status`.

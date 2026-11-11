# Estado da versão 2.0: o que foi testado e o que não foi

## Testado em máquina virtual (QEMU/KVM, UEFI, 4 GB de RAM)

- Boot da ISO, desktop live com o instalador (1,3 GB de RAM em uso; zram ativo).
- Instalação desassistida em btrfs; sistema instalado com SELinux em *Enforcing* e nenhum
  serviço em falha (0,9 GB em uso na tela de login).
- **Heloisa:** ponto da instalação e de inicialização; ponto manual; ponto automático antes
  de `dnf remove`; versões e diff de um arquivo; voltar um arquivo; voltar uma pasta (o
  apagado reaparece, o criado depois some); cópia ao lado; voltar o sistema e reiniciar;
  voltar pelo submenu do GRUB, com o estado anterior preservado; interface gráfica com
  autenticação pelo polkit.
- **Pandora:** caixa Alpine isolada criada no sistema instalado; internet funciona e a rede
  local é recusada; aplicativo instalado vira atalho no menu e some ao ser desinstalado;
  destruir remove caixa, atalhos e pasta.

## Escrito, mas ainda não testado nesta versão

- Resgate pela mídia (Heloisa em modo live reconstruindo `/boot`).
- Voltar `/home` inteiro e logs inteiros pela Heloisa (o mesmo mecanismo do sistema).
- Trava de espaço da Heloisa (apagar pontos automáticos com menos de 15% livre).
- Pandora no modo **Ponte** e com as imagens Debian, Kali, Alma, Ubuntu, Fedora, Arch,
  Rocky, openSUSE e Parrot (só Alpine foi criada de ponta a ponta).
- Atualização automática diária (`milizos-update`): o serviço e o repositório existem, mas
  o ciclo completo só pode ser provado depois da primeira publicação.
- Instalação pela interface gráfica, LUKS2, xfs/ext4, BIOS, Secure Boot e os perfis
  `neteng` e `sensor`: validados na 1.0, não repetidos na 2.0.

## Problemas e limites conhecidos

- **Pacotes do repositório do MilizOS não são assinados** (`gpgcheck=0`); a integridade
  depende do HTTPS do GitHub.
- A Heloisa compara versões de arquivos por tamanho e data, não por conteúdo.
- `/boot` e a partição EFI não entram nos pontos (o kernel de cada ponto, sim).
- O modo Ponte da Pandora compartilha a rede do host; a caixa não ganha IP próprio.
- A linha do kernel do sistema instalado repete `rootflags=subvol=root` (inofensivo).
- A ISO tem 3,2 GB, acima do limite de 2 GB por arquivo do GitHub Releases (vai em partes).

## Não testado

Hardware real.

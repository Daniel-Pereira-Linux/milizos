# Estado da versão 2.1.0: o que foi testado e o que não foi

## Testado em máquina virtual (QEMU/KVM, UEFI, 4 GB de RAM)

- Boot da ISO, desktop live com o instalador; instalação desassistida em btrfs; sistema
  instalado com SELinux em *Enforcing* e nenhum serviço em falha.
- **Heloisa, o que já vinha da 2.0:** pontos de instalação, inicialização, manuais e antes
  de `dnf`; versões e diff de um arquivo; voltar arquivo e pasta; voltar o sistema e
  reiniciar; voltar pelo submenu do GRUB; interface com autenticação pelo polkit.
- **Heloisa, novo na 2.1.0:**
  - resumo automático dos pontos, incluindo renomeações;
  - aviso de arquivo em uso, com um serviço de teste escrevendo no arquivo: parar, voltar
    e religar, pelo motor e pela interface;
  - *Quando mudou?* de um arquivo;
  - selar um ponto, conferir o selo e detectar adulteração;
  - criar um ramo, iniciar nele pelo GRUB, voltar ao principal pelo aplicativo;
  - procurar o que quebrou, de ponta a ponta, atravessando as reinicializações, com a
    máquina devolvida ao sistema original no fim;
  - experimentar um ponto em um terminal, com SELinux em *Enforcing*;
  - envio completo e incremental para um segundo disco btrfs (8,5 GB em 34 s no primeiro),
    e recusa de destino no mesmo disco;
  - clone a partir do disco de backup para um disco vazio, pelo motor e pelo botão
    *Clonar de uma cópia* da mídia (1 a 3 min), com a máquina clonada iniciando com outro
    nome, os arquivos pessoais e nenhum serviço em falha;
  - alarme de ransomware: sem falso positivo em uma edição em massa de texto, disparo em
    uma cifragem simulada de 160 arquivos, ponto anterior protegido e pasta recuperada;
  - abertura automática da Heloisa ao entrar na sessão com alarme pendente.
- **Atualização da 2.0 para a 2.1.0** com o mesmo comando do atualizador diário
  (`dnf upgrade --repo=milizos`), contra os pacotes novos servidos localmente.
- **Pandora:** caixa Alpine isolada; internet funciona e a rede local é recusada; atalho
  automático; destruir. Novo na 2.1.0: criar ponto da caixa, estragar a caixa (programa
  removido, arquivo pessoal alterado) e voltar, pelo motor e pela interface.

## Escrito, mas ainda não testado nesta versão

- **Envio de pontos por SSH** (`ssh://`): só o envio para disco local foi testado.
- **Clone com disco cifrado (LUKS)** e clone em máquina BIOS.
- Ramos e busca do que quebrou em **sistema cifrado** ou instalado em modo BIOS.
- Alarme de ransomware contra um ransomware real: o teste foi uma cifragem simulada.
- Pontos da Pandora em caixas no modo **Ponte** e em distribuições além da Alpine.
- O ciclo completo da atualização automática pelo temporizador diário, a partir do
  repositório publicado (o comando foi testado; o temporizador, não).
- As janelas de *Procurar o que quebrou* pela interface (o fluxo foi testado pelo motor).
- Resgate pela mídia (Heloisa em modo live reconstruindo `/boot`).
- Voltar `/home` inteiro e logs inteiros pela Heloisa (o mesmo mecanismo do sistema).
- Trava de espaço da Heloisa (apagar pontos automáticos com menos de 15% livre).
- Pandora com as imagens Debian, Kali, Alma, Ubuntu, Fedora, Arch, Rocky, openSUSE e
  Parrot (só Alpine foi criada de ponta a ponta).
- Instalação pela interface gráfica, LUKS2, xfs/ext4, BIOS, Secure Boot e os perfis
  `neteng` e `sensor`: validados na 1.0, não repetidos desde então.

## Problemas e limites conhecidos

- **Pacotes do repositório do MilizOS não são assinados** (`gpgcheck=0`); a integridade
  depende do HTTPS do GitHub.
- **O alarme de ransomware é uma heurística** sobre o que já aconteceu: não impede o
  ataque, pode disparar em conversões em massa legítimas e não vê arquivos fora de `/home`.
- **Um invasor com root apaga os pontos locais.** Só os pontos enviados para outro disco
  ou servidor resistem a isso.
- **A chave do selo fica na própria máquina.** O selo prova que o ponto não mudou desde
  que foi selado; contra um invasor com root, a prova é o hash guardado fora da máquina.
- **O clone copia usuários e senhas** da máquina de origem. Troque as senhas se o clone
  for para outra pessoa.
- Voltar um arquivo em uso: a Heloisa só sabe parar e religar **serviços do systemd**.
  Programas abertos à mão são listados, e cabe a você fechá-los.
- Um ramo guarda só o sistema; arquivos pessoais e logs são compartilhados entre os ramos.
- Selar um ponto lê o ponto inteiro: em um sistema de 9 GB levou cerca de meio minuto.
- A Heloisa compara versões de arquivos por tamanho e data, não por conteúdo.
- `/boot` e a partição EFI não entram nos pontos (o kernel de cada ponto, sim).
- O modo Ponte da Pandora compartilha a rede do host; a caixa não ganha IP próprio.
- A linha do kernel do sistema instalado repete `rootflags=subvol=root` (inofensivo).
- A ISO passa do limite de 2 GB por arquivo do GitHub Releases (vai em partes).

## Não testado

Hardware real.

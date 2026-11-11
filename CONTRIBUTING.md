# Como colaborar com o MilizOS

Obrigado pelo interesse. O MilizOS é uma distribuição para quem defende redes, e toda
contribuição que ajude um analista de SOC ou um engenheiro de redes a trabalhar melhor é
bem-vinda: ferramentas, cenários de detecção, correções, traduções e documentação.

Leia antes: [docs/BUILD.md](docs/BUILD.md) explica como construir e testar a ISO.

## Fluxo

1. Faça um fork e crie um branch a partir de `main` (`git checkout -b minha-mudanca`).
2. Faça a alteração e **construa a ISO** com ela.
3. **Teste em máquina virtual** (`tests/vm.py`) e descreva no pull request o que testou.
4. Abra o pull request explicando o problema que a mudança resolve.

Mudanças grandes (novo perfil, novo subcomando, troca de base) merecem uma issue antes,
para alinhar a ideia.

## Receitas

### Adicionar uma ferramenta

1. Confirme que o pacote existe no Fedora: `dnf info NOME`.
2. Inclua o nome na categoria certa de `build/tools-extra.list` e em
   `build/packages-extra.list`.
3. Refaça a base (`podman unshare rm -rf cache/rootfs && ./build.sh all`).

A ferramenta aparece sozinha em `nos tools`: o catálogo estendido é gerado a partir do que
foi instalado, com a descrição vinda do próprio RPM. Para dar a ela descrição em português,
lançador no menu e destaque, adicione uma entrada em
`packages/milizos-tools/root/usr/share/milizos/catalog.json`.

Se a ferramenta não existe no Fedora, não empacote binários de terceiros na ISO: ela fica
disponível por `nos box kali` (ou outra caixa).

### Criar um subcomando do `nos`

1. Crie `packages/milizos-tools/root/usr/lib/milizos/meucomando.py` com uma função
   `main(args)`. Use os utilitários de `ui.py` (cores, `sh`, `need_root`).
2. Registre o nome no dicionário `mods` em `packages/milizos-tools/root/usr/bin/nos`
   e acrescente uma linha na ajuda (`cmd_help`).
3. Suba o `Release:` em `packages/milizos-tools/milizos-tools.spec`.
4. `./build.sh rpms && ./build.sh configure --refresh && ./build.sh image`.

### Adicionar um cenário ao treino de detecção

Em `packages/milizos-tools/root/usr/lib/milizos/drill.py`:

1. Escreva uma função `s_nome(sc, src)` que devolve a lista de pacotes Scapy do ataque.
   Para TCP, use a classe `Flow`, que monta a sessão completa (handshake, dados, fim).
2. Acrescente a tupla em `SCENARIOS` com o identificador da técnica MITRE ATT&CK.
3. Adicione uma regra de referência em
   `packages/milizos-tools/root/usr/share/milizos/drill/baseline.rules` (SIDs 99000xx).
4. Teste: `sudo nos drill run nome --baseline` deve dar "DETECTADO".

### Mudar a identidade visual

- Logo e wordmark: `branding/src/*.svg`.
- Wallpapers: `branding/src/gen_wallpaper.py`.
- Animação do boot: `build/gen-bootanim.py` (quadros) e
  `packages/milizos-branding/root/usr/share/plymouth/themes/milizos/milizos.script`.
- Fundo animado do desktop e do login: a extensão em
  `packages/milizos-branding/root/usr/share/gnome-shell/extensions/`.
- Padrões do GNOME (favoritos, tema, extensões): `packages/milizos-branding/root/etc/dconf/db/`.

### Mudar o instalador

- `engine.py` faz o trabalho (particionar, formatar, copiar, bootloader) e não depende de
  interface gráfica; `gui.py` é só a tela.
- Toda opção nova deve funcionar também na instalação desassistida (JSON). Inclua um
  exemplo em `tests/` e rode `tests/vm.py start autoinstall --cfg ...`.

## Padrões

- **Idioma**: mensagens ao usuário em português do Brasil; identificadores de código em inglês.
- **Python**: só biblioteca padrão nos componentes do sistema (mais Scapy no `drill`).
  Sem dependências de `pip` na ISO.
- **Shell**: `bash` com `set -euo pipefail` nos scripts de build.
- **Nada de root no build**: tudo precisa funcionar em podman rootless.
- **Honestidade nas mensagens**: se algo não foi feito (sem btrfs, sem rede, sem
  ferramenta), o comando diz isso com clareza em vez de fingir sucesso.
- **Commits**: mensagem curta no imperativo, em português, explicando o porquê quando não
  for óbvio.

## Relatando problemas

Abra uma issue com: versão (`cat /etc/os-release`), como reproduzir, o que esperava e o
que aconteceu. Para falhas de instalação, anexe `/var/log/milizos-install.log`.

**Vulnerabilidades de segurança**: não abra issue pública. Escreva em privado para o
mantenedor pelo LinkedIn: https://www.linkedin.com/in/danielpereira-linux/

## Licença

Ao contribuir, você concorda em licenciar seu código sob a GPL-3.0-or-later e a arte sob
CC-BY-SA-4.0, as mesmas licenças do projeto.

---

MilizOS foi criado por **Daniel Pereira da Silva**.

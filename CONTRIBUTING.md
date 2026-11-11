# Como colaborar com o MilizOS

Obrigado pelo interesse. O MilizOS é uma distribuição para quem defende redes, e toda
contribuição que ajude um analista de SOC ou um engenheiro de redes a trabalhar melhor é
bem-vinda: ferramentas, correções, traduções e documentação.

Leia antes: [docs/ARQUITETURA.md](docs/ARQUITETURA.md) explica como tudo funciona por dentro.

## O que está neste repositório

O código de tudo o que é próprio do MilizOS: Heloisa, Pandora, instalador, identidade
visual, documentação e site. A montagem da ISO oficial é feita pelo mantenedor e não faz
parte deste repositório; para colaborar você não precisa dela.

## Fluxo

1. Faça um fork e crie um branch a partir de `main` (`git checkout -b minha-mudanca`).
2. Faça a alteração e **teste em um MilizOS instalado em máquina virtual**: copie o
   arquivo alterado por cima do instalado (os caminhos em `packages/*/root/` são os
   mesmos do sistema) e exercite o recurso.
3. Abra o pull request explicando o problema que a mudança resolve e o que você testou.
4. Depois do merge, o mantenedor gera o pacote e publica; a correção chega a todas as
   máquinas pela atualização automática diária.

Mudanças grandes (novo perfil, novo aplicativo, troca de base) merecem uma issue antes,
para alinhar a ideia.

## Receitas

### Sugerir uma ferramenta

Abra uma issue com o nome do pacote no Fedora (`dnf info NOME`) e para que ele serve em um
SOC ou em redes. Para dar a ela lançador no menu, adicione uma entrada em
`packages/milizos-tools/root/usr/share/milizos/catalog.json`. Se a ferramenta não existe
no Fedora, ela fica disponível em uma caixa da Pandora.

### Mexer na Heloisa ou na Pandora

Cada uma é um `engine.py` (toda a lógica, sem interface) e um `gui.py` (GTK4/libadwaita) em
`packages/milizos-tools/root/usr/lib/milizos/{heloisa,pandora}/`.

- O motor da Heloisa roda como root (via polkit) e responde JSON; teste sem interface com
  `sudo /usr/libexec/milizos/heloisa-engine status`. **Só rode em VM**: ele cria e troca
  subvolumes de verdade.
- O motor da Pandora roda como usuário e pode ser testado em qualquer máquina com podman e
  distrobox: `python3 engine.py create teste IMAGEM isolada`.
- Regra da casa: toda operação destrutiva cria um ponto antes, e nada de formato próprio.

### Mudar a identidade visual

- Logo e wordmark: `branding/src/*.svg`.
- Wallpapers: `branding/src/gen_wallpaper.py`.
- Animação do boot:
  `packages/milizos-branding/root/usr/share/plymouth/themes/milizos/milizos.script`.
- Padrões do GNOME (favoritos, tema, extensões): `packages/milizos-branding/root/etc/dconf/db/`.

### Mudar o instalador

- `engine.py` faz o trabalho (particionar, formatar, copiar, bootloader) e não depende de
  interface gráfica; `gui.py` é só a tela.
- Toda opção nova deve funcionar também na instalação desassistida (JSON). Inclua um
  exemplo no pull request.

## Padrões

- **Idioma**: mensagens ao usuário em português do Brasil; identificadores de código em inglês.
- **Python**: só biblioteca padrão nos componentes do sistema (mais PyGObject nas interfaces).
  Sem dependências de `pip`.
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

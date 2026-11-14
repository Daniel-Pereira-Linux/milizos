# Política de segurança do MilizOS

## Versões com correção

Só a versão mais recente recebe correções. Cada versão nova substitui a anterior, e as
correções dos pacotes do MilizOS chegam sozinhas às máquinas instaladas pela atualização
diária.

| Versão | Recebe correções |
|---|---|
| 2.1.x | sim |
| 2.0 e anteriores | não: atualize ou reinstale |

## Como relatar uma vulnerabilidade

**Não abra issue pública.** Relate em privado, por um destes caminhos:

1. Aba **Security** deste repositório, botão **Report a vulnerability**
   ([link direto](https://github.com/Daniel-Pereira-Linux/milizos/security/advisories/new)).
2. Mensagem ao mantenedor geral pelo LinkedIn:
   [linkedin.com/in/danielpereira-linux](https://www.linkedin.com/in/danielpereira-linux/).

Inclua a versão do MilizOS, o componente afetado, o passo a passo para reproduzir e o
impacto que você enxerga. Se tiver uma correção, ela é bem-vinda.

## O que esperar

O MilizOS é mantido no tempo livre, então não há prazo garantido. O compromisso é:
confirmar o recebimento, avaliar, corrigir pelo repositório de atualização e dar o crédito
a quem relatou nas notas da versão, se a pessoa quiser.

## O que é do MilizOS e o que não é

É do MilizOS, e entra nesta política: a Heloisa, a Pandora, o instalador, o repositório de
atualização e a montagem da ISO.

Não é do MilizOS: os pacotes que vêm do Fedora (kernel, GNOME, as ferramentas de rede e de
segurança). Falhas neles devem ir para o projeto de origem ou para o
[Fedora](https://docs.fedoraproject.org/en-US/project/#_security). Se a falha só aparece
por causa de uma configuração do MilizOS, relate aqui.

## Limites já conhecidos

Alguns limites de segurança são públicos e não precisam de relato privado. Eles estão em
[docs/PROBLEMAS-CONHECIDOS.md](docs/PROBLEMAS-CONHECIDOS.md), entre eles: os pacotes do
repositório do MilizOS ainda não são assinados, e um invasor com root apaga os pontos
locais da Heloisa.

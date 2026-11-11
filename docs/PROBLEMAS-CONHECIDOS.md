# Problemas conhecidos e pendências (MilizOS 1.0)

## Problemas
- **Fundo animado pesa sem aceleração 3D.** Em VM sem GPU (renderização por software) o
  gnome-shell chegou a ~385% de CPU. Contorno: `gnome-extensions disable milizos-fx@milizos.org`
  ou ligar a aceleração 3D da VM. Correção planejada: detectar software rendering e reduzir
  resolução/quadros, e pausar com janela maximizada.
- **`nos drill`: cenário `eicar` (T1105) não é detectado pelas regras de referência.** O cenário
  está com a direção cliente/servidor invertida. Os outros 7 cenários funcionam.
- **`nos drill` mostra um aviso do Python (cryptography)** antes do resultado. Inofensivo.
- **ISO com 2,8 GB**, acima do limite de 2 GB por arquivo do GitHub Releases.
- A barra de contagem do GRUB fica grossa em BIOS 640x480 (cosmético).

## Escrito, mas ainda não testado nesta versão
`nos incident`, `nos attest`, `nos forge`, `nos box`, `nos data`, `nos checkpoint rescue`,
a animação na tela de login (GDM) e o prompt de senha LUKS no novo tema de boot.
A instalação, o rollback e os perfis foram validados na versão anterior (antes do catálogo
estendido e da troca de nome) e precisam ser repetidos nesta.

## Testado nesta versão
Boot UEFI da ISO, animação 3D do boot (Plymouth), desktop live com fundo animado,
instalador abrindo com a nova identidade, `nos about`, `nos tools` (362 ferramentas),
`nos drill run --baseline` (7/8).

## Não testado
Hardware real.

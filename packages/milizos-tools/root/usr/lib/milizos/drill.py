# MilizOS - Treino de deteccao (purple team em uma maquina so)
# Gera trafego de ataque sintetico (pcap), passa pelo Suricata offline com as regras
# em uso e mostra o que o sensor enxerga e o que deixa passar, por tecnica MITRE ATT&CK.
# Nada trafega na rede: tudo acontece em arquivos.
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

from ui import ac, bad, dim, need_root, ok, warn

BASELINE = "/usr/share/milizos/drill/baseline.rules"
RULESETS = ["/var/lib/suricata/rules/suricata.rules"]
REPORTS = "/var/lib/milizos/drill"
VICTIM = "10.66.0.10"


class Flow:
    """Monta uma sessao TCP completa e valida (handshake, dados, encerramento)."""
    def __init__(self, sc, src, dst, dport, sport=40000):
        self.sc, self.src, self.dst, self.sport, self.dport = sc, src, dst, sport, dport
        self.cs, self.ss, self.pk = 1000, 5000, []

    def _p(self, c2s, flags, data=b""):
        s = self.sc
        if c2s:
            p = s.IP(src=self.src, dst=self.dst) / s.TCP(sport=self.sport, dport=self.dport, flags=flags, seq=self.cs, ack=self.ss if "A" in flags else 0)
        else:
            p = s.IP(src=self.dst, dst=self.src) / s.TCP(sport=self.dport, dport=self.sport, flags=flags, seq=self.ss, ack=self.cs)
        if data:
            p = p / s.Raw(data)
        self.pk.append(s.Ether(src="02:00:00:00:00:01" if c2s else "02:00:00:00:00:02",
                               dst="02:00:00:00:00:02" if c2s else "02:00:00:00:00:01") / p)

    def open(self):
        self._p(True, "S"); self.cs += 1
        self._p(False, "SA"); self.ss += 1
        self._p(True, "A")
        return self

    def send(self, data, c2s=True):
        for i in range(0, len(data), 1400):
            ch = data[i:i + 1400]
            self._p(c2s, "PA", ch)
            if c2s:
                self.cs += len(ch)
            else:
                self.ss += len(ch)
            self._p(not c2s, "A")
        return self

    def close(self):
        self._p(True, "FA"); self.cs += 1
        self._p(False, "FA"); self.ss += 1
        self._p(True, "A")
        return self.pk


def http(sc, src, req, body=b"OK", sport=40000, client=None, server=None):
    resp = b"HTTP/1.1 200 OK\r\nServer: nginx\r\nContent-Type: application/octet-stream\r\nContent-Length: " + \
        str(len(body)).encode() + b"\r\n\r\n" + body
    return Flow(sc, client or src, server or VICTIM, 80, sport).open().send(req).send(resp, c2s=False).close()


def s_portscan(sc, src):
    return [sc.Ether() / sc.IP(src=src, dst=VICTIM) / sc.TCP(sport=41000 + i, dport=p, flags="S", seq=i)
            for i, p in enumerate(range(20, 100))]


def s_sqlmap(sc, src):
    return http(sc, src, b"GET /produto.php?id=1%27%20UNION%20ALL%20SELECT%20NULL%2CNULL%2CCONCAT%280x71%2Cuser%28%29%29--%20- HTTP/1.1\r\n"
                b"Host: loja.exemplo\r\nUser-Agent: sqlmap/1.8.4#stable (https://sqlmap.org)\r\nAccept: */*\r\n\r\n")


def s_traversal(sc, src):
    return http(sc, src, b"GET /download?arquivo=../../../../../../etc/passwd HTTP/1.1\r\nHost: intranet.exemplo\r\n"
                b"User-Agent: Mozilla/5.0\r\nAccept: */*\r\n\r\n", body=b"root:x:0:0:root:/root:/bin/bash\n")


def s_shell(sc, src):
    # shell reversa: a vitima conecta no atacante e devolve a saida do comando id
    f = Flow(sc, VICTIM, src, 4444, 51000).open()
    f.send(b"id\n", c2s=False)
    f.send(b"uid=0(root) gid=0(root) groups=0(root)\n")
    return f.close()


def s_dnstunnel(sc, src):
    import binascii
    out = []
    for i in range(25):
        label = binascii.hexlify(os.urandom(25)).decode()
        out.append(sc.Ether() / sc.IP(src=VICTIM, dst=src) / sc.UDP(sport=33000 + i, dport=53) /
                   sc.DNS(id=i, rd=1, qd=sc.DNSQR(qname=f"{label}.t.exfil-drill.example", qtype="TXT")))
    return out


def s_sshbrute(sc, src):
    out = []
    for i in range(20):
        f = Flow(sc, src, VICTIM, 22, 42000 + i).open()
        f.send(b"SSH-2.0-OpenSSH_9.6\r\n", c2s=False).send(b"SSH-2.0-libssh_0.9.6\r\n")
        out += f.close()
    return out


def s_eicar(sc, src):
    body = ("X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + "EICAR-STANDARD-" + "ANTIVIRUS-TEST-FILE!$H+H*").encode()
    return http(sc, src, b"GET /atualizacao.bin HTTP/1.1\r\nHost: cdn.exemplo\r\nUser-Agent: curl/8.6.0\r\nAccept: */*\r\n\r\n", body=body,
                client=VICTIM, server=src)     # a vitima baixa o arquivo de um servidor do atacante


def s_icmptunnel(sc, src):
    return [sc.Ether() / sc.IP(src=VICTIM, dst=src) / sc.ICMP(type=8, id=7, seq=i) / sc.Raw(os.urandom(1200))
            for i in range(10)]


SCENARIOS = [
    ("portscan", "T1046", "Descoberta", "Varredura de portas TCP (SYN)", s_portscan),
    ("sqlmap", "T1190", "Acesso inicial", "Injeção de SQL automatizada contra aplicação web", s_sqlmap),
    ("traversal", "T1083", "Descoberta", "Leitura de /etc/passwd por path traversal", s_traversal),
    ("shell", "T1059", "Execução", "Shell reversa devolvendo uid=0(root)", s_shell),
    ("dnstunnel", "T1071.004", "Comando e controle", "Túnel/exfiltração por consultas DNS", s_dnstunnel),
    ("sshbrute", "T1110", "Acesso a credenciais", "Força bruta de SSH", s_sshbrute),
    ("eicar", "T1105", "Comando e controle", "Download de arquivo malicioso (EICAR) por HTTP", s_eicar),
    ("icmptunnel", "T1095", "Comando e controle", "Túnel por ICMP com carga grande", s_icmptunnel),
]


def attacker(i):
    return f"203.0.113.{10 + i}"


def build(sc, names=None):
    """Um pcap unico; cada cenario usa um IP de atacante proprio para atribuir os alertas."""
    pkts, t = [], 1700000000.0
    for i, (name, _t, _ta, _d, fn) in enumerate(SCENARIOS):
        if names and name not in names:
            continue
        for p in fn(sc, attacker(i)):
            t += 0.01
            p.time = t
            pkts.append(p)
        t += 120
    return pkts


def rules_file(force_baseline):
    if not force_baseline:
        for r in RULESETS:
            if os.path.exists(r) and os.path.getsize(r) > 0:
                return r, "regras em uso no sensor"
    return BASELINE, "regras de referência do MilizOS"


def run(args):
    need_root(["drill", "run"] + args)
    base = "--baseline" in args
    export = None
    if "--export" in args:
        export = args[args.index("--export") + 1] if args.index("--export") + 1 < len(args) else sys.exit("uso: --export DIRETÓRIO")
    names = [a for a in args if not a.startswith("-") and a != export] or None
    if names and (set(names) - {s[0] for s in SCENARIOS}):
        sys.exit("cenário desconhecido; veja: nos drill list")
    try:
        import logging
        import warnings
        warnings.filterwarnings("ignore")
        logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
        import scapy.all as sc
    except ImportError:
        sys.exit("python3-scapy não está instalado")
    if not shutil.which("suricata"):
        sys.exit("suricata não está instalado")
    rules, origin = rules_file(base)
    print(ac("▍Treino de detecção") + dim(f"   {origin}: {rules}"))
    work = tempfile.mkdtemp(prefix="nos-drill-")
    try:
        pcap = f"{work}/drill.pcap"
        sc.wrpcap(pcap, build(sc, names))
        if export:
            os.makedirs(export, exist_ok=True)
            for i, (name, *_r, fn) in enumerate(SCENARIOS):
                if not names or name in names:
                    sc.wrpcap(f"{export}/{name}.pcap", build(sc, [name]))
            print(dim(f"  pcaps exportados em {export} (reproduza na rede com tcpreplay)"))
        print(dim("  analisando o tráfego sintético com o Suricata…"), flush=True)
        p = subprocess.run(["suricata", "-r", pcap, "-l", work, "-k", "none", "-S", rules,
                            "--set", "outputs.1.eve-log.enabled=yes"], capture_output=True, text=True)
        hits = {}
        try:
            for line in open(f"{work}/eve.json", encoding="utf-8", errors="replace"):
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("event_type") != "alert":
                    continue
                for i, s in enumerate(SCENARIOS):
                    if attacker(i) in (e.get("src_ip"), e.get("dest_ip")):
                        hits.setdefault(s[0], {})[e["alert"]["signature_id"]] = e["alert"]["signature"]
        except OSError:
            sys.exit(f"o Suricata não produziu resultado:\n{(p.stderr or p.stdout)[-1500:]}")
        res, det = [], 0
        for name, tech, tactic, desc, _fn in SCENARIOS:
            if names and name not in names:
                continue
            h = hits.get(name, {})
            det += bool(h)
            res.append({"cenario": name, "tecnica": tech, "tatica": tactic, "descricao": desc,
                        "detectado": bool(h), "assinaturas": [{"sid": k, "msg": v} for k, v in h.items()]})
            print(f"  {ok('✔ DETECTADO') if h else bad('✘ PASSOU   ')}  {tech:<10} {desc}")
            for sid, msg in list(h.items())[:3]:
                print(dim(f"                 └ [{sid}] {msg}"))
        pct = 100 * det // max(len(res), 1)
        colr = ok if pct >= 80 else warn if pct >= 50 else bad
        print("\n  Cobertura: " + colr(f"{det}/{len(res)} técnicas ({pct}%)"))
        miss = [r for r in res if not r["detectado"]]
        if miss:
            print(warn("  Lacunas: ") + ", ".join(f"{r['tecnica']} ({r['cenario']})" for r in miss))
            if rules != BASELINE:
                print(dim(f"  regras de exemplo para cobri-las: {BASELINE}"))
        os.makedirs(REPORTS, mode=0o750, exist_ok=True)
        rep = f"{REPORTS}/drill-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        json.dump({"quando": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                   "regras": rules, "cobertura_pct": pct, "resultados": res},
                  open(rep, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(dim(f"  relatório: {rep}"))
        return 0 if not miss else 3
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(args):
    act = args[0] if args else "list"
    if act == "run":
        sys.exit(run(args[1:]))
    if act != "list":
        sys.exit("ações: list | run [cenário...] [--baseline] [--export DIR]")
    print(ac("▍Cenários do treino de detecção") + dim("   (nos drill run)"))
    for name, tech, tactic, desc, _f in SCENARIOS:
        print(f"  {name:<11} {tech:<10} {dim(tactic + ':')} {desc}")

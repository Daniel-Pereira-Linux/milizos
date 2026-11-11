#!/usr/bin/python3
"""Harness de teste do MilizOS em QEMU/KVM (sem root).

  vm.py start live|autoinstall|disk [--uefi] [--cfg arquivo.json] [--usb] [--append "args"]
  vm.py shot arquivo.png        captura a tela
  vm.py key  ret|down|...       envia teclas (nomes QMP, separadas por espaco; 'a-b' = combinacao)
  vm.py type "texto"            digita texto
  vm.py wait "regex" [seg]      espera um padrao no console serial
  vm.py stop
"""
import argparse, json, os, re, shutil, socket, subprocess, sys, time

P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W = os.path.join(P, "cache", "vm"); os.makedirs(W, exist_ok=True)
ISO = os.path.join(P, "out", "MilizOS-1.0-x86_64.iso")
DISK = os.path.join(W, "disk.qcow2"); QMP = os.path.join(W, "qmp.sock")
SER = os.path.join(W, "serial.log"); PID = os.path.join(W, "qemu.pid")
OV = "/usr/share/edk2/ovmf"


def qmp(*cmds):
    s = socket.socket(socket.AF_UNIX); s.connect(QMP); f = s.makefile("rw")
    json.loads(f.readline())
    out = []
    for c in ({"execute": "qmp_capabilities"},) + cmds:
        f.write(json.dumps(c) + "\n"); f.flush()
        while True:
            r = json.loads(f.readline())
            if "return" in r or "error" in r:
                out.append(r); break
    s.close()
    return out[1:]


def stop():
    if os.path.exists(PID):
        try:
            os.kill(int(open(PID).read()), 15)
        except (OSError, ValueError):
            pass
        time.sleep(1)
        for f in (PID, QMP):
            if os.path.exists(f):
                os.unlink(f)


def start(a):
    stop()
    if a.mode != "disk" or not os.path.exists(DISK):
        if a.mode != "live" or not os.path.exists(DISK):
            subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", DISK, a.size], check=True)
    open(SER, "w").close()
    q = ["qemu-system-x86_64", "-enable-kvm", "-cpu", "host", "-smp", "4", "-m", a.mem, "-machine", "q35",
         "-display", "none", "-vga", "none", "-device", "virtio-vga,xres=1280,yres=800",
         "-device", "virtio-rng-pci", "-device", "qemu-xhci", "-device", "usb-tablet", "-device", "usb-kbd",
         "-netdev", "user,id=n0", "-device", "virtio-net-pci,netdev=n0",
         "-qmp", f"unix:{QMP},server,nowait", "-chardev", f"socket,id=s0,path={W}/ser.sock,server=on,wait=off,logfile={SER}", "-serial", "chardev:s0", "-pidfile", PID, "-daemonize",
         "-drive", f"file={DISK},if=none,id=d0,format=qcow2,discard=unmap",
         "-device", "virtio-blk-pci,drive=d0,bootindex=1"]
    if a.secboot:
        v = os.path.join(W, "vars-sb.fd")
        if a.mode != "disk" or not os.path.exists(v):
            shutil.copyfile(f"{OV}/OVMF_VARS.secboot.fd", v)
        q[q.index("q35")] = "q35,smm=on"
        q += ["-global", "driver=cfi.pflash01,property=secure,value=on",
              "-drive", f"if=pflash,format=raw,readonly=on,file={OV}/OVMF_CODE.secboot.fd", "-drive", f"if=pflash,format=raw,file={v}"]
    elif a.uefi:
        v = os.path.join(W, "vars.fd")
        if a.mode != "disk" or not os.path.exists(v):
            shutil.copyfile(f"{OV}/OVMF_VARS.fd", v)
        q += ["-drive", f"if=pflash,format=raw,readonly=on,file={OV}/OVMF_CODE.fd", "-drive", f"if=pflash,format=raw,file={v}"]
    if a.mode in ("live", "autoinstall", "direct"):
        if a.usb:
            q += ["-drive", f"file={ISO},if=none,id=u0,format=raw,readonly=on", "-device", "usb-storage,drive=u0" + ("" if a.mode in ("autoinstall", "direct") else ",bootindex=0")]
        else:
            q += ["-drive", f"file={ISO},if=none,id=c0,media=cdrom,readonly=on", "-device", "ide-cd,drive=c0" + ("" if a.mode in ("autoinstall", "direct") else ",bootindex=0")]
    if a.mode == "direct":
        q += ["-kernel", f"{P}/cache/iso/boot/vmlinuz", "-initrd", f"{P}/cache/iso/boot/initrd.img",
              "-append", "root=live:CDLABEL=MILIZOS-1-0 rd.live.image enforcing=0 console=tty0 console=ttyS0 " + a.append]
    if a.mode == "autoinstall":
        q += ["-kernel", f"{P}/cache/iso/boot/vmlinuz", "-initrd", f"{P}/cache/iso/boot/initrd.img",
              "-append", "root=live:CDLABEL=MILIZOS-1-0 rd.live.image enforcing=0 console=tty0 console=ttyS0 "
                         "systemd.unit=multi-user.target milizos.autoinstall=poweroff " + a.append,
              "-fw_cfg", f"name=opt/milizos/autoinstall,file={os.path.abspath(a.cfg)}"]
    subprocess.run(q, check=True)
    print("VM iniciada; serial em", SER)


def alive():
    try:
        os.kill(int(open(PID).read()), 0); return True
    except (OSError, ValueError):
        return False


KEYMAP = {" ": "spc", "-": "minus", ".": "dot", "/": "slash", "=": "equal", ",": "comma", "\n": "ret", ";": "semicolon"}
SHIFT = {"_": "minus", ":": "semicolon", "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "&": "7", "*": "8",
         "(": "9", ")": "0", "+": "equal", "?": "slash", "|": "backslash", '"': "apostrophe", ">": "dot", "<": "comma"}


def send(keys):
    qmp({"execute": "send-key", "arguments": {"keys": [{"type": "qcode", "data": k} for k in keys]}})
    time.sleep(0.06)


def console(text, secs=4.0):
    """Envia uma linha ao console serial e devolve o que voltar."""
    s = socket.socket(socket.AF_UNIX); s.connect(os.path.join(W, "ser.sock")); s.settimeout(0.5)
    s.sendall(text.encode() + b"\n")
    buf = b""; end = time.time() + secs
    while time.time() < end:
        try:
            d = s.recv(65536)
            if d:
                buf += d; end = max(end, time.time() + 1.0)
        except socket.timeout:
            pass
    s.close()
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07\x1b]*(\x07|\x1b\\\\)", "", buf.decode(errors="replace"))


def main():
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("start"); s.add_argument("mode", choices=["live", "autoinstall", "direct", "disk"])
    s.add_argument("--uefi", action="store_true"); s.add_argument("--secboot", action="store_true"); s.add_argument("--usb", action="store_true")
    s.add_argument("--cfg"); s.add_argument("--append", default=""); s.add_argument("--size", default="24G")
    s.add_argument("--mem", default="4096")
    x = sp.add_parser("shot"); x.add_argument("file")
    k = sp.add_parser("key"); k.add_argument("keys", nargs="+")
    t = sp.add_parser("type"); t.add_argument("text")
    w = sp.add_parser("wait"); w.add_argument("regex"); w.add_argument("secs", nargs="?", type=int, default=300)
    c = sp.add_parser("sh"); c.add_argument("text"); c.add_argument("secs", nargs="?", type=float, default=4.0)
    m = sp.add_parser("click"); m.add_argument("x", type=int); m.add_argument("y", type=int)
    sp.add_parser("stop"); sp.add_parser("alive")
    a = ap.parse_args()
    if a.cmd == "start":
        start(a)
    elif a.cmd == "stop":
        stop()
    elif a.cmd == "alive":
        sys.exit(0 if alive() else 1)
    elif a.cmd == "click":
        ax, ay = int(a.x * 32767 / 1280), int(a.y * 32767 / 800)
        mv = [{"type": "abs", "data": {"axis": "x", "value": ax}}, {"type": "abs", "data": {"axis": "y", "value": ay}}]
        qmp({"execute": "input-send-event", "arguments": {"events": mv}}); time.sleep(0.15)
        for down in (True, False):
            qmp({"execute": "input-send-event", "arguments": {"events": [{"type": "btn", "data": {"down": down, "button": "left"}}]}})
            time.sleep(0.08)
    elif a.cmd == "sh":
        print(console(a.text, a.secs))
    elif a.cmd == "shot":
        r = qmp({"execute": "screendump", "arguments": {"filename": os.path.abspath(a.file), "format": "png"}})
        print(r[0])
    elif a.cmd == "key":
        for k in a.keys:
            send(k.split("-")); time.sleep(0.15)
    elif a.cmd == "type":
        for ch in a.text:
            if ch in SHIFT: send(["shift", SHIFT[ch]])
            elif ch.isupper(): send(["shift", ch.lower()])
            else: send([KEYMAP.get(ch, ch)])
    elif a.cmd == "wait":
        end = time.time() + a.secs; rx = re.compile(a.regex)
        while time.time() < end:
            txt = open(SER, errors="replace").read()
            m = rx.search(txt)
            if m:
                print("OK:", m.group(0)); return
            if not alive():
                print("VM encerrou sem o padrão"); print(txt[-1500:]); sys.exit(2)
            time.sleep(2)
        print("TIMEOUT"); print(open(SER, errors="replace").read()[-1500:]); sys.exit(1)


if __name__ == "__main__":
    main()

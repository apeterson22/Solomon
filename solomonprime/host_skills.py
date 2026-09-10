"""Fixed read-only host skills; never accepts a command line or environment."""
import shutil
import subprocess

COMMANDS={
    'os':['uname','-a'],
    'uptime':['uptime'],
    'disk_space':['df','-h','-x','tmpfs','-x','devtmpfs'],
    'usb':['lsusb'],
    'processes':['ps','-eo','pid,comm,pcpu,pmem','--sort=-pcpu'],
    'services':['systemctl','list-units','--type=service','--state=running','--no-pager','--plain'],
}

def inspect_host(skill):
    argv=COMMANDS.get(skill)
    if argv is None:raise ValueError('unknown host inspection skill')
    if not shutil.which(argv[0]):return {'skill':skill,'state':'unavailable','reason':'tool not installed'}
    # Fixed commands produce bounded practical output; do not return argv/env of processes.
    try:
        p=subprocess.run(argv,capture_output=True,text=True,timeout=10,check=False)
        return {'skill':skill,'state':'completed' if p.returncode==0 else 'failed','exit_code':p.returncode,
                'stdout':p.stdout[:16000],'stderr':p.stderr[:2000]}
    except (OSError,subprocess.TimeoutExpired) as exc:return {'skill':skill,'state':'failed','error':type(exc).__name__}

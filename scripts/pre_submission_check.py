#!/usr/bin/env python3
"""Fast, network-free pre-submission checks for the public release."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
REQUIRED=['README.md','ARCHITECTURE.md','MODELS.md','AUDIT.md','TЗ_COVERAGE.md','SUBMISSION_CHECKLIST.md','Dockerfile','docker-compose.yml','.env.example','VERSION','requirements.txt']


def run(cmd):
    return subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True)


def check_env_secret_errors():
    errors=[]
    env=ROOT/'.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8',errors='ignore').splitlines():
            raw=line.strip()
            if not raw or raw.startswith('#') or '=' not in raw: continue
            key,value=raw.split('=',1)
            if key.strip() in {'CLOUD_RU_API_KEY','HF_TOKEN'} and value.strip():
                errors.append(f'Секрет найден в .env: {key.strip()} (не публикуйте .env)')
    return errors


def main():
    errors=[];warnings=[]
    for rel in REQUIRED:
        if not (ROOT/rel).exists(): errors.append(f'Отсутствует обязательный файл: {rel}')
    version=(ROOT/'VERSION').read_text().strip() if (ROOT/'VERSION').exists() else ''
    if version!='7.4.2-final': warnings.append(f'VERSION={version!r}; ожидается 7.4.2-final')
    errors.extend(check_env_secret_errors())
    py=run([sys.executable,'-m','compileall','-q','.'])
    if py.returncode!=0:errors.append('compileall не прошёл')
    else: print('PASS compileall')
    if subprocess.run(['bash','-lc','command -v docker'],capture_output=True,text=True).returncode==0:
        dc=run(['docker','compose','config','-q'])
        if dc.returncode!=0:errors.append('docker compose config не прошёл: '+dc.stderr.strip()[:500])
        else:print('PASS docker compose config')
    else:warnings.append('Docker CLI не установлен: compose/build не проверялись в этой среде.')
    print(f'VERSION {version}')
    for w in warnings:print('WARN',w)
    if errors:
        for e in errors:print('FAIL',e)
        return 1
    print('PASS pre-submission structure/secret/syntax checks')
    return 0

if __name__=='__main__':sys.exit(main())

import os
import secrets
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
import click
from flask import current_app
from .db import get_db, init_db, transaction
from .auth import create_local_teacher


def register_cli(app):
    @app.cli.command('init-db')
    def init():
        init_db()
        click.echo('Database initialized.')

    @app.cli.command('create-teacher')
    @click.option('--email',default='admin@student.karazin.ua')
    @click.option('--credentials-file',required=True,type=click.Path(path_type=Path))
    def create(email,credentials_file):
        password = secrets.token_urlsafe(24)
        credentials_file.parent.mkdir(parents=True,exist_ok=True)
        fd = os.open(str(credentials_file),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'w') as output:
                with transaction():
                    create_local_teacher(email,password)
                    output.write(f"Платформа: {current_app.config['PUBLIC_URL']}/\nЛогин: {email}\nПароль: {password}\n\nТестовый вход преподавателя. Пароль меняется в кабинете.\n")
        except BaseException:
            credentials_file.unlink(missing_ok=True)
            raise
        click.echo('Teacher created; credentials saved to the requested private file.')

    @app.cli.command('backup')
    @click.option('--destination',required=True,type=click.Path(path_type=Path))
    def backup(destination):
        destination.mkdir(parents=True,exist_ok=True,mode=0o700)
        stamp=datetime.now(timezone.utc)
        path=destination / ('testing-'+stamp.strftime('%Y%m%d-%H%M%S-%f')+'.sqlite')
        fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        os.close(fd)
        with sqlite3.connect(path) as target:
            get_db().backup(target)
            check=target.execute('PRAGMA integrity_check').fetchone()[0]
            if check != 'ok':
                raise click.ClickException('Backup integrity check failed')
        cutoff=(stamp-timedelta(days=14)).timestamp()
        for previous in destination.glob('testing-*.sqlite'):
            if previous.is_file() and previous.stat().st_mtime < cutoff:
                previous.unlink()
        click.echo('Backup created and integrity verified.')

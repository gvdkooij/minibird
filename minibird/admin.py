"""Local-only administrator provisioning. Passwords never enter command arguments."""
import getpass
import hashlib
import secrets

from minibird.customers import database


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f'scrypt${salt}${digest}'


def verify_password(password, stored):
    try:
        algorithm, salt, _ = stored.split('$')
        return algorithm == 'scrypt' and secrets.compare_digest(hash_password(password, salt), stored)
    except (ValueError, TypeError):
        return False


def set_administrator(username, password):
    if not username.strip() or len(username) > 100:
        raise ValueError('Gebruikersnaam moet 1–100 tekens bevatten.')
    if not 12 <= len(password) <= 256:
        raise ValueError('Wachtwoord moet 12–256 tekens bevatten.')
    password_hash = hash_password(password)
    with database() as connection:
        connection.execute('INSERT INTO administrator VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET username=excluded.username, password_hash=excluded.password_hash', (username.strip(), password_hash))
        connection.execute('DELETE FROM web_sessions')
        # Do not clear the shared login throttle when changing credentials.


def main():
    username = input('Gebruikersnaam beheerder: ')
    password = getpass.getpass('Wachtwoord (minimaal 12 tekens): ')
    if password != getpass.getpass('Herhaal wachtwoord: '):
        raise SystemExit('Wachtwoorden komen niet overeen.')
    try:
        set_administrator(username, password)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print('Beheerdersaccount opgeslagen; bestaande sessies ingetrokken.')


if __name__ == '__main__':
    main()

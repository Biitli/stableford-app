"""Einmalig ausführen, um den Dropbox-Refresh-Token zu erhalten.

    pip install dropbox
    python scripts/dropbox_token.py

Fragt nach App key und App secret (von dropbox.com/developers/apps), öffnet
einen Link zur Freigabe und gibt danach den Refresh-Token aus.
"""

from dropbox import DropboxOAuth2FlowNoRedirect

key = input("App key: ").strip()
secret = input("App secret: ").strip()
flow = DropboxOAuth2FlowNoRedirect(key, secret, token_access_type="offline")
print("\n1. Diesen Link öffnen und 'Zulassen' klicken:\n  ", flow.start())
code = input("2. Den angezeigten Code hier einfügen: ").strip()
res = flow.finish(code)
print("\nDROPBOX_REFRESH_TOKEN =", res.refresh_token)

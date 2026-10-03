# LocalLink

A browser-based messenger for devices connected to your local network. Run it on one computer; phones, tablets, laptops, and PCs join through their browser. No account, cloud service, CDN, package installation, or internet connection is needed at runtime.

## Start on the host computer

You need **Python 3.10 or newer** on the host only. Extract the ZIP before starting it.

**Windows:** double-click `start-windows.bat`, or open a terminal in this folder and run:

```powershell
py -3 server.py
```

**macOS / Linux:** open a terminal in this folder and run:

```bash
python3 server.py
```

Open **http://localhost:8080** on the host. Keep the terminal open and the host awake.

## Join from another device

1. Connect the device to the same Wi-Fi / local network as the host.
2. The server prints one or more `Other devices` addresses, such as `http://192.168.1.25:8080`.
3. Open the host's Wi-Fi address in the other device's browser. Use **http**, not https. Enter a display name and join.

**`localhost` always means the device you are using.** On a phone, `localhost` points to that phone, so use the host computer's local IP instead. The `0.0.0.0` server bind address is not the address to share.

If multiple addresses are printed, choose the host's Wi-Fi/LAN IPv4 address. On Windows, run `ipconfig` and find the IPv4 address under the active Wi-Fi adapter. On macOS, see Wi-Fi → Details → TCP/IP. On Linux, run `hostname -I`. A VPN or virtual adapter can cause the automatically printed address to be the wrong one.

## Features

- One shared room with live messages and a list of active browser sessions.
- Responsive layout for mobile and desktop; room details are under the menu on small screens.
- Multiple file selection, desktop drag-and-drop, upload progress, and cancellation.
- All file types supported as downloads; files are never executed or previewed by the server.
- Saved messages and files, with a button to load older history.
- Optional room password, authenticated downloads, and reconnect after temporary network loss.
- Unicode names, messages, and filenames.
- Desktop: Enter sends; Shift+Enter adds a line. Mobile: Enter adds a line; tap the arrow to send.

Messages update through HTTP long polling, typically immediately on arrival. The presence list can take up to about a minute to reflect a closed browser. Separate browsers or devices are separate sessions, even with the same display name. Display names are not verified identities. A browser restores its session on refresh; a server restart requires everyone to join again. History stays saved.

## Optional settings

Prompt for a room password without exposing it in command history:

```bash
python3 server.py --password
```

On Windows replace `python3` with `py -3`. You can also set the `LOCALCHAT_PASSWORD` environment variable. Every member with access to the room can see **all** saved messages and download **all** shared files, including older ones.

Change port, file size, and total file storage:

```bash
python3 server.py --port 8090 --max-file-mb 500 --storage-mb 10240
```

Defaults: port 8080, 100 MiB per file, 2 GiB total uploaded file storage. The total limit applies to uploaded files, not the message database. Uploads stream to disk, rather than buffering entire files in memory. The host needs enough free disk space. Configure the limits to suit your network and available space.

Store the room elsewhere:

```bash
python3 server.py --data-dir /path/to/room-data
```

Local-only use (blocks other devices):

```bash
python3 server.py --host 127.0.0.1
```

Press **Ctrl+C** in the server terminal to stop. The default `data/` folder next to `server.py` contains the SQLite database and uploaded files. Back it up while the server is stopped. To reset the room, stop the server and move or delete the entire `data/` folder; this removes access to all history and files. There is no automatic expiry, individual deletion, private messaging, or user-account system in this version. Only run one server instance per data directory.

## If other devices cannot connect

- Keep the host on, connected, and awake. Check the page opens on the host first.
- Allow Python / inbound TCP port 8080 through the host firewall on your **private/home network**. If you change the port, allow that port instead. Do not disable the firewall.
- Guest Wi-Fi, client/AP isolation, workplace networks, or different VLANs may block devices from reaching each other. Use a network that permits local device communication.
- Recheck the host's IP after changing networks or restarting the router. A router DHCP reservation keeps it stable.
- Try disconnecting a VPN that blocks local network traffic.
- If the port is already in use, start with `--port 8090` and use that port in the URL.
- For a file download after a session expires, refresh and rejoin first.

## Network privacy

LocalLink uses **plain HTTP**, without end-to-end encryption or transport encryption. A room password controls who can join; it does not encrypt traffic. Use it on a trusted LAN. The server listens on all IPv4 interfaces by default: the OS firewall determines who can reach it. Do not expose the port to the internet or enable router port forwarding. Files pass through and remain on the host computer; transfers are not peer-to-peer.

## Project files

```text
server.py                Python standard-library HTTP server + SQLite storage
static/index.html        Chat interface
static/style.css         Responsive styling
static/app.js            Messaging, presence, and file uploads
start-windows.bat        Windows launcher
start-macos-linux.sh     macOS/Linux launcher
tests/test_server.py     HTTP integration tests
```

Run the included tests:

```bash
python3 -m unittest discover -s tests -v
```

The tests use temporary isolated data and cover two-client delivery, binary file integrity, password/session enforcement, cross-site blocking, file limits, pagination, and persistence across restart.
